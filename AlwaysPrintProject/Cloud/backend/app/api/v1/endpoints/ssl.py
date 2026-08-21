"""
Endpoints para monitoreo y renovación de certificados SSL.

Restringido a Corporate Admins (misma lógica que sync_inventory).

Arquitectura:
- Status: Lee el certificado PEM directamente desde /etc/letsencrypt (montado como volumen)
  o se conecta via SSL a host.docker.internal:443 (nginx en el host).
- Renovación: Ejecuta certbot en el HOST usando Docker socket (nsenter al PID 1 del host).
  Esto evita necesitar certbot dentro del contenedor del backend.
"""

import os
import ssl
import socket
import subprocess
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.security import require_admin
from app.models.user import User


# === DOMINIOS CORPORATIVOS AUTORIZADOS ===

ALLOWED_DOMAINS = ["@robles.ai", "@sistemas.com.pe"]


# === DEPENDENCIA DE AUTORIZACIÓN ===

async def require_corporate_admin(
    current_user: User = Depends(require_admin),
) -> User:
    """Verifica que el admin pertenezca a un dominio corporativo autorizado."""
    email = (current_user.email or "").lower()
    if not any(email.endswith(domain) for domain in ALLOWED_DOMAINS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores corporativos pueden gestionar certificados SSL.",
        )
    return current_user


# === SCHEMAS ===

class SslStatusResponse(BaseModel):
    """Estado del certificado SSL."""
    domain: str
    issuer: Optional[str] = None
    not_before: Optional[str] = None
    not_after: Optional[str] = None
    days_remaining: Optional[int] = None
    fingerprint_sha256: Optional[str] = None
    status: str  # "valid", "expiring_soon", "expired", "error"
    message: str


class SslRenewResponse(BaseModel):
    """Resultado de la renovación SSL."""
    success: bool
    message: str
    new_expiry: Optional[str] = None


# === HELPERS ===

def _get_domain() -> str:
    """Obtiene el dominio del certificado desde FRONTEND_URL."""
    frontend_url = os.environ.get("FRONTEND_URL", "")
    if frontend_url:
        parsed = urlparse(frontend_url)
        if parsed.hostname:
            return parsed.hostname
    return "unknown"


def _get_cert_from_file(domain: str) -> dict:
    """Lee información del certificado directamente del archivo PEM (montado como volumen)."""
    cert_path = f"/etc/letsencrypt/live/{domain}/cert.pem"
    if not os.path.exists(cert_path):
        return {"error": f"Certificado no encontrado: {cert_path}"}

    try:
        with open(cert_path, "rb") as f:
            cert_data = f.read()

        cert = x509.load_pem_x509_certificate(cert_data)
        now = datetime.now(timezone.utc)

        not_before = cert.not_valid_before_utc
        not_after = cert.not_valid_after_utc
        days_remaining = (not_after - now).days

        # Extraer issuer (Organization Name)
        issuer = "Unknown"
        try:
            org_names = cert.issuer.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
            if org_names:
                issuer = org_names[0].value
        except Exception:
            pass

        # Calcular fingerprint SHA-256
        fingerprint = cert.fingerprint(hashes.SHA256()).hex()
        fingerprint_formatted = ":".join(
            fingerprint[i:i+2].upper() for i in range(0, len(fingerprint), 2)
        )

        return {
            "issuer": issuer,
            "not_before": not_before.isoformat(),
            "not_after": not_after.isoformat(),
            "days_remaining": days_remaining,
            "fingerprint_sha256": fingerprint_formatted,
        }
    except Exception as e:
        return {"error": f"Error leyendo PEM: {str(e)}"}


