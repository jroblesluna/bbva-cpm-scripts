"""
Servicio de configuración con resolución jerárquica.

Este servicio implementa la lógica de resolución de configuración con tres niveles:
- GlobalConfig: configuración a nivel de cuenta
- VLANConfig: configuración a nivel de VLAN (sobrescribe GlobalConfig)
- WorkstationConfig: configuración a nivel de estación (sobrescribe VLANConfig y GlobalConfig)

La resolución sigue el orden de precedencia: WorkstationConfig > VLANConfig > GlobalConfig

Incluye compute_config_hash() para generar un hash SHA-256 determinístico
de la configuración efectiva, permitiendo al Client C# detectar cambios.
"""

import hashlib
import json
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.config import GlobalConfig, VLANConfig, WorkstationConfig
from app.models.workstation import Workstation
from app.models.vlan import VLAN


def compute_config_hash(config_dict: dict) -> str:
    """
    Computa SHA-256 del JSON de configuración efectiva.
    
    Excluye los campos 'source' y 'config_hash' del input antes de serializar.
    Serializa con sort_keys=True y ensure_ascii=False para garantizar determinismo.
    Los valores None se serializan como JSON null.
    
    Args:
        config_dict: Diccionario con la configuración efectiva resuelta.
        
    Returns:
        String de 64 caracteres hexadecimales en minúsculas (SHA-256 hex digest).
    """
    # Excluir campos no-hashables
    hashable = {k: v for k, v in config_dict.items() if k not in ("source", "config_hash")}
    # Serializar determinísticamente (None se convierte en JSON null automáticamente)
    json_str = json.dumps(hashable, sort_keys=True, ensure_ascii=False)
    # Computar SHA-256
    return hashlib.sha256(json_str.encode("utf-8")).hexdigest()


