"""
Property tests para el registro pendiente de IPs públicas desconocidas.

Verifica propiedades universales del flujo de registro automático de IPs
pendientes en el endpoint /updates/check.

Feature: pending-ip-registration, Property 1: Registro pendiente para IP desconocida
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.exc import IntegrityError, OperationalError

from app.api.v1.endpoints.updates import _register_pending_ip
from app.models.organization import PublicIP


# === Estrategias de generación de IPs válidas ===

# Estrategia para generar direcciones IPv4 válidas
ipv4_strategy = st.tuples(
    st.integers(min_value=1, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=1, max_value=254),
).map(lambda t: f"{t[0]}.{t[1]}.{t[2]}.{t[3]}")

# Estrategia para generar direcciones IPv6 válidas (formato completo)
ipv6_strategy = st.lists(
    st.integers(min_value=0, max_value=0xFFFF),
    min_size=8,
    max_size=8,
).map(lambda groups: ":".join(f"{g:04x}" for g in groups))

# Estrategia combinada: IPv4 o IPv6
valid_ip_strategy = st.one_of(ipv4_strategy, ipv6_strategy)


# === PROPERTY 1: REGISTRO PENDIENTE PARA IP DESCONOCIDA ===


class TestRegistroPendienteParaIPDesconocida:
    """
    Property 1: Registro pendiente para IP desconocida.

    Para cualquier dirección IP válida (IPv4 o IPv6) que no exista previamente
    en la tabla public_ips, cuando se recibe una solicitud no autenticada en el
    endpoint /updates/check, el sistema debe crear un registro con:
    - is_authorized=False
    - organization_id=None
    - ip_address igual a la IP del cliente
    - first_seen dentro de un margen de 5 segundos respecto a la hora UTC actual

    Feature: pending-ip-registration, Property 1: Registro pendiente para IP desconocida

    **Validates: Requirements 1.1, 1.2, 5.3**
    """

    @given(
        ip_address=valid_ip_strategy,
    )
    @settings(max_examples=100)
    def test_registro_pendiente_campos_correctos(self, ip_address: str):
        """
        Para cualquier IP válida (IPv4/IPv6), _register_pending_ip genera un
        statement INSERT con is_authorized=False, organization_id=None,
        ip_address correcta, y first_seen dentro de ±5s de UTC actual.

        **Validates: Requirements 1.1, 1.2, 5.3**
        """
        # Preparar mock del request con la IP generada (sin headers de metadata)
        mock_request = MagicMock()
        real_headers = {}
        mock_request.headers = MagicMock()
        mock_request.headers.get = lambda key, default=None: real_headers.get(key, default)

        # Preparar mock de la sesión de DB para capturar el statement ejecutado
        mock_db = MagicMock()
        captured_stmts = []

        def capture_execute(stmt):
            captured_stmts.append(stmt)

        mock_db.execute.side_effect = capture_execute
        mock_db.commit.return_value = None

        # Registrar timestamp antes de la llamada
        before_call = datetime.utcnow()

        # Ejecutar la función bajo test (mockear get_client_ip para controlar la IP)
        with patch(
            "app.api.v1.endpoints.updates.get_client_ip",
            return_value=ip_address,
        ):
            _register_pending_ip(mock_db, mock_request)

        # Registrar timestamp después de la llamada
        after_call = datetime.utcnow()

        # Verificar que se ejecutó un statement
        assert len(captured_stmts) == 1, (
            f"Se esperaba exactamente 1 statement ejecutado, "
            f"se obtuvieron {len(captured_stmts)}"
        )

        # Extraer los valores del INSERT compilado
        stmt = captured_stmts[0]
        compiled = stmt.compile(compile_kwargs={"literal_binds": False})
        params = compiled.params

        # Verificar ip_address correcta
        assert params["ip_address"] == ip_address, (
            f"ip_address incorrecto. Esperado: {ip_address}, "
            f"Obtenido: {params['ip_address']}"
        )

        # Verificar is_authorized=False
        assert params["is_authorized"] is False, (
            f"is_authorized debería ser False, "
            f"Obtenido: {params['is_authorized']}"
        )

        # Verificar organization_id=None
        assert params["organization_id"] is None, (
            f"organization_id debería ser None, "
            f"Obtenido: {params['organization_id']}"
        )

        # Verificar first_seen dentro de ±5s de UTC actual
        first_seen = params["first_seen"]
        assert isinstance(first_seen, datetime), (
            f"first_seen debería ser datetime, "
            f"Obtenido tipo: {type(first_seen)}"
        )

        # El first_seen debe estar entre before_call y after_call (con margen de 5s)
        lower_bound = before_call - timedelta(seconds=5)
        upper_bound = after_call + timedelta(seconds=5)
        assert lower_bound <= first_seen <= upper_bound, (
            f"first_seen fuera de rango ±5s. "
            f"Esperado: entre {lower_bound} y {upper_bound}, "
            f"Obtenido: {first_seen}"
        )

        # Verificar que se hizo commit (operación completada, Req 5.3)
        mock_db.commit.assert_called_once()

        # Verificar que NO se hizo rollback (operación exitosa)
        mock_db.rollback.assert_not_called()


# === PROPERTY 3: IDEMPOTENCIA — SIN REGISTROS DUPLICADOS ===

# Estrategia para IPs IPv6 válidas (formato completo)
ipv6_strategy = st.lists(
    st.integers(min_value=0, max_value=0xFFFF).map(lambda x: format(x, "x")),
    min_size=8,
    max_size=8,
).map(lambda parts: ":".join(parts))

# Estrategia combinada de IPs válidas (IPv4 + IPv6)
ip_strategy_combined = st.one_of(ipv4_strategy, ipv6_strategy)


class TestIdempotenciaSinRegistrosDuplicados:
    """
    Feature: pending-ip-registration, Property 3: Idempotencia — sin registros duplicados

    Para cualquier dirección IP que ya exista en la tabla public_ips
    (independientemente de su estado de autorización), enviar N solicitudes
    adicionales desde esa misma IP no debe incrementar el conteo total de
    registros con ese ip_address (siempre debe ser exactamente 1).

    Se verifica que _register_pending_ip usa el patrón upsert (INSERT ... ON CONFLICT)
    en cada una de las N invocaciones, garantizando que la constraint UNIQUE de
    ip_address impide la creación de registros duplicados.

    **Validates: Requirements 2.1, 2.5**
    """

    @given(
        ip=ip_strategy_combined,
        n_repetitions=st.integers(min_value=2, max_value=20),
    )
    @settings(max_examples=100)
    def test_n_llamadas_misma_ip_producen_exactamente_un_registro(
        self, ip: str, n_repetitions: int
    ):
        """
        Llamar _register_pending_ip N veces con la misma IP siempre produce
        exactamente 1 registro en la BD, gracias al patrón upsert idempotente.

        Se mockea db.execute y db.commit para verificar que cada invocación
        genera un statement con ON CONFLICT (upsert), lo que garantiza que
        la constraint UNIQUE de ip_address impide duplicados.

        **Validates: Requirements 2.1, 2.5**
        """
        # Simular el objeto request con la IP generada
        mock_request = MagicMock()
        mock_request.headers = MagicMock()
        mock_request.headers.get = MagicMock(return_value=None)

        # Simular db session
        mock_db = MagicMock()
        executed_statements = []

        def capture_execute(stmt):
            """Captura cada statement SQL para inspección posterior."""
            executed_statements.append(stmt)

        mock_db.execute = capture_execute
        mock_db.commit = MagicMock()
        mock_db.rollback = MagicMock()

        # Mockear get_client_ip para retornar siempre la misma IP
        with patch(
            "app.api.v1.endpoints.updates.get_client_ip", return_value=ip
        ):
            # Llamar N veces con la misma IP
            for _ in range(n_repetitions):
                _register_pending_ip(mock_db, mock_request)

        # Verificar que se ejecutó un statement por cada invocación
        assert len(executed_statements) == n_repetitions, (
            f"Se esperaban {n_repetitions} statements ejecutados (uno por llamada), "
            f"pero hubo {len(executed_statements)}. "
            f"IP={ip}, N={n_repetitions}"
        )

        # Verificar que CADA statement usa ON CONFLICT (patrón upsert idempotente)
        # Esto demuestra que no se usa INSERT simple — el upsert previene duplicados
        for i, stmt in enumerate(executed_statements):
            compiled = stmt.compile(compile_kwargs={"literal_binds": False})
            sql_str = str(compiled).lower()

            assert "on conflict" in sql_str, (
                f"La llamada #{i+1} de {n_repetitions} NO usó un statement upsert "
                f"(INSERT ... ON CONFLICT). Sin upsert, se crearían registros "
                f"duplicados para la misma IP. "
                f"IP={ip}, SQL generado: {str(compiled)}"
            )

            # Verificar que el target del conflict es ip_address (la constraint UNIQUE)
            assert "ip_address" in sql_str, (
                f"La llamada #{i+1} no referencia ip_address en el ON CONFLICT. "
                f"Sin la referencia al campo UNIQUE, el upsert no previene duplicados. "
                f"IP={ip}, SQL: {str(compiled)}"
            )

        # Verificar que se hizo commit N veces (una por invocación exitosa)
        assert mock_db.commit.call_count == n_repetitions, (
            f"Se esperaban {n_repetitions} commits, "
            f"pero hubo {mock_db.commit.call_count}. "
            f"IP={ip}, N={n_repetitions}"
        )

        # Verificar que NO hubo rollbacks (todas las operaciones exitosas)
        assert mock_db.rollback.call_count == 0, (
            f"No debería haber rollbacks en operaciones exitosas, "
            f"pero hubo {mock_db.rollback.call_count}. "
            f"IP={ip}, N={n_repetitions}"
        )

        # Verificar que todas las llamadas insertan la MISMA IP
        # Esto confirma que el upsert con UNIQUE constraint garantiza
        # que solo puede existir 1 registro para esa IP
        for i, stmt in enumerate(executed_statements):
            compiled = stmt.compile(compile_kwargs={"literal_binds": True})
            sql_str = str(compiled)
            assert ip in sql_str, (
                f"La llamada #{i+1} no contiene la IP '{ip}' en el statement. "
                f"Si la IP difiere entre llamadas, el upsert no previene duplicados. "
                f"SQL compilado: {sql_str}"
            )


# === PROPERTY 2: CAPTURA DE METADATA DESDE HEADERS ===


# Estrategia para valores de headers: ausente (None), vacío (""), o texto válido no vacío
_header_value_strategy = st.one_of(
    st.none(),
    st.just(""),
    st.text(min_size=1, max_size=100),
)


class TestCapturaMetadataDesdeHeaders:
    """
    Feature: pending-ip-registration, Property 2: Captura de metadata desde headers

    Para cualquier solicitud que genera un registro pendiente:
    - Si el header X-Workstation-ID tiene un valor no vacío → last_hostname coincide
    - Si el header X-Workstation-Local-IP tiene un valor no vacío → last_user coincide
    - Si un header está ausente o vacío → el campo correspondiente es NULL

    **Validates: Requirements 1.3, 1.4, 1.5**
    """

    @given(
        workstation_id_value=_header_value_strategy,
        local_ip_value=_header_value_strategy,
        client_ip=ipv4_strategy,
    )
    @settings(max_examples=100)
    def test_metadata_capturada_correctamente_desde_headers(
        self,
        workstation_id_value,
        local_ip_value,
        client_ip: str,
    ):
        """
        Verifica que _register_pending_ip captura correctamente la metadata
        de los headers X-Workstation-ID y X-Workstation-Local-IP.

        - Header presente y no vacío → campo tiene ese valor
        - Header ausente o vacío → campo es NULL (None)

        **Validates: Requirements 1.3, 1.4, 1.5**
        """
        # Construir headers simulados según los valores generados
        real_headers = {}
        if workstation_id_value is not None:
            real_headers["X-Workstation-ID"] = workstation_id_value
        if local_ip_value is not None:
            real_headers["X-Workstation-Local-IP"] = local_ip_value

        # Crear mock del request con headers generados
        mock_request = MagicMock()
        mock_request.headers = MagicMock()
        mock_request.headers.get = lambda key, default=None: real_headers.get(key, default)
        mock_request.client = MagicMock()
        mock_request.client.host = client_ip

        # Crear mock de la sesión de BD para capturar el statement ejecutado
        mock_db = MagicMock()
        captured_stmts = []

        def capture_execute(stmt):
            captured_stmts.append(stmt)

        mock_db.execute = capture_execute
        mock_db.commit = MagicMock()

        # Mockear get_client_ip para retornar nuestra IP generada
        with patch(
            "app.api.v1.endpoints.updates.get_client_ip", return_value=client_ip
        ):
            _register_pending_ip(mock_db, mock_request)

        # Verificar que se ejecutó un statement
        assert len(captured_stmts) == 1, (
            f"Se esperaba exactamente 1 statement ejecutado, "
            f"se obtuvieron {len(captured_stmts)}"
        )

        # Extraer los parámetros del INSERT del statement capturado
        stmt = captured_stmts[0]
        compiled = stmt.compile(compile_kwargs={"literal_binds": False})
        params = compiled.params

        # Calcular valores esperados según la lógica de la implementación:
        # `request.headers.get("X-Workstation-ID") or None`
        # → si es None o "" → resultado es None; si es no vacío → valor del header
        expected_hostname = (
            workstation_id_value
            if workstation_id_value is not None and workstation_id_value != ""
            else None
        )
        expected_user = (
            local_ip_value
            if local_ip_value is not None and local_ip_value != ""
            else None
        )

        # Verificar last_hostname en los parámetros del INSERT
        assert params.get("last_hostname") == expected_hostname, (
            f"last_hostname incorrecto. "
            f"Header X-Workstation-ID={repr(workstation_id_value)}, "
            f"Esperado: {repr(expected_hostname)}, "
            f"Obtenido: {repr(params.get('last_hostname'))}"
        )

        # Verificar last_user en los parámetros del INSERT
        assert params.get("last_user") == expected_user, (
            f"last_user incorrecto. "
            f"Header X-Workstation-Local-IP={repr(local_ip_value)}, "
            f"Esperado: {repr(expected_user)}, "
            f"Obtenido: {repr(params.get('last_user'))}"
        )

    @given(
        workstation_id_value=st.text(min_size=1, max_size=100),
        local_ip_value=st.text(min_size=1, max_size=100),
        client_ip=ipv4_strategy,
    )
    @settings(max_examples=100)
    def test_ambos_headers_presentes_captura_ambos_campos(
        self,
        workstation_id_value: str,
        local_ip_value: str,
        client_ip: str,
    ):
        """
        Cuando ambos headers están presentes y no vacíos, ambos campos
        (last_hostname y last_user) deben capturarse correctamente.

        **Validates: Requirements 1.3, 1.4**
        """
        real_headers = {
            "X-Workstation-ID": workstation_id_value,
            "X-Workstation-Local-IP": local_ip_value,
        }

        mock_request = MagicMock()
        mock_request.headers = MagicMock()
        mock_request.headers.get = lambda key, default=None: real_headers.get(key, default)
        mock_request.client = MagicMock()
        mock_request.client.host = client_ip

        mock_db = MagicMock()
        captured_stmts = []

        def capture_execute(stmt):
            captured_stmts.append(stmt)

        mock_db.execute = capture_execute
        mock_db.commit = MagicMock()

        with patch(
            "app.api.v1.endpoints.updates.get_client_ip", return_value=client_ip
        ):
            _register_pending_ip(mock_db, mock_request)

        assert len(captured_stmts) == 1, (
            "Se esperaba exactamente 1 statement ejecutado"
        )

        stmt = captured_stmts[0]
        compiled = stmt.compile(compile_kwargs={"literal_binds": False})
        params = compiled.params

        # Ambos headers presentes y no vacíos → ambos campos capturados
        assert params.get("last_hostname") == workstation_id_value, (
            f"last_hostname no coincide con X-Workstation-ID. "
            f"Esperado: {repr(workstation_id_value)}, "
            f"Obtenido: {repr(params.get('last_hostname'))}"
        )
        assert params.get("last_user") == local_ip_value, (
            f"last_user no coincide con X-Workstation-Local-IP. "
            f"Esperado: {repr(local_ip_value)}, "
            f"Obtenido: {repr(params.get('last_user'))}"
        )

    @given(
        client_ip=ipv4_strategy,
    )
    @settings(max_examples=100)
    def test_headers_ausentes_campos_null(
        self,
        client_ip: str,
    ):
        """
        Cuando ninguno de los headers está presente en la solicitud,
        los campos last_hostname y last_user deben ser NULL.

        **Validates: Requirements 1.5**
        """
        # Sin headers de workstation
        real_headers = {}

        mock_request = MagicMock()
        mock_request.headers = MagicMock()
        mock_request.headers.get = lambda key, default=None: real_headers.get(key, default)
        mock_request.client = MagicMock()
        mock_request.client.host = client_ip

        mock_db = MagicMock()
        captured_stmts = []

        def capture_execute(stmt):
            captured_stmts.append(stmt)

        mock_db.execute = capture_execute
        mock_db.commit = MagicMock()

        with patch(
            "app.api.v1.endpoints.updates.get_client_ip", return_value=client_ip
        ):
            _register_pending_ip(mock_db, mock_request)

        assert len(captured_stmts) == 1, (
            "Se esperaba exactamente 1 statement ejecutado"
        )

        stmt = captured_stmts[0]
        compiled = stmt.compile(compile_kwargs={"literal_binds": False})
        params = compiled.params

        # Sin headers → ambos campos NULL
        assert params.get("last_hostname") is None, (
            f"last_hostname debería ser None cuando X-Workstation-ID no está presente. "
            f"Obtenido: {repr(params.get('last_hostname'))}"
        )
        assert params.get("last_user") is None, (
            f"last_user debería ser None cuando X-Workstation-Local-IP no está presente. "
            f"Obtenido: {repr(params.get('last_user'))}"
        )


# === PROPERTY 4: ACTUALIZACIÓN SELECTIVA DE METADATA EN IP PENDIENTE ===


class TestActualizacionSelectivaMetadataIPPendiente:
    """
    Feature: pending-ip-registration, Property 4: Actualización selectiva de metadata en IP pendiente

    Para cualquier registro pendiente existente (is_authorized=False), cuando llega
    una solicitud con un header X-Workstation-ID no vacío, solo el campo last_hostname
    se actualiza con el nuevo valor; si llega con X-Workstation-Local-IP no vacío,
    solo last_user se actualiza. Los campos cuyo header correspondiente no está
    presente en la solicitud deben conservar su valor anterior sin cambios.

    **Validates: Requirements 2.2, 2.3**
    """

    @given(
        client_ip=ipv4_strategy,
        existing_hostname=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P")),
            min_size=1,
            max_size=50,
        ),
        existing_user=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P")),
            min_size=1,
            max_size=50,
        ),
        new_hostname=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P")),
            min_size=1,
            max_size=50,
        ),
    )
    @settings(max_examples=100)
    def test_solo_last_hostname_se_actualiza_cuando_solo_x_workstation_id_presente(
        self,
        client_ip: str,
        existing_hostname: str,
        existing_user: str,
        new_hostname: str,
    ):
        """
        Cuando solo el header X-Workstation-ID está presente, solo last_hostname
        debe aparecer en el set_ del ON CONFLICT DO UPDATE. El campo last_user
        no debe incluirse, preservando su valor anterior.

        **Validates: Requirements 2.2, 2.3**
        """
        # Preparar mock de request con solo X-Workstation-ID presente
        mock_request = MagicMock()
        headers_dict = {"X-Workstation-ID": new_hostname}
        mock_request.headers = MagicMock()
        mock_request.headers.get = lambda key, default=None: headers_dict.get(key, default)

        # Mock de sesión DB para capturar el statement
        mock_db = MagicMock()
        captured_stmts = []

        def capture_execute(stmt):
            """Captura el statement ejecutado para inspección."""
            captured_stmts.append(stmt)

        mock_db.execute = capture_execute
        mock_db.commit = MagicMock()

        # Mockear get_client_ip para retornar la IP generada
        with patch(
            "app.api.v1.endpoints.updates.get_client_ip",
            return_value=client_ip,
        ):
            _register_pending_ip(mock_db, mock_request)

        # Verificar que se ejecutó un statement
        assert len(captured_stmts) == 1, (
            "No se capturó ningún statement — _register_pending_ip no ejecutó db.execute()"
        )

        stmt = captured_stmts[0]

        # Inspeccionar el ON CONFLICT DO UPDATE — el statement tiene
        # _post_values_clause con la cláusula de conflicto
        assert hasattr(stmt, "_post_values_clause"), (
            "El statement no tiene cláusula ON CONFLICT — se esperaba on_conflict_do_update"
        )

        post_clause = stmt._post_values_clause
        # update_values_to_set es una lista de tuplas (columna, valor)
        update_columns = set(k for k, v in post_clause.update_values_to_set)

        # Solo last_hostname debe estar en el set_
        assert "last_hostname" in update_columns, (
            f"last_hostname NO está en set_ pero debería estarlo. "
            f"Columnas en set_: {update_columns}"
        )
        assert "last_user" not in update_columns, (
            f"last_user ESTÁ en set_ pero NO debería estarlo "
            f"(su header no fue enviado). Columnas en set_: {update_columns}"
        )

    @given(
        client_ip=ipv4_strategy,
        existing_hostname=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P")),
            min_size=1,
            max_size=50,
        ),
        existing_user=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P")),
            min_size=1,
            max_size=50,
        ),
        new_user=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P")),
            min_size=1,
            max_size=50,
        ),
    )
    @settings(max_examples=100)
    def test_solo_last_user_se_actualiza_cuando_solo_x_workstation_local_ip_presente(
        self,
        client_ip: str,
        existing_hostname: str,
        existing_user: str,
        new_user: str,
    ):
        """
        Cuando solo el header X-Workstation-Local-IP está presente, solo last_user
        debe aparecer en el set_ del ON CONFLICT DO UPDATE. El campo last_hostname
        no debe incluirse, preservando su valor anterior.

        **Validates: Requirements 2.2, 2.3**
        """
        # Preparar mock de request con solo X-Workstation-Local-IP presente
        mock_request = MagicMock()
        headers_dict = {"X-Workstation-Local-IP": new_user}
        mock_request.headers = MagicMock()
        mock_request.headers.get = lambda key, default=None: headers_dict.get(key, default)

        # Mock de sesión DB para capturar el statement
        mock_db = MagicMock()
        captured_stmts = []

        def capture_execute(stmt):
            """Captura el statement ejecutado para inspección."""
            captured_stmts.append(stmt)

        mock_db.execute = capture_execute
        mock_db.commit = MagicMock()

        # Mockear get_client_ip para retornar la IP generada
        with patch(
            "app.api.v1.endpoints.updates.get_client_ip",
            return_value=client_ip,
        ):
            _register_pending_ip(mock_db, mock_request)

        # Verificar que se ejecutó un statement
        assert len(captured_stmts) == 1, (
            "No se capturó ningún statement — _register_pending_ip no ejecutó db.execute()"
        )

        stmt = captured_stmts[0]

        # Inspeccionar la cláusula ON CONFLICT DO UPDATE
        assert hasattr(stmt, "_post_values_clause"), (
            "El statement no tiene cláusula ON CONFLICT — se esperaba on_conflict_do_update"
        )

        post_clause = stmt._post_values_clause
        # update_values_to_set es una lista de tuplas (columna, valor)
        update_columns = set(k for k, v in post_clause.update_values_to_set)

        # Solo last_user debe estar en el set_
        assert "last_user" in update_columns, (
            f"last_user NO está en set_ pero debería estarlo. "
            f"Columnas en set_: {update_columns}"
        )
        assert "last_hostname" not in update_columns, (
            f"last_hostname ESTÁ en set_ pero NO debería estarlo "
            f"(su header no fue enviado). Columnas en set_: {update_columns}"
        )



# === PROPERTY 7: RESILIENCIA ANTE FALLOS DE BD EN EL REGISTRO ===


class TestResilienciaAnteFallosDeBDEnElRegistro:
    """
    Feature: pending-ip-registration, Property 7: Resiliencia ante fallos de BD en el registro

    Para cualquier tipo de error de base de datos durante la operación de registro
    pendiente (constraint violation, timeout de conexión, deadlock, o cualquier otra
    excepción), el endpoint debe seguir retornando HTTP 401 (nunca HTTP 5xx) y la
    sesión de base de datos debe quedar en estado limpio (rollback completado).

    Se verifica que _register_pending_ip captura silenciosamente todas las excepciones,
    ejecuta rollback, y retorna None sin propagar el error. Esto garantiza que el
    endpoint siempre puede continuar lanzando HTTPException 401 sin ser interrumpido
    por un fallo de BD.

    **Validates: Requirements 5.1**
    """

    @given(
        exception=st.sampled_from([
            IntegrityError("duplicate", {}, None),
            OperationalError("connection lost", {}, None),
            TimeoutError("timeout"),
            RuntimeError("unexpected"),
            ConnectionError("no connection"),
            Exception("generic error"),
        ]),
        client_ip=ipv4_strategy,
    )
    @settings(max_examples=100)
    def test_funcion_no_propaga_excepciones_y_hace_rollback(
        self,
        exception: Exception,
        client_ip: str,
    ):
        """
        Para cualquier excepción inyectada en db.execute, _register_pending_ip:
        1. NO propaga la excepción (la captura silenciosamente)
        2. Ejecuta db.rollback() para limpiar la sesión
        3. Retorna None normalmente

        Esto garantiza que el endpoint siempre puede lanzar HTTPException 401
        sin ser interrumpido por fallos de BD.

        **Validates: Requirements 5.1**
        """
        # Preparar mock del request
        mock_request = MagicMock()
        real_headers = {"X-Workstation-ID": "test-host", "X-Workstation-Local-IP": "192.168.1.1"}
        mock_request.headers = MagicMock()
        mock_request.headers.get = lambda key, default=None: real_headers.get(key, default)

        # Preparar mock de la sesión DB que lanza la excepción inyectada
        mock_db = MagicMock()
        mock_db.execute.side_effect = exception
        mock_db.rollback = MagicMock()
        mock_db.commit = MagicMock()

        # Ejecutar la función — NO debe lanzar ninguna excepción
        with patch(
            "app.api.v1.endpoints.updates.get_client_ip",
            return_value=client_ip,
        ):
            result = _register_pending_ip(mock_db, mock_request)

        # 1. La función retorna None (no propaga la excepción)
        assert result is None, (
            f"_register_pending_ip debería retornar None ante un fallo de BD, "
            f"pero retornó: {repr(result)}. "
            f"Excepción inyectada: {type(exception).__name__}('{exception}')"
        )

        # 2. db.rollback() fue llamado (sesión limpia)
        mock_db.rollback.assert_called_once(), (
            f"db.rollback() debería haberse llamado exactamente una vez para "
            f"limpiar la sesión después de {type(exception).__name__}('{exception}'). "
            f"Llamadas a rollback: {mock_db.rollback.call_count}"
        )

        # 3. db.commit() NO fue llamado (la operación falló antes)
        mock_db.commit.assert_not_called(), (
            f"db.commit() NO debería haberse llamado cuando db.execute() lanza "
            f"{type(exception).__name__}('{exception}'). "
            f"Llamadas a commit: {mock_db.commit.call_count}"
        )

    @given(
        exception=st.sampled_from([
            IntegrityError("duplicate key", {}, None),
            OperationalError("connection refused", {}, None),
            TimeoutError("query timeout"),
            RuntimeError("internal error"),
            ConnectionError("network unreachable"),
            Exception("unknown failure"),
        ]),
        client_ip=ipv6_strategy,
        hostname_header=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
        user_header=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
    )
    @settings(max_examples=100)
    def test_resiliencia_con_variedad_de_headers_e_ips(
        self,
        exception: Exception,
        client_ip: str,
        hostname_header,
        user_header,
    ):
        """
        Independientemente de la combinación de headers y tipo de IP (IPv6),
        cualquier excepción en db.execute se maneja sin propagarse.
        El rollback siempre se ejecuta y la función retorna None.

        **Validates: Requirements 5.1**
        """
        # Preparar mock del request con headers variables
        mock_request = MagicMock()
        real_headers = {}
        if hostname_header is not None:
            real_headers["X-Workstation-ID"] = hostname_header
        if user_header is not None:
            real_headers["X-Workstation-Local-IP"] = user_header

        mock_request.headers = MagicMock()
        mock_request.headers.get = lambda key, default=None: real_headers.get(key, default)

        # Preparar mock de la sesión DB que lanza la excepción
        mock_db = MagicMock()
        mock_db.execute.side_effect = exception
        mock_db.rollback = MagicMock()
        mock_db.commit = MagicMock()

        # Ejecutar — NUNCA debe propagar la excepción
        with patch(
            "app.api.v1.endpoints.updates.get_client_ip",
            return_value=client_ip,
        ):
            result = _register_pending_ip(mock_db, mock_request)

        # Verificaciones: la función es resiliente a cualquier fallo
        assert result is None, (
            f"La función debería retornar None ante fallo de BD. "
            f"Excepción: {type(exception).__name__}, IP: {client_ip}, "
            f"Headers: hostname={repr(hostname_header)}, user={repr(user_header)}"
        )

        mock_db.rollback.assert_called_once(), (
            f"rollback() no fue llamado tras {type(exception).__name__}. "
            f"La sesión de BD queda en estado sucio."
        )

        mock_db.commit.assert_not_called(), (
            f"commit() fue llamado erróneamente tras {type(exception).__name__}."
        )


# === PROPERTY 6: RESPUESTA HTTP 401 INVARIANTE PARA IPS NO AUTORIZADAS ===


class TestRespuestaHTTP401InvarianteParaIPsNoAutorizadas:
    """
    Feature: pending-ip-registration, Property 6: Respuesta HTTP 401 invariante para IPs no autorizadas

    Para cualquier dirección IP que no esté autorizada (ya sea completamente
    desconocida o ya registrada como pendiente), la respuesta del endpoint debe
    ser idéntica: HTTP 401 con body {"detail": "Workstation no autenticada"}.
    No debe haber diferencia observable por el cliente entre ambos casos.

    Se verifica a nivel de función check_update que en ambos escenarios
    (IP desconocida e IP pendiente) se lanza HTTPException 401 con detail
    idéntico, garantizando indistinguibilidad para el cliente.

    **Validates: Requirements 3.1, 3.2, 3.4**
    """

    def _simulate_check_update_for_unauthorized_ip(self, ip_address: str, ip_exists_as_pending: bool):
        """
        Simula la ejecución de check_update para una IP no autorizada.

        Mockea:
        - get_client_ip → retorna la IP generada
        - _identify_workstation → lanza HTTPException 401
        - db.query(PublicIP).filter(...).first() → retorna None (ip no autorizada)
        - _register_pending_ip → no-op (validado en otras properties)

        Args:
            ip_address: La IP a simular
            ip_exists_as_pending: True si la IP ya existe como pendiente,
                                  False si es completamente desconocida.
                                  En ambos casos, la query con is_authorized=True
                                  retorna None.

        Returns:
            La HTTPException capturada (status_code y detail)
        """
        from app.api.v1.endpoints.updates import check_update

        # Mock del request sin Authorization header
        mock_request = MagicMock()
        mock_request.headers = MagicMock()
        mock_request.headers.get = lambda key, default=None: {}.get(key, default)

        # Mock de la sesión de BD
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        # La query de PublicIP con is_authorized=True siempre retorna None
        # (la IP no está autorizada, sea desconocida o pendiente)
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        # Mockear _identify_workstation para lanzar 401
        # Mockear get_client_ip para retornar la IP generada
        # Mockear _register_pending_ip como no-op
        with patch(
            "app.api.v1.endpoints.updates.get_client_ip",
            return_value=ip_address,
        ), patch(
            "app.api.v1.endpoints.updates._identify_workstation",
            side_effect=HTTPException(
                status_code=401,
                detail="Workstation no autenticada",
            ),
        ), patch(
            "app.api.v1.endpoints.updates._register_pending_ip",
        ):
            # Ejecutar check_update y capturar la HTTPException
            try:
                check_update(request=mock_request, db=mock_db)
                # Si no lanza excepción, es un fallo
                return None
            except HTTPException as exc:
                return exc

    @given(
        ip_address=valid_ip_strategy,
    )
    @settings(max_examples=100)
    def test_ip_desconocida_retorna_401_con_body_correcto(self, ip_address: str):
        """
        Para cualquier IP desconocida (no existe en la tabla public_ips),
        check_update lanza HTTPException 401 con detail "Workstation no autenticada".

        **Validates: Requirements 3.1, 3.4**
        """
        exc = self._simulate_check_update_for_unauthorized_ip(
            ip_address, ip_exists_as_pending=False
        )

        # Verificar que se lanzó HTTPException
        assert exc is not None, (
            f"check_update no lanzó HTTPException para IP desconocida '{ip_address}'"
        )

        # Verificar status code HTTP 401
        assert exc.status_code == 401, (
            f"Se esperaba HTTP 401 para IP desconocida '{ip_address}', "
            f"pero se obtuvo HTTP {exc.status_code}. "
            f"Detail: {exc.detail}"
        )

        # Verificar detail idéntico al esperado
        assert exc.detail == "Workstation no autenticada", (
            f"Detail incorrecto para IP desconocida '{ip_address}'. "
            f"Esperado: 'Workstation no autenticada', "
            f"Obtenido: {repr(exc.detail)}"
        )

    @given(
        ip_address=valid_ip_strategy,
    )
    @settings(max_examples=100)
    def test_ip_pendiente_retorna_401_con_body_correcto(self, ip_address: str):
        """
        Para cualquier IP que ya existe como pendiente (is_authorized=False),
        check_update lanza HTTPException 401 con detail "Workstation no autenticada".

        La query filtra por is_authorized=True, así que una IP pendiente
        no es encontrada → mismo flujo que IP desconocida.

        **Validates: Requirements 3.2, 3.4**
        """
        exc = self._simulate_check_update_for_unauthorized_ip(
            ip_address, ip_exists_as_pending=True
        )

        # Verificar que se lanzó HTTPException
        assert exc is not None, (
            f"check_update no lanzó HTTPException para IP pendiente '{ip_address}'"
        )

        # Verificar status code HTTP 401
        assert exc.status_code == 401, (
            f"Se esperaba HTTP 401 para IP pendiente '{ip_address}', "
            f"pero se obtuvo HTTP {exc.status_code}. "
            f"Detail: {exc.detail}"
        )

        # Verificar detail idéntico al esperado
        assert exc.detail == "Workstation no autenticada", (
            f"Detail incorrecto para IP pendiente '{ip_address}'. "
            f"Esperado: 'Workstation no autenticada', "
            f"Obtenido: {repr(exc.detail)}"
        )

    @given(
        ip_desconocida=valid_ip_strategy,
        ip_pendiente=valid_ip_strategy,
    )
    @settings(max_examples=100)
    def test_respuesta_identica_entre_ip_desconocida_y_pendiente(
        self, ip_desconocida: str, ip_pendiente: str
    ):
        """
        Para cualquier par de IPs (una desconocida y una pendiente), las
        respuestas de check_update deben ser idénticas en status_code y detail.
        El cliente no puede distinguir entre ambos casos.

        **Validates: Requirements 3.1, 3.2, 3.4**
        """
        # Caso 1: IP completamente desconocida
        exc_desconocida = self._simulate_check_update_for_unauthorized_ip(
            ip_desconocida, ip_exists_as_pending=False
        )

        # Caso 2: IP ya registrada como pendiente (is_authorized=False)
        exc_pendiente = self._simulate_check_update_for_unauthorized_ip(
            ip_pendiente, ip_exists_as_pending=True
        )

        # Verificar que ambas lanzaron HTTPException
        assert exc_desconocida is not None, (
            f"check_update no lanzó HTTPException para IP desconocida '{ip_desconocida}'"
        )
        assert exc_pendiente is not None, (
            f"check_update no lanzó HTTPException para IP pendiente '{ip_pendiente}'"
        )

        # Verificar que los status codes son idénticos
        assert exc_desconocida.status_code == exc_pendiente.status_code, (
            f"Status codes difieren entre IP desconocida y pendiente. "
            f"Desconocida ({ip_desconocida}): {exc_desconocida.status_code}, "
            f"Pendiente ({ip_pendiente}): {exc_pendiente.status_code}"
        )

        # Verificar que los details son idénticos
        assert exc_desconocida.detail == exc_pendiente.detail, (
            f"Details difieren entre IP desconocida y pendiente. "
            f"Desconocida ({ip_desconocida}): {repr(exc_desconocida.detail)}, "
            f"Pendiente ({ip_pendiente}): {repr(exc_pendiente.detail)}"
        )

        # Verificar el contenido exacto esperado
        assert exc_desconocida.status_code == 401, (
            f"Status code no es 401. Obtenido: {exc_desconocida.status_code}"
        )
        assert exc_desconocida.detail == "Workstation no autenticada", (
            f"Detail no coincide con el esperado. "
            f"Obtenido: {repr(exc_desconocida.detail)}"
        )
