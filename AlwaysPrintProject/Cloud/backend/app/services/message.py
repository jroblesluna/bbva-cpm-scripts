"""
Servicio de gestión de mensajes.

Este servicio implementa la lógica de negocio para:
- Envío de mensajes a workstations, VLANs o cuentas completas
- Gestión de estado de entrega
- Encolado de mensajes para workstations offline
- Consulta de mensajes pendientes y entregados
"""

from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.message import Message, TargetType
from app.models.workstation import Workstation
from app.models.vlan import VLAN
from app.models.user import User


class MessageService:
    """
    Servicio para gestión de mensajes.
    
    Proporciona métodos para:
    - Enviar mensajes a diferentes tipos de destinatarios
    - Marcar mensajes como entregados
    - Obtener mensajes pendientes
    - Listar mensajes con filtros
    """
    
    def send_message_to_workstation(
        self,
        db: Session,
        account_id: str,
        sender_id: str,
        workstation_id: str,
        content: str
    ) -> Message:
        """
        Envía un mensaje a una workstation específica.
        
        Args:
            db: Sesión de base de datos
            account_id: UUID de la cuenta
            sender_id: UUID del usuario que envía el mensaje
            workstation_id: UUID de la workstation destinataria
            content: Contenido del mensaje (máx 5000 caracteres)
            
        Returns:
            Message creado
            
        Raises:
            ValueError: Si la workstation no existe o no pertenece a la cuenta
            ValueError: Si el contenido excede 5000 caracteres
        """
        # Validar longitud del contenido
        if len(content) > 5000:
            raise ValueError(
                f"El contenido del mensaje excede el límite de 5000 caracteres "
                f"(actual: {len(content)})"
            )
        
        # Verificar que la workstation existe y pertenece a la cuenta
        workstation = db.query(Workstation).filter_by(
            id=workstation_id,
            organization_id=account_id
        ).first()
        
        if not workstation:
            raise ValueError(
                f"Workstation {workstation_id} no encontrada o no pertenece "
                f"a la cuenta {account_id}"
            )
        
        # Crear mensaje
        message = Message(
            organization_id=account_id,
            sender_id=sender_id,
            target_type=TargetType.WORKSTATION,
            target_id=workstation_id,
            content=content,
            is_delivered=False,
            sent_at=datetime.utcnow()
        )
        
        db.add(message)
        db.commit()
        db.refresh(message)
        
        return message
    
    def send_message_to_vlan(
        self,
        db: Session,
        account_id: str,
        sender_id: str,
        vlan_id: str,
        content: str
    ) -> Message:
        """
        Envía un mensaje a todas las workstations de una VLAN.
        
        Args:
            db: Sesión de base de datos
            account_id: UUID de la cuenta
            sender_id: UUID del usuario que envía el mensaje
            vlan_id: UUID de la VLAN destinataria
            content: Contenido del mensaje (máx 5000 caracteres)
            
        Returns:
            Message creado
            
        Raises:
            ValueError: Si la VLAN no existe o no pertenece a la cuenta
            ValueError: Si el contenido excede 5000 caracteres
        """
        # Validar longitud del contenido
        if len(content) > 5000:
            raise ValueError(
                f"El contenido del mensaje excede el límite de 5000 caracteres "
                f"(actual: {len(content)})"
            )
        
        # Verificar que la VLAN existe y pertenece a la cuenta
        vlan = db.query(VLAN).filter_by(
            id=vlan_id,
            organization_id=account_id
        ).first()
        
        if not vlan:
            raise ValueError(
                f"VLAN {vlan_id} no encontrada o no pertenece a la cuenta {account_id}"
            )
        
        # Crear mensaje
        message = Message(
            organization_id=account_id,
            sender_id=sender_id,
            target_type=TargetType.VLAN,
            target_id=vlan_id,
            content=content,
            is_delivered=False,
            sent_at=datetime.utcnow()
        )
        
        db.add(message)
        db.commit()
        db.refresh(message)
        
        return message
    
    def send_message_to_account(
        self,
        db: Session,
        account_id: str,
        sender_id: str,
        content: str
    ) -> Message:
        """
        Envía un mensaje a todas las workstations de una cuenta (broadcast).
        
        Args:
            db: Sesión de base de datos
            account_id: UUID de la cuenta
            sender_id: UUID del usuario que envía el mensaje
            content: Contenido del mensaje (máx 5000 caracteres)
            
        Returns:
            Message creado
            
        Raises:
            ValueError: Si el contenido excede 5000 caracteres
        """
        # Validar longitud del contenido
        if len(content) > 5000:
            raise ValueError(
                f"El contenido del mensaje excede el límite de 5000 caracteres "
                f"(actual: {len(content)})"
            )
        
        # Crear mensaje (target_id es NULL para broadcast a cuenta)
        message = Message(
            organization_id=account_id,
            sender_id=sender_id,
            target_type=TargetType.ACCOUNT,
            target_id=None,
            content=content,
            is_delivered=False,
            sent_at=datetime.utcnow()
        )
        
        db.add(message)
        db.commit()
        db.refresh(message)
        
        return message
    
    def mark_message_as_delivered(
        self,
        db: Session,
        message_id: str
    ) -> Message:
        """
        Marca un mensaje como entregado.
        
        Args:
            db: Sesión de base de datos
            message_id: UUID del mensaje
            
        Returns:
            Message actualizado
            
        Raises:
            ValueError: Si el mensaje no existe
        """
        message = db.query(Message).filter_by(id=message_id).first()
        if not message:
            raise ValueError(f"Mensaje {message_id} no encontrado")
        
        message.is_delivered = True
        message.delivered_at = datetime.utcnow()
        
        db.commit()
        db.refresh(message)
        
        return message
    
    def get_pending_messages_for_workstation(
        self,
        db: Session,
        workstation_id: str
    ) -> List[Message]:
        """
        Obtiene mensajes pendientes para una workstation.
        
        Incluye:
        - Mensajes dirigidos específicamente a la workstation
        - Mensajes dirigidos a la VLAN de la workstation
        - Mensajes broadcast a la cuenta de la workstation
        
        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation
            
        Returns:
            Lista de mensajes pendientes (no entregados)
            
        Raises:
            ValueError: Si la workstation no existe
        """
        # Obtener workstation
        workstation = db.query(Workstation).filter_by(id=workstation_id).first()
        if not workstation:
            raise ValueError(f"Workstation {workstation_id} no encontrada")
        
        # Construir query para mensajes pendientes
        messages = []
        
        # 1. Mensajes dirigidos a la workstation específica
        ws_messages = db.query(Message).filter(
            Message.organization_id == workstation.organization_id,
            Message.target_type == TargetType.WORKSTATION,
            Message.target_id == workstation_id,
            Message.is_delivered == False
        ).order_by(Message.sent_at.asc()).all()
        messages.extend(ws_messages)
        
        # 2. Mensajes dirigidos a la VLAN (si la workstation pertenece a una)
        if workstation.vlan_id:
            vlan_messages = db.query(Message).filter(
                Message.organization_id == workstation.organization_id,
                Message.target_type == TargetType.VLAN,
                Message.target_id == workstation.vlan_id,
                Message.is_delivered == False
            ).order_by(Message.sent_at.asc()).all()
            messages.extend(vlan_messages)
        
        # 3. Mensajes broadcast a la cuenta
        account_messages = db.query(Message).filter(
            Message.organization_id == workstation.organization_id,
            Message.target_type == TargetType.ACCOUNT,
            Message.is_delivered == False
        ).order_by(Message.sent_at.asc()).all()
        messages.extend(account_messages)
        
        # Ordenar por fecha de envío
        messages.sort(key=lambda m: m.sent_at)
        
        return messages
    
    def get_messages_by_account(
        self,
        db: Session,
        account_id: str,
        target_type: Optional[TargetType] = None,
        is_delivered: Optional[bool] = None,
        sender_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[List[Message], int]:
        """
        Obtiene mensajes de una cuenta con filtros opcionales.
        
        Args:
            db: Sesión de base de datos
            account_id: UUID de la cuenta
            target_type: Filtrar por tipo de destinatario (opcional)
            is_delivered: Filtrar por estado de entrega (opcional)
            sender_id: Filtrar por remitente (opcional)
            skip: Número de registros a saltar (paginación)
            limit: Número máximo de registros a devolver
            
        Returns:
            Tupla (messages, total) donde:
            - messages: Lista de mensajes
            - total: Número total de mensajes (sin paginación)
        """
        query = db.query(Message).filter_by(organization_id=account_id)
        
        # Aplicar filtros
        if target_type is not None:
            query = query.filter_by(target_type=target_type)
        
        if is_delivered is not None:
            query = query.filter_by(is_delivered=is_delivered)
        
        if sender_id is not None:
            query = query.filter_by(sender_id=sender_id)
        
        # Contar total antes de paginación
        total = query.count()
        
        # Aplicar paginación y ordenamiento (más recientes primero)
        messages = query.order_by(
            Message.sent_at.desc()
        ).offset(skip).limit(limit).all()
        
        return messages, total
    
    def get_message_by_id(
        self,
        db: Session,
        message_id: str
    ) -> Optional[Message]:
        """
        Obtiene un mensaje por su ID.
        
        Args:
            db: Sesión de base de datos
            message_id: UUID del mensaje
            
        Returns:
            Message si existe, None si no
        """
        return db.query(Message).filter_by(id=message_id).first()
    
    def get_pending_count(self, db: Session, account_id: str) -> int:
        """
        Obtiene el número de mensajes pendientes de una cuenta.
        
        Args:
            db: Sesión de base de datos
            account_id: UUID de la cuenta
            
        Returns:
            Número de mensajes pendientes
        """
        return db.query(Message).filter_by(
            organization_id=account_id,
            is_delivered=False
        ).count()
    
    def get_delivered_count(self, db: Session, account_id: str) -> int:
        """
        Obtiene el número de mensajes entregados de una cuenta.
        
        Args:
            db: Sesión de base de datos
            account_id: UUID de la cuenta
            
        Returns:
            Número de mensajes entregados
        """
        return db.query(Message).filter_by(
            organization_id=account_id,
            is_delivered=True
        ).count()
    
    def delete_old_delivered_messages(
        self,
        db: Session,
        account_id: str,
        days_old: int = 30
    ) -> int:
        """
        Elimina mensajes entregados antiguos.
        
        Útil para limpieza periódica de mensajes ya entregados.
        
        Args:
            db: Sesión de base de datos
            account_id: UUID de la cuenta
            days_old: Número de días de antigüedad (default: 30)
            
        Returns:
            Número de mensajes eliminados
        """
        from datetime import timedelta
        
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        # Buscar mensajes antiguos entregados
        old_messages = db.query(Message).filter(
            Message.organization_id == account_id,
            Message.is_delivered == True,
            Message.delivered_at < cutoff_date
        ).all()
        
        count = len(old_messages)
        
        # Eliminar
        for message in old_messages:
            db.delete(message)
        
        db.commit()
        
        return count
    
    def get_workstations_for_message(
        self,
        db: Session,
        message_id: str
    ) -> List[Workstation]:
        """
        Obtiene las workstations destinatarias de un mensaje.
        
        Args:
            db: Sesión de base de datos
            message_id: UUID del mensaje
            
        Returns:
            Lista de workstations destinatarias
            
        Raises:
            ValueError: Si el mensaje no existe
        """
        message = db.query(Message).filter_by(id=message_id).first()
        if not message:
            raise ValueError(f"Mensaje {message_id} no encontrado")
        
        workstations = []
        
        if message.target_type == TargetType.WORKSTATION:
            # Mensaje a workstation específica
            ws = db.query(Workstation).filter_by(id=message.target_id).first()
            if ws:
                workstations.append(ws)
        
        elif message.target_type == TargetType.VLAN:
            # Mensaje a todas las workstations de una VLAN
            workstations = db.query(Workstation).filter_by(
                vlan_id=message.target_id
            ).all()
        
        elif message.target_type == TargetType.ACCOUNT:
            # Mensaje broadcast a toda la cuenta
            workstations = db.query(Workstation).filter_by(
                account_id=message.organization_id
            ).all()
        
        return workstations