def _get_ssl_cert_info(domain: str) -> dict:
    """Lee información del certificado SSL. Intenta conexión a nginx, luego archivo PEM."""
    # Primero intentar leer del archivo PEM (más confiable desde Docker)
    file_info = _get_cert_from_file(domain)
    if "error" not in file_info:
        return file_info

    # Fallback: conectarse a nginx en el host via SSL
    try:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        # Conectar a nginx en el host (no localhost — estamos en un contenedor)
        host = "host.docker.internal"
        with socket.create_connection((host, 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert(binary_form=False)
                if not cert:
                    return file_info  # Retornar el error original del archivo

                not_after = datetime.strptime(
                    cert["notAfter"], "%b %d %H:%M:%S %Y %Z"
                ).replace(tzinfo=timezone.utc)
                not_before = datetime.strptime(
                    cert["notBefore"], "%b %d %H:%M:%S %Y %Z"
                ).replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                days_remaining = (not_after - now).days

                issuer_parts = dict(x[0] for x in cert.get("issuer", []))
                issuer = issuer_parts.get("organizationName", "Unknown")

                return {
                    "issuer": issuer,
                    "not_before": not_before.isoformat(),
                    "not_after": not_after.isoformat(),
                    "days_remaining": days_remaining,
                }
    except Exception:
        return file_info  # Retornar el error original del archivo


def _run_on_host(command: str, timeout: int = 90) -> tuple[int, str, str]:
    """
    Ejecuta un comando en el HOST desde dentro del contenedor Docker.
    Usa nsenter al PID 1 para ejecutar en el namespace del host.
    Requiere que el contenedor tenga --pid=host o acceso privilegiado.

    Alternativa: usa Docker socket para lanzar un contenedor efímero en el host.
    """
    # Método 1: nsenter (requiere --pid=host y --privileged o CAP_SYS_ADMIN)
    try:
        result = subprocess.run(
            ["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "--", "bash", "-c", command],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        return 1, "", "Timeout ejecutando comando en el host"

    # Método 2: Docker CLI via socket (ejecutar en un contenedor con host networking)
    try:
        docker_cmd = [
            "docker", "run", "--rm",
            "--network", "host",
            "--pid", "host",
            "-v", "/etc/letsencrypt:/etc/letsencrypt",
            "-v", "/usr/share/nginx/html:/usr/share/nginx/html",
            "-v", "/var/lib/letsencrypt:/var/lib/letsencrypt",
            "certbot/certbot:latest",
            "bash", "-c", command,
        ]
        result = subprocess.run(
            docker_cmd, capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", f"Error ejecutando en host: {str(e)}"


# === ROUTER ===

router = APIRouter(prefix="/admin/ssl", tags=["SSL Certificate"])


@router.get("/status", response_model=SslStatusResponse)
async def get_ssl_status(
    current_user: User = Depends(require_corporate_admin),
):
    """
    Obtiene el estado actual del certificado SSL.

    Retorna información del certificado: dominio, emisor, fechas,
    días restantes y estado (valid/expiring_soon/expired/error).
    """
    domain = _get_domain()
    cert_info = _get_ssl_cert_info(domain)

    if "error" in cert_info:
        return SslStatusResponse(
            domain=domain,
            status="error",
            message=cert_info["error"],
        )

    days = cert_info["days_remaining"]
    if days < 0:
        cert_status = "expired"
        message = f"Certificado expirado hace {abs(days)} días"
    elif days < 14:
        cert_status = "expiring_soon"
        message = f"Certificado expira en {days} días — renovar pronto"
    else:
        cert_status = "valid"
        message = f"Certificado válido — {days} días restantes"

    return SslStatusResponse(
        domain=domain,
        issuer=cert_info.get("issuer"),
        not_before=cert_info.get("not_before"),
        not_after=cert_info.get("not_after"),
        days_remaining=days,
        fingerprint_sha256=cert_info.get("fingerprint_sha256"),
        status=cert_status,
        message=message,
    )


@router.post("/renew", response_model=SslRenewResponse)
async def renew_ssl_certificate(
    current_user: User = Depends(require_corporate_admin),
):
    """
    Renueva el certificado SSL usando certbot con método webroot.

    Ejecuta certbot en el HOST (no dentro del contenedor del backend) via nsenter.
    Luego recarga nginx en el host para aplicar el nuevo certificado.
    """
    domain = _get_domain()

    if domain == "unknown":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo determinar el dominio del certificado.",
        )

    # Comando que se ejecuta en el HOST
    renew_command = (
        f"pkill -f certbot 2>/dev/null; "
        f"rm -f /var/lib/letsencrypt/.certbot.lock; "
        f"sleep 1; "
        f"certbot certonly --webroot -w /usr/share/nginx/html "
        f"-d {domain} --non-interactive --force-renewal 2>&1; "
        f"CERTBOT_EXIT=$?; "
        f"if [ $CERTBOT_EXIT -eq 0 ]; then systemctl reload nginx; fi; "
        f"exit $CERTBOT_EXIT"
    )

    try:
        returncode, stdout, stderr = _run_on_host(renew_command, timeout=90)

        if returncode != 0:
            error_msg = stderr or stdout
            return SslRenewResponse(
                success=False,
                message=f"Certbot falló (exit {returncode}): {error_msg[-500:]}",
            )

        # Leer nueva fecha de expiración del certificado renovado
        cert_info = _get_cert_from_file(domain)
        new_expiry = cert_info.get("not_after")

        return SslRenewResponse(
            success=True,
            message="Certificado renovado exitosamente. Nginx recargado.",
            new_expiry=new_expiry,
        )

    except Exception as e:
        return SslRenewResponse(
            success=False,
            message=f"Error inesperado: {str(e)}",
        )
