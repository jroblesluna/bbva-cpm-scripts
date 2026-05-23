"""
Tests unitarios para funciones de detección y normalización del log_processor.

Valida detect_keywords, parse_timestamp y normalize_line.
"""

import pytest

from app.services.log_processor import (
    DEFAULT_KEYWORDS,
    detect_keywords,
    normalize_line,
    parse_timestamp,
)


# === TESTS DE detect_keywords ===


class TestDetectKeywords:
    """Tests para la función detect_keywords."""

    def test_detecta_keyword_simple(self) -> None:
        """Detecta un keyword simple en la línea."""
        assert detect_keywords("An error occurred", ["error"]) is True

    def test_no_detecta_si_no_hay_match(self) -> None:
        """Retorna False si ningún keyword está presente."""
        assert detect_keywords("Everything is fine", ["error", "failed"]) is False

    def test_case_insensitive_por_defecto(self) -> None:
        """La comparación es case-insensitive por defecto."""
        assert detect_keywords("ERROR: something broke", ["error"]) is True
        assert detect_keywords("Error: something broke", ["error"]) is True
        assert detect_keywords("eRrOr: something broke", ["error"]) is True

    def test_case_sensitive_cuando_se_indica(self) -> None:
        """Respeta case_insensitive=False."""
        assert detect_keywords("ERROR: broke", ["error"], case_insensitive=False) is False
        assert detect_keywords("error: broke", ["error"], case_insensitive=False) is True

    def test_detecta_keyword_multipalabra(self) -> None:
        """Detecta keywords compuestos como 'access denied'."""
        assert detect_keywords(
            "User got access denied on resource", ["access denied"]
        ) is True

    def test_detecta_con_lista_default(self) -> None:
        """Funciona con la lista de keywords por defecto."""
        assert detect_keywords("Connection refused by host", DEFAULT_KEYWORDS) is True
        assert detect_keywords("SSL certificate expired", DEFAULT_KEYWORDS) is True
        assert detect_keywords("service started successfully", DEFAULT_KEYWORDS) is True

    def test_linea_vacia(self) -> None:
        """Línea vacía no contiene ningún keyword."""
        assert detect_keywords("", DEFAULT_KEYWORDS) is False

    def test_keywords_vacia(self) -> None:
        """Lista de keywords vacía siempre retorna False."""
        assert detect_keywords("error occurred", []) is False

    def test_substring_match_no_word_boundary(self) -> None:
        """Detecta substring sin requerir word boundary."""
        # "warn" está dentro de "warning"
        assert detect_keywords("This is a warning message", ["warn"]) is True

    def test_keyword_ssl_case_insensitive(self) -> None:
        """SSL se detecta en cualquier case."""
        assert detect_keywords("Ssl handshake failed", DEFAULT_KEYWORDS) is True


# === TESTS DE parse_timestamp ===


class TestParseTimestamp:
    """Tests para la función parse_timestamp."""

    def test_extrae_timestamp_formato_estandar(self) -> None:
        """Extrae timestamp en formato YYYY-MM-DD HH:MM:SS."""
        line = "[2024-01-15 14:30:45] [SVC] Event 1000: Service started"
        assert parse_timestamp(line) == "2024-01-15 14:30:45"

    def test_retorna_none_sin_timestamp(self) -> None:
        """Retorna None si no hay timestamp en la línea."""
        assert parse_timestamp("No timestamp here") is None

    def test_extrae_primer_timestamp(self) -> None:
        """Si hay múltiples timestamps, extrae el primero."""
        line = "2024-01-15 10:00:00 something 2024-01-15 11:00:00"
        assert parse_timestamp(line) == "2024-01-15 10:00:00"

    def test_timestamp_al_inicio(self) -> None:
        """Detecta timestamp al inicio de la línea."""
        line = "2024-12-31 23:59:59 End of year"
        assert parse_timestamp(line) == "2024-12-31 23:59:59"

    def test_timestamp_en_medio(self) -> None:
        """Detecta timestamp en medio de la línea."""
        line = "Log entry at 2024-06-15 08:30:00 with data"
        assert parse_timestamp(line) == "2024-06-15 08:30:00"

    def test_linea_vacia(self) -> None:
        """Línea vacía retorna None."""
        assert parse_timestamp("") is None

    def test_formato_parcial_no_match(self) -> None:
        """Formato incompleto no se detecta."""
        assert parse_timestamp("2024-01-15 14:30") is None
        assert parse_timestamp("2024-01-15") is None

    def test_timestamp_con_corchetes(self) -> None:
        """Detecta timestamp dentro de corchetes (formato AlwaysPrint)."""
        line = "[2025-03-20 09:15:33] [APP] Event 1009: Tray initialized"
        assert parse_timestamp(line) == "2025-03-20 09:15:33"


# === TESTS DE normalize_line ===


