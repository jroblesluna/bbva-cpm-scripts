"""
Property tests para validación CIDR en endpoints de registro.

Verifica las propiedades de normalización y rechazo de CIDRs:
- Property 2: CIDR Normalization Idempotence
- Property 3: Invalid CIDR Rejection

**Validates: Requirements 2.2, 2.3, 9.1, 9.2, 9.3**
"""

import ipaddress
import string

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from pydantic import ValidationError

from app.schemas.workstation import WorkstationRegisterRequest


# === ESTRATEGIAS DE GENERACIÓN ===

# Octetos IPv4 válidos
_octet = st.integers(min_value=0, max_value=255)

# Prefijos CIDR válidos según requisitos (rango 8-30)
_valid_prefix = st.integers(min_value=8, max_value=30)


@st.composite
def valid_cidr_strategy(draw):
    """
    Genera un CIDR IPv4 válido con prefix en rango 8-30.

    Puede tener host bits encendidos (no necesariamente normalizado).
    Útil para verificar que la normalización funciona.
    """
    o1 = draw(_octet)
    o2 = draw(_octet)
    o3 = draw(_octet)
    o4 = draw(_octet)
    prefix = draw(_valid_prefix)

    raw_cidr = f"{o1}.{o2}.{o3}.{o4}/{prefix}"
    # Verificar que es parseable como red IPv4
    try:
        ipaddress.ip_network(raw_cidr, strict=False)
    except ValueError:
        assume(False)
        return None

    return raw_cidr


@st.composite
def normalized_cidr_strategy(draw):
    """
    Genera un CIDR IPv4 ya normalizado (host bits en cero).

    Útil para verificar idempotencia de la normalización.
    """
    o1 = draw(_octet)
    o2 = draw(_octet)
    o3 = draw(_octet)
    o4 = draw(_octet)
    prefix = draw(_valid_prefix)

    raw_cidr = f"{o1}.{o2}.{o3}.{o4}/{prefix}"
    try:
        network = ipaddress.ip_network(raw_cidr, strict=False)
    except ValueError:
        assume(False)
        return None

    return str(network)


@st.composite
def invalid_cidr_strategy(draw):
    """
    Genera strings que NO son CIDRs IPv4 válidos.

    Incluye: texto aleatorio, IPs sin prefix, prefixes inválidos, etc.
    """
    tipo = draw(st.sampled_from([
        "texto_aleatorio",
        "ip_sin_prefix",
        "prefix_invalido_alto",
        "prefix_invalido_bajo",
        "octeto_fuera_rango",
        "formato_incorrecto",
    ]))

    if tipo == "texto_aleatorio":
        # Texto que no es una dirección IP
        texto = draw(st.text(
            alphabet=string.ascii_letters + string.digits + ".-_@#",
            min_size=1,
            max_size=30
        ))
        # Asegurar que no sea accidentalmente un CIDR válido
        try:
            net = ipaddress.ip_network(texto, strict=False)
            if 8 <= net.prefixlen <= 30:
                assume(False)
        except (ValueError, TypeError):
            pass
        return texto

    elif tipo == "ip_sin_prefix":
        # IP válida pero sin prefix length
        o1 = draw(st.integers(min_value=1, max_value=254))
        o2 = draw(_octet)
        o3 = draw(_octet)
        o4 = draw(_octet)
        return f"{o1}.{o2}.{o3}.{o4}"

    elif tipo == "prefix_invalido_alto":
        # Prefix > 30 (fuera del rango permitido)
        o1 = draw(_octet)
        o2 = draw(_octet)
        o3 = draw(_octet)
        o4 = draw(_octet)
        prefix = draw(st.integers(min_value=31, max_value=32))
        return f"{o1}.{o2}.{o3}.{o4}/{prefix}"

    elif tipo == "prefix_invalido_bajo":
        # Prefix < 8 (fuera del rango permitido)
        o1 = draw(_octet)
        o2 = draw(_octet)
        o3 = draw(_octet)
        o4 = draw(_octet)
        prefix = draw(st.integers(min_value=0, max_value=7))
        return f"{o1}.{o2}.{o3}.{o4}/{prefix}"

    elif tipo == "octeto_fuera_rango":
        # Octeto > 255
        octeto_malo = draw(st.integers(min_value=256, max_value=999))
        o2 = draw(_octet)
        o3 = draw(_octet)
        o4 = draw(_octet)
        prefix = draw(_valid_prefix)
        return f"{octeto_malo}.{o2}.{o3}.{o4}/{prefix}"

    else:  # formato_incorrecto
        # Formatos que no son IP/prefix
        variantes = draw(st.sampled_from([
            "192.168.1",
            "192.168.1.0.0/24",
            "/24",
            "192.168.1.0/",
            "abc.def.ghi.jkl/24",
        ]))
        return variantes


# === PROPERTY 2: CIDR NORMALIZATION IDEMPOTENCE ===


