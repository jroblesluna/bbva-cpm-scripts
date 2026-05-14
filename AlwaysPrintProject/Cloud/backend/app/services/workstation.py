"""
Servicio de gestión de workstations y licencias.

Este servicio implementa la lógica de negocio para:
- Registro de workstations
- Gestión de licencias
- Detección automática de VLAN por IP
- Actualización de estado (online/offline, contingencia)
"""

import hashlib
import ipaddress
from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.workstation import Workstation, License
from app.models.account import Account, PublicIP
from app.models.vlan import VLAN


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
        account_id: str, 
        ip_private: str
    ) -> Optional[str]:
        """
        Detecta la VLAN a la que pertenece una IP privada.
        
        Busca en todas las VLANs de la cuenta y verifica si la IP
        está dentro de alguno de los rangos CIDR definidos.
        
        Si la IP pertenece a múltiples VLANs, devuelve la más reciente.
        
        Args:
            db: Sesión de base de datos
            account_id: UUID de la cuenta
            ip_private: Dirección IP privada a verificar
            
        Returns:
            UUID de la VLAN si se encuentra, None si no pertenece a ninguna
        """
        # Obtener todas las VLANs de la cuenta
        vlans = db.query(VLAN).filter_by(account_id=account_id).order_by(
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
    
    def get_account_by_public_ip(
        self, 
        db: Session, 
        public_ip: str
    ) -> Optional[Account]:
        """
        Obtiene la cuenta asociada a una IP pública.
        
        Args:
            db: Sesión de base de datos
            public_ip: Dirección IP pública
            
        Returns:
            Account si la IP está autorizada, None si no
        """
        public_ip_record = db.query(PublicIP).filter_by(
            ip_address=public_ip
        ).first()
        
        if not public_ip_record:
            return None
        
        return public_ip_record.account
    
    def register_or_queue_public_ip(
        self,
        db: Session,
        public_ip: str
    ) -> tuple[Optional[Account], bool]:
        """
        Registra una IP pública o la pone en cola de autorización.
        
        Flujo:
        1. Buscar si la IP ya está registrada
        2. Si está autorizada, devolver la cuenta
        3. Si está pendiente, devolver None (en cola)
        4. Si no existe, crearla como pendiente
        
        Args:
            db: Sesión de base de datos
            public_ip: Dirección IP pública
            
        Returns:
            Tupla (account, is_authorized) donde:
            - account: Account si está autorizada, None si está pendiente
            - is_authorized: True si está autorizada, False si está pendiente
        """
        from app.models.account import PublicIP
        
        # Buscar IP existente
        public_ip_record = db.query(PublicIP).filter_by(
            ip_address=public_ip
        ).first()
        
        if public_ip_record:
            # IP ya registrada
            if public_ip_record.is_authorized and public_ip_record.account_id:
                # Autorizada: devolver cuenta
                return public_ip_record.account, True
            else:
                # Pendiente de autorización
                return None, False
        
        # IP nueva: registrar como pendiente
        new_public_ip = PublicIP(
            ip_address=public_ip,
            is_authorized=False,
            account_id=None,
            description=f"Detectada automáticamente el {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
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
        current_user: Optional[str] = None
    ) -> tuple[Optional[Workstation], bool, str]:
        """
        Registra una workstation nueva o actualiza una existente.
        
        Flujo:
        1. Buscar workstation existente por IP privada
        2. Si existe, actualizar y devolver
        3. Si no existe, verificar autorización de IP pública
        4. Si IP autorizada, crear workstation
        5. Si IP no autorizada, registrarla como pendiente y rechazar
        
        Args:
            db: Sesión de base de datos
            ip_private: IP privada de la workstation (identificador único)
            public_ip: IP pública desde donde se conecta
            hostname: Nombre del host Windows (opcional)
            os_serial: Serial del sistema operativo (opcional)
            current_user: Usuario actualmente logueado (opcional)
            
        Returns:
            Tupla (workstation, is_new, status) donde:
            - workstation: Objeto Workstation creado/actualizado, o None si IP no autorizada
            - is_new: True si es nueva, False si se actualizó existente
            - status: "authorized", "pending", "inactive_account"
            
        Raises:
            ValueError: Si hay error en los datos
        """
        # 1. Buscar workstation existente
        workstation = db.query(Workstation).filter_by(
            ip_private=ip_private
        ).first()
        
        if workstation:
            # Actualizar workstation existente
            if hostname:
                workstation.hostname = hostname
            if os_serial:
                workstation.os_serial = os_serial
            if current_user:
                workstation.current_user = current_user
            
            workstation.is_online = True
            workstation.last_connection = datetime.utcnow()
            
            # Detectar VLAN (puede haber cambiado)
            vlan_id = self.detect_vlan_for_ip(
                db, 
                str(workstation.account_id), 
                ip_private
            )
            workstation.vlan_id = vlan_id
            
            db.commit()
            db.refresh(workstation)
            
            return workstation, False, "authorized"
        
        # 2. Workstation nueva: verificar autorización de IP pública
        account, is_authorized = self.register_or_queue_public_ip(db, public_ip)
        
        if not is_authorized:
            # IP no autorizada: rechazar conexión
            return None, False, "pending"
        
        if not account:
            # No debería pasar, pero por seguridad
            return None, False, "pending"
        
        if not account.is_active:
            # Cuenta desactivada
            return None, False, "inactive_account"
        
        # 3. Crear workstation
        vlan_id = self.detect_vlan_for_ip(db, str(account.id), ip_private)
        
        workstation = Workstation(
            account_id=account.id,
            vlan_id=vlan_id,
            ip_private=ip_private,
            hostname=hostname,
            os_serial=os_serial,
            current_user=current_user,
            is_online=True,
            contingency_active=False,
            last_connection=datetime.utcnow(),
            first_seen=datetime.utcnow()
        )
        
        db.add(workstation)
        db.flush()  # Para obtener el ID antes de commit
        
        # 4. Activar licencia
        self.activate_license(db, str(workstation.id))
        
        db.commit()
        db.refresh(workstation)
        
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
            lic.deactivated_at = datetime.utcnow()
        
        # Calcular serial
        serial_number = self.calculate_license_serial(workstation.ip_private)
        
        # Crear nueva licencia
        license = License(
            workstation_id=workstation_id,
            serial_number=serial_number,
            is_active=True,
            activated_at=datetime.utcnow()
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
            workstation.last_connection = datetime.utcnow()
        
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
    
    def get_workstations_by_account(
        self,
        db: Session,
        account_id: str,
        is_online: Optional[bool] = None,
        contingency_active: Optional[bool] = None,
        vlan_id: Optional[str] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[List[Workstation], int]:
        """
        Obtiene workstations de una cuenta con filtros opcionales.
        
        Args:
            db: Sesión de base de datos
            account_id: UUID de la cuenta
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
        query = db.query(Workstation).filter_by(account_id=account_id)
        
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
    
    def get_online_count(self, db: Session, account_id: Optional[str] = None) -> int:
        """
        Obtiene el número de workstations online.
        
        Args:
            db: Sesión de base de datos
            account_id: UUID de la cuenta (None para admin = todas las cuentas)
            
        Returns:
            Número de workstations online
        """
        query = db.query(Workstation).filter(Workstation.is_online.is_(True))
        
        if account_id is not None:
            query = query.filter(Workstation.account_id == account_id)
        
        return query.count()
    
    def get_contingency_count(self, db: Session, account_id: Optional[str] = None) -> int:
        """
        Obtiene el número de workstations en contingencia.
        
        Args:
            db: Sesión de base de datos
            account_id: UUID de la cuenta (None para admin = todas las cuentas)
            
        Returns:
            Número de workstations en contingencia
        """
        query = db.query(Workstation).filter(Workstation.contingency_active.is_(True))
        
        if account_id is not None:
            query = query.filter(Workstation.account_id == account_id)
        
        return query.count()
    
    def get_total_count(self, db: Session, account_id: Optional[str] = None) -> int:
        """
        Obtiene el número total de workstations.
        
        Args:
            db: Sesión de base de datos
            account_id: UUID de la cuenta (None para admin = todas las cuentas)
            
        Returns:
            Número total de workstations
        """
        query = db.query(Workstation)
        
        if account_id is not None:
            query = query.filter(Workstation.account_id == account_id)
        
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

