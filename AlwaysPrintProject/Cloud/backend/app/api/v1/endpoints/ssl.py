"""
Endpoints para monitoreo y renovación de certificados SSL.

Restringido a Corporate Admins (misma lógica que sync_inventory).
Usa certbot con --webroot para evitar deadlocks con nginx.
"""

import subprocess
import ssl
import socket
from datetime import datetime, timezone
from typing import Optional

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
    status: str  # "valid", "expiring_soon", "expired", "error"
    message: str


class SslRenewResponse(BaseModel):
    """Resultado de la renovación SSL."""
    success: bool
    message: str
    new_expiry: Optional[str] = None


# === HELPERS ===

def _get_ssl_cert_info(domain: str) -> dict:
    """Lee información del certificado SSL conectándose al dominio local."""
    try:
        # Conectarse a localhost (nginx) con SNI del dominio
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        with socket.create_connection(("127.0.0.1", 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert(binary_form=False)
                if not cert:
                    # Fallback: leer desde archivo de certbot
                    return _get_cert_from_file(domain)
                
                not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                not_before = datetime.strptime(cert["notBefore"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
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
        return _get_cert_from_file(domain)


def _get_cert_from_file(domain: str) -> dict:
    """Lee la fecha de expiración directamente del archivo PEM de certbot."""
    import os
    cert_path = f"/etc/letsencrypt/live/{domain}/cert.pem"
    if not os.path.exists(cert_path):
        return {"error": f"Certificado no encontrado: {cert_path}"}

    try:
        result = subprocess.run(
            ["openssl", "x509", "-enddate", "-noout", "-in", cert_path],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return {"error": f"Error leyendo certificado: {result.stderr}"}

        # Parse: notAfter=Nov 19 03:35:55 2026 GMT
        line = result.stdout.strip()
        date_str = line.split("=", 1)[1]
        not_after = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days_remaining = (not_after - now).days

        # Obtener issuer
        result_issuer = subprocess.run(
            ["openssl", "x509", "-issuer", "-noout", "-in", cert_path],
            capture_output=True, text=True, timeout=5
        )
        issuer = "Let's Encrypt"
        if result_issuer.returncode == 0:
            issuer_line = result_issuer.stdout.strip()
            if "O = " in issuer_line:
                issuer = issuer_line.split("O = ")[1].split(",")[0].strip()

        # Obtener not_before
        result_start = subprocess.run(
            ["openssl", "x509", "-startdate", "-noout", "-in", cert_path],
            capture_output=True, text=True, timeout=5
        )
        not_before = None
        if result_start.returncode == 0:
            start_str = result_start.stdout.strip().split("=", 1)[1]
            not_before = datetime.strptime(start_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc).isoformat()

        return {
            "issuer": issuer,
            "not_before": not_before,
            "not_after": not_after.isoformat(),
            "days_remaining": days_remaining,
        }
    except Exception as e:
        return {"error": str(e)}


def _get_domain() -> str:
    """Obtiene el dominio del certificado desde la configuración."""
    import os
    from urllib.parse import urlparse

    # Extraer dominio de FRONTEND_URL (ej: https://alwaysprint.dev.iol.pe → alwaysprint.dev.iol.pe)
    frontend_url = os.environ.get("FRONTEND_URL", "")
    if frontend_url:
        parsed = urlparse(frontend_url)
        if parsed.hostname:
            return parsed.hostname

    # Fallback: listar certificados de certbot
    try:
        result = subprocess.run(
            ["certbot", "certificates"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.split("\n"):
            if "Domains:" in line:
                return line.split("Domains:")[1].strip().split()[0]
    except Exception:
        pass

    return "unknown"


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
        status=cert_status,
        message=message,
    )


@router.post("/renew", response_model=SslRenewResponse)
async def renew_ssl_certificate(
    current_user: User = Depends(require_corporate_admin),
):
    """
    Renueva el certificado SSL usando certbot con método webroot.

    Ejecuta: certbot certonly --webroot -w /usr/share/nginx/html -d {domain}
    Luego recarga nginx para usar el nuevo certificado.
    """
    domain = _get_domain()

    if domain == "unknown":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo determinar el dominio del certificado.",
        )

    try:
        # Matar certbot zombie si existe
        subprocess.run(["pkill", "-f", "certbot"], capture_output=True, timeout=5)
        subprocess.run(
            ["rm", "-f", "/var/lib/letsencrypt/.certbot.lock"],
            capture_output=True, timeout=5
        )

        # Ejecutar certbot con webroot (no manipula nginx)
        result = subprocess.run(
            [
                "certbot", "certonly",
                "--webroot",
                "-w", "/usr/share/nginx/html",
                "-d", domain,
                "--non-interactive",
                "--force-renewal",
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout
            return SslRenewResponse(
                success=False,
                message=f"Certbot falló (exit {result.returncode}): {error_msg[-500:]}",
            )

        # Recargar nginx para usar el nuevo certificado
        reload_result = subprocess.run(
            ["systemctl", "reload", "nginx"],
            capture_output=True, text=True, timeout=10,
        )

        if reload_result.returncode != 0:
            return SslRenewResponse(
                success=True,
                message=f"Certificado renovado pero nginx no se recargó: {reload_result.stderr}",
            )

        # Obtener nueva fecha de expiración
        cert_info = _get_cert_from_file(domain)
        new_expiry = cert_info.get("not_after")

        return SslRenewResponse(
            success=True,
            message="Certificado renovado exitosamente. Nginx recargado.",
            new_expiry=new_expiry,
        )

    except subprocess.TimeoutExpired:
        return SslRenewResponse(
            success=False,
            message="Timeout: certbot no completó en 90 segundos.",
        )
    except Exception as e:
        return SslRenewResponse(
            success=False,
            message=f"Error inesperado: {str(e)}",
        )
