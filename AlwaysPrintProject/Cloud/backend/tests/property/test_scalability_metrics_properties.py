"""
Property tests para métricas de escalabilidad del sistema.

Verifica propiedades universales de los colectores de métricas de escalabilidad.

Feature: system-status-metrics, Property 2: WebSocket total is sum of components
Feature: system-status-metrics, Property 1: Graceful degradation under partial collector failures
"""

import asyncio
from unittest.mock import patch, MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.scalability_metrics import ScalabilityMetricsCollector
from app.schemas.scalability_metrics import ScalabilityMetricsResponse


# === PROPERTY 2: WEBSOCKET TOTAL IS SUM OF COMPONENTS ===


class TestWebSocketTotalIsSumOfComponents:
    """
    Property 2: WebSocket total is sum of components.

    Para cualquier entero no negativo workstation_count y cualquier entero no negativo
    operator_count, el campo total en WebSocketMetricsResponse SHALL ser igual a
    workstation_count + operator_count.

    **Validates: Requirements 2.3**
    """

    @given(
        workstation_count=st.integers(min_value=0, max_value=10000),
        operator_count=st.integers(min_value=0, max_value=1000),
    )
    @settings(max_examples=100)
    def test_total_equals_workstation_plus_operator(
        self, workstation_count: int, operator_count: int
    ):
        """
        El campo total de WebSocketMetricsResponse siempre es igual a
        workstation_count + operator_count para cualquier combinación válida.

        **Validates: Requirements 2.3**
        """
        # Preparar mock del connection_manager para retornar los valores generados
        mock_connection_manager = MagicMock()
        mock_connection_manager.get_connection_count.return_value = {
            "workstations": workstation_count,
            "operators": operator_count,
        }

        # Mockear el módulo websocket_manager que se importa dentro del método
        mock_ws_module = MagicMock()
        mock_ws_module.connection_manager = mock_connection_manager

        with patch.dict(
            "sys.modules",
            {"app.services.websocket_manager": mock_ws_module},
        ):
            collector = ScalabilityMetricsCollector()
            resultado = collector.collect_websocket_metrics()

        # Verificar que total es exactamente la suma de workstations + operadores
        expected_total = workstation_count + operator_count
        assert resultado.total == expected_total, (
            f"total incorrecto. "
            f"Esperado: {expected_total} (workstation_count={workstation_count} + "
            f"operator_count={operator_count}), Obtenido: {resultado.total}"
        )

        # Verificar también que los conteos individuales se preservan correctamente
        assert resultado.workstation_count == workstation_count, (
            f"workstation_count incorrecto. "
            f"Esperado: {workstation_count}, Obtenido: {resultado.workstation_count}"
        )
        assert resultado.operator_count == operator_count, (
            f"operator_count incorrecto. "
            f"Esperado: {operator_count}, Obtenido: {resultado.operator_count}"
        )

        # Verificar que data_available es True cuando el ConnectionManager responde
        assert resultado.data_available is True, (
            f"data_available debería ser True cuando el ConnectionManager responde, "
            f"pero fue {resultado.data_available}"
        )


# === PROPERTY 3: VMRSS KB TO MB CONVERSION ===


