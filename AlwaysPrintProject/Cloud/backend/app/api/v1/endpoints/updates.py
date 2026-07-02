"""
Endpoints de actualizaciones automáticas.

Este módulo define los endpoints para:
- Verificación de versión disponible del MSI (GET /updates/check)
- Descarga del MSI via presigned URL (GET /updates/download) [tarea 4.2]

La autenticación de workstations se realiza por IP pública o token Bearer,
siguiendo el mismo patrón que el endpoint de configuración efectiva.
"""

import logging
from datetime import datetime, timezone

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token, require_admin, get_current_user
from app.core.utils import get_client_ip
from app.models.organization import Organization, PublicIP
from app.models.user import User, UserRole
from app.models.workstation import Workstation
from app.schemas.updates import UpdateCheckResponse
from app.services.s3_update_service import S3UpdateService

# Logger del módulo
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/updates", tags=["Actualizaciones"])


@router.get(
    "/versions",
    summary="Listar versiones disponibles",
    description="Retorna todas las versiones del MSI disponibles en S3 (solo admin).",
    responses={
        401: {"description": "No autenticado"},
        403: {"description": "No autorizado"},
        503: {"description": "S3 no disponible"},
    },
)
def list_versions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lista todas las versiones disponibles en S3."""
    try:
        s3_service = S3UpdateService()
        versions = s3_service.list_versions()
        return versions
    except Exception as e:
        logger.error("Error listando versiones: %s", str(e))
        raise HTTPException(status_code=503, detail="No se pueden listar las versiones")


@router.post(
    "/upload",
    summary="Subir MSI de actualización (admin)",
    description="Sube un archivo MSI al bucket S3 como latest y como versión específica.",
    responses={
        200: {"description": "MSI subido exitosamente"},
        400: {"description": "Archivo inválido"},
        401: {"description": "No autenticado"},
        403: {"description": "No autorizado"},
        500: {"description": "Error al subir a S3"},
    },
)
async def upload_msi(
    file: UploadFile = File(..., description="Archivo MSI a subir"),
    version: str = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Sube un archivo MSI al bucket S3. Solo admin."""
    # Validar que es un archivo .msi
    if not file.filename or not file.filename.lower().endswith('.msi'):
        raise HTTPException(status_code=400, detail="Solo se permiten archivos .msi")

    # Leer contenido del archivo
    file_data = await file.read()
    if len(file_data) < 1024:  # Mínimo 1KB
        raise HTTPException(status_code=400, detail="Archivo demasiado pequeño para ser un MSI válido")

    # Determinar versión (del query param o generar una basada en timestamp)
    if not version:
        now = datetime.now(timezone.utc)
        version = now.strftime("1.%y.%m%d.%H%M%S")

    build_date = datetime.now(timezone.utc).isoformat()
    commit_hash = "manual-upload"

    try:
        s3_service = S3UpdateService()
        result = s3_service.upload_msi(
            file_data=file_data,
            version=version,
            build_date=build_date,
            commit_hash=commit_hash,
        )

        logger.info(
            "MSI subido por admin: usuario=%s, version=%s, tamaño=%d bytes",
            current_user.email,
            version,
            len(file_data),
        )

        return {
            "message": "MSI subido exitosamente",
            "version": result['version'],
            "build_date": result['build_date'],
            "commit_hash": result['commit_hash'],
            "file_size": result['file_size'],
        }
    except ClientError as e:
        logger.error("Error S3 al subir MSI: %s", str(e))
        raise HTTPException(status_code=500, detail="Error al subir archivo a S3")
    except Exception as e:
        logger.error("Error inesperado al subir MSI: %s", str(e))
        raise HTTPException(status_code=500, detail="Error interno al subir archivo")


