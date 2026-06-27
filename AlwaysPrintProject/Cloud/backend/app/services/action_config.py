"""
Servicio para gestión de configuraciones de acciones administrativas.

Soporta herencia jerárquica: Organización → VLAN → Workstation.
Resolución (de abajo hacia arriba, con mandatory de arriba anulando):
1. Si org.action_config_mandatory → usar config activa de org (nadie sobreescribe)
2. Si VLAN.action_config_mandatory y tiene config → usar VLAN (ignora workstation)
3. Si workstation tiene config activa propia → usar workstation
4. Si VLAN tiene config activa (no mandatory) → usar VLAN
5. Fallback: usar config activa de org (default)
"""

import json
import logging
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.action_config import ActionConfig, ActionConfigScope
from app.models.organization import Organization
from app.models.vlan import VLAN
from app.models.workstation import Workstation
from app.schemas.action_config import (
    ActionConfigUpload,
    ActionConfigUpdate,
    calculate_config_hash,
)
from app.services.crypto_service import CryptoService
from app.services.s3_config_service import S3ConfigService
from app.core.config import settings

logger = logging.getLogger(__name__)


class DuplicateConfigError(Exception):
    """Error lanzado cuando se intenta subir una configuración con hash duplicado."""
    pass


class ActionConfigService:
    """Servicio para gestionar configuraciones de acciones administrativas."""
    
    @staticmethod
    def get_active_config(db: Session, organization_id, scope: str = "org",
                          vlan_id=None, workstation_id=None) -> Optional[ActionConfig]:
        """
        Obtiene la configuración activa para un scope específico.
        
        Args:
            db: Sesión de base de datos
            organization_id: ID de la organización
            scope: 'org', 'vlan' o 'workstation'
            vlan_id: ID de la VLAN (requerido si scope='vlan')
            workstation_id: ID de la workstation (requerido si scope='workstation')
            
        Returns:
            ActionConfig activa o None si no existe
        """
        query = db.query(ActionConfig).filter(
            and_(
                ActionConfig.organization_id == organization_id,
                ActionConfig.is_active == True,
                ActionConfig.scope == scope
            )
        )
        
        if scope == "vlan" and vlan_id:
            query = query.filter(ActionConfig.vlan_id == vlan_id)
        elif scope == "workstation" and workstation_id:
            query = query.filter(ActionConfig.workstation_id == workstation_id)
        
        return query.first()

    @staticmethod
    def resolve_effective_config(db: Session, workstation_id) -> Optional[ActionConfig]:
        """
        Resuelve la configuración efectiva para una workstation aplicando herencia.
        
        Orden de resolución:
        1. Si org.action_config_mandatory → config activa de org
        2. Si VLAN es mandatory y tiene config → VLAN (ignora workstation)
        3. Si workstation tiene config propia → workstation
        4. Si VLAN tiene config (no mandatory) → VLAN
        5. Fallback: config activa de org
        
        Args:
            db: Sesión de base de datos
            workstation_id: ID de la workstation
            
        Returns:
            ActionConfig efectiva o None
        """
        workstation = db.query(Workstation).filter(Workstation.id == workstation_id).first()
        if not workstation:
            return None
        
        org = db.query(Organization).filter(Organization.id == workstation.organization_id).first()
        if not org:
            return None
        
        # 1. Si org es mandatory → usar config de org directamente
        if org.action_config_mandatory:
            return ActionConfigService.get_active_config(
                db, org.id, scope="org"
            )
        
        # 2. Verificar VLAN
        vlan = None
        vlan_config = None
        if workstation.vlan_id:
            vlan = db.query(VLAN).filter(VLAN.id == workstation.vlan_id).first()
            if vlan:
                vlan_config = ActionConfigService.get_active_config(
                    db, org.id, scope="vlan", vlan_id=vlan.id
                )
        
        # 3. Si VLAN es mandatory → usar config de VLAN (ignora workstation)
        if vlan and vlan.action_config_mandatory and vlan_config:
            return vlan_config
        
        # 4. Workstation tiene config propia → usar workstation
        # (solo se llega aquí si ni org ni VLAN son mandatory)
        ws_config = ActionConfigService.get_active_config(
            db, org.id, scope="workstation", workstation_id=workstation.id
        )
        if ws_config:
            return ws_config
        
        # 5. Si VLAN tiene config (no mandatory) → usar VLAN
        if vlan_config:
            return vlan_config
        
        # 6. Fallback: config de org (default)
        return ActionConfigService.get_active_config(db, org.id, scope="org")
    
    @staticmethod
    def get_config_by_id(db: Session, config_id, organization_id) -> Optional[ActionConfig]:
        """
        Obtiene una configuración por ID verificando que pertenezca a la organización.
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
        organization_id,
        data: ActionConfigUpload,
        created_by_id,
        storage_path: Optional[str] = None,
        scope: str = "org",
        vlan_id=None,
        workstation_id=None
    ) -> ActionConfig:
        """
        Crea una nueva configuración de acciones.
        
        Si is_active=True, desactiva cualquier configuración activa previa del mismo scope/target.
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
        
        # Verificar duplicado dentro del mismo scope/target (no globalmente)
        # El mismo archivo puede subirse a diferentes VLANs/workstations,
        # pero no puede existir duplicado dentro del mismo scope+target.
        dup_query = db.query(ActionConfig).filter(
            and_(
                ActionConfig.organization_id == organization_id,
                ActionConfig.config_hash == config_hash,
                ActionConfig.scope == scope
            )
        )
        
        if scope == "vlan" and vlan_id:
            dup_query = dup_query.filter(ActionConfig.vlan_id == vlan_id)
        elif scope == "workstation" and workstation_id:
            dup_query = dup_query.filter(ActionConfig.workstation_id == workstation_id)
        elif scope == "org":
            dup_query = dup_query.filter(
                ActionConfig.vlan_id == None,
                ActionConfig.workstation_id == None
            )
        
        existing = dup_query.first()
        
        if existing:
            logger.warning(
                f"Configuración duplicada: org={organization_id}, scope={scope}, "
                f"vlan_id={vlan_id}, workstation_id={workstation_id}, hash={config_hash}, "
                f"existente_id={existing.id}, nombre='{existing.name}'"
            )
            raise DuplicateConfigError(
                f"Ya existe una configuración con el mismo contenido (hash: {config_hash}) "
                f"en este scope. No se puede subir un archivo idéntico al mismo destino."
            )
        
        # Si is_active=True, desactivar configuración activa previa del mismo scope/target
        if data.is_active:
            ActionConfigService._deactivate_configs_for_scope(
                db, organization_id, scope, vlan_id, workstation_id
            )
        
        # Crear nueva configuración
        new_config = ActionConfig(
            organization_id=organization_id,
            scope=scope,
            vlan_id=vlan_id if scope == "vlan" else None,
            workstation_id=workstation_id if scope == "workstation" else None,
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
            f"Configuración de acciones creada: id={new_config.id}, scope={scope}, "
            f"org={organization_id}, name={name}, hash={config_hash}, active={data.is_active}"
        )
        
        # === FIRMA DIGITAL ECDSA Y SUBIDA A S3 ===
        # Solo firmar si la organización tiene certificado generado.
        # La firma NO es bloqueante: si falla, la config ya está guardada en BD.
        try:
            org = db.query(Organization).filter(
                Organization.id == organization_id
            ).first()
            
            if (
                org
                and org.ecdsa_cert_version > 0
                and org.ecdsa_private_key_encrypted is not None
            ):
                # Firmar la configuración con la clave privada de la org
                hash_full, signature_b64 = CryptoService.sign_config(
                    org.ecdsa_private_key_encrypted,
                    data.config_json,
                    settings.SECRET_KEY,
                    str(organization_id),
                )
                
                # Construir JSON envolvente firmado
                signed_json = CryptoService.build_signed_config(
                    data.config_json,
                    hash_full,
                    signature_b64,
                    org.ecdsa_cert_version,
                )
                
                # Subir a S3
                s3_key = S3ConfigService().upload_signed_config(
                    str(organization_id),
                    hash_full[:8],
                    signed_json,
                )
                
                # Actualizar storage_path en la config recién creada
                new_config.storage_path = s3_key
                db.commit()
                
                logger.info(
                    f"Config firmada y subida a S3: id={new_config.id}, "
                    f"s3_key={s3_key}, cert_version={org.ecdsa_cert_version}"
                )
            else:
                logger.debug(
                    f"Org {organization_id} no tiene certificado ECDSA, "
                    f"config creada sin firma digital"
                )
        except Exception as e:
            # La firma no debe impedir la creación de la config
            logger.error(
                f"Error al firmar/subir config a S3: id={new_config.id}, "
                f"org={organization_id}, error={e}"
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
        Si se activa, desactiva las demás del mismo scope/target.
        """
        if data.is_active is not None:
            if data.is_active and not config.is_active:
                ActionConfigService._deactivate_configs_for_scope(
                    db, config.organization_id, config.scope,
                    config.vlan_id, config.workstation_id
                )
            config.is_active = data.is_active
        
        db.commit()
        db.refresh(config)
        
        logger.info(
            f"Configuración de acciones actualizada: id={config.id}, "
            f"org={config.organization_id}, scope={config.scope}, active={config.is_active}"
        )
        
        # Firmar y subir a S3 si se está activando y la org tiene certificado
        if data.is_active and config.is_active:
            try:
                org = db.query(Organization).filter(
                    Organization.id == config.organization_id
                ).first()
                
                if org and org.ecdsa_cert_version and org.ecdsa_cert_version > 0 and org.ecdsa_private_key_encrypted:
                    hash_full, signature_b64 = CryptoService.sign_config(
                        org.ecdsa_private_key_encrypted, config.config_json,
                        settings.SECRET_KEY, str(config.organization_id)
                    )
                    signed_json = CryptoService.build_signed_config(
                        config.config_json, hash_full, signature_b64, org.ecdsa_cert_version
                    )
                    s3_key = S3ConfigService().upload_signed_config(
                        str(config.organization_id), hash_full[:8], signed_json
                    )
                    config.storage_path = s3_key
                    db.commit()
                    db.refresh(config)
                    logger.info(
                        "Config firmada y subida a S3 al activar: config_id=%s, s3_key=%s",
                        config.id, s3_key
                    )
            except Exception as e:
                logger.error(
                    "Error al firmar/subir config activada: config_id=%s, error=%s",
                    config.id, str(e)
                )
        
        return config
    
    @staticmethod
    def delete_config(db: Session, config: ActionConfig) -> None:
        """Elimina una configuración."""
        config_id = config.id
        org_id = config.organization_id
        
        # Eliminar config firmada de S3 si existe
        if config.storage_path:
            try:
                S3ConfigService().delete_signed_config(config.storage_path)
                logger.info(
                    "Config firmada eliminada de S3: config_id=%s, s3_key=%s",
                    config_id, config.storage_path
                )
            except Exception as e:
                logger.error(
                    "Error al eliminar config firmada de S3: config_id=%s, s3_key=%s, error=%s",
                    config_id, config.storage_path, str(e)
                )
        
        db.delete(config)
        db.commit()
        
        logger.info(f"Configuración de acciones eliminada: id={config_id}, org={org_id}")
    
    @staticmethod
    def _deactivate_configs_for_scope(
        db: Session, organization_id, scope: str,
        vlan_id=None, workstation_id=None
    ) -> None:
        """
        Desactiva todas las configuraciones de un scope/target específico.
        Solo desactiva configs del mismo nivel (no afecta otros niveles).
        """
        query = db.query(ActionConfig).filter(
            and_(
                ActionConfig.organization_id == organization_id,
                ActionConfig.scope == scope
            )
        )
        
        if scope == "vlan" and vlan_id:
            query = query.filter(ActionConfig.vlan_id == vlan_id)
        elif scope == "workstation" and workstation_id:
            query = query.filter(ActionConfig.workstation_id == workstation_id)
        elif scope == "org":
            query = query.filter(ActionConfig.vlan_id == None, ActionConfig.workstation_id == None)
        
        query.update({"is_active": False}, synchronize_session=False)
        logger.debug(f"Configs desactivadas: org={organization_id}, scope={scope}")
    
    @staticmethod
    def get_all_configs(
        db: Session, organization_id, scope: str = "org",
        vlan_id=None, workstation_id=None
    ) -> list[ActionConfig]:
        """
        Obtiene todas las configuraciones de un scope/target.
        """
        query = db.query(ActionConfig).filter(
            and_(
                ActionConfig.organization_id == organization_id,
                ActionConfig.scope == scope
            )
        )
        
        if scope == "vlan" and vlan_id:
            query = query.filter(ActionConfig.vlan_id == vlan_id)
        elif scope == "workstation" and workstation_id:
            query = query.filter(ActionConfig.workstation_id == workstation_id)
        elif scope == "org":
            query = query.filter(ActionConfig.vlan_id == None, ActionConfig.workstation_id == None)
        
        return query.order_by(ActionConfig.created_at.desc()).all()