class TestVmRSSKbToMbConversion:
    """
    Property 3: VmRSS kB to MB conversion.

    Para cualquier entero no negativo vmrss_kb leído de /proc/self/status,
    el output rss_mb SHALL ser igual a round(vmrss_kb / 1024, 2).

    Feature: system-status-metrics, Property 3: VmRSS kB to MB conversion

    **Validates: Requirements 3.1**
    """

    @given(
        vmrss_kb=st.integers(min_value=0, max_value=100000000),
    )
    @settings(max_examples=100)
    def test_rss_mb_equals_vmrss_kb_divided_by_1024_rounded(self, vmrss_kb: int):
        """
        El campo rss_mb siempre es igual a round(vmrss_kb / 1024, 2) para cualquier
        valor no negativo de VmRSS leído de /proc/self/status.

        Se mockea /proc/self/status con el valor generado y se verifica que
        collect_python_memory() retorne la conversión correcta.

        **Validates: Requirements 3.1**
        """
        # Construir contenido simulado de /proc/self/status con el VmRSS generado
        proc_status_content = (
            "Name:\tpython3\n"
            "Umask:\t0022\n"
            "State:\tS (sleeping)\n"
            f"VmRSS:\t{vmrss_kb} kB\n"
            "VmSize:\t200000 kB\n"
            "Threads:\t4\n"
        )

        # Mockear la lectura de /proc/self/status y el connection_manager
        mock_connection_manager = MagicMock()
        mock_connection_manager.get_connection_count.return_value = {
            "workstations": 0,
            "operators": 0,
        }
        mock_ws_module = MagicMock()
        mock_ws_module.connection_manager = mock_connection_manager

        from unittest.mock import mock_open

        with patch("builtins.open", mock_open(read_data=proc_status_content)):
            with patch.dict(
                "sys.modules",
                {"app.services.websocket_manager": mock_ws_module},
            ):
                collector = ScalabilityMetricsCollector()
                resultado = collector.collect_python_memory()

        # Verificar que el resultado no es None (la lectura fue exitosa)
        assert resultado is not None, (
            f"collect_python_memory() retornó None con VmRSS={vmrss_kb} kB válido"
        )

        # Verificar la conversión: rss_mb == round(vmrss_kb / 1024, 2)
        expected_rss_mb = round(vmrss_kb / 1024, 2)
        assert resultado.rss_mb == expected_rss_mb, (
            f"Conversión VmRSS incorrecta. "
            f"Esperado: round({vmrss_kb} / 1024, 2) = {expected_rss_mb}, "
            f"Obtenido: {resultado.rss_mb}"
        )


# === PROPERTY 4: MEMORY PER WORKSTATION AVERAGE ===


class TestMemoryPerWorkstationAverage:
    """
    Property 4: Memory per workstation average.

    Para cualquier rss_mb >= 0 y ws_count > 0, el output avg_per_workstation_mb
    SHALL ser igual a round(rss_mb / ws_count, 2).

    Feature: system-status-metrics, Property 4: Memory per workstation average

    **Validates: Requirements 3.3**
    """

    @given(
        rss_mb=st.floats(min_value=0, max_value=100000, allow_nan=False, allow_infinity=False),
        ws_count=st.integers(min_value=1, max_value=10000),
    )
    @settings(max_examples=100)
    def test_avg_per_workstation_equals_rss_mb_divided_by_ws_count(
        self, rss_mb: float, ws_count: int
    ):
        """
        El campo avg_per_workstation_mb siempre es igual a round(rss_mb / ws_count, 2)
        para cualquier rss_mb >= 0 y ws_count > 0.

        Se verifica directamente el cálculo del promedio de memoria por workstation.

        **Validates: Requirements 3.3**
        """
        # Calcular el valor esperado según la propiedad definida
        expected_avg = round(rss_mb / ws_count, 2)

        # Convertir rss_mb de vuelta a vmrss_kb para simular /proc/self/status
        # Nota: se usa el valor redondeado que generaría el colector para evitar
        # discrepancias de redondeo intermedio
        vmrss_kb = round(rss_mb * 1024)
        # El rss_mb real que calcula el colector es round(vmrss_kb / 1024, 2)
        actual_rss_mb = round(vmrss_kb / 1024, 2)
        # Recalcular expected_avg con el rss_mb real del colector
        expected_avg = round(actual_rss_mb / ws_count, 2)

        # Construir contenido simulado de /proc/self/status
        proc_status_content = (
            "Name:\tpython3\n"
            "Umask:\t0022\n"
            "State:\tS (sleeping)\n"
            f"VmRSS:\t{vmrss_kb} kB\n"
            "VmSize:\t200000 kB\n"
            "Threads:\t4\n"
        )

        # Mockear connection_manager con ws_count workstations
        mock_connection_manager = MagicMock()
        mock_connection_manager.get_connection_count.return_value = {
            "workstations": ws_count,
            "operators": 0,
        }
        mock_ws_module = MagicMock()
        mock_ws_module.connection_manager = mock_connection_manager

        from unittest.mock import mock_open

        with patch("builtins.open", mock_open(read_data=proc_status_content)):
            with patch.dict(
                "sys.modules",
                {"app.services.websocket_manager": mock_ws_module},
            ):
                collector = ScalabilityMetricsCollector()
                resultado = collector.collect_python_memory()

        # Verificar que el resultado no es None
        assert resultado is not None, (
            f"collect_python_memory() retornó None con VmRSS válido"
        )

        # Verificar el promedio por workstation
        assert resultado.avg_per_workstation_mb == expected_avg, (
            f"Promedio por workstation incorrecto. "
            f"Esperado: round({actual_rss_mb} / {ws_count}, 2) = {expected_avg}, "
            f"Obtenido: {resultado.avg_per_workstation_mb}"
        )


