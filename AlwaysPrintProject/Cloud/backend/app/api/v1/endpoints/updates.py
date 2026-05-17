"""
Endpoints de actualizaciones automáticas.

Este módulo define los endpoints para:
- Verificación de versión disponible del MSI (GET /updates/check)
- Descarga del MSI via presigned URL (GET /updates/download) [tarea 4.2]

La autenticación de workstations se realiza por IP pública o token Bearer,
siguiendo el mismo patrón que el endpoint de configuración efectiva.
"""

import logging

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.core.utils import get_client_ip
from app.models.organization import Organization, Account, PublicIP
from app.models.user import User, UserRole
from app.models.workstation import Workstation
from app.schemas.updates import UpdateCheckResponse
from app.services.s3_update_service import S3UpdateService

# Logger del módulo
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/updates", tags=["Actualizaciones"])


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
                if user and user.account_id:
                    # Buscar workstation por IP privada dentro de la cuenta
                    local_ip = request.headers.get("X-Workstation-Local-IP")
                    if local_ip:
                        workstation = db.query(Workstation).filter(
                            Workstation.organization_id == user.account_id,
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

    if public_ip_record and public_ip_record.account_id:
        # Buscar workstation por IP privada dentro de la cuenta
        local_ip = request.headers.get("X-Workstation-Local-IP")
        if local_ip:
            workstation = db.query(Workstation).filter(
                Workstation.organization_id == public_ip_record.account_id,
                Workstation.ip_private == local_ip.strip()
            ).first()
            if workstation:
                return workstation

        # Si no hay IP privada, buscar la primera workstation de la cuenta
        # (caso de una sola workstation por IP pública)
        workstation = db.query(Workstation).filter(
            Workstation.organization_id == public_ip_record.account_id
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

    Identifica la workstation por IP pública o token, obtiene el flag
    de auto-actualización de la organización, y consulta la metadata
    del MSI más reciente en S3.

    Retorna:
        - 200: UpdateCheckResponse con versión, flag, tamaño, fecha y commit
        - 401: Workstation no autenticada
        - 503: S3 no disponible
    """
    # 1. Identificar workstation
    workstation = _identify_workstation(request, db)

    # 2. Obtener account_id y leer auto_update_enabled
    account = db.query(Account).filter(
        Account.id == workstation.account_id
    ).first()

    if not account:
        logger.error(
            "Cuenta no encontrada para workstation: workstation_id=%s, account_id=%s",
            workstation.id,
            workstation.account_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno: cuenta no encontrada"
        )

    auto_update_enabled = account.auto_update_enabled

    # 3. Obtener metadata del MSI desde S3
    try:
        s3_service = S3UpdateService()
        msi_metadata = s3_service.get_msi_metadata()
    except ClientError:
        logger.error(
            "S3 no disponible al verificar actualización: "
            "workstation_id=%s, ip_private=%s",
            workstation.id,
            workstation.ip_private,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se puede determinar la versión disponible"
        )
    except Exception as e:
        logger.error(
            "Error inesperado al consultar S3: workstation_id=%s, error=%s",
            workstation.id,
            str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se puede determinar la versión disponible"
        )

    # 4. Construir respuesta
    response = UpdateCheckResponse(
        version=msi_metadata['version'],
        auto_update_enabled=auto_update_enabled,
        file_size=msi_metadata['file_size'],
        build_date=msi_metadata['build_date'],
        commit_hash=msi_metadata['commit_hash'],
    )

    # 5. Loggear request con identificador de workstation y status
    logger.info(
        "Verificación de actualización: workstation_id=%s, ip_private=%s, "
        "version_disponible=%s, auto_update_enabled=%s, status=200",
        workstation.id,
        workstation.ip_private,
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
        302: {"description": "Redirect a presigned URL de S3"},
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
        - 302: Redirect a la presigned URL de S3
        - 401: Workstation no autenticada
        - 403: Auto-actualizaciones deshabilitadas para la organización
        - 500: Error al generar la URL presigned
    """
    # 1. Identificar workstation
    workstation = _identify_workstation(request, db)

    # 2. Obtener cuenta y verificar flag de auto-actualización
    account = db.query(Account).filter(
        Account.id == workstation.account_id
    ).first()

    if not account:
        logger.error(
            "Cuenta no encontrada para workstation en descarga: "
            "workstation_id=%s, account_id=%s",
            workstation.id,
            workstation.account_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno: cuenta no encontrada"
        )

    # 3. Verificar que auto-actualizaciones están habilitadas para la organización
    if not account.auto_update_enabled:
        logger.warning(
            "Descarga denegada - auto-actualizaciones deshabilitadas: "
            "workstation_id=%s, account_id=%s, organización=%s",
            workstation.id,
            workstation.account_id,
            getattr(account, 'name', 'desconocida'),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Actualizaciones automáticas deshabilitadas para esta organización"
        )

    # 4. Generar presigned URL para descarga del MSI
    try:
        s3_service = S3UpdateService()
        presigned_url = s3_service.generate_download_url()
    except ClientError:
        logger.error(
            "Error de S3 al generar URL de descarga: "
            "workstation_id=%s, account_id=%s",
            workstation.id,
            workstation.account_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al generar URL de descarga"
        )
    except Exception as e:
        logger.error(
            "Error inesperado al generar URL de descarga: "
            "workstation_id=%s, error=%s",
            workstation.id,
            str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al generar URL de descarga"
        )

    # 5. Loggear descarga exitosa y redirigir
    logger.info(
        "Descarga de actualización autorizada: workstation_id=%s, "
        "ip_private=%s, account_id=%s, status=302",
        workstation.id,
        workstation.ip_private,
        workstation.account_id,
    )

    return RedirectResponse(url=presigned_url, status_code=302)
