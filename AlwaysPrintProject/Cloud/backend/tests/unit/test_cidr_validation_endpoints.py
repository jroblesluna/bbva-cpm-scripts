"""
Tests unitarios para validación CIDR en endpoints de registro.

Verifica que:
- CIDR válido acepta registro (schema Pydantic pasa validación)
- CIDR inválido retorna error de validación (422)
- CIDR con prefix fuera de rango 8-30 retorna error (422)
- Normalización funciona correctamente (192.168.1.50/24 → 192.168.1.0/24)

**Validates: Requirements 2.2, 2.3, 9.1, 9.2, 9.3**
"""

import pytest
from pydantic import ValidationError

from app.schemas.workstation import WorkstationRegisterRequest


class TestCidrValidoAceptaRegistro:
    """Tests para verificar que CIDRs válidos son aceptados."""

    def test_cidr_clase_c_valido(self):
        """CIDR /24 típico de red local es aceptado."""
        request = WorkstationRegisterRequest(
            ip_private="192.168.1.50",
            cidr="192.168.1.0/24"
        )
        assert request.cidr == "192.168.1.0/24"

    def test_cidr_clase_b_valido(self):
        """CIDR /16 de red corporativa es aceptado."""
        request = WorkstationRegisterRequest(
            ip_private="10.0.1.100",
            cidr="10.0.0.0/16"
        )
        assert request.cidr == "10.0.0.0/16"

    def test_cidr_clase_a_valido(self):
        """CIDR /8 de red grande es aceptado (límite inferior del rango)."""
        request = WorkstationRegisterRequest(
            ip_private="10.1.2.3",
            cidr="10.0.0.0/8"
        )
        assert request.cidr == "10.0.0.0/8"

    def test_cidr_prefix_30_valido(self):
        """CIDR /30 es aceptado (límite superior del rango)."""
        request = WorkstationRegisterRequest(
            ip_private="192.168.1.1",
            cidr="192.168.1.0/30"
        )
        assert request.cidr == "192.168.1.0/30"

    def test_cidr_con_tray_version(self):
        """CIDR válido con tray_version opcional es aceptado."""
        request = WorkstationRegisterRequest(
            ip_private="172.16.0.10",
            cidr="172.16.0.0/12",
            tray_version="2.1.0.0"
        )
        assert request.cidr == "172.16.0.0/12"
        assert request.tray_version == "2.1.0.0"


class TestCidrInvalidoRetorna422:
    """Tests para verificar que CIDRs inválidos son rechazados con error."""

    def test_cidr_texto_aleatorio(self):
        """Texto que no es CIDR es rechazado."""
        with pytest.raises(ValidationError) as exc_info:
            WorkstationRegisterRequest(
                ip_private="192.168.1.50",
                cidr="no-es-un-cidr"
            )
        assert "CIDR inválido" in str(exc_info.value)

    def test_cidr_solo_ip_sin_prefix(self):
        """IP sin prefix length es rechazada."""
        with pytest.raises(ValidationError) as exc_info:
            WorkstationRegisterRequest(
                ip_private="192.168.1.50",
                cidr="192.168.1.0"
            )
        assert "CIDR inválido" in str(exc_info.value)

    def test_cidr_vacio(self):
        """String vacío es rechazado."""
        with pytest.raises(ValidationError) as exc_info:
            WorkstationRegisterRequest(
                ip_private="192.168.1.50",
                cidr=""
            )
        assert "CIDR inválido" in str(exc_info.value)

    def test_cidr_octeto_fuera_de_rango(self):
        """IP con octeto > 255 es rechazada."""
        with pytest.raises(ValidationError) as exc_info:
            WorkstationRegisterRequest(
                ip_private="192.168.1.50",
                cidr="256.168.1.0/24"
            )
        assert "CIDR inválido" in str(exc_info.value)

    def test_cidr_ipv6_rechazado(self):
        """Dirección IPv6 es rechazada (solo se admite IPv4)."""
        with pytest.raises(ValidationError) as exc_info:
            WorkstationRegisterRequest(
                ip_private="192.168.1.50",
                cidr="2001:db8::/32"
            )
        # Puede fallar por IPv6 o por prefix fuera de rango
        error_str = str(exc_info.value)
        assert "CIDR inválido" in error_str or "IPv4" in error_str

    def test_cidr_sin_campo_obligatorio(self):
        """Registro sin campo cidr es rechazado."""
        with pytest.raises(ValidationError):
            WorkstationRegisterRequest(
                ip_private="192.168.1.50"
            )