# === PROPERTY 6: NETWORK INTERFACE TRAFFIC SUMMING ===


class TestNetworkInterfaceTrafficSumming:
    """
    Property 6: Network interface traffic summing.

    Para cualquier contenido parseado de /proc/net/dev con N interfaces no-loopback,
    cada una con valores rx_bytes y tx_bytes, el total rx_bytes de salida SHALL ser
    igual a la suma de todos los rx_bytes individuales de cada interfaz, y lo mismo
    para tx_bytes.

    **Validates: Requirements 5.1**
    """

    @given(
        interfaces=st.lists(
            st.tuples(
                st.sampled_from(["eth0", "eth1", "wlan0", "enp0s3", "docker0", "br-lan"]),
                st.integers(min_value=0, max_value=2**48),  # rx_bytes
                st.integers(min_value=0, max_value=2**48),  # tx_bytes
            ),
            min_size=1,
            max_size=8,
        )
    )
    @settings(max_examples=100)
    def test_total_rx_tx_equals_sum_of_all_interfaces(self, interfaces):
        """
        El total de rx_bytes y tx_bytes retornado por _parse_proc_net_dev
        es igual a la suma de los bytes de todas las interfaces no-loopback.

        **Validates: Requirements 5.1**
        """
        # Construir contenido simulado de /proc/net/dev con las interfaces generadas
        # Formato real de /proc/net/dev:
        # Inter-|   Receive                                                |  Transmit
        #  face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets ...
        #   eth0: rx_bytes rx_packets rx_errs rx_drop rx_fifo rx_frame rx_compressed rx_multicast tx_bytes tx_packets tx_errs tx_drop tx_fifo tx_colls tx_carrier tx_compressed
        lines = [
            "Inter-|   Receive                                                |  Transmit\n",
            " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n",
        ]

        for iface_name, rx_bytes, tx_bytes in interfaces:
            # Generar campos: rx_bytes, rx_packets(0), rx_errs(0), rx_drop(0),
            #   rx_fifo(0), rx_frame(0), rx_compressed(0), rx_multicast(0),
            #   tx_bytes, tx_packets(0), tx_errs(0), tx_drop(0), tx_fifo(0),
            #   tx_colls(0), tx_carrier(0), tx_compressed(0)
            line = f"  {iface_name}: {rx_bytes} 0 0 0 0 0 0 0 {tx_bytes} 0 0 0 0 0 0 0\n"
            lines.append(line)

        proc_net_dev_content = "".join(lines)

        # Mockear open("/proc/net/dev") para retornar nuestro contenido generado
        from unittest.mock import mock_open

        m = mock_open(read_data=proc_net_dev_content)

        with patch("builtins.open", m):
            collector = ScalabilityMetricsCollector()
            resultado = collector._parse_proc_net_dev()

        # Calcular la suma esperada de todas las interfaces (todas son no-loopback)
        expected_rx = sum(rx for _, rx, _ in interfaces)
        expected_tx = sum(tx for _, _, tx in interfaces)

        assert resultado.rx_bytes == expected_rx, (
            f"rx_bytes incorrecto. "
            f"Esperado: {expected_rx}, Obtenido: {resultado.rx_bytes}. "
            f"Interfaces: {interfaces}"
        )
        assert resultado.tx_bytes == expected_tx, (
            f"tx_bytes incorrecto. "
            f"Esperado: {expected_tx}, Obtenido: {resultado.tx_bytes}. "
            f"Interfaces: {interfaces}"
        )

    @given(
        non_lo_interfaces=st.lists(
            st.tuples(
                st.sampled_from(["eth0", "eth1", "wlan0", "enp0s3"]),
                st.integers(min_value=0, max_value=2**48),
                st.integers(min_value=0, max_value=2**48),
            ),
            min_size=1,
            max_size=5,
        ),
        lo_rx=st.integers(min_value=0, max_value=2**48),
        lo_tx=st.integers(min_value=0, max_value=2**48),
    )
    @settings(max_examples=100)
    def test_loopback_interface_excluded_from_sum(self, non_lo_interfaces, lo_rx, lo_tx):
        """
        La interfaz loopback (lo) no se incluye en la suma de rx_bytes y tx_bytes.

        **Validates: Requirements 5.1**
        """
        # Construir contenido con interfaces no-loopback + la interfaz lo
        lines = [
            "Inter-|   Receive                                                |  Transmit\n",
            " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n",
        ]

        # Agregar interfaz loopback
        lines.append(f"    lo: {lo_rx} 0 0 0 0 0 0 0 {lo_tx} 0 0 0 0 0 0 0\n")

        # Agregar interfaces no-loopback
        for iface_name, rx_bytes, tx_bytes in non_lo_interfaces:
            lines.append(f"  {iface_name}: {rx_bytes} 0 0 0 0 0 0 0 {tx_bytes} 0 0 0 0 0 0 0\n")

        proc_net_dev_content = "".join(lines)

        from unittest.mock import mock_open

        m = mock_open(read_data=proc_net_dev_content)

        with patch("builtins.open", m):
            collector = ScalabilityMetricsCollector()
            resultado = collector._parse_proc_net_dev()

        # Solo las interfaces no-loopback deben sumarse
        expected_rx = sum(rx for _, rx, _ in non_lo_interfaces)
        expected_tx = sum(tx for _, _, tx in non_lo_interfaces)

        assert resultado.rx_bytes == expected_rx, (
            f"rx_bytes incluyó loopback incorrectamente. "
            f"Esperado: {expected_rx}, Obtenido: {resultado.rx_bytes}"
        )
        assert resultado.tx_bytes == expected_tx, (
            f"tx_bytes incluyó loopback incorrectamente. "
            f"Esperado: {expected_tx}, Obtenido: {resultado.tx_bytes}"
        )