@router.put(
    "/pin/{organization_id}",
    summary="Pinear versión para una organización",
    description="Establece una versión específica como objetivo para una organización.",
    responses={
        200: {"description": "Versión pineada exitosamente"},
        401: {"description": "No autenticado"},
        403: {"description": "No autorizado"},
        404: {"description": "Organización no encontrada"},
    },
)
async def pin_version(
    organization_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Pinea una versión específica para una organización. Solo admin."""
    # Leer body
    body = await request.json()
    version = body.get("version")  # None o string vacío para despinear

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organización no encontrada")

    org.target_version = version if version else None
    db.commit()

    action = "asignada" if version else "desasignada"
    logger.info("Versión %s para organización %s: %s", action, org.name, version or "latest")

    # Push-based distribution: actualizar state map → Redis → push a workstations
    if version:
        try:
            from app.services.push_services import get_state_map_service, get_push_distribution_service

            state_map = get_state_map_service()
            push_service = get_push_distribution_service()

            update_info = S3UpdateService().get_broadcast_update_info(
                target_version=version
            )

            if update_info:
                await state_map.update_msi(
                    org_id=str(organization_id),
                    msi_version=update_info["version"],
                    msi_url=update_info["download_url"],
                )

                enviados = await push_service.push_msi_update(
                    org_id=str(organization_id),
                    msi_version=update_info["version"],
                    download_url=update_info["download_url"],
                    file_size=update_info["file_size"],
                )

                logger.info(
                    "push.msi_pin_version_admin: org_id=%s, version=%s, ws_notificadas=%d",
                    organization_id, version, enviados,
                )
            else:
                logger.warning(
                    "push.msi_pin_version_sin_s3: org_id=%s, version=%s",
                    organization_id, version,
                )
        except Exception as e:
            logger.error(
                "push.msi_pin_version_error: org_id=%s, version=%s, error=%s",
                organization_id, version, str(e),
            )

    return {"message": f"Versión {action} exitosamente", "target_version": org.target_version}


@router.get(
    "/download/{version}",
    summary="Descargar versión específica (admin)",
    description="Genera una URL presigned de S3 para una versión específica y la retorna como JSON.",
    responses={
        200: {"description": "URL presigned para descarga"},
        401: {"description": "No autenticado o no autorizado"},
        403: {"description": "No autorizado"},
        404: {"description": "Versión no encontrada en S3"},
        500: {"description": "Error al generar URL de descarga"},
    },
)
def admin_download_version(
    version: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Genera una URL presigned para descargar una versión específica."""
    try:
        s3_service = S3UpdateService()
        target_key = f"versions/{version}/AlwaysPrint.msi"
        # Verificar que el objeto existe antes de generar URL
        s3_service.get_msi_metadata(key=target_key)
        presigned_url = s3_service.generate_download_url(
            key=target_key,
            filename=f"AlwaysPrint-{version}.msi"
        )
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code in ('404', 'NoSuchKey'):
            raise HTTPException(status_code=404, detail=f"Versión {version} no encontrada en S3")
        logger.error("Error S3 al generar URL de descarga para admin: %s", str(e))
        raise HTTPException(status_code=500, detail="Error al generar URL de descarga")
    except Exception as e:
        logger.error("Error inesperado al generar URL de descarga para admin: %s", str(e))
        raise HTTPException(status_code=500, detail="Error al generar URL de descarga")

    logger.info(
        "Descarga admin autorizada: usuario=%s, versión=%s",
        current_user.email,
        version,
    )

    return {"download_url": presigned_url, "version": version}


@router.post(
    "/versions/delete",
    summary="Eliminar versiones de S3 (admin)",
    description="Elimina múltiples versiones del bucket S3. No permite eliminar la versión latest ni versiones pineadas.",
    responses={
        200: {"description": "Resultado de la eliminación"},
        401: {"description": "No autenticado o no autorizado"},
        403: {"description": "No autorizado"},
        400: {"description": "No se proporcionaron versiones"},
    },
)
async def admin_delete_versions(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Elimina múltiples versiones de S3. No permite eliminar latest ni pineadas. Solo admin."""
    # Leer body con las versiones a eliminar
    body = await request.json()
    versions_to_delete = body.get("versions", [])

    if not versions_to_delete or not isinstance(versions_to_delete, list):
        raise HTTPException(status_code=400, detail="Se requiere una lista de versiones a eliminar")

    # Obtener la versión latest para protegerla
    try:
        s3_service = S3UpdateService()
        latest_metadata = s3_service.get_msi_metadata()
        latest_version = latest_metadata.get('version', '')
    except Exception:
        raise HTTPException(status_code=503, detail="No se puede determinar la versión latest")

    # Obtener versiones pineadas por organizaciones
    pinned_versions = set()
    orgs_with_pins = db.query(Organization).filter(
        Organization.target_version.isnot(None),
        Organization.target_version != ''
    ).all()
    for org in orgs_with_pins:
        if org.target_version:
            pinned_versions.add(org.target_version)

    # Procesar eliminaciones
    deleted = []
    skipped = []

    for version in versions_to_delete:
        version = version.strip()
        if not version:
            continue

        # No permitir eliminar la versión latest
        if version == latest_version:
            skipped.append({"version": version, "reason": "Es la versión latest actual"})
            continue

        # No permitir eliminar versiones pineadas
        if version in pinned_versions:
            orgs_using = [org.name for org in orgs_with_pins if org.target_version == version]
            skipped.append({
                "version": version,
                "reason": f"Pineada por: {', '.join(orgs_using)}"
            })
            continue

        # Intentar eliminar
        try:
            result = s3_service.delete_version(version)
            if result:
                deleted.append(version)
            else:
                skipped.append({"version": version, "reason": "No se encontraron objetos en S3"})
        except ClientError as e:
            logger.error("Error al eliminar versión %s: %s", version, str(e))
            skipped.append({"version": version, "reason": f"Error de S3: {str(e)}"})

    logger.info(
        "Eliminación de versiones completada: usuario=%s, eliminadas=%d, omitidas=%d",
        current_user.email,
        len(deleted),
        len(skipped),
    )

    return {
        "deleted": deleted,
        "skipped": skipped,
        "total_deleted": len(deleted),
        "total_skipped": len(skipped),
    }


def _register_pending_ip(db: Session, request: Request) -> None:
    """
    Registra una IP pública desconocida como pendiente de aprobación.

    Usa upsert (INSERT ... ON CONFLICT) para idempotencia.
    - Primera vez: guarda first_payload con info del request y request_count=1
    - Repetidos: incrementa request_count y actualiza last_hostname/last_user

    Errores de BD se capturan silenciosamente — no deben interrumpir
    el flujo HTTP 401 al cliente.
    """
    import json as json_module

    try:
        client_ip = get_client_ip(request)
        now = datetime.utcnow()

        # Extraer metadata de headers (solo valores no vacíos)
        hostname_header = request.headers.get("X-Workstation-Hostname") or request.headers.get("X-Workstation-ID") or None
        user_header = request.headers.get("X-Workstation-User") or None
        ip_private_header = request.headers.get("X-Workstation-IP-Private") or request.headers.get("X-Workstation-Local-IP") or None

        # Construir payload del primer request para diagnóstico
        first_payload_dict = {
            "endpoint": str(request.url.path),
            "method": request.method,
            "ip": client_ip,
            "hostname": hostname_header,
            "user": user_header,
            "ip_private": ip_private_header,
            "user_agent": request.headers.get("User-Agent"),
            "timestamp": now.isoformat() + "Z",
        }
        try:
            first_payload_json = json_module.dumps(first_payload_dict, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            first_payload_json = None

        # Valores para el INSERT inicial
        insert_values = {
            "ip_address": client_ip,
            "is_authorized": False,
            "organization_id": None,
            "first_seen": now,
            "last_hostname": hostname_header,
            "last_user": user_header,
            "request_count": 1,
            "first_payload": first_payload_json,
        }

        # Construir el SET para ON CONFLICT DO UPDATE
        # Siempre incrementar request_count; actualizar metadata si headers presentes
        update_set = {"request_count": PublicIP.request_count + 1}
        if hostname_header:
            update_set["last_hostname"] = hostname_header
        if user_header:
            update_set["last_user"] = user_header

        stmt = pg_insert(PublicIP).values(**insert_values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ip_address"],
            set_=update_set,
            where=(PublicIP.is_authorized == False),
        )

        db.execute(stmt)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(
            "Error al registrar IP pendiente: ip=%s, error=%s",
            get_client_ip(request),
            str(e),
        )


def _identify_workstation(request: Request, db: Session) -> Workstation:
    """
    Identifica la workstation que realiza la solicitud.

    Soporta dos métodos de autenticación:
    - Token Bearer: identifica al usuario y busca workstation por contexto
    - IP pública: busca la cuenta asociada a la IP y luego la workstation

    Para workstations reales, se usa el header X-Workstation-ID si está presente,
    o se busca por la IP privada reportada en X-Workstation-Local-IP.

    Args:
        request: Objeto Request de FastAPI
        db: Sesión de base de datos

    Returns:
        Workstation identificada

    Raises:
        HTTPException 401: Si no se puede identificar la workstation
    """
    # Intentar identificar por header X-Workstation-ID (enviado por el Tray)
    workstation_id = request.headers.get("X-Workstation-ID")
    if workstation_id:
        workstation = db.query(Workstation).filter(
            Workstation.id == workstation_id
        ).first()
        if workstation:
            return workstation

    # Intentar autenticación por token Bearer
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            token = auth_header[7:]
            payload = decode_access_token(token)
            user_id = payload.get("sub")
            if user_id:
                user = db.query(User).filter(User.id == user_id).first()
                if user and user.organization_id:
                    # Buscar workstation por IP privada dentro de la cuenta
                    local_ip = request.headers.get("X-Workstation-Local-IP")
                    if local_ip:
                        workstation = db.query(Workstation).filter(
                            Workstation.organization_id == user.organization_id,
                            Workstation.ip_private == local_ip.strip()
                        ).first()
                        if workstation:
                            return workstation
        except Exception:
            pass  # Si falla el token, intentar por IP pública

    # Autenticación por IP pública (Tray clients sin token)
    client_ip = get_client_ip(request)

    public_ip_record = db.query(PublicIP).filter(
        PublicIP.ip_address == client_ip,
        PublicIP.is_authorized == True,
    ).first()

    if public_ip_record and public_ip_record.organization_id:
        # Buscar workstation por IP privada dentro de la organización
        local_ip = request.headers.get("X-Workstation-Local-IP")
        if local_ip:
            workstation = db.query(Workstation).filter(
                Workstation.organization_id == public_ip_record.organization_id,
                Workstation.ip_private == local_ip.strip()
            ).first()
            if workstation:
                return workstation

        # Si no hay IP privada, buscar la primera workstation de la organización
        # (caso de una sola workstation por IP pública)
        workstation = db.query(Workstation).filter(
            Workstation.organization_id == public_ip_record.organization_id
        ).first()
        if workstation:
            return workstation

    # No se pudo identificar la workstation
    logger.warning(
        "Workstation no autenticada: ip_publica=%s, "
        "x_workstation_id=%s, x_workstation_local_ip=%s",
        get_client_ip(request),
        request.headers.get("X-Workstation-ID", "no-presente"),
        request.headers.get("X-Workstation-Local-IP", "no-presente"),
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Workstation no autenticada"
    )


@router.get(
    "/check",
    response_model=UpdateCheckResponse,
    summary="Verificar actualización disponible",
    description=(
        "Retorna la versión disponible del MSI, el estado del flag de "
        "auto-actualización de la organización, y metadata del build."
    ),
    responses={
        401: {"description": "Workstation no autenticada"},
        503: {"description": "No se puede determinar la versión disponible (S3 no responde)"},
    },
)
def check_update(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Verificar si hay una actualización disponible.

    Soporta dos modos:
    - Admin (Bearer token con rol admin): retorna metadata del MSI sin requerir workstation
    - Workstation (IP pública o X-Workstation-ID): retorna metadata + flag de organización

    Retorna:
        - 200: UpdateCheckResponse con versión, flag, tamaño, fecha y commit
        - 401: No autenticado
        - 503: S3 no disponible
    """
    # Verificar si es un admin autenticado por Bearer token
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            token = auth_header[7:]
            payload = decode_access_token(token)
            user_id = payload.get("sub")
            if user_id:
                user = db.query(User).filter(User.id == user_id).first()
                is_admin_user = user and (user.role == UserRole.ADMIN or str(user.role.value if hasattr(user.role, 'value') else user.role) == "admin")
                is_operator_user = user and (user.role == UserRole.OPERATOR or str(user.role.value if hasattr(user.role, 'value') else user.role) == "operator")

                if user and (is_admin_user or is_operator_user):
                    # Admin/Operador: retornar solo metadata del MSI (sin requerir workstation)
                    try:
                        s3_service = S3UpdateService()
                        msi_metadata = s3_service.get_msi_metadata()
                    except (ClientError, Exception) as e:
                        logger.error("S3 no disponible para check: %s", str(e))
                        raise HTTPException(
                            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="No se puede determinar la versión disponible"
                        )

                    return UpdateCheckResponse(
                        version=msi_metadata['version'],
                        auto_update_enabled=False,
                        file_size=msi_metadata['file_size'],
                        build_date=msi_metadata['build_date'],
                        commit_hash=msi_metadata['commit_hash'],
                    )
                elif user:
                    # Usuario autenticado pero sin rol suficiente — no caer al flujo workstation
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Acceso no permitido"
                    )
        except HTTPException:
            raise  # Re-lanzar HTTPExceptions (403, 503)
        except Exception as e:
            logger.warning("Error al verificar token admin en /updates/check: %s", str(e))
            pass  # Si falla el token, intentar como workstation

    # Flujo normal: identificar workstation o al menos la organización
    # Para clientes antiguos que no envían X-Workstation-ID ni X-Workstation-Local-IP,
    # intentamos identificar la organización por IP pública directamente.
    try:
        workstation = _identify_workstation(request, db)
        account = db.query(Organization).filter(
            Organization.id == workstation.organization_id
        ).first()
    except HTTPException:
        # No se pudo identificar la workstation — intentar identificar organización por IP pública
        # (backward compatibility con clientes antiguos que no envían headers de identificación)
        client_ip = get_client_ip(request)
        public_ip_record = db.query(PublicIP).filter(
            PublicIP.ip_address == client_ip,
            PublicIP.is_authorized == True,
        ).first()
        
        if public_ip_record and public_ip_record.organization_id:
            account = db.query(Organization).filter(
                Organization.id == public_ip_record.organization_id
            ).first()
            workstation = None
            logger.info(
                "Verificación de actualización (fallback por IP pública): "
                "ip_publica=%s, organization=%s",
                client_ip,
                account.name if account else "desconocida"
            )
        else:
            # Tampoco se pudo identificar la organización
            # → Registrar IP como pendiente antes de retornar 401
            ip_publica = client_ip
            x_workstation_id = request.headers.get("X-Workstation-ID", "no-presente")
            x_workstation_local_ip = request.headers.get("X-Workstation-Local-IP", "no-presente")
            logger.warning(
                "IP no autorizada intentando verificar actualizaciones: "
                "ip_publica=%s, x_workstation_id=%s, x_workstation_local_ip=%s",
                ip_publica,
                x_workstation_id,
                x_workstation_local_ip,
            )
            _register_pending_ip(db, request)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Workstation no autenticada"
            )

    if not account:
        logger.error(
            "Organización no encontrada para workstation: workstation_id=%s, organization_id=%s",
            workstation.id,
            workstation.organization_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno: cuenta no encontrada"
        )

    auto_update_enabled = account.auto_update_enabled

    # 3. Obtener metadata del MSI desde S3
    # Si la organización tiene target_version, usar esa versión específica
    try:
        s3_service = S3UpdateService()
        if account.target_version:
            # Usar versión específica configurada para la organización
            target_key = f"versions/{account.target_version}/AlwaysPrint.msi"
            msi_metadata = s3_service.get_msi_metadata(key=target_key)
        else:
            # Usar latest por defecto
            msi_metadata = s3_service.get_msi_metadata()
    except ClientError:
        logger.error(
            "S3 no disponible al verificar actualización: "
            "workstation_id=%s, ip_private=%s",
            workstation.id if workstation else "N/A",
            workstation.ip_private if workstation else get_client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se puede determinar la versión disponible"
        )
    except Exception as e:
        logger.error(
            "Error inesperado al consultar S3: workstation_id=%s, error=%s",
            workstation.id if workstation else "N/A",
            str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se puede determinar la versión disponible"
        )

    # 4. Construir respuesta
    # Si hay target_version, el campo version refleja la versión objetivo
    response = UpdateCheckResponse(
        version=account.target_version if account.target_version else msi_metadata['version'],
        auto_update_enabled=auto_update_enabled,
        file_size=msi_metadata['file_size'],
        build_date=msi_metadata['build_date'],
        commit_hash=msi_metadata['commit_hash'],
    )

    # 5. Loggear request con identificador de workstation y status
    logger.info(
        "Verificación de actualización: workstation_id=%s, ip_private=%s, "
        "version_disponible=%s, auto_update_enabled=%s, status=200",
        workstation.id if workstation else "N/A (fallback por IP)",
        workstation.ip_private if workstation else get_client_ip(request),
        msi_metadata['version'],
        auto_update_enabled,
    )

    return response


