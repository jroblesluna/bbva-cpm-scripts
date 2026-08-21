"""
Endpoints para monitoreo y renovación de certificados SSL.

Restringido a Corporate Admins (misma lógica que sync_inventory).

Arquitectura:
- Status: Lee el certificado PEM directamente desde /etc/letsencrypt (montado como volumen)
  o se conecta via SSL a host.docker.internal:443 (nginx en el host).
- Renovación: Lanza un contenedor certbot efímero via Docker Engine API (unix socket).
  No requiere docker CLI ni capabilities especiales — solo el socket montado.
  Tras renovar, recarga nginx via señal HUP (pid:host) o container efímero.
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

    Estrategia (en orden de prioridad):
    1. Docker Engine API via unix socket — crea un contenedor efímero con acceso al host.
       No requiere binario docker CLI ni capabilities especiales, solo el socket montado.
    2. nsenter al PID 1 (fallback, requiere --pid=host + CAP_SYS_ADMIN).
    """
    import http.client
    import json
    import time

    # Método 1: Docker Engine API via unix socket
    docker_socket = "/var/run/docker.sock"
    if os.path.exists(docker_socket):
        try:
            conn = http.client.HTTPConnection("localhost")
            # Monkey-patch para usar unix socket
            import socket as _socket

            class UnixHTTPConnection(http.client.HTTPConnection):
                def __init__(self, socket_path: str):
                    super().__init__("localhost")
                    self._socket_path = socket_path

                def connect(self):
                    self.sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
                    self.sock.connect(self._socket_path)

            conn = UnixHTTPConnection(docker_socket)

            # Crear contenedor efímero con certbot
            container_config = {
                "Image": "certbot/certbot:latest",
                "Entrypoint": ["/bin/sh", "-c"],
                "Cmd": [command],
                "HostConfig": {
                    "NetworkMode": "host",
                    "Binds": [
                        "/etc/letsencrypt:/etc/letsencrypt",
                        "/usr/share/nginx/html:/usr/share/nginx/html",
                        "/var/lib/letsencrypt:/var/lib/letsencrypt",
                    ],
                    "AutoRemove": True,
                },
            }

            body = json.dumps(container_config)
            conn.request("POST", "/containers/create", body=body,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            create_data = json.loads(resp.read())

            if resp.status != 201:
                # Si la imagen no existe, intentar pull
                if resp.status == 404:
                    conn.request("POST", "/images/create?fromImage=certbot/certbot&tag=latest")
                    pull_resp = conn.getresponse()
                    pull_resp.read()  # Consumir respuesta del pull
                    # Reintentar crear el contenedor
                    conn.request("POST", "/containers/create", body=body,
                                 headers={"Content-Type": "application/json"})
                    resp = conn.getresponse()
                    create_data = json.loads(resp.read())
                    if resp.status != 201:
                        return 1, "", f"Error creando contenedor: {create_data}"
                else:
                    return 1, "", f"Error creando contenedor: {create_data}"

            container_id = create_data["Id"]

            # Iniciar contenedor
            conn.request("POST", f"/containers/{container_id}/start")
            start_resp = conn.getresponse()
            start_resp.read()

            # Esperar a que termine (con timeout)
            conn.request("POST", f"/containers/{container_id}/wait")
            # Usar timeout manual
            conn.sock.settimeout(timeout)
            try:
                wait_resp = conn.getresponse()
                wait_data = json.loads(wait_resp.read())
                exit_code = wait_data.get("StatusCode", 1)
            except _socket.timeout:
                # Timeout — intentar matar el contenedor
                try:
                    conn2 = UnixHTTPConnection(docker_socket)
                    conn2.request("POST", f"/containers/{container_id}/kill")
                    conn2.getresponse().read()
                except Exception:
                    pass
                return 1, "", "Timeout ejecutando certbot en el host"

            # Obtener logs
            conn.request("GET", f"/containers/{container_id}/logs?stdout=true&stderr=true")
            logs_resp = conn.getresponse()
            raw_logs = logs_resp.read()

            # Docker logs tienen un header de 8 bytes por frame, limpiar
            stdout_output = ""
            try:
                # Intentar decodificar quitando headers de Docker stream
                i = 0
                lines = []
                while i < len(raw_logs):
                    if i + 8 <= len(raw_logs):
                        # Header: [stream_type(1), 0, 0, 0, size(4)]
                        size = int.from_bytes(raw_logs[i+4:i+8], "big")
                        if size > 0 and i + 8 + size <= len(raw_logs):
                            lines.append(raw_logs[i+8:i+8+size].decode("utf-8", errors="replace"))
                            i += 8 + size
                            continue
                    # Si el formato no coincide, decodificar todo directamente
                    stdout_output = raw_logs.decode("utf-8", errors="replace")
                    break
                else:
                    stdout_output = "".join(lines)
            except Exception:
                stdout_output = raw_logs.decode("utf-8", errors="replace")

            conn.close()
            return exit_code, stdout_output, ""

        except Exception as e:
            # Si falla el Docker API, caer al método 2
            pass

    # Método 2: nsenter (requiere --pid=host y CAP_SYS_ADMIN)
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

    return 1, "", "No se encontró método disponible para ejecutar en el host (sin docker socket ni nsenter)"


def _reload_nginx_on_host():
    """
    Recarga nginx en el host enviando señal HUP al proceso master.
    Usa /proc del host (disponible con pid:host) para encontrar nginx master PID.
    Si no funciona, intenta via Docker API ejecutando nginx -s reload en un container.
    """
    import signal

    # Con pid:host, podemos ver los procesos del host en /proc
    # Buscar el PID master de nginx
    try:
        result = subprocess.run(
            ["pgrep", "-f", "nginx: master"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            nginx_pid = int(result.stdout.strip().split()[0])
            os.kill(nginx_pid, signal.SIGHUP)
            return
    except Exception:
        pass

    # Fallback: ejecutar nginx -s reload via Docker API (container efímero con nginx)
    try:
        _run_on_host("nginx -s reload", timeout=10)
    except Exception:
        pass


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

    # Comando de certbot (se ejecuta en container efímero via Docker socket)
    renew_command = (
        f"certbot certonly --webroot -w /usr/share/nginx/html "
        f"-d {domain} --non-interactive --force-renewal 2>&1"
    )

    try:
        returncode, stdout, stderr = _run_on_host(renew_command, timeout=90)

        if returncode != 0:
            error_msg = stderr or stdout
            return SslRenewResponse(
                success=False,
                message=f"Certbot falló (exit {returncode}): {error_msg[-500:]}",
            )

        # Recargar nginx en el host (necesita nsenter o señal via docker)
        _reload_nginx_on_host()

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