class TestCidrNormalizationIdempotence:
    """
    Property 2: CIDR Normalization Idempotence.

    Para cualquier CIDR string válido, normalizar con
    ipaddress.ip_network(cidr, strict=False) SHALL ser idempotente —
    normalizar el resultado una segunda vez SHALL producir el mismo string.

    **Validates: Requirements 2.4, 9.3**
    """

    @given(cidr=valid_cidr_strategy())
    @settings(max_examples=200, deadline=None)
    def test_normalizacion_es_idempotente(self, cidr: str):
        """
        Normalizar un CIDR válido dos veces produce el mismo resultado.

        Primera normalización: el validator de Pydantic normaliza el CIDR.
        Segunda normalización: aplicar el validator al resultado no lo cambia.

        **Validates: Requirements 2.4, 9.3**
        """
        # Primera normalización (a través del schema Pydantic)
        request1 = WorkstationRegisterRequest(
            ip_private="10.0.0.1",
            cidr=cidr
        )
        primera_normalizacion = request1.cidr

        # Segunda normalización (pasar el resultado como input)
        request2 = WorkstationRegisterRequest(
            ip_private="10.0.0.1",
            cidr=primera_normalizacion
        )
        segunda_normalizacion = request2.cidr

        # Propiedad: f(f(x)) == f(x) — idempotencia
        assert primera_normalizacion == segunda_normalizacion, (
            f"La normalización NO es idempotente. "
            f"Input: '{cidr}' → Primera: '{primera_normalizacion}' → "
            f"Segunda: '{segunda_normalizacion}'"
        )

    @given(cidr=normalized_cidr_strategy())
    @settings(max_examples=200, deadline=None)
    def test_cidr_normalizado_no_cambia(self, cidr: str):
        """
        Un CIDR ya normalizado no se modifica al pasar por el validator.

        **Validates: Requirements 9.3**
        """
        request = WorkstationRegisterRequest(
            ip_private="10.0.0.1",
            cidr=cidr
        )

        # Propiedad: si el input ya está normalizado, el output es idéntico
        assert request.cidr == cidr, (
            f"CIDR normalizado fue modificado. "
            f"Input: '{cidr}' → Output: '{request.cidr}'"
        )

    @given(cidr=valid_cidr_strategy())
    @settings(max_examples=200, deadline=None)
    def test_resultado_normalizado_es_cidr_valido(self, cidr: str):
        """
        El resultado de la normalización siempre es un CIDR IPv4 válido
        con host bits en cero.

        **Validates: Requirements 9.3**
        """
        request = WorkstationRegisterRequest(
            ip_private="10.0.0.1",
            cidr=cidr
        )

        # Propiedad: el resultado es parseable como red IPv4 estricta
        network = ipaddress.ip_network(request.cidr, strict=True)
        assert network.version == 4, (
            f"El resultado no es IPv4: {request.cidr}"
        )
        assert 8 <= network.prefixlen <= 30, (
            f"Prefix fuera de rango: {network.prefixlen}"
        )


# === PROPERTY 3: INVALID CIDR REJECTION ===


class TestInvalidCidrRejection:
    """
    Property 3: Invalid CIDR Rejection.

    Para cualquier string que NO sea una notación IPv4 CIDR válida,
    o que tenga un prefix length fuera del rango 8-30, el validador
    CIDR SHALL rechazarlo y retornar un error descriptivo.

    **Validates: Requirements 2.3, 9.1, 9.2**
    """

    @given(cidr=invalid_cidr_strategy())
    @settings(max_examples=200, deadline=None)
    def test_cidr_invalido_es_rechazado(self, cidr: str):
        """
        Cualquier string que no sea un CIDR IPv4 válido con prefix 8-30
        es rechazado por el validator con ValidationError.

        **Validates: Requirements 2.3, 9.1, 9.2**
        """
        with pytest.raises(ValidationError) as exc_info:
            WorkstationRegisterRequest(
                ip_private="10.0.0.1",
                cidr=cidr
            )

        # Propiedad: el error contiene información descriptiva
        error_str = str(exc_info.value)
        assert "cidr" in error_str.lower() or "CIDR" in error_str, (
            f"El error no menciona 'cidr'. Input: '{cidr}', Error: {error_str}"
        )

    @given(prefix=st.integers(min_value=31, max_value=32))
    @settings(max_examples=50, deadline=None)
    def test_prefix_mayor_a_30_rechazado(self, prefix: int):
        """
        Prefix length > 30 siempre es rechazado.

        **Validates: Requirements 9.2**
        """
        cidr = f"192.168.1.0/{prefix}"

        with pytest.raises(ValidationError) as exc_info:
            WorkstationRegisterRequest(
                ip_private="10.0.0.1",
                cidr=cidr
            )

        error_str = str(exc_info.value)
        assert "prefix" in error_str.lower() or "30" in error_str, (
            f"Error no menciona prefix/30. Input: '{cidr}', Error: {error_str}"
        )

    @given(prefix=st.integers(min_value=0, max_value=7))
    @settings(max_examples=50, deadline=None)
    def test_prefix_menor_a_8_rechazado(self, prefix: int):
        """
        Prefix length < 8 siempre es rechazado.

        **Validates: Requirements 9.2**
        """
        cidr = f"10.0.0.0/{prefix}"

        with pytest.raises(ValidationError) as exc_info:
            WorkstationRegisterRequest(
                ip_private="10.0.0.1",
                cidr=cidr
            )

        error_str = str(exc_info.value)
        assert "prefix" in error_str.lower() or "8" in error_str, (
            f"Error no menciona prefix/8. Input: '{cidr}', Error: {error_str}"
        )