# === PROPERTY 7: NETWORK RATE CALCULATION ===


class TestNetworkRateCalculation:
    """
    Property 7: Network rate calculation.

    Para cualquier dos lecturas consecutivas de red (prev_bytes, prev_time) y
    (curr_bytes, curr_time) donde curr_bytes >= prev_bytes y
    (curr_time - prev_time) >= 0.5 segundos, la tasa calculada SHALL ser igual a
    (curr_bytes - prev_bytes) / (curr_time - prev_time).

    **Validates: Requirements 5.2**
    """

    @given(
        prev_rx=st.integers(min_value=0, max_value=2**47),
        prev_tx=st.integers(min_value=0, max_value=2**47),
        delta_rx=st.integers(min_value=0, max_value=2**47),
        delta_tx=st.integers(min_value=0, max_value=2**47),
        prev_time=st.floats(min_value=1_000_000_000.0, max_value=2_000_000_000.0),
        delta_t=st.floats(min_value=0.5, max_value=3600.0),
    )
    @settings(max_examples=100)
    def test_rate_equals_delta_bytes_divided_by_delta_time(
        self, prev_rx, prev_tx, delta_rx, delta_tx, prev_time, delta_t
    ):
        """
        La tasa de transferencia calculada es exactamente
        (curr_bytes - prev_bytes) / (curr_time - prev_time)
        cuando curr_bytes >= prev_bytes y delta_t >= 0.5 segundos.

        **Validates: Requirements 5.2**
        """
        from app.services.scalability_metrics import NetReading

        # Calcular valores actuales a partir de prev + delta
        curr_rx = prev_rx + delta_rx
        curr_tx = prev_tx + delta_tx
        curr_time = prev_time + delta_t

        # Configurar el colector con estado previo (simular que ya hubo una lectura)
        collector = ScalabilityMetricsCollector()
        collector._prev_net_reading = NetReading(rx_bytes=prev_rx, tx_bytes=prev_tx)
        collector._prev_net_timestamp = prev_time
        collector._last_rates = None

        # Mockear _parse_proc_net_dev para retornar la lectura actual
        current_reading = NetReading(rx_bytes=curr_rx, tx_bytes=curr_tx)

        with patch.object(collector, "_parse_proc_net_dev", return_value=current_reading):
            with patch("app.services.scalability_metrics.time.time", return_value=curr_time):
                resultado = collector.collect_network_traffic()

        # Calcular tasas esperadas
        expected_rx_rate = (curr_rx - prev_rx) / delta_t
        expected_tx_rate = (curr_tx - prev_tx) / delta_t

        # Verificar que las tasas coinciden (usar tolerancia para flotantes)
        assert resultado.rx_rate_bps is not None, (
            "rx_rate_bps no debería ser None cuando delta_t >= 0.5 y no hay counter reset"
        )
        assert resultado.tx_rate_bps is not None, (
            "tx_rate_bps no debería ser None cuando delta_t >= 0.5 y no hay counter reset"
        )

        # Verificar igualdad con tolerancia relativa para aritmética de punto flotante
        assert abs(resultado.rx_rate_bps - expected_rx_rate) < 1e-6 * max(1, abs(expected_rx_rate)), (
            f"rx_rate_bps incorrecto. "
            f"Esperado: {expected_rx_rate}, Obtenido: {resultado.rx_rate_bps}. "
            f"delta_rx={delta_rx}, delta_t={delta_t}"
        )
        assert abs(resultado.tx_rate_bps - expected_tx_rate) < 1e-6 * max(1, abs(expected_tx_rate)), (
            f"tx_rate_bps incorrecto. "
            f"Esperado: {expected_tx_rate}, Obtenido: {resultado.tx_rate_bps}. "
            f"delta_tx={delta_tx}, delta_t={delta_t}"
        )

        # Verificar que los bytes totales actuales se reportan correctamente
        assert resultado.rx_bytes == curr_rx, (
            f"rx_bytes incorrecto. Esperado: {curr_rx}, Obtenido: {resultado.rx_bytes}"
        )
        assert resultado.tx_bytes == curr_tx, (
            f"tx_bytes incorrecto. Esperado: {curr_tx}, Obtenido: {resultado.tx_bytes}"
        )


