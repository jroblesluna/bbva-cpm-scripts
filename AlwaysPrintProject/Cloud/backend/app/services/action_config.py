"""
Servicio para gestión de configuraciones de acciones administrativas.
"""

import json
import logging
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.action_config import ActionConfig
from app.schemas.action_config import (
    ActionConfigUpload,
    ActionConfigUpdate,
    calculate_config_hash,
)

logger = logging.getLogger(__name__)


class ActionConfigService:
    """Servicio para gestionar configuraciones de acciones administrativas."""
    
    @staticmethod
    def get_active_config(db: Session, organization_id: int) -> Optional[ActionConfig]:
        """
        Obtiene la configuración activa de una organización.
        
        Args:
            db: Sesión de base de datos
            organization_id: ID de la organización
            
        Returns:
            ActionConfig activa o None si no existe
        """
        return db.query(ActionConfig).filter(
            and_(
                ActionConfig.organization_id == organization_id,
                ActionConfig.is_active == True
            )
        ).first()
    
    @staticmethod
    def get_config_by_id(db: Session, config_id: int, organization_id: int) -> Optional[ActionConfig]:
        """
        Obtiene una configuración por ID verificando que pertenezca a la organización.
        
        Args:
            db: Sesión de base de datos
            config_id: ID de la configuración
            organization_id: ID de la organización
            
        Returns:
            ActionConfig o None si no existe
        """
        return db.query(ActionConfig).filter(
            and_(
                ActionConfig.id == config_id,
                ActionConfig.organization_id == organization_id
            )
        ).first()
    
    @staticmethod
    def create_config(
        db: Session,
        organization_id: int,
        data: ActionConfigUpload,
        created_by_id: int,
        storage_path: Optional[str] = None
    ) -> ActionConfig:
        """
        Crea una nueva configuración de acciones.
        
        Si is_active=True, desactiva cualquier configuración activa previa.
        
        Args:
            db: Sesión de base de datos
            organization_id: ID de la organización
            data: Datos de la configuración
            created_by_id: ID del usuario que crea la configuración
            storage_path: Ruta de almacenamiento (S3 o local)
            
        Returns:
            ActionConfig creada
        """
        # Parsear JSON para extraer metadatos
        try:
            config_data = json.loads(data.config_json)
            name = config_data.get("name", "Unnamed")
            version = config_data.get("version", "1.0")
            description = config_data.get("description")
        except json.JSONDecodeError:
            logger.error(f"JSON inválido en config_json para org {organization_id}")
            raise ValueError("config_json no es un JSON válido")
        
        # Calcular hash
        config_hash = calculate_config_hash(data.config_json)
        
        # Si is_active=True, desactivar configuración activa previa
        if data.is_active:
            ActionConfigService._deactivate_all_configs(db, organization_id)
        
        # Crear nueva configuración
        new_config = ActionConfig(
            organization_id=organization_id,
            name=name,
            version=version,
            description=description,
            config_json=data.config_json,
            config_hash=config_hash,
            is_active=data.is_active,
            storage_path=storage_path,
            created_by_id=created_by_id
        )
        
        db.add(new_config)
        db.commit()
        db.refresh(new_config)
        
        logger.info(
            f"Configuración de acciones creada: id={new_config.id}, "
            f"org={organization_id}, name={name}, hash={config_hash}, active={data.is_active}"
        )
        
        return new_config
    
    @staticmethod
    def update_config(
        db: Session,
        config: ActionConfig,
        data: ActionConfigUpdate
    ) -> ActionConfig:
        """
        Actualiza una configuración existente.
        
        Args:
            db: Sesión de base de datos
            config: Configuración a actualizar
            data: Datos de actualización
            
        Returns:
            ActionConfig actualizada
        """
        if data.is_active is not None:
            # Si se activa esta config, desactivar las demás
            if data.is_active and not config.is_active:
                ActionConfigService._deactivate_all_configs(db, config.organization_id)
            
            config.is_active = data.is_active
        
        db.commit()
        db.refresh(config)
        
        logger.info(
            f"Configuración de acciones actualizada: id={config.id}, "
            f"org={config.organization_id}, active={config.is_active}"
        )
        
        return config
    
    @staticmethod
    def delete_config(db: Session, config: ActionConfig) -> None:
        """
        Elimina una configuración.
        
        Args:
            db: Sesión de base de datos
            config: Configuración a eliminar
        """
        config_id = config.id
        org_id = config.organization_id
        
        db.delete(config)
        db.commit()
        
        logger.info(
            f"Configuración de acciones eliminada: id={config_id}, org={org_id}"
        )
    
    @staticmethod
    def _deactivate_all_configs(db: Session, organization_id: int) -> None:
        """
        Desactiva todas las configuraciones de una organización.
        
        Args:
            db: Sesión de base de datos
            organization_id: ID de la organización
        """
        db.query(ActionConfig).filter(
            ActionConfig.organization_id == organization_id
        ).update({"is_active": False})
        
        logger.debug(f"Todas las configuraciones de org {organization_id} desactivadas")
    
    @staticmethod
    def get_all_configs(db: Session, organization_id: int) -> list[ActionConfig]:
        """
        Obtiene todas las configuraciones de una organización.
        
        Args:
            db: Sesión de base de datos
            organization_id: ID de la organización
            
        Returns:
            Lista de ActionConfig
        """
        return db.query(ActionConfig).filter(
            ActionConfig.organization_id == organization_id
        ).order_by(ActionConfig.created_at.desc()).all()
