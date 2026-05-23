"""
Endpoints de análisis de logs de workstations.

Este módulo define los endpoints para:
- Solicitar análisis de log bajo demanda (POST)
- Verificar si existe análisis del día actual (GET today)
- Listar historial de análisis paginado (GET list)
- Obtener un análisis individual por ID (GET single)
"""

import base64
import logging
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.models.workstation import Workstation
from app.schemas.log_analysis import (
    LogAnalysisListResponse,
    LogAnalysisResponse,
    LogAnalysisTodayCheckResponse,
)
from app.services.llm_service import LLMServiceError
from app.services.log_analysis import LogAnalysisService
from app.services.websocket_manager import connection_manager

router = APIRouter()
logger = logging.getLogger(__name__)


# === HELPERS ===


def _verify_workstation_access(
    workstation_id: UUID, current_user: User, db: Session
) -> Workstation:
    """
    Verifica que la workstation existe y que el usuario tiene permisos.

    Retorna la workstation si todo es válido.

    Raises:
        HTTPException 404: Workstation no encontrada
        HTTPException 403: Sin permisos para acceder a esta workstation
    """
    workstation = db.query(Workstation).filter(Workstation.id == workstation_id).first()

    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada",
        )

    # Verificar permisos: operadores solo pueden acceder a workstations de su organización
    if current_user.role == UserRole.OPERATOR:
        if workstation.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para acceder a esta workstation",
            )

    return workstation


# === ENDPOINTS ===


@router.post(
    "/{workstation_id}/analyze-log",
    response_model=LogAnalysisResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"description": "Workstation no encontrada"},
        408: {"description": "Timeout esperando respuesta de la workstation"},
        409: {"description": "Workstation offline o análisis existente sin confirmación"},
        413: {"description": "Upload excede tamaño máximo"},
        422: {"description": "ZIP corrupto o formato inválido"},
        502: {"description": "Error del servicio LLM"},
    },
)
async def analyze_workstation_log(
    workstation_id: UUID,
    overwrite: bool = Query(False, description="Sobrescribir análisis existente del día"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LogAnalysisResponse:
    """
    Solicitar análisis de log del día actual de una workstation.

    Flujo:
    1. Verificar workstation existe y permisos
    2. Verificar si ya existe análisis del día (si no overwrite, retornar 409)
    3. Enviar comando analyze_log vía WebSocket
    4. Esperar respuesta con log data
    5. Procesar log (directo o estructural según tamaño)
    6. Invocar LLM
    7. Guardar resultado y retornar
    """
    # 1. Verificar workstation y permisos
    workstation = _verify_workstation_access(workstation_id, current_user, db)

    # Determinar organization_id del usuario
    organization_id = str(workstation.organization_id)

    # 2. Verificar análisis existente del día
    service = LogAnalysisService()
    workstation_id_str = str(workstation_id)

    if not overwrite:
        existing = service.get_today_analysis(db, workstation_id_str, organization_id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe un análisis para esta workstation hoy. "
                "Use overwrite=true para sobrescribir.",
            )

    # 3. Verificar que la workstation está online
    if not connection_manager.is_workstation_online(workstation_id_str):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La workstation está offline. No se puede solicitar el análisis de log.",
        )

    # 4. Enviar comando analyze_log vía WebSocket
    command_id = str(uuid.uuid4())
    connection_manager.register_command_waiter(command_id)

    message = {
        "type": "command",
        "command_id": command_id,
        "command_type": "analyze_log",
        "params": {},
    }

    sent = await connection_manager.send_to_workstation(workstation_id_str, message)

    if not sent:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La workstation se desconectó antes de recibir el comando.",
        )

    logger.info(
        "[LOG_ANALYZER] Comando analyze_log enviado: command_id=%s, "
        "workstation_id=%s, solicitado_por=%s",
        command_id,
        workstation_id,
        current_user.email,
    )

    # 5. Esperar respuesta con timeout configurable
    timeout = float(settings.LOG_ANALYZER_COMMAND_TIMEOUT)
    response_data = await connection_manager.wait_for_command_response(
        command_id, timeout=timeout
    )

    if response_data is None:
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail="Timeout esperando respuesta de la workstation. Intente nuevamente.",
        )

    if not response_data.get("success"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en la workstation: {response_data.get('output', 'Error desconocido')}",
        )

    # 6. Extraer datos del log de la respuesta
    output = response_data.get("output") or ""

    # Parsear respuesta: puede ser JSON con filename, content, original_size, is_compressed
    import json as json_module

    try:
        output_data = json_module.loads(output) if isinstance(output, str) else output
    except (json_module.JSONDecodeError, ValueError):
        output_data = output

    if isinstance(output_data, dict):
        filename = output_data.get("filename", "alwaysprint.log")
        content_b64 = output_data.get("content", "")
        original_size = output_data.get("original_size", 0)
        is_compressed = output_data.get("is_compressed", False)
    else:
        # Fallback: asumir base64 directo
        filename = "alwaysprint.log"
        content_b64 = str(output_data)
        original_size = 0
        is_compressed = False

    # Decodificar contenido base64
    if not content_b64:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La workstation no envió contenido del log en la respuesta.",
        )

    try:
        raw_payload = base64.b64decode(content_b64)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Error decodificando el contenido del log recibido (base64 inválido).",
        )

    # 7. Validar tamaño máximo de upload
    max_upload_size = settings.LOG_ANALYZER_MAX_UPLOAD_SIZE
    if len(raw_payload) > max_upload_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"El log excede el tamaño máximo permitido "
            f"({max_upload_size // (1024 * 1024)}MB).",
        )

    # 8. Procesar log vía LogAnalysisService
    try:
        log_analysis = await service.process_log(
            db=db,
            workstation_id=workstation_id_str,
            organization_id=organization_id,
            raw_payload=raw_payload,
            is_compressed=is_compressed,
            original_filename=filename,
            original_size=original_size,
            overwrite=overwrite,
        )
    except ValueError as e:
        # ZIP corrupto o sin archivos válidos
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Error procesando el log: {str(e)}",
        )
    except LLMServiceError as e:
        # Error del LLM después de reintentos
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error del servicio de análisis IA: {str(e)}",
        )

    logger.info(
        "[LOG_ANALYZER] Análisis completado: workstation_id=%s, "
        "analysis_id=%s, path=%s, duration=%dms",
        workstation_id,
        log_analysis.id,
        log_analysis.processing_path,
        log_analysis.processing_duration_ms,
    )

    return log_analysis


