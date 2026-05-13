"""
Servicio de auditoría de operaciones.

Este servicio implementa la lógica de negocio para:
- Registro de todas las operaciones críticas del sistema
- Búsqueda y filtrado de logs de auditoría
- Limpieza de logs antiguos (retención de 12 meses)
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.models.audit import AuditLog, ActionType


def _sanitize_for_json(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Convierte valores no serializables (UUID, datetime, etc.) a strings para JSON."""
    if data is None:
        return None
    result = {}
    for key, value in data.items():
        if isinstance(value, UUID):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, dict):
            result[key] = _sanitize_for_json(value)
        elif isinstance(value, list):
            result[key] = [str(v) if isinstance(v, UUID) else v for v in value]
        else:
            result[key] = value
    return result


class AuditService:
    """
    Servicio para gestión de auditoría.
    
    Proporciona métodos para:
    - Registrar acciones auditables
    - Buscar logs con filtros avanzados
    - Limpiar logs antiguos
    
    IMPORTANTE: Los registros de auditoría son inmutables.
    No se deben modificar ni eliminar excepto por retención.
    """
    
    def log_action(
        self,
        db: Session,
        action_type: ActionType,
        entity_type: str,
        entity_id: str,
        user_id: Optional[str] = None,
        workstation_id: Optional[str] = None,
        account_id: Optional[str] = None,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """
        Registra una acción auditable en el sistema.
        
        Args:
            db: Sesión de base de datos
            action_type: Tipo de acción (CREATE, UPDATE, DELETE, etc.)
            entity_type: Tipo de entidad afectada (ej: "Account", "Workstation")
            entity_id: UUID de la entidad afectada
            user_id: UUID del usuario que realizó la acción (None para sistema)
            workstation_id: UUID de la workstation afectada (opcional)
            account_id: UUID de la cuenta afectada (opcional)
            old_values: Valores anteriores (para UPDATE)
            new_values: Valores nuevos (para CREATE/UPDATE)
            ip_address: IP desde donde se realizó la acción
            
        Returns:
            AuditLog creado
        """
        audit_log = AuditLog(
            user_id=user_id,
            workstation_id=workstation_id,
            account_id=account_id,
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            old_values=_sanitize_for_json(old_values),
            new_values=_sanitize_for_json(new_values),
            ip_address=ip_address,
            created_at=datetime.utcnow()
        )
        
        db.add(audit_log)
        db.commit()
        db.refresh(audit_log)
        
        return audit_log
    
    def log_config_change(
        self,
        db: Session,
        entity_type: str,
        entity_id: str,
        user_id: str,
        account_id: str,
        old_config: Dict[str, Any],
        new_config: Dict[str, Any],
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """
        Registra un cambio de configuración.
        
        Args:
            db: Sesión de base de datos
            entity_type: Tipo de configuración ("GlobalConfig", "VLANConfig", "WorkstationConfig")
            entity_id: UUID de la configuración
            user_id: UUID del usuario que realizó el cambio
            account_id: UUID de la cuenta
            old_config: Configuración anterior
            new_config: Configuración nueva
            ip_address: IP desde donde se realizó el cambio
            
        Returns:
            AuditLog creado
        """
        return self.log_action(
            db=db,
            action_type=ActionType.CONFIG_CHANGE,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            account_id=account_id,
            old_values=old_config,
            new_values=new_config,
            ip_address=ip_address
        )
    
    def log_contingency_toggle(
        self,
        db: Session,
        workstation_id: str,
        account_id: str,
        user_id: Optional[str],
        activated: bool,
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """
        Registra activación/desactivación de contingencia.
        
        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation
            account_id: UUID de la cuenta
            user_id: UUID del usuario (None si fue automático)
            activated: True si se activó, False si se desactivó
            ip_address: IP desde donde se realizó la acción
            
        Returns:
            AuditLog creado
        """
        return self.log_action(
            db=db,
            action_type=ActionType.CONTINGENCY_TOGGLE,
            entity_type="Workstation",
            entity_id=workstation_id,
            user_id=user_id,
            workstation_id=workstation_id,
            account_id=account_id,
            new_values={"contingency_active": activated},
            ip_address=ip_address
        )
    
    def log_message_sent(
        self,
        db: Session,
        message_id: str,
        sender_id: str,
        account_id: str,
        target_type: str,
        target_id: Optional[str],
        content_preview: str,
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """
        Registra envío de mensaje.
        
        Args:
            db: Sesión de base de datos
            message_id: UUID del mensaje
            sender_id: UUID del usuario que envió el mensaje
            account_id: UUID de la cuenta
            target_type: Tipo de destinatario ("workstation", "vlan", "account")
            target_id: UUID del destinatario (None para broadcast)
            content_preview: Preview del contenido (primeros 200 caracteres)
            ip_address: IP desde donde se envió
            
        Returns:
            AuditLog creado
        """
        return self.log_action(
            db=db,
            action_type=ActionType.MESSAGE_SENT,
            entity_type="Message",
            entity_id=message_id,
            user_id=sender_id,
            account_id=account_id,
            new_values={
                "target_type": target_type,
                "target_id": target_id,
                "content_preview": content_preview[:200]
            },
            ip_address=ip_address
        )
    
    def log_command_sent(
        self,
        db: Session,
        command_type: str,
        workstation_id: str,
        account_id: str,
        user_id: str,
        command_params: Dict[str, Any],
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """
        Registra envío de comando a workstation.
        
        Args:
            db: Sesión de base de datos
            command_type: Tipo de comando ("restart_service", "update_config", etc.)
            workstation_id: UUID de la workstation destinataria
            account_id: UUID de la cuenta
            user_id: UUID del usuario que envió el comando
            command_params: Parámetros del comando
            ip_address: IP desde donde se envió
            
        Returns:
            AuditLog creado
        """
        return self.log_action(
            db=db,
            action_type=ActionType.COMMAND_SENT,
            entity_type="Command",
            entity_id=workstation_id,  # Usamos workstation_id como entity_id
            user_id=user_id,
            workstation_id=workstation_id,
            account_id=account_id,
            new_values={
                "command_type": command_type,
                "params": command_params
            },
            ip_address=ip_address
        )
    
    def log_create(
        self,
        db: Session,
        entity_type: str,
        entity_id: str,
        user_id: str,
        account_id: Optional[str],
        entity_data: Dict[str, Any],
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """
        Registra creación de entidad.
        
        Args:
            db: Sesión de base de datos
            entity_type: Tipo de entidad ("Account", "User", "VLAN", etc.)
            entity_id: UUID de la entidad creada
            user_id: UUID del usuario que creó la entidad
            account_id: UUID de la cuenta (si aplica)
            entity_data: Datos de la entidad creada
            ip_address: IP desde donde se creó
            
        Returns:
            AuditLog creado
        """
        return self.log_action(
            db=db,
            action_type=ActionType.CREATE,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            account_id=account_id,
            new_values=entity_data,
            ip_address=ip_address
        )
    
    def log_update(
        self,
        db: Session,
        entity_type: str,
        entity_id: str,
        user_id: str,
        account_id: Optional[str],
        old_data: Dict[str, Any],
        new_data: Dict[str, Any],
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """
        Registra actualización de entidad.
        
        Args:
            db: Sesión de base de datos
            entity_type: Tipo de entidad
            entity_id: UUID de la entidad actualizada
            user_id: UUID del usuario que actualizó
            account_id: UUID de la cuenta (si aplica)
            old_data: Datos anteriores
            new_data: Datos nuevos
            ip_address: IP desde donde se actualizó
            
        Returns:
            AuditLog creado
        """
        return self.log_action(
            db=db,
            action_type=ActionType.UPDATE,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            account_id=account_id,
            old_values=old_data,
            new_values=new_data,
            ip_address=ip_address
        )
    
    def log_delete(
        self,
        db: Session,
        entity_type: str,
        entity_id: str,
        user_id: str,
        account_id: Optional[str],
        entity_data: Dict[str, Any],
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """
        Registra eliminación de entidad.
        
        Args:
            db: Sesión de base de datos
            entity_type: Tipo de entidad
            entity_id: UUID de la entidad eliminada
            user_id: UUID del usuario que eliminó
            account_id: UUID de la cuenta (si aplica)
            entity_data: Datos de la entidad antes de eliminar
            ip_address: IP desde donde se eliminó
            
        Returns:
            AuditLog creado
        """
        return self.log_action(
            db=db,
            action_type=ActionType.DELETE,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            account_id=account_id,
            old_values=entity_data,
            ip_address=ip_address
        )
    
    def search_audit_logs(
        self,
        db: Session,
        account_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workstation_id: Optional[str] = None,
        action_type: Optional[ActionType] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        ip_address: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[List[AuditLog], int]:
        """
        Busca logs de auditoría con filtros avanzados.
        
        Args:
            db: Sesión de base de datos
            account_id: Filtrar por cuenta (opcional)
            user_id: Filtrar por usuario (opcional)
            workstation_id: Filtrar por workstation (opcional)
            action_type: Filtrar por tipo de acción (opcional)
            entity_type: Filtrar por tipo de entidad (opcional)
            entity_id: Filtrar por ID de entidad (opcional)
            start_date: Fecha de inicio (opcional)
            end_date: Fecha de fin (opcional)
            ip_address: Filtrar por IP (opcional)
            skip: Número de registros a saltar (paginación)
            limit: Número máximo de registros a devolver
            
        Returns:
            Tupla (logs, total) donde:
            - logs: Lista de AuditLog
            - total: Número total de logs (sin paginación)
        """
        query = db.query(AuditLog)
        
        # Aplicar filtros
        if account_id is not None:
            query = query.filter_by(account_id=account_id)
        
        if user_id is not None:
            query = query.filter_by(user_id=user_id)
        
        if workstation_id is not None:
            query = query.filter_by(workstation_id=workstation_id)
        
        if action_type is not None:
            query = query.filter_by(action_type=action_type)
        
        if entity_type is not None:
            query = query.filter_by(entity_type=entity_type)
        
        if entity_id is not None:
            query = query.filter_by(entity_id=entity_id)
        
        if start_date is not None:
            query = query.filter(AuditLog.created_at >= start_date)
        
        if end_date is not None:
            query = query.filter(AuditLog.created_at <= end_date)
        
        if ip_address is not None:
            query = query.filter_by(ip_address=ip_address)
        
        # Contar total antes de paginación
        total = query.count()
        
        # Aplicar paginación y ordenamiento (más recientes primero)
        logs = query.order_by(
            AuditLog.created_at.desc()
        ).offset(skip).limit(limit).all()
        
        return logs, total
    
    def get_audit_logs_by_entity(
        self,
        db: Session,
        entity_type: str,
        entity_id: str,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[List[AuditLog], int]:
        """
        Obtiene todos los logs de auditoría de una entidad específica.
        
        Args:
            db: Sesión de base de datos
            entity_type: Tipo de entidad
            entity_id: UUID de la entidad
            skip: Número de registros a saltar
            limit: Número máximo de registros a devolver
            
        Returns:
            Tupla (logs, total)
        """
        query = db.query(AuditLog).filter(
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_id
        )
        
        total = query.count()
        
        logs = query.order_by(
            AuditLog.created_at.desc()
        ).offset(skip).limit(limit).all()
        
        return logs, total
    
    def get_recent_activity(
        self,
        db: Session,
        account_id: str,
        hours: int = 24,
        limit: int = 50
    ) -> List[AuditLog]:
        """
        Obtiene actividad reciente de una cuenta.
        
        Args:
            db: Sesión de base de datos
            account_id: UUID de la cuenta
            hours: Número de horas hacia atrás (default: 24)
            limit: Número máximo de registros
            
        Returns:
            Lista de AuditLog recientes
        """
        cutoff_date = datetime.utcnow() - timedelta(hours=hours)
        
        logs = db.query(AuditLog).filter(
            AuditLog.account_id == account_id,
            AuditLog.created_at >= cutoff_date
        ).order_by(
            AuditLog.created_at.desc()
        ).limit(limit).all()
        
        return logs
    
    def get_user_activity(
        self,
        db: Session,
        user_id: str,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[List[AuditLog], int]:
        """
        Obtiene toda la actividad de un usuario.
        
        Args:
            db: Sesión de base de datos
            user_id: UUID del usuario
            skip: Número de registros a saltar
            limit: Número máximo de registros
            
        Returns:
            Tupla (logs, total)
        """
        query = db.query(AuditLog).filter_by(user_id=user_id)
        
        total = query.count()
        
        logs = query.order_by(
            AuditLog.created_at.desc()
        ).offset(skip).limit(limit).all()
        
        return logs, total
    
    def cleanup_old_logs(
        self,
        db: Session,
        retention_months: int = 12
    ) -> int:
        """
        Elimina logs de auditoría antiguos.
        
        IMPORTANTE: Solo debe ejecutarse como tarea programada.
        La retención mínima recomendada es 12 meses.
        
        Args:
            db: Sesión de base de datos
            retention_months: Número de meses de retención (default: 12)
            
        Returns:
            Número de logs eliminados
        """
        cutoff_date = datetime.utcnow() - timedelta(days=retention_months * 30)
        
        # Buscar logs antiguos
        old_logs = db.query(AuditLog).filter(
            AuditLog.created_at < cutoff_date
        ).all()
        
        count = len(old_logs)
        
        # Eliminar
        for log in old_logs:
            db.delete(log)
        
        db.commit()
        
        return count
    
    def get_action_count_by_type(
        self,
        db: Session,
        account_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, int]:
        """
        Obtiene conteo de acciones por tipo.
        
        Útil para métricas y reportes.
        
        Args:
            db: Sesión de base de datos
            account_id: UUID de la cuenta
            start_date: Fecha de inicio (opcional)
            end_date: Fecha de fin (opcional)
            
        Returns:
            Diccionario {action_type: count}
        """
        query = db.query(AuditLog).filter_by(account_id=account_id)
        
        if start_date:
            query = query.filter(AuditLog.created_at >= start_date)
        
        if end_date:
            query = query.filter(AuditLog.created_at <= end_date)
        
        logs = query.all()
        
        # Contar por tipo
        counts = {}
        for log in logs:
            action_type = log.action_type.value
            counts[action_type] = counts.get(action_type, 0) + 1
        
        return counts