class TestCidrPrefixFueraDeRango:
    """Tests para verificar que prefix length fuera de 8-30 es rechazado."""

    def test_prefix_menor_a_8(self):
        """Prefix /7 está fuera del rango permitido."""
        with pytest.raises(ValidationError) as exc_info:
            WorkstationRegisterRequest(
                ip_private="192.168.1.50",
                cidr="10.0.0.0/7"
            )
        error_str = str(exc_info.value)
        assert "prefix length" in error_str or "8" in error_str

    def test_prefix_0(self):
        """Prefix /0 (toda Internet) está fuera del rango permitido."""
        with pytest.raises(ValidationError) as exc_info:
            WorkstationRegisterRequest(
                ip_private="192.168.1.50",
                cidr="0.0.0.0/0"
            )
        error_str = str(exc_info.value)
        assert "prefix length" in error_str or "8" in error_str

    def test_prefix_31(self):
        """Prefix /31 está fuera del rango permitido."""
        with pytest.raises(ValidationError) as exc_info:
            WorkstationRegisterRequest(
                ip_private="192.168.1.50",
                cidr="192.168.1.0/31"
            )
        error_str = str(exc_info.value)
        assert "prefix length" in error_str or "30" in error_str

    def test_prefix_32(self):
        """Prefix /32 (host individual) está fuera del rango permitido."""
        with pytest.raises(ValidationError) as exc_info:
            WorkstationRegisterRequest(
                ip_private="192.168.1.50",
                cidr="192.168.1.1/32"
            )
        error_str = str(exc_info.value)
        assert "prefix length" in error_str or "30" in error_str


class TestNormalizacionCidr:
    """Tests para verificar la normalización de CIDR a forma canónica."""

    def test_normaliza_host_bits_a_cero(self):
        """192.168.1.50/24 se normaliza a 192.168.1.0/24."""
        request = WorkstationRegisterRequest(
            ip_private="192.168.1.50",
            cidr="192.168.1.50/24"
        )
        assert request.cidr == "192.168.1.0/24"

    def test_normaliza_host_bits_clase_b(self):
        """172.16.5.100/16 se normaliza a 172.16.0.0/16."""
        request = WorkstationRegisterRequest(
            ip_private="172.16.5.100",
            cidr="172.16.5.100/16"
        )
        assert request.cidr == "172.16.0.0/16"

    def test_normaliza_host_bits_clase_a(self):
        """10.1.2.3/8 se normaliza a 10.0.0.0/8."""
        request = WorkstationRegisterRequest(
            ip_private="10.1.2.3",
            cidr="10.1.2.3/8"
        )
        assert request.cidr == "10.0.0.0/8"

    def test_cidr_ya_normalizado_no_cambia(self):
        """Un CIDR ya en forma canónica no se modifica."""
        request = WorkstationRegisterRequest(
            ip_private="192.168.1.50",
            cidr="192.168.1.0/24"
        )
        assert request.cidr == "192.168.1.0/24"

    def test_normaliza_prefix_20(self):
        """192.168.1.200/20 se normaliza a 192.168.0.0/20."""
        request = WorkstationRegisterRequest(
            ip_private="192.168.1.200",
            cidr="192.168.1.200/20"
        )
        assert request.cidr == "192.168.0.0/20"
