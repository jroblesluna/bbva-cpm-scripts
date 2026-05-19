"""
Servicio de gestión de workstations y licencias.

Este servicio implementa la lógica de negocio para:
- Registro de workstations
- Gestión de licencias
- Detección automática de VLAN por IP
- Auto-asignación de VLAN por CIDR
- Actualización de estado (online/offline, contingencia)
"""

import hashlib
import ipaddress
import logging
from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_

from app.models.workstation import Workstation, License
from app.models.organization import Organization, PublicIP
from app.models.vlan import VLAN

logger = logging.getLogger(__name__)


class WorkstationService:
    """
    Servicio para gestión de workstations y licencias.
    
    Proporciona métodos para:
    - Registrar workstations nuevas o actualizar existentes
    - Calcular y activar licencias
    - Detectar VLAN automáticamente por IP
    - Actualizar estado de conexión y contingencia
    """
    
    def calculate_license_serial(self, ip_private: str) -> str:
        """
        Calcula el número de serie de licencia.
        
        El serial es los últimos 8 caracteres del hash MD5 de la IP privada.
        
        Args:
            ip_private: Dirección IP privada de la workstation
            
        Returns:
            String de 8 caracteres (últimos 8 del MD5)
            
        Example:
            >>> calculate_license_serial("192.168.1.100")
            "a3f5c2d1"
        """
        md5_hash = hashlib.md5(ip_private.encode()).hexdigest()
        return md5_hash[-8:]
    
    def detect_vlan_for_ip(
        self, 
        db: Session, 
        organization_id: str, 
        ip_private: str
    ) -> Optional[str]:
        """
        Detecta la VLAN a la que pertenece una IP privada.
        
        Busca en todas las VLANs de la organización y verifica si la IP
        está dentro de alguno de los rangos CIDR definidos.
        
        Si la IP pertenece a múltiples VLANs, devuelve la más reciente.
        
        Args:
            db: Sesión de base de datos
            organization_id: UUID de la organización
            ip_private: Dirección IP privada a verificar
            
        Returns:
            UUID de la VLAN si se encuentra, None si no pertenece a ninguna
        """
        # Obtener todas las VLANs de la organización
        vlans = db.query(VLAN).filter_by(organization_id=organization_id).order_by(
            VLAN.created_at.desc()
        ).all()
        
        try:
            ip_obj = ipaddress.ip_address(ip_private)
        except ValueError:
            # IP inválida
            return None
        
        # Verificar cada VLAN
        for vlan in vlans:
            if not vlan.cidr_ranges:
                continue
            
            # Verificar cada rango CIDR de la VLAN
            for cidr_str in vlan.cidr_ranges:
                try:
                    network = ipaddress.ip_network(cidr_str, strict=False)
                    if ip_obj in network:
                        return str(vlan.id)
                except ValueError:
                    # CIDR inválido, continuar con el siguiente
                    continue
        
        return None
    
    def detect_or_create_vlan_for_cidr(
        self,
        db: Session,
        organization_id: str,
        cidr: str
    ) -> Optional[str]:
        """
        Busca una VLAN existente que contenga el CIDR reportado.
        Si no existe, auto-crea una VLAN con nombre VLAN_{CIDR}.
        
        Maneja race conditions: si dos workstations con el mismo CIDR
        se registran simultáneamente, la segunda encontrará la VLAN
        creada por la primera tras un reintento.
        
        Args:
            db: Sesión de base de datos
            organization_id: UUID de la organización (tenant isolation)
            cidr: String CIDR válido (ya validado por Pydantic)
            
        Returns:
            UUID de la VLAN asignada (existente o nueva), None si el CIDR es inválido
            
        Precondiciones:
            - cidr es un string CIDR válido (validado previamente)
            - organization_id corresponde a una organización existente
            
        Postcondiciones:
            - Retorna UUID de VLAN (nunca None para CIDR válido)
            - Si VLAN existente contiene el CIDR exacto → retorna esa VLAN
            - Si no existe → crea VLAN con nombre VLAN_{cidr} y retorna su UUID
            - La VLAN creada tiene cidr_ranges = [cidr]
            - La VLAN pertenece a la organización indicada
        """
        # Normalizar CIDR a forma canónica
        try:
            normalized_cidr = str(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            logger.error(f"[VLAN-CIDR] CIDR inválido recibido: {cidr}")
            return None
        
        # Buscar VLANs de la organización que contengan el CIDR
        vlan_id = self._find_vlan_with_cidr(db, organization_id, normalized_cidr)
        if vlan_id:
            logger.info(
                f"[VLAN-CIDR] VLAN existente encontrada para CIDR {normalized_cidr}: "
                f"vlan_id={vlan_id}"
            )
            return vlan_id
        
        # Verificar unicidad de CIDR antes de auto-crear VLAN
        conflict = self.validate_cidr_uniqueness(db, organization_id, [normalized_cidr])
        if conflict:
            cidr_dup, vlan_name = conflict
            logger.error(
                f"[VLAN-CIDR] CIDR {normalized_cidr} ya existe en VLAN '{vlan_name}' "
                f"de la organización {organization_id}. No se puede auto-crear VLAN."
            )
            return None
        
        # No encontrada: auto-crear VLAN
        try:
            new_vlan = VLAN(
                organization_id=organization_id,
                name=f"VLAN_{normalized_cidr}",
                description=f"Auto-creada durante registro de workstation con CIDR {normalized_cidr}",
                cidr_ranges=[normalized_cidr]
            )
            db.add(new_vlan)
            db.flush()
            
            logger.info(
                f"[VLAN-CIDR] VLAN auto-creada para CIDR {normalized_cidr}: "
                f"vlan_id={new_vlan.id}, nombre=VLAN_{normalized_cidr}"
            )
            return str(new_vlan.id)
        
        except IntegrityError:
            # Race condition: otra transacción creó la VLAN simultáneamente
            # Reintentar búsqueda tras rollback del savepoint
            db.rollback()
            logger.warning(
                f"[VLAN-CIDR] Race condition detectada para CIDR {normalized_cidr}. "
                f"Reintentando búsqueda..."
            )
            
            vlan_id = self._find_vlan_with_cidr(db, organization_id, normalized_cidr)
            if vlan_id:
                logger.info(
                    f"[VLAN-CIDR] VLAN encontrada tras reintento para CIDR {normalized_cidr}: "
                    f"vlan_id={vlan_id}"
                )
                return vlan_id
            
            # Si aún no se encuentra, algo inesperado ocurrió
            logger.error(
                f"[VLAN-CIDR] No se pudo encontrar ni crear VLAN para CIDR {normalized_cidr} "
                f"en organización {organization_id}"
            )
            return None
    
    def _find_vlan_with_cidr(
        self,
        db: Session,
        organization_id: str,
        normalized_cidr: str
    ) -> Optional[str]:
        """
        Busca una VLAN de la organización que contenga el CIDR exacto en cidr_ranges.
        
        Args:
            db: Sesión de base de datos
            organization_id: UUID de la organización
            normalized_cidr: CIDR normalizado a buscar
            
        Returns:
            UUID de la VLAN si se encuentra, None si no
        """
        vlans = db.query(VLAN).filter_by(organization_id=organization_id).all()
        
        for vlan in vlans:
            if normalized_cidr in (vlan.cidr_ranges or []):
                return str(vlan.id)
        
        return None
    
    def validate_cidr_uniqueness(
        self,
        db: Session,
        organization_id: str,
        cidrs: List[str],
        exclude_vlan_id: Optional[str] = None
    ) -> Optional[tuple[str, str]]:
        """
        Valida que los CIDRs no existan en otra VLAN de la misma organización.
        
        Verifica unicidad de CIDR por organización: un CIDR solo puede pertenecer
        a una VLAN dentro de la misma organización.
        
        Args:
            db: Sesión de base de datos
            organization_id: UUID de la organización (tenant isolation)
            cidrs: Lista de CIDRs a validar
            exclude_vlan_id: UUID de VLAN a excluir de la verificación
                            (útil al actualizar una VLAN existente)
            
        Returns:
            None si todos los CIDRs son únicos.
            Tupla (cidr_duplicado, vlan_name) si se encuentra un CIDR duplicado.
        """
        # Obtener todas las VLANs de la organización
        vlans = db.query(VLAN).filter_by(organization_id=organization_id).all()
        
        for cidr in cidrs:
            # Normalizar CIDR para comparación consistente
            try:
                normalized_cidr = str(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                continue
            
            for vlan in vlans:
                # Excluir la VLAN actual (para actualizaciones)
                if exclude_vlan_id and str(vlan.id) == exclude_vlan_id:
                    continue
                
                if normalized_cidr in (vlan.cidr_ranges or []):
                    return (normalized_cidr, vlan.name)
        
        return None
    
    def get_organization_by_public_ip(
        self, 
        db: Session, 
        public_ip: str
    ) -> Optional[Organization]:
        """
        Obtiene la organización asociada a una IP pública.
        
        Args:
            db: Sesión de base de datos
            public_ip: Dirección IP pública
            
        Returns:
            Organization si la IP está autorizada, None si no
        """
        public_ip_record = db.query(PublicIP).filter_by(
            ip_address=public_ip
        ).first()
        
        if not public_ip_record:
            return None
        
        return public_ip_record.organization
    
    def register_or_queue_public_ip(
        self,
        db: Session,
        public_ip: str
    ) -> tuple[Optional[Organization], bool]:
        """
        Registra una IP pública o la pone en cola de autorización.
        
        Flujo:
        1. Buscar si la IP ya está registrada
        2. Si está autorizada, devolver la organización
        3. Si está pendiente, devolver None (en cola)
        4. Si no existe, crearla como pendiente
        
        Args:
            db: Sesión de base de datos
            public_ip: Dirección IP pública
            
        Returns:
            Tupla (organization, is_authorized) donde:
            - organization: Organization si está autorizada, None si está pendiente
            - is_authorized: True si está autorizada, False si está pendiente
        """
        from app.models.organization import PublicIP
        
        # Buscar IP existente
        public_ip_record = db.query(PublicIP).filter_by(
            ip_address=public_ip
        ).first()
        
        if public_ip_record:
            # IP ya registrada
            if public_ip_record.is_authorized and public_ip_record.organization_id:
                # Autorizada: devolver organización
                return public_ip_record.organization, True
            else:
                # Pendiente de autorización
                return None, False
        
        # IP nueva: registrar como pendiente
        new_public_ip = PublicIP(
            ip_address=public_ip,
            is_authorized=False,
            organization_id=None,
            description=f"Detectada automáticamente el {datetime.now(timezone.utc).replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        db.add(new_public_ip)
        db.commit()
        
        return None, False
    
    def register_workstation(
        self,
        db: Session,
        ip_private: str,
        public_ip: str,
        hostname: Optional[str] = None,
        os_serial: Optional[str] = None,
        current_user: Optional[str] = None,
        cidr: Optional[str] = None,
        tray_version: Optional[str] = None
    ) -> tuple[Optional[Workstation], bool, str]:
        """
        Registra una workstation nueva o actualiza una existente.
        
        Flujo:
        1. Buscar workstation existente por IP privada
        2. Si existe, actualizar campos y re-evaluar VLAN si CIDR cambió
        3. Si no existe, verificar autorización de IP pública
        4. Si IP autorizada, crear workstation con VLAN auto-asignada por CIDR
        5. Si IP no autorizada, registrarla como pendiente y rechazar
        
        La asignación de VLAN se realiza mediante CIDR cuando está disponible:
        - Si se proporciona `cidr`, se usa `detect_or_create_vlan_for_cidr`
        - Si no hay `cidr`, se usa el fallback `detect_vlan_for_ip`
        
        Args:
            db: Sesión de base de datos
            ip_private: IP privada de la workstation (identificador único)
            public_ip: IP pública desde donde se conecta
            hostname: Nombre del host Windows (opcional)
            os_serial: Serial del sistema operativo (opcional)
            current_user: Usuario actualmente logueado (opcional)
            cidr: CIDR reportado por la workstation (ej: "192.168.1.0/24")
            tray_version: Versión del Tray instalado (ej: "2.1.0.0")
            
        Returns:
            Tupla (workstation, is_new, status) donde:
            - workstation: Objeto Workstation creado/actualizado, o None si IP no autorizada
            - is_new: True si es nueva, False si se actualizó existente
            - status: "authorized", "pending", "inactive_organization"
            
        Raises:
            ValueError: Si hay error en los datos
        """
        # Normalizar CIDR si se proporcionó
        normalized_cidr = None
        if cidr:
            try:
                normalized_cidr = str(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                logger.warning(
                    f"[REGISTRO] CIDR inválido recibido: {cidr}. Se ignorará."
                )
        
        # Log detallado para debugging
        logger.info(
            f"[REGISTRO] Intentando registrar workstation: "
            f"ip_private={ip_private}, "
            f"public_ip={public_ip}, "
            f"hostname={hostname}, "
            f"cidr={normalized_cidr}, "
            f"tray_version={tray_version}"
        )
        
        # 1. Buscar workstation existente
        workstation = db.query(Workstation).filter_by(
            ip_private=ip_private
        ).first()
        
        if workstation:
            logger.info(
                f"[REGISTRO] Workstation existente encontrada: "
                f"id={workstation.id}, "
                f"ip_private={workstation.ip_private}, "
                f"hostname={workstation.hostname}"
            )
            
            # Actualizar campos básicos de la workstation existente
            if hostname:
                workstation.hostname = hostname
            if os_serial:
                workstation.os_serial = os_serial
            if current_user:
                workstation.current_user = current_user
            
            workstation.is_online = True
            workstation.last_connection = datetime.now(timezone.utc).replace(tzinfo=None)
            
            # Guardar tray_version si se proporcionó
            if tray_version:
                workstation.tray_version = tray_version
            
            # Determinar VLAN: usar CIDR si está disponible
            organization_id = str(workstation.organization_id)
            
            if normalized_cidr:
                # Verificar si el CIDR cambió respecto al almacenado
                cidr_changed = workstation.cidr != normalized_cidr
                
                if cidr_changed:
                    logger.info(
                        f"[REGISTRO] CIDR cambió para workstation {workstation.id}: "
                        f"anterior={workstation.cidr}, nuevo={normalized_cidr}. "
                        f"Re-evaluando VLAN..."
                    )
                
                # Actualizar CIDR almacenado
                workstation.cidr = normalized_cidr
                
                # Asignar VLAN por CIDR (siempre re-evaluar para consistencia)
                vlan_id = self.detect_or_create_vlan_for_cidr(
                    db, organization_id, normalized_cidr
                )
                workstation.vlan_id = vlan_id
            else:
                # Fallback: detectar VLAN por IP privada (legacy)
                vlan_id = self.detect_vlan_for_ip(
                    db, organization_id, ip_private
                )
                workstation.vlan_id = vlan_id
            
            db.commit()
            db.refresh(workstation)
            
            logger.info(
                f"[REGISTRO] Workstation actualizada exitosamente: "
                f"id={workstation.id}, vlan_id={workstation.vlan_id}, "
                f"cidr={workstation.cidr}"
            )
            
            return workstation, False, "authorized"
        
        logger.info(
            f"[REGISTRO] Workstation nueva, verificando autorización de IP pública: {public_ip}"
        )
        
        # 2. Workstation nueva: verificar autorización de IP pública
        account, is_authorized = self.register_or_queue_public_ip(db, public_ip)
        
        if not is_authorized:
            logger.warning(
                f"[REGISTRO] IP pública no autorizada: {public_ip}. "
                f"Registro rechazado para ip_private={ip_private}"
            )
            # IP no autorizada: rechazar conexión
            return None, False, "pending"
        
        if not account:
            logger.warning(
                f"[REGISTRO] No se encontró cuenta para IP pública: {public_ip}. "
                f"Registro rechazado para ip_private={ip_private}"
            )
            # No debería pasar, pero por seguridad
            return None, False, "pending"
        
        if not account.is_active:
            logger.warning(
                f"[REGISTRO] Cuenta desactivada: {account.name} (id={account.id}). "
                f"Registro rechazado para ip_private={ip_private}"
            )
            # Cuenta desactivada
            return None, False, "inactive_organization"
        
        logger.info(
            f"[REGISTRO] IP pública autorizada. Creando workstation para cuenta: "
            f"{account.name} (id={account.id})"
        )
        
        # 3. Crear workstation — determinar VLAN por CIDR o fallback por IP
        organization_id = str(account.id)
        
        if normalized_cidr:
            # Asignar VLAN por CIDR (método preferido)
            vlan_id = self.detect_or_create_vlan_for_cidr(
                db, organization_id, normalized_cidr
            )
        else:
            # Fallback: detectar VLAN por IP privada (legacy)
            vlan_id = self.detect_vlan_for_ip(db, organization_id, ip_private)
        
        workstation = Workstation(
            organization_id=account.id,
            vlan_id=vlan_id,
            ip_private=ip_private,
            hostname=hostname,
            os_serial=os_serial,
            current_user=current_user,
            cidr=normalized_cidr,
            tray_version=tray_version,
            is_online=True,
            contingency_active=False,
            last_connection=datetime.now(timezone.utc).replace(tzinfo=None),
            first_seen=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        
        db.add(workstation)
        db.flush()  # Para obtener el ID antes de commit
        
        logger.info(
            f"[REGISTRO] Workstation creada: "
            f"id={workstation.id}, "
            f"ip_private={workstation.ip_private}, "
            f"hostname={workstation.hostname}, "
            f"organization_id={workstation.organization_id}, "
            f"cidr={workstation.cidr}, "
            f"vlan_id={workstation.vlan_id}"
        )
        
        # 4. Activar licencia
        self.activate_license(db, str(workstation.id))
        
        db.commit()
        db.refresh(workstation)
        
        logger.info(
            f"[REGISTRO] Workstation registrada exitosamente: id={workstation.id}"
        )
        
        return workstation, True, "authorized"
    
    def activate_license(self, db: Session, workstation_id: str) -> License:
        """
        Activa una licencia para una workstation.
        
        Desactiva cualquier licencia previa activa y crea una nueva.
        
        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation
            
        Returns:
            License creada
            
        Raises:
            ValueError: Si la workstation no existe
        """
        workstation = db.query(Workstation).filter_by(id=workstation_id).first()
        if not workstation:
            raise ValueError(f"Workstation {workstation_id} no encontrada")
        
        # Desactivar licencias previas activas
        active_licenses = db.query(License).filter_by(
            workstation_id=workstation_id,
            is_active=True
        ).all()
        
        for lic in active_licenses:
            lic.is_active = False
            lic.deactivated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        
        # Calcular serial
        serial_number = self.calculate_license_serial(workstation.ip_private)
        
        # Crear nueva licencia
        license = License(
            workstation_id=workstation_id,
            serial_number=serial_number,
            is_active=True,
            activated_at=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        
        db.add(license)
        db.commit()
        db.refresh(license)
        
        return license
    
    def update_workstation_status(
        self,
        db: Session,
        workstation_id: str,
        is_online: bool,
        current_user: Optional[str] = None
    ) -> Workstation:
        """
        Actualiza el estado de conexión de una workstation.
        
        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation
            is_online: Estado de conexión
            current_user: Usuario actualmente logueado (opcional)
            
        Returns:
            Workstation actualizada
            
        Raises:
            ValueError: Si la workstation no existe
        """
        workstation = db.query(Workstation).filter_by(id=workstation_id).first()
        if not workstation:
            raise ValueError(f"Workstation {workstation_id} no encontrada")
        
        workstation.is_online = is_online
        
        if is_online:
            workstation.last_connection = datetime.now(timezone.utc).replace(tzinfo=None)
        
        if current_user is not None:
            workstation.current_user = current_user
        
        db.commit()
        db.refresh(workstation)
        
        return workstation
    
    def update_contingency_status(
        self,
        db: Session,
        workstation_id: str,
        contingency_active: bool
    ) -> Workstation:
        """
        Actualiza el estado de contingencia de una workstation.
        
        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation
            contingency_active: Estado de contingencia
            
        Returns:
            Workstation actualizada
            
        Raises:
            ValueError: Si la workstation no existe
        """
        workstation = db.query(Workstation).filter_by(id=workstation_id).first()
        if not workstation:
            raise ValueError(f"Workstation {workstation_id} no encontrada")
        
        workstation.contingency_active = contingency_active
        
        db.commit()
        db.refresh(workstation)
        
        return workstation
    
    def get_workstation_by_ip(
        self, 
        db: Session, 
        ip_private: str
    ) -> Optional[Workstation]:
        """
        Obtiene una workstation por su IP privada.
        
        Args:
            db: Sesión de base de datos
            ip_private: IP privada de la workstation
            
        Returns:
            Workstation si existe, None si no
        """
        return db.query(Workstation).filter_by(ip_private=ip_private).first()
    
    def get_workstation_by_id(
        self, 
        db: Session, 
        workstation_id: str
    ) -> Optional[Workstation]:
        """
        Obtiene una workstation por su ID.
        
        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation
            
        Returns:
            Workstation si existe, None si no
        """
        return db.query(Workstation).filter_by(id=workstation_id).first()
    
    def get_workstations_by_organization(
        self,
        db: Session,
        organization_id: str,
        is_online: Optional[bool] = None,
        contingency_active: Optional[bool] = None,
        vlan_id: Optional[str] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[List[Workstation], int]:
        """
        Obtiene workstations de una organización con filtros opcionales.
        
        Args:
            db: Sesión de base de datos
            organization_id: UUID de la organización
            is_online: Filtrar por estado online (opcional)
            contingency_active: Filtrar por contingencia (opcional)
            vlan_id: Filtrar por VLAN (opcional)
            search: Buscar en IP, hostname (opcional)
            skip: Número de registros a saltar (paginación)
            limit: Número máximo de registros a devolver
            
        Returns:
            Tupla (workstations, total) donde:
            - workstations: Lista de workstations
            - total: Número total de workstations (sin paginación)
        """
        query = db.query(Workstation).filter_by(organization_id=organization_id)
        
        # Aplicar filtros
        if is_online is not None:
            query = query.filter_by(is_online=is_online)
        
        if contingency_active is not None:
            query = query.filter_by(contingency_active=contingency_active)
        
        if vlan_id is not None:
            query = query.filter_by(vlan_id=vlan_id)
        
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                or_(
                    Workstation.ip_private.ilike(search_pattern),
                    Workstation.hostname.ilike(search_pattern),
                    Workstation.current_user.ilike(search_pattern)
                )
            )
        
        # Contar total antes de paginación
        total = query.count()
        
        # Aplicar paginación y ordenamiento
        workstations = query.order_by(
            Workstation.last_connection.desc()
        ).offset(skip).limit(limit).all()
        
        return workstations, total
    
    def get_workstations_by_vlan(
        self,
        db: Session,
        vlan_id: str,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[List[Workstation], int]:
        """
        Obtiene workstations de una VLAN específica.
        
        Args:
            db: Sesión de base de datos
            vlan_id: UUID de la VLAN
            skip: Número de registros a saltar
            limit: Número máximo de registros a devolver
            
        Returns:
            Tupla (workstations, total)
        """
        query = db.query(Workstation).filter_by(vlan_id=vlan_id)
        
        total = query.count()
        
        workstations = query.order_by(
            Workstation.last_connection.desc()
        ).offset(skip).limit(limit).all()
        
        return workstations, total
    
    def get_online_count(self, db: Session, organization_id: Optional[str] = None) -> int:
        """
        Obtiene el número de workstations online.
        
        Args:
            db: Sesión de base de datos
            organization_id: UUID de la organización (None para admin = todas)
            
        Returns:
            Número de workstations online
        """
        query = db.query(Workstation).filter(Workstation.is_online.is_(True))
        
        if organization_id is not None:
            query = query.filter(Workstation.organization_id == organization_id)
        
        return query.count()
    
    def get_contingency_count(self, db: Session, organization_id: Optional[str] = None) -> int:
        """
        Obtiene el número de workstations en contingencia.
        
        Args:
            db: Sesión de base de datos
            organization_id: UUID de la organización (None para admin = todas)
            
        Returns:
            Número de workstations en contingencia
        """
        query = db.query(Workstation).filter(Workstation.contingency_active.is_(True))
        
        if organization_id is not None:
            query = query.filter(Workstation.organization_id == organization_id)
        
        return query.count()
    
    def get_total_count(self, db: Session, organization_id: Optional[str] = None) -> int:
        """
        Obtiene el número total de workstations.
        
        Args:
            db: Sesión de base de datos
            organization_id: UUID de la organización (None para admin = todas)
            
        Returns:
            Número total de workstations
        """
        query = db.query(Workstation)
        
        if organization_id is not None:
            query = query.filter(Workstation.organization_id == organization_id)
        
        return query.count()
    
    def get_active_license(
        self, 
        db: Session, 
        workstation_id: str
    ) -> Optional[License]:
        """
        Obtiene la licencia activa de una workstation.
        
        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation
            
        Returns:
            License activa si existe, None si no
        """
        return db.query(License).filter_by(
            workstation_id=workstation_id,
            is_active=True
        ).first()

