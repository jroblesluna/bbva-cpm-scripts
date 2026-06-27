"""
Tests unitarios para CryptoService: generate, sign, verify round-trip.

Cubre:
- Generación de par de claves ECDSA P-256
- Descifrado de clave privada round-trip
- Firma de configuración y verificación de formato
- Verificación de firma con clave pública del certificado
- Formato del JSON firmado (signed config)
- Fallo de descifrado con secret_key o org_id incorrectos
- Determinismo del hash
"""

import base64
import hashlib
import json
from datetime import datetime, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes

from app.services.crypto_service import CryptoService


# Constantes de prueba
_TEST_SECRET_KEY = "test-secret-key-for-unit-tests-2024"
_TEST_ORG_ID = "org-test-12345"
_TEST_CONFIG = json.dumps({"printers": [{"name": "HP01", "ip": "10.0.1.50"}], "version": 3})


class TestCryptoService:
    """Tests unitarios para el servicio criptográfico ECDSA."""

    def test_generate_key_pair_produces_valid_output(self):
        """Verifica que generate_key_pair retorna clave cifrada no vacía, cert PEM válido y expires_at futuro."""
        encrypted_key, cert_pem, expires_at = CryptoService.generate_key_pair(
            _TEST_ORG_ID, _TEST_SECRET_KEY
        )

        # Clave cifrada no vacía y es base64 válido
        assert len(encrypted_key) > 0
        decoded = base64.b64decode(encrypted_key)
        assert len(decoded) > 12 + 16  # nonce (12) + tag (16) mínimo

        # Certificado PEM válido (se puede parsear)
        cert = x509.load_pem_x509_certificate(cert_pem)
        assert cert is not None
        assert b"BEGIN CERTIFICATE" in cert_pem

        # expires_at es futuro
        now = datetime.now(timezone.utc)
        assert expires_at > now

    def test_decrypt_private_key_round_trip(self):
        """Genera claves, descifra la privada y verifica que es una clave EC válida."""
        encrypted_key, _cert_pem, _expires_at = CryptoService.generate_key_pair(
            _TEST_ORG_ID, _TEST_SECRET_KEY
        )

        # Descifrar debe devolver una clave EC privada
        private_key = CryptoService.decrypt_private_key(
            encrypted_key, _TEST_SECRET_KEY, _TEST_ORG_ID
        )

        assert isinstance(private_key, ec.EllipticCurvePrivateKey)
        # Verificar que es curva P-256
        assert private_key.curve.name == "secp256r1"

    def test_sign_config_produces_valid_signature(self):
        """Firma un config y verifica que el hash es 64 hex chars y la firma es base64 válido."""
        encrypted_key, _cert_pem, _expires_at = CryptoService.generate_key_pair(
            _TEST_ORG_ID, _TEST_SECRET_KEY
        )

        hash_full, signature_b64 = CryptoService.sign_config(
            encrypted_key, _TEST_CONFIG, _TEST_SECRET_KEY, _TEST_ORG_ID
        )

        # Hash SHA256 debe ser 64 caracteres hexadecimales
        assert len(hash_full) == 64
        assert all(c in "0123456789abcdef" for c in hash_full)

        # Firma debe ser base64 válido y no vacía
        signature_bytes = base64.b64decode(signature_b64)
        assert len(signature_bytes) > 0

    def test_sign_and_verify_round_trip(self):
        """Genera claves, firma config, verifica firma con la clave pública del certificado."""
        encrypted_key, cert_pem, _expires_at = CryptoService.generate_key_pair(
            _TEST_ORG_ID, _TEST_SECRET_KEY
        )

        hash_full, signature_b64 = CryptoService.sign_config(
            encrypted_key, _TEST_CONFIG, _TEST_SECRET_KEY, _TEST_ORG_ID
        )

        # Extraer clave pública del certificado
        cert = x509.load_pem_x509_certificate(cert_pem)
        public_key = cert.public_key()

        # Decodificar firma y hash_bytes
        signature_bytes = base64.b64decode(signature_b64)
        hash_bytes = bytes.fromhex(hash_full)

        # Verificar firma: sign_config usa private_key.sign(hash_bytes, ECDSA(SHA256()))
        # por lo tanto para verificar usamos public_key.verify(sig, hash_bytes, ECDSA(SHA256()))
        # Esto no lanza excepción si la firma es válida
        public_key.verify(signature_bytes, hash_bytes, ec.ECDSA(hashes.SHA256()))

    def test_build_signed_config_format(self):
        """Verifica que el JSON firmado tiene config (objeto), hash, signature y cert_version."""
        encrypted_key, _cert_pem, _expires_at = CryptoService.generate_key_pair(
            _TEST_ORG_ID, _TEST_SECRET_KEY
        )

        hash_full, signature_b64 = CryptoService.sign_config(
            encrypted_key, _TEST_CONFIG, _TEST_SECRET_KEY, _TEST_ORG_ID
        )

        result_json = CryptoService.build_signed_config(
            _TEST_CONFIG, hash_full, signature_b64, cert_version=1
        )

        # Parsear resultado
        result = json.loads(result_json)

        # Debe tener las 4 claves esperadas
        assert "config" in result
        assert "hash" in result
        assert "signature" in result
        assert "cert_version" in result

        # config debe ser un objeto (dict), no un string
        assert isinstance(result["config"], dict)
        assert result["config"] == json.loads(_TEST_CONFIG)

        # hash y signature deben ser strings
        assert result["hash"] == hash_full
        assert result["signature"] == signature_b64
        assert result["cert_version"] == 1

    def test_decrypt_with_wrong_secret_fails(self):
        """Verifica que descifrar con un secret_key incorrecto lanza ValueError."""
        encrypted_key, _cert_pem, _expires_at = CryptoService.generate_key_pair(
            _TEST_ORG_ID, _TEST_SECRET_KEY
        )

        with pytest.raises(ValueError):
            CryptoService.decrypt_private_key(
                encrypted_key, "clave-secreta-incorrecta", _TEST_ORG_ID
            )

    def test_decrypt_with_wrong_org_id_fails(self):
        """Verifica que descifrar con un org_id incorrecto lanza ValueError."""
        encrypted_key, _cert_pem, _expires_at = CryptoService.generate_key_pair(
            _TEST_ORG_ID, _TEST_SECRET_KEY
        )

        with pytest.raises(ValueError):
            CryptoService.decrypt_private_key(
                encrypted_key, _TEST_SECRET_KEY, "org-id-incorrecto"
            )

    def test_sign_config_hash_is_deterministic(self):
        """El mismo config_json siempre produce el mismo hash."""
        encrypted_key, _cert_pem, _expires_at = CryptoService.generate_key_pair(
            _TEST_ORG_ID, _TEST_SECRET_KEY
        )

        hash_1, _sig_1 = CryptoService.sign_config(
            encrypted_key, _TEST_CONFIG, _TEST_SECRET_KEY, _TEST_ORG_ID
        )
        hash_2, _sig_2 = CryptoService.sign_config(
            encrypted_key, _TEST_CONFIG, _TEST_SECRET_KEY, _TEST_ORG_ID
        )

        assert hash_1 == hash_2

        # Verificar que coincide con hashlib directamente
        expected_hash = hashlib.sha256(_TEST_CONFIG.encode("utf-8")).hexdigest()
        assert hash_1 == expected_hash
