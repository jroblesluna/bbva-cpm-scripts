"""
Servicio orquestador de análisis de logs de workstations.

Coordina el flujo completo de procesamiento:
descompresión → routing → procesamiento (directo o estructural) → LLM → guardado en BD.

Incluye el prompt contextualizado para AlwaysPrint (LLM_PROMPT) con tabla de Event IDs
y las instrucciones de análisis en español.
"""

import logging
import time
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.log_analysis import LogAnalysis
from app.services.llm_service import LLMService
from app.services.log_processor import (
    DEFAULT_KEYWORDS,
    assemble_direct_payload,
    assemble_structural_payload,
    decompress_if_needed,
    route_by_size,
    run_structural_analysis,
)

logger = logging.getLogger(__name__)


# === PROMPT LLM CONTEXTUALIZADO PARA ALWAYSPRINT ===

LLM_PROMPT = """Eres un experto en diagnóstico de sistemas Windows y servicios de impresión corporativa.

Estás analizando logs de una workstation Windows que ejecuta AlwaysPrint, un sistema de contingencia \
de impresión para BBVA. AlwaysPrint coexiste con Lexmark CPM (Cloud Print Manager) y se activa \
cuando CPM falla, redirigiendo el tráfico de impresión directamente a la IP de la impresora, \
haciendo bypass del servidor Linux.

## Formato de log

El formato de cada línea es: `[yyyy-MM-dd HH:mm:ss] [SVC/APP] Event NNNN: mensaje`
- SVC = AlwaysPrintService (servicio Windows)
- APP = AlwaysPrintTray (aplicación de bandeja del usuario)
- NNNN = Event ID numérico (rango 1000-1091)

## Tabla de Event IDs clave

| Event ID | Significado |
|----------|-------------|
| 1000 | Servicio iniciado |
| 1001 | Servicio detenido |
| 1003 | Monitoreo de Tray |
| 1004 | Cola de tareas |
| 1005 | Servidor de pipe (IPC) |
| 1007 | Usuario detectado |
| 1008 | Tray lanzado |
| 1009 | Tray inicializado |
| 1020 | Tarea despachada |
| 1021 | Tarea completada |
| 1030 | Configuración guardada |
| 1090 | Info/debug |
| 1091 | Error |

## Análisis solicitado

Analiza la evidencia proporcionada evaluando:
1. Estado operativo del servicio (arranques, paradas, estabilidad)
2. Validez de la configuración del servicio
3. Eventos de entrada/salida de contingencia
4. Cambios de sesión de usuario
5. Conectividad de red con Cloud Manager e impresoras
6. Causas raíz de errores basándote en los Event IDs

## Formato de respuesta requerido

Estructura tu respuesta en las siguientes secciones:

### (a) Resumen de hallazgos
Resumen ejecutivo de 2-3 párrafos con los problemas principales encontrados.

### (b) Narrativa cronológica
Secuencia de eventos con timestamps, describiendo qué ocurrió y cuándo.

### (c) Causas raíz identificadas
Lista de causas raíz mapeadas a Event IDs específicos.

### (d) Evaluación de impacto
Impacto en la disponibilidad del servicio de impresión.

### (e) Acciones correctivas recomendadas
Lista priorizada de acciones para resolver los problemas encontrados.

---
FIN DEL PROMPT. A continuación se presenta la evidencia del log:
---"""