@router.get(
    "/{workstation_id}/log-analyses/today",
    response_model=LogAnalysisTodayCheckResponse,
    status_code=status.HTTP_200_OK,
)
async def check_today_analysis(
    workstation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LogAnalysisTodayCheckResponse:
    """Verificar si existe un análisis del día actual para la workstation."""
    # Verificar workstation y permisos
    workstation = _verify_workstation_access(workstation_id, current_user, db)

    organization_id = str(workstation.organization_id)
    workstation_id_str = str(workstation_id)

    service = LogAnalysisService()
    existing = service.get_today_analysis(db, workstation_id_str, organization_id)

    if existing:
        return LogAnalysisTodayCheckResponse(
            exists=True,
            analysis_id=existing.id,
        )

    return LogAnalysisTodayCheckResponse(exists=False, analysis_id=None)


@router.get(
    "/{workstation_id}/log-analyses",
    response_model=LogAnalysisListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_workstation_analyses(
    workstation_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LogAnalysisListResponse:
    """Listar historial de análisis de una workstation, paginado."""
    # Verificar workstation y permisos
    workstation = _verify_workstation_access(workstation_id, current_user, db)

    organization_id = str(workstation.organization_id)
    workstation_id_str = str(workstation_id)

    service = LogAnalysisService()
    items, total = service.get_analysis_history(
        db=db,
        workstation_id=workstation_id_str,
        organization_id=organization_id,
        page=page,
        page_size=page_size,
    )

    return LogAnalysisListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/log-analyses/{analysis_id}",
    response_model=LogAnalysisResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"description": "Análisis no encontrado"}},
)
async def get_analysis(
    analysis_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LogAnalysisResponse:
    """Obtener un análisis específico por su ID."""
    # Determinar organization_id para filtro de tenant
    if current_user.role == UserRole.OPERATOR:
        organization_id = str(current_user.organization_id)
    else:
        # Admin: buscar sin restricción de organización (pasamos None y ajustamos query)
        organization_id = None

    service = LogAnalysisService()

    if organization_id:
        analysis = service.get_analysis_by_id(db, str(analysis_id), organization_id)
    else:
        # Admin puede ver cualquier análisis
        from app.models.log_analysis import LogAnalysis

        analysis = (
            db.query(LogAnalysis).filter(LogAnalysis.id == str(analysis_id)).first()
        )

    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Análisis con ID {analysis_id} no encontrado",
        )

    return analysis