class ConfigService:
    """
    Servicio para gestión de configuración jerárquica.
    
    Proporciona métodos para:
    - Resolver configuración efectiva con precedencia
    - Actualizar configuración en los tres niveles
    - Eliminar overrides de configuración
    """
    
    def get_effective_config(
        self, 
        db: Session, 
        workstation_id: str
    ) -> Dict[str, Any]:
        """
        Resuelve la configuración efectiva para una workstation.
        
        Aplica el orden de precedencia: WorkstationConfig > VLANConfig > GlobalConfig
        
        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation
            
        Returns:
            Dict con la configuración efectiva:
            {
                "corporate_queue_name": str,
                "search_targets": dict,
                "pending_task_polling_minutes": int,
                "bootstrap_domains": str,
                "source": {
                    "corporate_queue_name": "global|vlan|workstation",
                    "search_targets": "global|vlan|workstation",
                    ...
                }
            }
            
        Raises:
            ValueError: Si la workstation no existe
        """
        # 1. Obtener workstation
        workstation = db.query(Workstation).filter_by(id=workstation_id).first()
        if not workstation:
            raise ValueError(f"Workstation {workstation_id} no encontrada")
        
        # 2. Obtener GlobalConfig (puede no existir si la organización es nueva)
        global_config = db.query(GlobalConfig).filter_by(
            organization_id=workstation.organization_id
        ).first()
        
        if not global_config:
            # Crear una GlobalConfig por defecto para la organización
            global_config = GlobalConfig(
                organization_id=workstation.organization_id,
                corporate_queue_name="LexmarkBBVA",
                pending_task_polling_minutes=3,
                bootstrap_domains="apps.iol.pe,sistemas.com.pe",
                telemetry_enabled=True,
                telemetry_interval_seconds=300,
            )
            db.add(global_config)
            db.commit()
            db.refresh(global_config)
        
        # 3. Obtener VLANConfig si existe
        vlan_config = None
        if workstation.vlan_id:
            vlan_config = db.query(VLANConfig).filter_by(
                vlan_id=workstation.vlan_id
            ).first()
        
        # 4. Obtener WorkstationConfig si existe
        workstation_config = db.query(WorkstationConfig).filter_by(
            workstation_id=workstation_id
        ).first()
        
        # 5. Resolver cada campo con precedencia
        config = {}
        sources = {}
        
        fields = [
            "corporate_queue_name",
            "search_targets",
            "pending_task_polling_minutes",
            "bootstrap_domains",
            "connectivity_checks",
            "locale",
            "telemetry_enabled",
            "telemetry_interval_seconds",
        ]
        
        for field in fields:
            value, source = self._resolve_field(
                workstation_config, 
                vlan_config, 
                global_config, 
                field
            )
            config[field] = value
            sources[field] = source
        
        config["source"] = sources
        
        # 6. Computar config_hash (excluye 'source' y 'config_hash')
        config["config_hash"] = compute_config_hash(config)
        
        return config
    
    def _resolve_field(
        self, 
        ws_config: Optional[WorkstationConfig], 
        vlan_config: Optional[VLANConfig], 
        global_config: GlobalConfig, 
        field_name: str
    ) -> tuple[Any, str]:
        """
        Resuelve un campo específico con precedencia.
        
        Args:
            ws_config: WorkstationConfig (puede ser None)
            vlan_config: VLANConfig (puede ser None)
            global_config: GlobalConfig (siempre existe)
            field_name: Nombre del campo a resolver
            
        Returns:
            Tupla (valor, fuente) donde fuente es "workstation", "vlan" o "global"
        """
        # 1. WorkstationConfig tiene mayor precedencia
        if ws_config and getattr(ws_config, field_name) is not None:
            return getattr(ws_config, field_name), "workstation"
        
        # 2. VLANConfig tiene precedencia intermedia
        if vlan_config and getattr(vlan_config, field_name) is not None:
            return getattr(vlan_config, field_name), "vlan"
        
        # 3. GlobalConfig es el fallback
        return getattr(global_config, field_name), "global"
    
    def create_global_config(
        self,
        db: Session,
        organization_id: str,
        corporate_queue_name: str = "LexmarkRoblesAI",
        search_targets: Optional[Dict] = None,
        pending_task_polling_minutes: int = 3,
        bootstrap_domains: str = "apps.iol.pe,iol.pe,sistemas.com.pe,robles.ai",
        connectivity_checks: Optional[list] = None,
        locale: str = "",
        telemetry_enabled: bool = True,
        telemetry_interval_seconds: int = 300
    ) -> GlobalConfig:
        """
        Crea una configuración global para una organización.
        
        Args:
            db: Sesión de base de datos
            organization_id: UUID de la organización
            corporate_queue_name: Nombre de la cola corporativa
            search_targets: Objetivos de búsqueda de impresoras
            pending_task_polling_minutes: Intervalo de polling (1-1440)
            bootstrap_domains: Dominios de bootstrap separados por comas
            
        Returns:
            GlobalConfig creada
            
        Raises:
            ValueError: Si ya existe una GlobalConfig para la cuenta
            ValueError: Si pending_task_polling_minutes está fuera de rango
        """
        # Validar rango de pending_task_polling_minutes
        if not (1 <= pending_task_polling_minutes <= 1440):
            raise ValueError(
                f"pending_task_polling_minutes debe estar entre 1 y 1440, "
                f"recibido: {pending_task_polling_minutes}"
            )
        
        # Verificar que no exista ya una GlobalConfig
        existing = db.query(GlobalConfig).filter_by(organization_id=organization_id).first()
        if existing:
            raise ValueError(f"Ya existe una GlobalConfig para organización {organization_id}")
        
        # Crear GlobalConfig
        global_config = GlobalConfig(
            organization_id=organization_id,
            corporate_queue_name=corporate_queue_name,
            search_targets=search_targets,
            pending_task_polling_minutes=pending_task_polling_minutes,
            bootstrap_domains=bootstrap_domains,
            connectivity_checks=connectivity_checks or [],
            locale=locale,
            telemetry_enabled=telemetry_enabled,
            telemetry_interval_seconds=telemetry_interval_seconds
        )
        
        db.add(global_config)
        db.commit()
        db.refresh(global_config)
        
        return global_config
    
    def update_global_config(
        self,
        db: Session,
        organization_id: str,
        corporate_queue_name: Optional[str] = None,
        search_targets: Optional[Dict] = None,
        pending_task_polling_minutes: Optional[int] = None,
        bootstrap_domains: Optional[str] = None,
        connectivity_checks: Optional[list] = None,
        locale: Optional[str] = None,
        telemetry_enabled: Optional[bool] = None,
        telemetry_interval_seconds: Optional[int] = None
    ) -> GlobalConfig:
        """
        Actualiza la configuración global de una organización.
        
        Args:
            db: Sesión de base de datos
            organization_id: UUID de la organización
            corporate_queue_name: Nuevo nombre de cola (opcional)
            search_targets: Nuevos objetivos de búsqueda (opcional)
            pending_task_polling_minutes: Nuevo intervalo de polling (opcional)
            bootstrap_domains: Nuevos dominios de bootstrap (opcional)
            
        Returns:
            GlobalConfig actualizada
            
        Raises:
            ValueError: Si no existe GlobalConfig para la cuenta
            ValueError: Si pending_task_polling_minutes está fuera de rango
        """
        global_config = db.query(GlobalConfig).filter_by(organization_id=organization_id).first()
        if not global_config:
            raise ValueError(f"GlobalConfig no encontrada para organización {organization_id}")
        
        # Actualizar campos si se proporcionan
        if corporate_queue_name is not None:
            global_config.corporate_queue_name = corporate_queue_name
        
        if search_targets is not None:
            global_config.search_targets = search_targets
        
        if pending_task_polling_minutes is not None:
            if not (1 <= pending_task_polling_minutes <= 1440):
                raise ValueError(
                    f"pending_task_polling_minutes debe estar entre 1 y 1440, "
                    f"recibido: {pending_task_polling_minutes}"
                )
            global_config.pending_task_polling_minutes = pending_task_polling_minutes
        
        if bootstrap_domains is not None:
            global_config.bootstrap_domains = bootstrap_domains
        
        if connectivity_checks is not None:
            global_config.connectivity_checks = connectivity_checks
        
        if locale is not None:
            global_config.locale = locale
        
        if telemetry_enabled is not None:
            global_config.telemetry_enabled = telemetry_enabled
        
        if telemetry_interval_seconds is not None:
            global_config.telemetry_interval_seconds = telemetry_interval_seconds
        
        db.commit()
        db.refresh(global_config)
        
        return global_config
    
    def create_or_update_vlan_config(
        self,
        db: Session,
        vlan_id: str,
        corporate_queue_name: Optional[str] = None,
        search_targets: Optional[Dict] = None,
        pending_task_polling_minutes: Optional[int] = None,
        bootstrap_domains: Optional[str] = None
    ) -> VLANConfig:
        """
        Crea o actualiza la configuración de una VLAN.
        
        Args:
            db: Sesión de base de datos
            vlan_id: UUID de la VLAN
            corporate_queue_name: Override de nombre de cola (None = usar global)
            search_targets: Override de objetivos de búsqueda (None = usar global)
            pending_task_polling_minutes: Override de intervalo (None = usar global)
            bootstrap_domains: Override de dominios (None = usar global)
            
        Returns:
            VLANConfig creada o actualizada
            
        Raises:
            ValueError: Si la VLAN no existe
            ValueError: Si pending_task_polling_minutes está fuera de rango
        """
        # Verificar que la VLAN existe
        vlan = db.query(VLAN).filter_by(id=vlan_id).first()
        if not vlan:
            raise ValueError(f"VLAN {vlan_id} no encontrada")
        
        # Validar pending_task_polling_minutes si se proporciona
        if pending_task_polling_minutes is not None:
            if not (1 <= pending_task_polling_minutes <= 1440):
                raise ValueError(
                    f"pending_task_polling_minutes debe estar entre 1 y 1440, "
                    f"recibido: {pending_task_polling_minutes}"
                )
        
        # Buscar VLANConfig existente
        vlan_config = db.query(VLANConfig).filter_by(vlan_id=vlan_id).first()
        
        if vlan_config:
            # Actualizar existente
            if corporate_queue_name is not None:
                vlan_config.corporate_queue_name = corporate_queue_name
            if search_targets is not None:
                vlan_config.search_targets = search_targets
            if pending_task_polling_minutes is not None:
                vlan_config.pending_task_polling_minutes = pending_task_polling_minutes
            if bootstrap_domains is not None:
                vlan_config.bootstrap_domains = bootstrap_domains
        else:
            # Crear nueva
            vlan_config = VLANConfig(
                vlan_id=vlan_id,
                corporate_queue_name=corporate_queue_name,
                search_targets=search_targets,
                pending_task_polling_minutes=pending_task_polling_minutes,
                bootstrap_domains=bootstrap_domains
            )
            db.add(vlan_config)
        
        db.commit()
        db.refresh(vlan_config)
        
        return vlan_config
    
    def delete_vlan_config(self, db: Session, vlan_id: str) -> bool:
        """
        Elimina la configuración de una VLAN.
        
        Las workstations afectadas volverán a usar GlobalConfig.
        
        Args:
            db: Sesión de base de datos
            vlan_id: UUID de la VLAN
            
        Returns:
            True si se eliminó, False si no existía
        """
        vlan_config = db.query(VLANConfig).filter_by(vlan_id=vlan_id).first()
        if not vlan_config:
            return False
        
        db.delete(vlan_config)
        db.commit()
        
        return True
    
    def create_or_update_workstation_config(
        self,
        db: Session,
        workstation_id: str,
        corporate_queue_name: Optional[str] = None,
        search_targets: Optional[Dict] = None,
        pending_task_polling_minutes: Optional[int] = None,
        bootstrap_domains: Optional[str] = None
    ) -> WorkstationConfig:
        """
        Crea o actualiza la configuración de una workstation específica.
        
        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation
            corporate_queue_name: Override de nombre de cola (None = usar vlan/global)
            search_targets: Override de objetivos (None = usar vlan/global)
            pending_task_polling_minutes: Override de intervalo (None = usar vlan/global)
            bootstrap_domains: Override de dominios (None = usar vlan/global)
            
        Returns:
            WorkstationConfig creada o actualizada
            
        Raises:
            ValueError: Si la workstation no existe
            ValueError: Si pending_task_polling_minutes está fuera de rango
        """
        # Verificar que la workstation existe
        workstation = db.query(Workstation).filter_by(id=workstation_id).first()
        if not workstation:
            raise ValueError(f"Workstation {workstation_id} no encontrada")
        
        # Validar pending_task_polling_minutes si se proporciona
        if pending_task_polling_minutes is not None:
            if not (1 <= pending_task_polling_minutes <= 1440):
                raise ValueError(
                    f"pending_task_polling_minutes debe estar entre 1 y 1440, "
                    f"recibido: {pending_task_polling_minutes}"
                )
        
        # Buscar WorkstationConfig existente
        ws_config = db.query(WorkstationConfig).filter_by(
            workstation_id=workstation_id
        ).first()
        
        if ws_config:
            # Actualizar existente
            if corporate_queue_name is not None:
                ws_config.corporate_queue_name = corporate_queue_name
            if search_targets is not None:
                ws_config.search_targets = search_targets
            if pending_task_polling_minutes is not None:
                ws_config.pending_task_polling_minutes = pending_task_polling_minutes
            if bootstrap_domains is not None:
                ws_config.bootstrap_domains = bootstrap_domains
        else:
            # Crear nueva
            ws_config = WorkstationConfig(
                workstation_id=workstation_id,
                corporate_queue_name=corporate_queue_name,
                search_targets=search_targets,
                pending_task_polling_minutes=pending_task_polling_minutes,
                bootstrap_domains=bootstrap_domains
            )
            db.add(ws_config)
        
        db.commit()
        db.refresh(ws_config)
        
        return ws_config
    
    def delete_workstation_config(self, db: Session, workstation_id: str) -> bool:
        """
        Elimina la configuración de una workstation específica.
        
        La workstation volverá a usar VLANConfig o GlobalConfig.
        
        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation
            
        Returns:
            True si se eliminó, False si no existía
        """
        ws_config = db.query(WorkstationConfig).filter_by(
            workstation_id=workstation_id
        ).first()
        if not ws_config:
            return False
        
        db.delete(ws_config)
        db.commit()
        
        return True
    
    def get_workstations_affected_by_vlan_config(
        self, 
        db: Session, 
        vlan_id: str
    ) -> list[Workstation]:
        """
        Obtiene todas las workstations afectadas por una VLANConfig.
        
        Args:
            db: Sesión de base de datos
            vlan_id: UUID de la VLAN
            
        Returns:
            Lista de workstations en la VLAN que no tienen WorkstationConfig
        """
        # Obtener todas las workstations de la VLAN
        workstations = db.query(Workstation).filter_by(vlan_id=vlan_id).all()
        
        # Filtrar las que no tienen WorkstationConfig (son afectadas por VLANConfig)
        affected = []
        for ws in workstations:
            ws_config = db.query(WorkstationConfig).filter_by(
                workstation_id=ws.id
            ).first()
            if not ws_config:
                affected.append(ws)
        
        return affected
