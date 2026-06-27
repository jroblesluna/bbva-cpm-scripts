"""
Servicio criptográfico para firma digital ECDSA de configuraciones.

Responsabilidades:
- Generación de par ECDSA P-256 (secp256r1) por organización
- Cifrado de clave privada con AES-256-GCM (key derivada de SECRET_KEY via PBKDF2)
- Generación de certificado X.509 auto-firmado (10 años de validez)
- Firma de hash SHA256 con clave privada ECDSA
- Construcción del JSON envolvente firmado (signed config)
"""

import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.x509.oid import NameOID

logger = logging.getLogger(__name__)

# Constantes de configuración criptográfica
_PBKDF2_ITERATIONS = 100_000
_AES_NONCE_BYTES = 12
_CERT_VALIDITY_YEARS = 10


class CryptoService:
    """
    Servicio para operaciones criptográficas ECDSA.

    Usa curva P-256 (secp256r1) para firma digital y AES-256-GCM
    para cifrado de la clave privada en reposo.
    """

    @staticmethod
    def _derive_aes_key(secret_key: str, org_id: str) -> bytes:
        """
        Deriva una clave AES-256 a partir del secret_key y org_id como salt.

        Usa PBKDF2 con SHA256 y 100.000 iteraciones para resistir fuerza bruta.

        Args:
            secret_key: Clave secreta de la aplicación (settings.SECRET_KEY)
            org_id: ID de la organización (usado como salt)

        Returns:
            Clave AES de 32 bytes
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=org_id.encode("utf-8"),
            iterations=_PBKDF2_ITERATIONS,
        )
        return kdf.derive(secret_key.encode("utf-8"))

    @staticmethod
    def generate_key_pair(
        org_id: str, secret_key: str
    ) -> tuple[str, bytes, datetime]:
        """
        Genera un par de claves ECDSA P-256 y un certificado X.509 auto-firmado.

        La clave privada se serializa en formato DER, se cifra con AES-256-GCM
        y se codifica en base64. El certificado tiene validez de 10 años.

        Args:
            org_id: ID de la organización (usado como salt para cifrado y CN del cert)
            secret_key: Clave secreta de la aplicación para derivar clave AES

        Returns:
            Tupla con:
            - encrypted_private_key: str base64 con formato nonce||ciphertext||tag
            - cert_pem: bytes del certificado X.509 en formato PEM
            - expires_at: datetime de expiración del certificado
        """
        # Generar par de claves ECDSA P-256
        private_key = ec.generate_private_key(ec.SECP256R1())

        # Serializar clave privada a DER (formato compacto)
        private_key_der = private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        # Cifrar clave privada con AES-256-GCM
        aes_key = CryptoService._derive_aes_key(secret_key, org_id)
        nonce = os.urandom(_AES_NONCE_BYTES)
        aesgcm = AESGCM(aes_key)
        ciphertext_and_tag = aesgcm.encrypt(nonce, private_key_der, None)

        # Formato almacenamiento: base64(nonce || ciphertext || tag)
        encrypted_blob = nonce + ciphertext_and_tag
        encrypted_private_key = base64.b64encode(encrypted_blob).decode("utf-8")

        # Generar certificado X.509 auto-firmado
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=_CERT_VALIDITY_YEARS * 365)

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, f"AlwaysPrint Org {org_id}"),
        ])

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(expires_at)
            .sign(private_key, hashes.SHA256())
        )

        cert_pem = cert.public_bytes(serialization.Encoding.PEM)

        logger.info(
            "Par de claves ECDSA generado: org_id=%s, expira=%s",
            org_id, expires_at.isoformat()
        )

        return encrypted_private_key, cert_pem, expires_at

    @staticmethod
    def decrypt_private_key(
        encrypted_data: str, secret_key: str, org_id: str
    ) -> ec.EllipticCurvePrivateKey:
        """
        Descifra la clave privada ECDSA almacenada en base de datos.

        El formato esperado es base64(nonce[12] || ciphertext || tag[16]).

        Args:
            encrypted_data: Clave privada cifrada en base64
            secret_key: Clave secreta de la aplicación
            org_id: ID de la organización (salt para derivación)

        Returns:
            Instancia de ECPrivateKey lista para firmar

        Raises:
            ValueError: Si los datos cifrados son inválidos o la decriptación falla
        """
        try:
            blob = base64.b64decode(encrypted_data)
        except Exception as e:
            raise ValueError(f"Datos cifrados inválidos (base64 malformado): {e}")

        if len(blob) < _AES_NONCE_BYTES + 16:
            raise ValueError(
                f"Datos cifrados demasiado cortos: {len(blob)} bytes "
                f"(mínimo {_AES_NONCE_BYTES + 16})"
            )

        # Extraer nonce y ciphertext+tag
        nonce = blob[:_AES_NONCE_BYTES]
        ciphertext_and_tag = blob[_AES_NONCE_BYTES:]

        # Derivar clave AES y descifrar
        aes_key = CryptoService._derive_aes_key(secret_key, org_id)
        aesgcm = AESGCM(aes_key)

        try:
            private_key_der = aesgcm.decrypt(nonce, ciphertext_and_tag, None)
        except Exception as e:
            raise ValueError(f"Error al descifrar clave privada: {e}")

        # Cargar clave privada desde DER
        private_key = serialization.load_der_private_key(private_key_der, password=None)

        if not isinstance(private_key, ec.EllipticCurvePrivateKey):
            raise ValueError("La clave descifrada no es una clave ECDSA válida")

        return private_key

    @staticmethod
    def sign_config(
        encrypted_private_key: str, config_json: str, secret_key: str, org_id: str
    ) -> tuple[str, str]:
        """
        Firma una configuración JSON con la clave privada ECDSA de la organización.

        Proceso:
        1. Descifra la clave privada
        2. Normaliza config_json (parse + re-serialize con separadores compactos)
           para garantizar que el hash coincida con lo que el cliente C# computa
           al re-serializar con Newtonsoft Formatting.None
        3. Calcula SHA256 del config normalizado → hash hex de 64 chars
        4. Firma los 32 bytes raw del hash (no el hex string) con ECDSA

        Args:
            encrypted_private_key: Clave privada cifrada (base64)
            config_json: String JSON de la configuración a firmar
            secret_key: Clave secreta de la aplicación
            org_id: ID de la organización

        Returns:
            Tupla con:
            - hash_full: Hash SHA256 hex completo (64 caracteres)
            - signature_b64: Firma ECDSA codificada en base64
        """
        # Descifrar clave privada
        private_key = CryptoService.decrypt_private_key(
            encrypted_private_key, secret_key, org_id
        )

        # Normalizar: parsear y re-serializar con formato compacto idéntico al del envelope.
        # Esto garantiza que el hash corresponde al config tal como aparece en el JSON final
        # y coincide con lo que C# computa con configToken.ToString(Formatting.None).
        config_obj = json.loads(config_json)
        normalized_config = json.dumps(config_obj, ensure_ascii=False, separators=(",", ":"))

        # Calcular SHA256 del config NORMALIZADO como bytes UTF-8
        config_bytes = normalized_config.encode("utf-8")
        hash_bytes = hashlib.sha256(config_bytes).digest()  # 32 bytes raw
        hash_full = hash_bytes.hex()  # 64 caracteres hex

        # Firmar los 32 bytes raw del hash (no el string hex)
        signature = private_key.sign(hash_bytes, ec.ECDSA(hashes.SHA256()))
        signature_b64 = base64.b64encode(signature).decode("utf-8")

        logger.info(
            "Configuración firmada: org_id=%s, hash=%s...%s",
            org_id, hash_full[:8], hash_full[-4:]
        )

        return hash_full, signature_b64

    @staticmethod
    def build_signed_config(
        config_json: str, hash_full: str, signature_b64: str, cert_version: int
    ) -> str:
        """
        Construye el JSON envolvente firmado (signed config).

        El config_json se parsea para incluirlo como objeto JSON (no como string escapado).

        Formato de salida:
        {
            "config": { ... },
            "hash": "<sha256_hex_64>",
            "signature": "<base64_ecdsa>",
            "cert_version": <int>
        }

        Args:
            config_json: String JSON de la configuración original
            hash_full: Hash SHA256 hex (64 caracteres)
            signature_b64: Firma ECDSA en base64
            cert_version: Versión del certificado usado para firmar

        Returns:
            String JSON del sobre firmado (serializado con separadores compactos)
        """
        # Parsear config_json para incluirlo como objeto, no como string escapado
        config_obj = json.loads(config_json)

        signed_envelope = {
            "config": config_obj,
            "hash": hash_full,
            "signature": signature_b64,
            "cert_version": cert_version,
        }

        return json.dumps(signed_envelope, ensure_ascii=False, separators=(",", ":"))