# === PROPERTY 1: GRACEFUL DEGRADATION UNDER PARTIAL COLLECTOR FAILURES ===


# Estrategia: subconjunto aleatorio de colectores que fallarán
_collector_names = [
    "collect_websocket_metrics",
    "collect_python_memory",
    "collect_file_descriptors",
    "collect_network_traffic",
    "collect_db_pool_metrics",
]

# Mapeo de nombre de colector a campo correspondiente en ScalabilityMetricsResponse
_COLLECTOR_TO_FIELD = {
    "collect_websocket_metrics": "websocket",
    "collect_python_memory": "python_memory",
    "collect_file_descriptors": "file_descriptors",
    "collect_network_traffic": "network",
    "collect_db_pool_metrics": "db_pool",
}


class TestGracefulDegradationUnderPartialCollectorFailures:
    """
    Property 1: Graceful degradation under partial collector failures.

    Para cualquier subconjunto de los 5 colectores de métricas que lanzan excepciones,
    el método collect_all_metrics() SHALL retornar un ScalabilityMetricsResponse válido
    donde solo los colectores que fallaron producen valores null y todos los colectores
    que no fallan producen sus resultados esperados no-null.

    Feature: system-status-metrics, Property 1: Graceful degradation under partial collector failures

    **Validates: Requirements 1.5, 7.3**
    """

    @given(
        failing_collectors=st.lists(
            st.sampled_from(_collector_names),
            unique=True,
            min_size=0,
            max_size=5,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_partial_failures_produce_null_only_for_failed_collectors(
        self, failing_collectors: list,
    ):
        """
        Para cualquier subconjunto de colectores que fallan, collect_all_metrics()
        retorna un ScalabilityMetricsResponse válido donde:
        - Los colectores que fallan tienen valor null en su campo correspondiente
        - Los colectores que no fallan tienen valor no-null en su campo correspondiente
        - La respuesta siempre es un ScalabilityMetricsResponse válido (no excepción)

        **Validates: Requirements 1.5, 7.3**
        """
        # Crear instancia del colector
        collector = ScalabilityMetricsCollector()

        # Preparar valores de retorno para colectores que NO fallan
        mock_websocket = MagicMock()
        mock_websocket.workstation_count = 10
        mock_websocket.operator_count = 2
        mock_websocket.total = 12
        mock_websocket.data_available = True

        mock_memory = MagicMock()
        mock_memory.rss_mb = 128.5
        mock_memory.container_total_mb = 512.0
        mock_memory.avg_per_workstation_mb = 12.85

        mock_fd = MagicMock()
        mock_fd.open_count = 50
        mock_fd.limit = 1024
        mock_fd.usage_percent = 4.9

        mock_network = MagicMock()
        mock_network.rx_bytes = 1000000
        mock_network.tx_bytes = 500000
        mock_network.rx_rate_bps = 1000.0
        mock_network.tx_rate_bps = 500.0

        mock_db_pool = MagicMock()
        mock_db_pool.checked_out = 3
        mock_db_pool.idle = 7
        mock_db_pool.pool_size = 10
        mock_db_pool.overflow = 0
        mock_db_pool.max_overflow = 5
        mock_db_pool.pg_active_connections = 2
        mock_db_pool.usage_percent = 30.0

        # Mapeo de nombre de colector a su mock de retorno
        mock_returns = {
            "collect_websocket_metrics": mock_websocket,
            "collect_python_memory": mock_memory,
            "collect_file_descriptors": mock_fd,
            "collect_network_traffic": mock_network,
            "collect_db_pool_metrics": mock_db_pool,
        }

        # Configurar side_effect para cada colector: excepción si está en failing_collectors,
        # mock de retorno si no
        def make_side_effect(name, return_value):
            """Crea un side_effect que lanza excepción si el colector debe fallar."""
            if name in failing_collectors:
                return RuntimeError(f"Fallo simulado en {name}")
            return return_value

        # Patchear los métodos del colector
        patches = {}
        for name in _collector_names:
            if name in failing_collectors:
                patches[name] = patch.object(
                    collector, name, side_effect=RuntimeError(f"Fallo simulado en {name}")
                )
            else:
                patches[name] = patch.object(
                    collector, name, return_value=mock_returns[name]
                )

        # Aplicar todos los patches y ejecutar collect_all_metrics
        started_patches = {name: p.start() for name, p in patches.items()}
        try:
            # Ejecutar el método asíncrono (pasamos db=None, el colector de db_pool
            # se invoca solo cuando db no es None, así que forzamos con un mock de db)
            mock_db = MagicMock()
            resultado = asyncio.run(collector.collect_all_metrics(db=mock_db))
        finally:
            # Detener todos los patches
            for p in patches.values():
                p.stop()

        # Verificar que el resultado es un ScalabilityMetricsResponse válido
        assert isinstance(resultado, ScalabilityMetricsResponse), (
            f"collect_all_metrics() no retornó un ScalabilityMetricsResponse. "
            f"Tipo obtenido: {type(resultado)}"
        )

        # Verificar que collected_at está presente (siempre debe estar)
        assert resultado.collected_at is not None, (
            "collected_at no debería ser None en la respuesta"
        )

        # Verificar que los colectores que fallaron tienen valor null
        for collector_name in failing_collectors:
            field_name = _COLLECTOR_TO_FIELD[collector_name]
            field_value = getattr(resultado, field_name)
            assert field_value is None, (
                f"El colector '{collector_name}' falló pero el campo '{field_name}' "
                f"no es null. Valor obtenido: {field_value}"
            )

        # Verificar que los colectores que NO fallaron tienen valor no-null
        non_failing = [n for n in _collector_names if n not in failing_collectors]
        for collector_name in non_failing:
            field_name = _COLLECTOR_TO_FIELD[collector_name]
            field_value = getattr(resultado, field_name)
            assert field_value is not None, (
                f"El colector '{collector_name}' no falló pero el campo '{field_name}' "
                f"es null. Colectores que fallaron: {failing_collectors}"
            )