class TestNormalizeLine:
    """Tests para la función normalize_line."""

    def test_reemplaza_timestamp(self) -> None:
        """Reemplaza timestamps con [TIMESTAMP]."""
        line = "[2024-01-15 14:30:45] Error occurred"
        result = normalize_line(line)
        assert "[TIMESTAMP]" in result
        assert "2024-01-15 14:30:45" not in result

    def test_reemplaza_uuid(self) -> None:
        """Reemplaza UUIDs con [UUID]."""
        line = "Request a1b2c3d4-e5f6-7890-abcd-ef1234567890 failed"
        result = normalize_line(line)
        assert "[UUID]" in result
        assert "a1b2c3d4-e5f6-7890-abcd-ef1234567890" not in result

    def test_reemplaza_ipv4(self) -> None:
        """Reemplaza direcciones IPv4 con [IP]."""
        line = "Connection to 192.168.1.100 refused"
        result = normalize_line(line)
        assert "[IP]" in result
        assert "192.168.1.100" not in result

    def test_reemplaza_temp_path_windows(self) -> None:
        """Reemplaza rutas temporales Windows con [TEMP_PATH]."""
        line = r"File written to C:\Users\admin\AppData\Local\Temp\log123.tmp"
        result = normalize_line(line)
        assert "[TEMP_PATH]" in result
        assert r"\Temp\\" not in result

    def test_reemplaza_numeros_2_digitos_o_mas(self) -> None:
        """Reemplaza secuencias numéricas de 2+ dígitos con [NUMBER]."""
        line = "Error code 42 at position 1234"
        result = normalize_line(line)
        assert "[NUMBER]" in result
        assert "42" not in result
        assert "1234" not in result

    def test_no_reemplaza_un_solo_digito(self) -> None:
        """No reemplaza dígitos individuales."""
        line = "Step 1 completed"
        result = normalize_line(line)
        assert "1" in result
        assert "[NUMBER]" not in result

    def test_orden_fijo_timestamp_antes_numeros(self) -> None:
        """Los dígitos dentro de timestamps no se reemplazan por [NUMBER]."""
        line = "[2024-01-15 14:30:45] Event 1091: Error"
        result = normalize_line(line)
        # El timestamp se reemplaza primero como [TIMESTAMP]
        assert "[TIMESTAMP]" in result
        # El event ID 1091 se reemplaza como [NUMBER]
        assert "[NUMBER]" in result
        # No debe haber dígitos del timestamp sueltos
        assert "2024" not in result

    def test_orden_fijo_uuid_antes_numeros(self) -> None:
        """Los dígitos dentro de UUIDs no se reemplazan por [NUMBER]."""
        line = "ID: a1b2c3d4-e5f6-7890-abcd-ef1234567890 count 99"
        result = normalize_line(line)
        assert "[UUID]" in result
        assert "[NUMBER]" in result
        # Los dígitos del UUID no deben quedar como [NUMBER] separados
        assert "a1b2c3d4" not in result

    def test_orden_fijo_ip_antes_numeros(self) -> None:
        """Los dígitos dentro de IPs no se reemplazan por [NUMBER]."""
        line = "Host 10.0.0.1 port 8080"
        result = normalize_line(line)
        assert "[IP]" in result
        assert "[NUMBER]" in result
        # 8080 se reemplaza como [NUMBER], pero la IP ya fue reemplazada
        assert "10.0.0.1" not in result

    def test_multiples_reemplazos_en_una_linea(self) -> None:
        """Aplica múltiples normalizaciones en la misma línea."""
        line = (
            "[2024-01-15 14:30:45] Connection from 192.168.1.50 "
            "request a1b2c3d4-e5f6-7890-abcd-ef1234567890 failed after 30 retries"
        )
        result = normalize_line(line)
        assert "[TIMESTAMP]" in result
        assert "[IP]" in result
        assert "[UUID]" in result
        assert "[NUMBER]" in result

    def test_linea_sin_patrones(self) -> None:
        """Línea sin patrones reconocibles queda sin cambios."""
        line = "Simple text message"
        assert normalize_line(line) == "Simple text message"

    def test_temp_path_con_tmp(self) -> None:
        """Detecta rutas con \\tmp\\ (minúsculas)."""
        line = r"Writing to C:\Windows\tmp\session_data.dat"
        result = normalize_line(line)
        assert "[TEMP_PATH]" in result

    def test_ip_boundary_no_falso_positivo(self) -> None:
        """No detecta IPs inválidas (octetos > 255)."""
        line = "Version 999.999.999.999 is invalid"
        result = normalize_line(line)
        # 999 > 255, no debería ser reemplazado como IP
        assert "[IP]" not in result

    def test_uuid_case_insensitive(self) -> None:
        """Detecta UUIDs con letras mayúsculas."""
        line = "ID: A1B2C3D4-E5F6-7890-ABCD-EF1234567890"
        result = normalize_line(line)
        assert "[UUID]" in result
