"""
Property tests para la clasificación de días del certificado SSL.

Verifica que el SystemStatusCollector calcula correctamente los días restantes
del certificado SSL y clasifica el resultado según las reglas:
- "valid": más de 14 días restantes
- "warning": entre 1 y 14 días restantes
- "expired": 0 o menos días restantes

**Validates: Requirements 2.6**

Feature: system-status-monitoring, Property 6: SSL certificate days classification
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.system_status import SystemStatusCollector


# === ESTRATEGIAS DE GENERACIÓN ===

# Fecha base "ahora" fija para controlar el cálculo de días
_base_now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

# Días de diferencia entre expiración y ahora (rango amplio: -365 a +365)
_days_offset = st.integers(min_value=-365, max_value=365)

# Dominio de prueba
_test_domain = "test.example.com"


def _format_cert_date(dt: datetime) -> str:
    """
    Formatea una fecha al formato notAfter de certificados SSL.

    Formato: "%b %d %H:%M:%S %Y %Z" (ej: "Jan 15 12:00:00 2025 GMT")
    """
    return dt.strftime("%b %d %H:%M:%S %Y GMT")


# === PROPERTY 6: SSL CERTIFICATE DAYS CLASSIFICATION ===


class TestSSLDaysClassification:
    """
    Property 6: SSL certificate days classification.

    Para cualquier fecha de expiración de certificado SSL y fecha actual,
    el SSL checker SHALL calcular days_remaining = (expiry - now).days y
    clasificar como: "valid" si days_remaining > 14, "warning" si
    1 <= days_remaining <= 14, "expired" si days_remaining <= 0.

    **Validates: Requirements 2.6**
    """

    @given(days_offset=_days_offset)
    @settings(max_examples=200, deadline=None)
    def test_days_remaining_calculado_correctamente(self, days_offset: int):
        """
        Los días restantes se calculan como (expiry - now).days para cualquier
        combinación de fecha de expiración y fecha actual.

        **Validates: Requirements 2.6**
        """
        # Calcular fecha de expiración basada en el offset
        expiry_date = _base_now + timedelta(days=days_offset)
        cert_not_after = _format_cert_date(expiry_date)

        # Calcular días esperados
        expected_days = (expiry_date - _base_now).days

        # Preparar mock del certificado SSL
        mock_cert = {"notAfter": cert_not_after}

        # Mock de socket y ssl para inyectar el certificado
        with patch("app.services.system_status.socket.create_connection") as mock_conn, \
             patch("app.services.system_status.ssl.create_default_context") as mock_ssl_ctx, \
             patch("app.services.system_status.datetime") as mock_datetime:

            # Configurar mock de datetime.now para controlar "ahora"
            mock_datetime.now.return_value = _base_now
            # Permitir que strptime funcione normalmente
            mock_datetime.strptime = datetime.strptime

            # Configurar mock de socket/ssl
            mock_ssock = MagicMock()
            mock_ssock.getpeercert.return_value = mock_cert
            mock_ssock.__enter__ = MagicMock(return_value=mock_ssock)
            mock_ssock.__exit__ = MagicMock(return_value=False)

            mock_sock = MagicMock()
            mock_sock.__enter__ = MagicMock(return_value=mock_sock)
            mock_sock.__exit__ = MagicMock(return_value=False)

            mock_conn.return_value = mock_sock

            mock_ctx = MagicMock()
            mock_ctx.wrap_socket.return_value = mock_ssock
            mock_ssl_ctx.return_value = mock_ctx

            collector = SystemStatusCollector()
            result = collector._check_ssl(_test_domain)

        # Verificar que days_remaining se calculó correctamente
        assert result.details is not None, "details no debe ser None para SSL exitoso"
        assert result.details["days_remaining"] == expected_days, (
            f"days_remaining incorrecto. "
            f"Esperado: {expected_days}, Obtenido: {result.details['days_remaining']}"
        )

    @given(days_offset=st.integers(min_value=15, max_value=365))
    @settings(max_examples=200, deadline=None)
    def test_clasificacion_valid_cuando_dias_mayor_a_14(self, days_offset: int):
        """
        El certificado se clasifica como "valid" cuando days_remaining > 14.

        **Validates: Requirements 2.6**
        """
        # Fecha de expiración con más de 14 días
        expiry_date = _base_now + timedelta(days=days_offset)
        cert_not_after = _format_cert_date(expiry_date)

        mock_cert = {"notAfter": cert_not_after}

        with patch("app.services.system_status.socket.create_connection") as mock_conn, \
             patch("app.services.system_status.ssl.create_default_context") as mock_ssl_ctx, \
             patch("app.services.system_status.datetime") as mock_datetime:

            mock_datetime.now.return_value = _base_now
            mock_datetime.strptime = datetime.strptime

            mock_ssock = MagicMock()
            mock_ssock.getpeercert.return_value = mock_cert
            mock_ssock.__enter__ = MagicMock(return_value=mock_ssock)
            mock_ssock.__exit__ = MagicMock(return_value=False)

            mock_sock = MagicMock()
            mock_sock.__enter__ = MagicMock(return_value=mock_sock)
            mock_sock.__exit__ = MagicMock(return_value=False)

            mock_conn.return_value = mock_sock

            mock_ctx = MagicMock()
            mock_ctx.wrap_socket.return_value = mock_ssock
            mock_ssl_ctx.return_value = mock_ctx

            collector = SystemStatusCollector()
            result = collector._check_ssl(_test_domain)

        # Verificar clasificación "valid"
        assert result.details["classification"] == "valid", (
            f"Clasificación incorrecta para {days_offset} días restantes. "
            f"Esperado: 'valid', Obtenido: '{result.details['classification']}'"
        )
        # Verificar que is_available es True para "valid"
        assert result.is_available is True, (
            f"is_available debe ser True para clasificación 'valid'. "
            f"Obtenido: {result.is_available}"
        )

    @given(days_offset=st.integers(min_value=1, max_value=14))
    @settings(max_examples=200, deadline=None)
    def test_clasificacion_warning_cuando_dias_entre_1_y_14(self, days_offset: int):
        """
        El certificado se clasifica como "warning" cuando 1 <= days_remaining <= 14.

        **Validates: Requirements 2.6**
        """
        # Fecha de expiración entre 1 y 14 días
        expiry_date = _base_now + timedelta(days=days_offset)
        cert_not_after = _format_cert_date(expiry_date)

        mock_cert = {"notAfter": cert_not_after}

        with patch("app.services.system_status.socket.create_connection") as mock_conn, \
             patch("app.services.system_status.ssl.create_default_context") as mock_ssl_ctx, \
             patch("app.services.system_status.datetime") as mock_datetime:

            mock_datetime.now.return_value = _base_now
            mock_datetime.strptime = datetime.strptime

            mock_ssock = MagicMock()
            mock_ssock.getpeercert.return_value = mock_cert
            mock_ssock.__enter__ = MagicMock(return_value=mock_ssock)
            mock_ssock.__exit__ = MagicMock(return_value=False)

            mock_sock = MagicMock()
            mock_sock.__enter__ = MagicMock(return_value=mock_sock)
            mock_sock.__exit__ = MagicMock(return_value=False)

            mock_conn.return_value = mock_sock

            mock_ctx = MagicMock()
            mock_ctx.wrap_socket.return_value = mock_ssock
            mock_ssl_ctx.return_value = mock_ctx

            collector = SystemStatusCollector()
            result = collector._check_ssl(_test_domain)

        # Verificar clasificación "warning"
        assert result.details["classification"] == "warning", (
            f"Clasificación incorrecta para {days_offset} días restantes. "
            f"Esperado: 'warning', Obtenido: '{result.details['classification']}'"
        )
        # Verificar que is_available es True para "warning"
        assert result.is_available is True, (
            f"is_available debe ser True para clasificación 'warning'. "
            f"Obtenido: {result.is_available}"
        )

    @given(days_offset=st.integers(min_value=-365, max_value=0))
    @settings(max_examples=200, deadline=None)
    def test_clasificacion_expired_cuando_dias_menor_o_igual_a_0(self, days_offset: int):
        """
        El certificado se clasifica como "expired" cuando days_remaining <= 0.

        **Validates: Requirements 2.6**
        """
        # Fecha de expiración en el pasado o justo hoy
        expiry_date = _base_now + timedelta(days=days_offset)
        cert_not_after = _format_cert_date(expiry_date)

        mock_cert = {"notAfter": cert_not_after}

        with patch("app.services.system_status.socket.create_connection") as mock_conn, \
             patch("app.services.system_status.ssl.create_default_context") as mock_ssl_ctx, \
             patch("app.services.system_status.datetime") as mock_datetime:

            mock_datetime.now.return_value = _base_now
            mock_datetime.strptime = datetime.strptime

            mock_ssock = MagicMock()
            mock_ssock.getpeercert.return_value = mock_cert
            mock_ssock.__enter__ = MagicMock(return_value=mock_ssock)
            mock_ssock.__exit__ = MagicMock(return_value=False)

            mock_sock = MagicMock()
            mock_sock.__enter__ = MagicMock(return_value=mock_sock)
            mock_sock.__exit__ = MagicMock(return_value=False)

            mock_conn.return_value = mock_sock

            mock_ctx = MagicMock()
            mock_ctx.wrap_socket.return_value = mock_ssock
            mock_ssl_ctx.return_value = mock_ctx

            collector = SystemStatusCollector()
            result = collector._check_ssl(_test_domain)

        # Verificar clasificación "expired"
        assert result.details["classification"] == "expired", (
            f"Clasificación incorrecta para {days_offset} días restantes. "
            f"Esperado: 'expired', Obtenido: '{result.details['classification']}'"
        )
        # Verificar que is_available es False para "expired"
        assert result.is_available is False, (
            f"is_available debe ser False para clasificación 'expired'. "
            f"Obtenido: {result.is_available}"
        )

    @given(days_offset=_days_offset)
    @settings(max_examples=200, deadline=None)
    def test_is_available_coherente_con_clasificacion(self, days_offset: int):
        """
        is_available es True para "valid" y "warning", False para "expired".

        **Validates: Requirements 2.6**
        """
        # Generar fecha de expiración
        expiry_date = _base_now + timedelta(days=days_offset)
        cert_not_after = _format_cert_date(expiry_date)

        mock_cert = {"notAfter": cert_not_after}

        with patch("app.services.system_status.socket.create_connection") as mock_conn, \
             patch("app.services.system_status.ssl.create_default_context") as mock_ssl_ctx, \
             patch("app.services.system_status.datetime") as mock_datetime:

            mock_datetime.now.return_value = _base_now
            mock_datetime.strptime = datetime.strptime

            mock_ssock = MagicMock()
            mock_ssock.getpeercert.return_value = mock_cert
            mock_ssock.__enter__ = MagicMock(return_value=mock_ssock)
            mock_ssock.__exit__ = MagicMock(return_value=False)

            mock_sock = MagicMock()
            mock_sock.__enter__ = MagicMock(return_value=mock_sock)
            mock_sock.__exit__ = MagicMock(return_value=False)

            mock_conn.return_value = mock_sock

            mock_ctx = MagicMock()
            mock_ctx.wrap_socket.return_value = mock_ssock
            mock_ssl_ctx.return_value = mock_ctx

            collector = SystemStatusCollector()
            result = collector._check_ssl(_test_domain)

        # Determinar clasificación esperada
        expected_days = (expiry_date - _base_now).days
        if expected_days > 14:
            expected_available = True
        elif expected_days >= 1:
            expected_available = True
        else:
            expected_available = False

        assert result.is_available == expected_available, (
            f"is_available incorrecto para {expected_days} días restantes. "
            f"Clasificación: '{result.details['classification']}'. "
            f"Esperado: {expected_available}, Obtenido: {result.is_available}"
        )