@router.get(
    "/download",
    summary="Descargar MSI de actualización",
    description=(
        "Genera una URL presigned de S3 para el MSI más reciente y redirige "
        "al cliente. Requiere que la organización tenga auto-actualizaciones "
        "habilitadas."
    ),
    responses={
        200: {"description": "Archivo MSI (streaming)"},
        401: {"description": "Workstation no autenticada"},
        403: {"description": "Actualizaciones automáticas deshabilitadas para esta organización"},
        500: {"description": "Error interno al generar URL de descarga"},
    },
)
def download_update(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Descargar el MSI de actualización via presigned URL.

    Identifica la workstation, verifica que su organización tiene
    auto-actualizaciones habilitadas, genera una URL presigned de S3,
    y redirige al cliente con un 302.

    Retorna:
        - 200: Archivo MSI (streaming directo desde S3)
        - 401: Workstation no autenticada
        - 403: Auto-actualizaciones deshabilitadas para la organización
        - 500: Error al generar la URL presigned
    """
    # 1. Identificar workstation o al menos la organización (backward compatibility)
    try:
        workstation = _identify_workstation(request, db)
        account = db.query(Organization).filter(
            Organization.id == workstation.organization_id
        ).first()
    except HTTPException:
        # Fallback por IP pública para clientes antiguos sin headers de identificación
        client_ip = get_client_ip(request)
        public_ip_record = db.query(PublicIP).filter(
            PublicIP.ip_address == client_ip,
            PublicIP.is_authorized == True,
        ).first()
        
        if public_ip_record and public_ip_record.organization_id:
            account = db.query(Organization).filter(
                Organization.id == public_ip_record.organization_id
            ).first()
            workstation = None
            logger.info(
                "Descarga de actualización (fallback por IP pública): "
                "ip_publica=%s, organization=%s",
                client_ip,
                account.name if account else "desconocida"
            )
        else:
            # IP no autorizada: registrar como pendiente si no existe
            existing_ip = db.query(PublicIP).filter(
                PublicIP.ip_address == client_ip
            ).first()
            if not existing_ip:
                import json as json_module
                from datetime import datetime, timezone
                payload_dict = {
                    "endpoint": "/updates/download",
                    "method": "GET",
                    "ip": client_ip,
                    "hostname": request.headers.get("X-Workstation-Hostname") if hasattr(request, 'headers') else None,
                    "user": request.headers.get("X-Workstation-User") if hasattr(request, 'headers') else None,
                    "ip_private": request.headers.get("X-Workstation-IP-Private") if hasattr(request, 'headers') else None,
                    "user_agent": request.headers.get("User-Agent") if hasattr(request, 'headers') else None,
                    "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                }
                try:
                    payload_json = json_module.dumps(payload_dict, ensure_ascii=False, default=str)
                except (TypeError, ValueError):
                    payload_json = None
                new_pending_ip = PublicIP(
                    ip_address=client_ip,
                    is_authorized=False,
                    organization_id=None,
                    description=f"Detectada en endpoint /updates/download el {datetime.now(timezone.utc).replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S')}",
                    request_count=1,
                    first_payload=payload_json,
                )
                db.add(new_pending_ip)
                db.commit()
                logger.info(
                    "IP registrada como pendiente de aprobación (desde /updates/download): %s",
                    client_ip
                )
            else:
                # IP ya existe como pendiente: incrementar contador
                if not existing_ip.is_authorized:
                    existing_ip.request_count = (existing_ip.request_count or 0) + 1
                    db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Workstation no autenticada"
            )

    if not account:
        logger.error(
            "Organización no encontrada para workstation en descarga: "
            "workstation_id=%s, ip_publica=%s",
            workstation.id if workstation else "N/A",
            get_client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno: cuenta no encontrada"
        )

    # 3. Verificar que auto-actualizaciones están habilitadas para la organización
    if not account.auto_update_enabled:
        logger.warning(
            "Descarga denegada - auto-actualizaciones deshabilitadas: "
            "workstation_id=%s, organización=%s",
            workstation.id if workstation else "N/A",
            getattr(account, 'name', 'desconocida'),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Actualizaciones automáticas deshabilitadas para esta organización"
        )

    # 4. Descargar el MSI desde S3 y servirlo directamente (streaming)
    # Se evita el redirect a presigned URL porque algunos clientes no lo manejan correctamente
    # IMPORTANTE: Cerrar sesión de BD ANTES del streaming para no retener conexión del pool
    # durante toda la descarga (que puede tardar minutos con archivos grandes)
    target_key = None
    if account.target_version:
        target_key = f"versions/{account.target_version}/AlwaysPrint.msi"
    
    # Capturar datos necesarios antes de cerrar la sesión
    ws_id = str(workstation.id) if workstation else "N/A (fallback IP)"
    client_ip = get_client_ip(request)
    account_name = account.name if account else "desconocida"
    
    # Liberar sesión de BD — ya no la necesitamos para el streaming
    db.close()
    
    try:
        s3_service = S3UpdateService()
        s3_response = s3_service.get_object(key=target_key)
    except ClientError:
        logger.error(
            "Error de S3 al descargar MSI: "
            "workstation_id=%s, ip_publica=%s",
            ws_id,
            client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al descargar archivo"
        )
    except Exception as e:
        logger.error(
            "Error inesperado al descargar MSI: "
            "workstation_id=%s, error=%s",
            ws_id,
            str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al descargar archivo"
        )

    # 5. Loggear descarga exitosa y servir archivo
    logger.info(
        "Descarga de actualización autorizada: workstation_id=%s, "
        "ip_publica=%s, organization=%s, status=200",
        ws_id,
        client_ip,
        account_name,
    )

    return StreamingResponse(
        s3_response['Body'].iter_chunks(chunk_size=65536),
        media_type="application/x-msi",
        headers={
            "Content-Disposition": "attachment; filename=AlwaysPrint.msi",
            "Content-Length": str(s3_response.get('ContentLength', 0)),
        },
    )


@router.post(
    "/notify-new-version",
    summary="Notificar nueva versión disponible (CI/CD)",
    description=(
        "Llamado por el CI después de subir un MSI a S3. "
        "Refresca el state map de todas las organizaciones en modo 'Latest' "
        "para que las workstations reciban la nueva versión en el próximo enrichment."
    ),
    responses={
        200: {"description": "State map actualizado"},
        404: {"description": "No se encontró metadata de MSI en S3"},
    },
)
async def notify_new_version(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Notifica al backend que hay una nueva versión MSI en S3.

    Refresca el state map para todas las organizaciones que usan 'Latest (automatic)'
    (target_version IS NULL y auto_update_enabled = True).

    Llamado por GitHub Actions después del upload a S3.
    No requiere autenticación JWT — es idempotente y solo refresca caché interno.
    """
    from app.services.push_services import get_state_map_service, get_push_distribution_service

    s3_service = S3UpdateService()
    metadata = s3_service.get_msi_metadata()

    if not metadata or not metadata.get("version"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró metadata de MSI en S3 (latest).",
        )

    new_version = metadata["version"]
    file_size = metadata.get("file_size", 0)

    # Obtener organizaciones en modo "Latest" (sin versión pinneada, auto-update habilitado)
    orgs = db.query(Organization).filter(
        Organization.target_version.is_(None),
        Organization.auto_update_enabled == True,
    ).all()

    if not orgs:
        return {
            "version": new_version,
            "organizations_updated": 0,
            "message": "No hay organizaciones en modo Latest con auto-update habilitado.",
        }

    state_map = get_state_map_service()
    push_service = get_push_distribution_service()

    # Obtener URL de descarga (presigned o pública)
    update_info = s3_service.get_broadcast_update_info(target_version=new_version)
    download_url = update_info["download_url"] if update_info else None

    updated_orgs = 0
    total_ws_notified = 0

    for org in orgs:
        org_id = str(org.id)
        try:
            # Actualizar state map en memoria
            await state_map.update_msi(
                org_id=org_id,
                msi_version=new_version,
                msi_url=download_url,
            )

            # Push a workstations online
            if download_url:
                enviados = await push_service.push_msi_update(
                    org_id=org_id,
                    msi_version=new_version,
                    download_url=download_url,
                    file_size=file_size,
                )
                total_ws_notified += enviados

            updated_orgs += 1
        except Exception as e:
            logger.error(
                "notify_new_version: error actualizando org=%s: %s", org_id, str(e)
            )

    logger.info(
        "notify_new_version: version=%s, orgs_actualizadas=%d, ws_notificadas=%d",
        new_version, updated_orgs, total_ws_notified,
    )

    return {
        "version": new_version,
        "organizations_updated": updated_orgs,
        "workstations_notified": total_ws_notified,
        "message": f"State map actualizado para {updated_orgs} organización(es). {total_ws_notified} WS notificadas.",
    }
