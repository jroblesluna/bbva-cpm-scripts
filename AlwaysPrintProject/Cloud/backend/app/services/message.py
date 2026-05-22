"""
Servicio de gestión de mensajes.

Este servicio implementa la lógica de negocio para:
- Envío de mensajes a workstations, VLANs o cuentas completas
- Creación de entregas individuales (message_deliveries)
- Push en tiempo real vía WebSocket a workstations online
- Gestión de estado de entrega
- Consulta de mensajes pendientes y entregados
"""

import asyncio
import logging
from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.message import Message, TargetType, DeliveryMode
from app.models.message_delivery import MessageDelivery, DeliveryStatus
from app.models.workstation import Workstation
from app.models.vlan import VLAN
from app.models.user import User

logger = logging.getLogger(__name__)


class MessageService:
    """
    Servicio para gestión de mensajes.
    
    Proporciona métodos para:
    - Enviar mensajes a diferentes tipos de destinatarios
    - Crear entregas individuales por workstation
    - Push en tiempo real a workstations online
    - Marcar entregas como enviadas
    - Obtener entregas pendientes al reconectar
    """
    
    def send_message_to_workstation(
        self,
        db: Session,
        organization_id: str,
        sender_id: str,
        workstation_id: str,
        content: str,
        delivery_mode: DeliveryMode = DeliveryMode.ALL
    ) -> Message:
        """
        Envía un mensaje a una workstation específica.
        Crea 1 delivery para esa workstation.
        """
        if len(content) > 5000:
            raise ValueError(
                f"El contenido del mensaje excede el límite de 5000 caracteres "
                f"(actual: {len(content)})"
            )
        
        # Verificar que la workstation existe y pertenece a la organización
        workstation = db.query(Workstation).filter_by(
            id=workstation_id,
            organization_id=organization_id
        ).first()
        
        if not workstation:
            raise ValueError(
                f"Workstation {workstation_id} no encontrada o no pertenece "
                f"a la organización {organization_id}"
            )
        
        # Crear mensaje
        message = Message(
            organization_id=organization_id,
            sender_id=sender_id,
            target_type=TargetType.WORKSTATION,
            target_id=workstation_id,
            content=content,
            delivery_mode=DeliveryMode.ALL,  # Siempre ALL para workstation individual
            is_delivered=False,
            sent_at=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        
        db.add(message)
        db.flush()  # Obtener message.id sin commit
        
        # Crear delivery individual
        delivery = MessageDelivery(
            message_id=message.id,
            workstation_id=workstation_id,
            status=DeliveryStatus.PENDING
        )
        db.add(delivery)
        db.commit()
        db.refresh(message)
        
        return message
    
    def send_message_to_vlan(
        self,
        db: Session,
        organization_id: str,
        sender_id: str,
        vlan_id: str,
        content: str,
        delivery_mode: DeliveryMode = DeliveryMode.ALL
    ) -> Message:
        """
        Envía un mensaje a todas las workstations de una VLAN.
        Crea N deliveries (una por workstation de la VLAN).
        """
        if len(content) > 5000:
            raise ValueError(
                f"El contenido del mensaje excede el límite de 5000 caracteres "
                f"(actual: {len(content)})"
            )
        
        # Verificar que la VLAN existe y pertenece a la organización
        vlan = db.query(VLAN).filter_by(
            id=vlan_id,
            organization_id=organization_id
        ).first()
        
        if not vlan:
            raise ValueError(
                f"VLAN {vlan_id} no encontrada o no pertenece a la organización {organization_id}"
            )
        
        # Crear mensaje
        message = Message(
            organization_id=organization_id,
            sender_id=sender_id,
            target_type=TargetType.VLAN,
            target_id=vlan_id,
            content=content,
            delivery_mode=delivery_mode,
            is_delivered=False,
            sent_at=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        
        db.add(message)
        db.flush()
        
        # Obtener workstations de la VLAN
        workstations = db.query(Workstation).filter_by(vlan_id=vlan_id).all()
        
        # Crear deliveries
        self._create_deliveries(db, message, workstations, delivery_mode)
        
        db.commit()
        db.refresh(message)
        
        return message
    
    def send_message_to_organization(
        self,
        db: Session,
        organization_id: str,
        sender_id: str,
        content: str,
        delivery_mode: DeliveryMode = DeliveryMode.ALL
    ) -> Message:
        """
        Envía un mensaje a todas las workstations de una organización (broadcast).
        Crea N deliveries (una por workstation de la organización).
        """
        if len(content) > 5000:
            raise ValueError(
                f"El contenido del mensaje excede el límite de 5000 caracteres "
                f"(actual: {len(content)})"
            )
        
        # Crear mensaje (target_id es NULL para broadcast a organización)
        message = Message(
            organization_id=organization_id,
            sender_id=sender_id,
            target_type=TargetType.ACCOUNT,
            target_id=None,
            content=content,
            delivery_mode=delivery_mode,
            is_delivered=False,
            sent_at=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        
        db.add(message)
        db.flush()
        
        # Obtener todas las workstations de la organización
        workstations = db.query(Workstation).filter_by(
            organization_id=organization_id
        ).all()
        
        # Crear deliveries
        self._create_deliveries(db, message, workstations, delivery_mode)
        
        db.commit()
        db.refresh(message)
        
        return message
    
    def _create_deliveries(
        self,
        db: Session,
        message: Message,
        workstations: List[Workstation],
        delivery_mode: DeliveryMode
    ):
        """
        Crea registros de delivery para cada workstation.
        
        Si delivery_mode es ONLY_CONNECTED, las workstations offline se marcan como SKIPPED.
        Si delivery_mode es ALL, todas se marcan como PENDING.
        """
        from app.services.websocket_manager import connection_manager
        
        for ws in workstations:
            ws_id_str = str(ws.id)
            is_online = connection_manager.is_workstation_online(ws_id_str)
            
            if delivery_mode == DeliveryMode.ONLY_CONNECTED and not is_online:
                # Marcar como SKIPPED (no se enviará aunque se reconecte)
                status = DeliveryStatus.SKIPPED
            else:
                # PENDING: se enviará ahora (si online) o al reconectar (si offline)
                status = DeliveryStatus.PENDING
            
            delivery = MessageDelivery(
                message_id=message.id,
                workstation_id=ws.id,
                status=status
            )
            db.add(delivery)
    
    async def push_message_to_online_workstations(
        self,
        db: Session,
        message: Message
    ) -> int:
        """
        Envía el mensaje vía WebSocket a todas las workstations online que tengan
        un delivery PENDING. Marca los deliveries como SENT.
        
        Returns:
            Número de workstations a las que se envió exitosamente.
        """
        from app.services.websocket_manager import connection_manager
        
        # Obtener deliveries pendientes
        pending_deliveries = db.query(MessageDelivery).filter(
            MessageDelivery.message_id == message.id,
            MessageDelivery.status == DeliveryStatus.PENDING
        ).all()
        
        sent_count = 0
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        
        # Preparar mensaje WebSocket
        ws_message = {
            "type": "message",
            "message_id": str(message.id),
            "content": message.content,
            "sent_at": message.sent_at.isoformat(),
            "sender_name": message.sender.full_name if message.sender else None,
        }
        
        # Enviar en paralelo a las online
        tasks = []
        online_deliveries = []  # Lista ordenada de deliveries para las que se envía
        
        for delivery in pending_deliveries:
            ws_id_str = str(delivery.workstation_id)
            if connection_manager.is_workstation_online(ws_id_str):
                tasks.append(connection_manager.send_to_workstation(ws_id_str, ws_message))
                online_deliveries.append(delivery)
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, delivery in enumerate(online_deliveries):
                result = results[i]
                if result is True or (isinstance(result, bool) and result):
                    # Enviado exitosamente
                    delivery.status = DeliveryStatus.SENT
                    delivery.delivered_at = now
                    sent_count += 1
        
        # Verificar si todos los deliveries están completos
        self._update_message_delivered_status(db, message)
        
        db.commit()
        
        logger.info(
            f"[MENSAJES] Push realizado: message_id={message.id}, "
            f"enviados={sent_count}/{len(pending_deliveries)} pendientes"
        )
        
        return sent_count
    
    def _update_message_delivered_status(self, db: Session, message: Message):
        """
        Actualiza is_delivered del mensaje padre basándose en el estado de sus deliveries.
        Se marca como entregado cuando no quedan deliveries PENDING.
        """
        pending_count = db.query(MessageDelivery).filter(
            MessageDelivery.message_id == message.id,
            MessageDelivery.status == DeliveryStatus.PENDING
        ).count()
        
        if pending_count == 0:
            message.is_delivered = True
            message.delivered_at = datetime.now(timezone.utc).replace(tzinfo=None)
    
    def mark_delivery_as_sent(
        self,
        db: Session,
        message_id: str,
        workstation_id: str
    ) -> Optional[MessageDelivery]:
        """
        Marca un delivery específico como enviado.
        Usado cuando se envía un mensaje pendiente al reconectar una workstation.
        """
        delivery = db.query(MessageDelivery).filter(
            MessageDelivery.message_id == message_id,
            MessageDelivery.workstation_id == workstation_id,
            MessageDelivery.status == DeliveryStatus.PENDING
        ).first()
        
        if delivery:
            delivery.status = DeliveryStatus.SENT
            delivery.delivered_at = datetime.now(timezone.utc).replace(tzinfo=None)
            
            # Verificar si el mensaje padre se completó
            message = db.query(Message).filter_by(id=message_id).first()
            if message:
                self._update_message_delivered_status(db, message)
            
            db.commit()
        
        return delivery
    
    def get_pending_deliveries_for_workstation(
        self,
        db: Session,
        workstation_id: str
    ) -> List[MessageDelivery]:
        """
        Obtiene deliveries pendientes para una workstation (al reconectar).
        Solo retorna deliveries con status PENDING.
        """
        deliveries = db.query(MessageDelivery).filter(
            MessageDelivery.workstation_id == workstation_id,
            MessageDelivery.status == DeliveryStatus.PENDING
        ).join(Message).order_by(Message.sent_at.asc()).all()
        
        return deliveries
    
    def get_deliveries_for_message(
        self,
        db: Session,
        message_id: str
    ) -> List[MessageDelivery]:
        """
        Obtiene todas las entregas de un mensaje con información de workstation.
        """
        return db.query(MessageDelivery).filter(
            MessageDelivery.message_id == message_id
        ).all()
    
    def get_delivery_summary(
        self,
        db: Session,
        message_id: str
    ) -> dict:
        """
        Obtiene resumen de entregas para un mensaje.
        Returns: {total, sent, pending, skipped}
        """
        deliveries = db.query(MessageDelivery).filter(
            MessageDelivery.message_id == message_id
        ).all()
        
        total = len(deliveries)
        sent = sum(1 for d in deliveries if d.status == DeliveryStatus.SENT)
        pending = sum(1 for d in deliveries if d.status == DeliveryStatus.PENDING)
        skipped = sum(1 for d in deliveries if d.status == DeliveryStatus.SKIPPED)
        
        return {
            "total": total,
            "sent": sent,
            "pending": pending,
            "skipped": skipped
        }
    
    # === MÉTODOS LEGACY (compatibilidad) ===
    
    def mark_message_as_delivered(
        self,
        db: Session,
        message_id: str
    ) -> Message:
        """
        Marca un mensaje como entregado (legacy).
        Usado por el flujo antiguo de entrega directa.
        """
        message = db.query(Message).filter_by(id=message_id).first()
        if not message:
            raise ValueError(f"Mensaje {message_id} no encontrado")
        
        message.is_delivered = True
        message.delivered_at = datetime.now(timezone.utc).replace(tzinfo=None)
        
        db.commit()
        db.refresh(message)
        
        return message
    
    def get_pending_messages_for_workstation(
        self,
        db: Session,
        workstation_id: str
    ) -> List[Message]:
        """
        Obtiene mensajes pendientes para una workstation (legacy).
        DEPRECATED: Usar get_pending_deliveries_for_workstation() en su lugar.
        Se mantiene por compatibilidad con el flujo de reconexión existente.
        """
        workstation = db.query(Workstation).filter_by(id=workstation_id).first()
        if not workstation:
            raise ValueError(f"Workstation {workstation_id} no encontrada")
        
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
        org_messages = db.query(Message).filter(
            Message.organization_id == workstation.organization_id,
            Message.target_type == TargetType.ACCOUNT,
            Message.is_delivered == False
        ).order_by(Message.sent_at.asc()).all()
        messages.extend(org_messages)
        
        messages.sort(key=lambda m: m.sent_at)
        
        return messages
    
    def get_messages_by_organization(
        self,
        db: Session,
        organization_id: str,
        target_type: Optional[TargetType] = None,
        is_delivered: Optional[bool] = None,
        sender_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[List[Message], int]:
        """Obtiene mensajes de una organización con filtros opcionales."""
        query = db.query(Message).filter_by(organization_id=organization_id)
        
        if target_type is not None:
            query = query.filter_by(target_type=target_type)
        
        if is_delivered is not None:
            query = query.filter_by(is_delivered=is_delivered)
        
        if sender_id is not None:
            query = query.filter_by(sender_id=sender_id)
        
        total = query.count()
        messages = query.order_by(
            Message.sent_at.desc()
        ).offset(skip).limit(limit).all()
        
        return messages, total
    
    def get_message_by_id(
        self,
        db: Session,
        message_id: str
    ) -> Optional[Message]:
        """Obtiene un mensaje por su ID."""
        return db.query(Message).filter_by(id=message_id).first()
    
    def get_pending_count(self, db: Session, organization_id: str) -> int:
        """Obtiene el número de mensajes pendientes de una organización."""
        return db.query(Message).filter_by(
            organization_id=organization_id,
            is_delivered=False
        ).count()
    
    def get_delivered_count(self, db: Session, organization_id: str) -> int:
        """Obtiene el número de mensajes entregados de una organización."""
        return db.query(Message).filter_by(
            organization_id=organization_id,
            is_delivered=True
        ).count()