class LogAnalysisService:
    """
    Servicio orquestador del análisis de logs de workstations.

    Coordina descompresión, routing por tamaño, procesamiento estructural,
    invocación del LLM y persistencia del resultado en base de datos.
    Todas las queries filtran por organization_id para tenant isolation.
    """

    def __init__(self) -> None:
        self.llm_service = LLMService()

    async def process_log(
        self,
        db: Session,
        workstation_id: str,
        organization_id: str,
        raw_payload: bytes,
        is_compressed: bool,
        original_filename: str,
        original_size: int,
        overwrite: bool = False,
    ) -> LogAnalysis:
        """
        Procesa un log recibido de una workstation.

        Flujo completo:
        1. Descompresión (si viene como ZIP)
        2. Routing por tamaño (directo vs estructural)
        3. Procesamiento según ruta
        4. Invocación del LLM
        5. Guardado del resultado en BD

        Parámetros:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation (string)
            organization_id: UUID de la organización (string)
            raw_payload: Contenido del log en bytes (puede ser ZIP)
            is_compressed: Si el payload viene comprimido como ZIP
            original_filename: Nombre original del archivo de log
            original_size: Tamaño original en bytes
            overwrite: Si debe sobrescribir análisis existente del día

        Retorna:
            LogAnalysis: Registro guardado con el resultado del análisis.

        Raises:
            ValueError: Si el ZIP es corrupto o no contiene archivos válidos.
            LLMServiceError: Si el LLM falla después de reintentos.
        """
        start_time = time.time()

        # 1. Manejo de overwrite: eliminar registro existente si corresponde
        if overwrite:
            existing = self.get_today_analysis(db, workstation_id, organization_id)
            if existing:
                logger.info(
                    "[LOG_ANALYZER] Eliminando análisis existente para overwrite: "
                    "workstation_id=%s, analysis_id=%s",
                    workstation_id,
                    existing.id,
                )
                db.delete(existing)
                db.flush()

        # 2. Descompresión
        content, file_contents = decompress_if_needed(raw_payload, is_compressed)
        log_size_bytes = len(content.encode("utf-8"))

        logger.info(
            "[LOG_ANALYZER] Log descomprimido: workstation_id=%s, "
            "tamaño=%d bytes, archivos=%d",
            workstation_id,
            log_size_bytes,
            len(file_contents),
        )

        # 3. Procesamiento estructural (siempre, independiente del tamaño)
        # El análisis estructural extrae keywords, patrones, contexto y timeline
        # para enviar solo información relevante al LLM, optimizando tokens.
        keywords = DEFAULT_KEYWORDS + settings.log_analyzer_extra_keywords_list
        context_size = settings.LOG_ANALYZER_CONTEXT_WINDOW_SIZE
        max_blocks = settings.LOG_ANALYZER_MAX_CONTEXT_BLOCKS
        top_n = settings.LOG_ANALYZER_TOP_PATTERNS

        structured_analysis = run_structural_analysis(
            content=content,
            filename=original_filename,
            keywords=keywords,
            context_size=context_size,
            max_blocks=max_blocks,
            top_n=top_n,
        )

        processing_path = "structural"

        logger.info(
            "[LOG_ANALYZER] Análisis estructural completado: workstation_id=%s, "
            "log_size=%d bytes",
            workstation_id,
            log_size_bytes,
        )

        payload = assemble_structural_payload(
            structured_analysis=structured_analysis,
            prompt=LLM_PROMPT,
        )

        # 4. Invocación del LLM
        # Obtener configuración LLM de la organización
        from app.models.organization import Organization
        org = db.query(Organization).filter(Organization.id == organization_id).first()
        org_model_id = org.llm_model_id if org else None
        org_openai_key = org.openai_api_key if org else None

        # Si la organización tiene API Key de OpenAI, usar OpenAI directamente
        if org_openai_key:
            from app.services.llm_service import OpenAIProvider, LLMServiceError as _Err
            logger.info(
                "[LOG_ANALYZER] Invocando OpenAI (API key de organización): "
                "workstation_id=%s, payload_length=%d chars",
                workstation_id,
                len(payload),
            )
            openai_provider = OpenAIProvider()
            openai_provider.api_key = org_openai_key
            # Usar modelo de la organización si está configurado, sino gpt-4o
            if org_model_id:
                openai_provider.model = org_model_id
            analysis_text = await openai_provider.invoke(
                payload, settings.LOG_ANALYZER_LLM_MAX_TOKENS
            )
        else:
            # Usar Bedrock (default del sistema)
            logger.info(
                "[LOG_ANALYZER] Invocando Bedrock: workstation_id=%s, "
                "model_override=%s, payload_length=%d chars",
                workstation_id,
                org_model_id or "(default)",
                len(payload),
            )
            analysis_text = await self.llm_service.invoke(payload, model_id=org_model_id)

        # 6. Calcular duración del procesamiento
        duration_ms = int((time.time() - start_time) * 1000)

        logger.info(
            "[LOG_ANALYZER] Análisis completado: workstation_id=%s, "
            "path=%s, log_size=%d bytes, duration=%dms",
            workstation_id,
            processing_path,
            log_size_bytes,
            duration_ms,
        )

        # 7. Guardar en base de datos
        log_analysis = LogAnalysis(
            workstation_id=workstation_id,
            organization_id=organization_id,
            analysis_date=date.today(),
            analysis_text=analysis_text,
            processing_path=processing_path,
            log_size_bytes=log_size_bytes,
            processing_duration_ms=duration_ms,
            original_filename=original_filename,
        )

        db.add(log_analysis)
        db.commit()
        db.refresh(log_analysis)

        return log_analysis

    def get_today_analysis(
        self, db: Session, workstation_id: str, organization_id: str
    ) -> Optional[LogAnalysis]:
        """
        Obtener análisis del día actual para una workstation.

        Filtra por workstation_id + fecha actual + organization_id
        para mantener tenant isolation.

        Parámetros:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation (string)
            organization_id: UUID de la organización (string)

        Retorna:
            LogAnalysis si existe un análisis para hoy, None en caso contrario.
        """
        return (
            db.query(LogAnalysis)
            .filter(
                LogAnalysis.workstation_id == workstation_id,
                LogAnalysis.organization_id == organization_id,
                LogAnalysis.analysis_date == date.today(),
            )
            .first()
        )

    def get_analysis_history(
        self,
        db: Session,
        workstation_id: str,
        organization_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[LogAnalysis], int]:
        """
        Obtener historial paginado de análisis de una workstation.

        Retorna los análisis ordenados por fecha descendente (más reciente primero).
        Filtra por organization_id para tenant isolation.

        Parámetros:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation (string)
            organization_id: UUID de la organización (string)
            page: Número de página (1-based)
            page_size: Cantidad de resultados por página (default 20)

        Retorna:
            Tupla (lista_de_análisis, total_de_registros).
        """
        base_query = db.query(LogAnalysis).filter(
            LogAnalysis.workstation_id == workstation_id,
            LogAnalysis.organization_id == organization_id,
        )

        # Contar total de registros
        total = base_query.count()

        # Obtener página con orden descendente por fecha
        offset = (page - 1) * page_size
        items = (
            base_query
            .order_by(LogAnalysis.analysis_date.desc(), LogAnalysis.created_at.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )

        return (items, total)

    def get_analysis_by_id(
        self, db: Session, analysis_id: str, organization_id: str
    ) -> Optional[LogAnalysis]:
        """
        Obtener un análisis por su ID con filtro de tenant.

        Filtra por organization_id para garantizar que un usuario
        solo pueda acceder a análisis de su propia organización.

        Parámetros:
            db: Sesión de base de datos
            analysis_id: UUID del análisis (string)
            organization_id: UUID de la organización (string)

        Retorna:
            LogAnalysis si existe y pertenece a la organización, None en caso contrario.
        """
        return (
            db.query(LogAnalysis)
            .filter(
                LogAnalysis.id == analysis_id,
                LogAnalysis.organization_id == organization_id,
            )
            .first()
        )
