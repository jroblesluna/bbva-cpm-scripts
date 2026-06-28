"""
Batch writer para actualizaciones de status de workstations.

Acumula updates en memoria y los escribe a BD cada 5 segundos en un solo
batch SQL, usando 1 sola conexion de pool. Esto evita el pool exhaustion
cuando 300+ workstations envian status_update simultaneamente.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

_FLUSH_INTERVAL = 5.0  # segundos entre flushes


@dataclass
class PendingStatusUpdate:
    """Datos pendientes de escribir a BD para una workstation."""
    workstation_id: str
    current_user: Optional[str] = None
    action_config_name: Optional[str] = None
    action_config_hash: Optional[str] = None
    action_config_version: Optional[str] = None


class StatusBatchWriter:
    """
    Acumula actualizaciones de status y las escribe a BD en batch.
    
    En vez de 1 SessionLocal() por cada status_update (300 conexiones simultaneas),
    usa 1 sola conexion cada 5 segundos para escribir todos los pendientes.
    
    Solo batchea campos de alta frecuencia y baja prioridad:
    - current_user
    - action_config_name / action_config_hash / action_config_version
    
    NO batchea contingency_active (requiere persistencia inmediata + auditoria).
    """
    
    def __init__(self):
        self._pending: dict[str, PendingStatusUpdate] = {}
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False
    
    def start(self):
        """Inicia el flush loop en background."""
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.ensure_future(self._flush_loop())
        logger.info("StatusBatchWriter: iniciado (flush cada %.1fs)", _FLUSH_INTERVAL)
    
    def stop(self):
        """Detiene el flush loop."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
    
    def enqueue_update(
        self,
        workstation_id: str,
        current_user: Optional[str] = None,
        action_config_name: Optional[str] = None,
        action_config_hash: Optional[str] = None,
        action_config_version: Optional[str] = None,
    ):
        """
        Encola una actualizacion de status para batch write.
        Si ya hay un update pendiente para esta WS, lo sobreescribe (ultimo gana).
        """
        existing = self._pending.get(workstation_id)
        
        if existing:
            # Merge: solo sobreescribir campos que vienen con valor
            if current_user is not None:
                existing.current_user = current_user
            if action_config_name is not None:
                existing.action_config_name = action_config_name
            if action_config_hash is not None:
                existing.action_config_hash = action_config_hash
            if action_config_version is not None:
                existing.action_config_version = action_config_version
        else:
            self._pending[workstation_id] = PendingStatusUpdate(
                workstation_id=workstation_id,
                current_user=current_user,
                action_config_name=action_config_name,
                action_config_hash=action_config_hash,
                action_config_version=action_config_version,
            )
    
    async def _flush_loop(self):
        """Background loop que flushea updates pendientes cada N segundos."""
        while self._running:
            await asyncio.sleep(_FLUSH_INTERVAL)
            await self._flush()
    
    async def _flush(self):
        """Escribe todos los updates pendientes a BD en un solo batch."""
        if not self._pending:
            return
        
        # Swap: tomar los pendientes y limpiar para no bloquear nuevos enqueues
        batch = self._pending
        self._pending = {}
        
        try:
            db = SessionLocal()
            try:
                from app.models.workstation import Workstation
                
                for ws_id, update in batch.items():
                    # Construir SET dinamico solo con campos que tienen valor
                    values = {}
                    if update.current_user is not None:
                        values["current_user"] = update.current_user
                        values["is_online"] = True
                    if update.action_config_name is not None:
                        values["action_config_name"] = update.action_config_name
                    if update.action_config_hash is not None:
                        values["action_config_hash"] = update.action_config_hash
                    if update.action_config_version is not None:
                        values["action_config_version"] = update.action_config_version
                    
                    if values:
                        db.query(Workstation).filter(
                            Workstation.id == ws_id
                        ).update(values, synchronize_session=False)
                
                db.commit()
                
                if len(batch) > 0:
                    logger.debug(
                        "StatusBatchWriter: flush completado. %d workstations actualizadas.",
                        len(batch)
                    )
            finally:
                db.close()
        
        except Exception as e:
            logger.error("StatusBatchWriter: error en flush batch: %s", str(e))


# Singleton global (1 por worker)
status_batch_writer = StatusBatchWriter()
