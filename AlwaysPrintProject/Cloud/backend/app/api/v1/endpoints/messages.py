"""
Endpoints de gestión de mensajes.

Este módulo define los endpoints para:
- Envío de mensajes a workstations con push en tiempo real
- Listado de mensajes con resumen de entregas
- Detalle de mensaje con entregas individuales
- Estadísticas de mensajes
"""

import logging
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.utils import get_client_ip
from app.models.user import User, UserRole
from app.models.message import Message, TargetType, DeliveryMode
from app.models.message_delivery import MessageDelivery, DeliveryStatus
from app.models.workstation import Workstation
from app.schemas.message import (
    MessageCreate,
    MessageResponse,
    MessageDeliveryResponse,
    MessageDetailResponse,
    MessageListResponse,
    MessageStatsResponse,
)
from app.services.message import MessageService
from app.services.audit import AuditService

router = APIRouter()
logger = logging.getLogger(__name__)


def _build_message_response(db: Session, message: Message) -> dict:
    """Construye la respuesta de un mensaje con resumen de entregas."""
    message_service = MessageService()
    summary = message_service.get_delivery_summary(db, str(message.id))
    
    return {
        "id": message.id,
        "organization_id": message.organization_id,
        "sender_id": message.sender_id,
        "sender_name": message.sender.full_name if message.sender else None,
        "target_type": message.target_type,
        "target_id": message.target_id,
        "content": message.content,
        "delivery_mode": message.delivery_mode,
        "is_delivered": message.is_delivered,
        "sent_at": message.sent_at,
        "delivered_at": message.delivered_at,
        "total_deliveries": summary["total"],
        "sent_deliveries": summary["sent"],
        "pending_deliveries": summary["pending"],
        "skipped_deliveries": summary["skipped"],
    }


@router.get("/", response_model=MessageListResponse)
def list_messages(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    target_type: Optional[TargetType] = Query(None),
    is_delivered: Optional[bool] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Listar mensajes de la organización con resumen de entregas."""
    if current_user.role == UserRole.OPERATOR and not current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador sin cuenta asignada")
    
    org_id = current_user.organization_id if current_user.role == UserRole.OPERATOR else None
    
    query = db.query(Message)
    if org_id:
        query = query.filter(Message.organization_id == org_id)
    if target_type:
        query = query.filter(Message.target_type == target_type)
    if is_delivered is not None:
        query = query.filter(Message.is_delivered == is_delivered)
    
    total = query.count()
    offset = (page - 1) * page_size
    messages = query.order_by(Message.sent_at.desc()).offset(offset).limit(page_size).all()
    
    # Construir respuestas con resumen de entregas
    message_responses = [_build_message_response(db, msg) for msg in messages]
    
    return MessageListResponse(total=total, page=page, page_size=page_size, messages=message_responses)


@router.post("/", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    request: Request,
    message_data: MessageCreate,
    organization_id: Optional[UUID] = Query(None, description="ID de la organización destino (requerido para admin)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Enviar un mensaje a workstation(s) con push en tiempo real."""
    if current_user.role == UserRole.OPERATOR and not current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador sin cuenta asignada")
    
    # Determinar organization_id: operador usa su organización, admin debe especificar
    target_org_id = current_user.organization_id if current_user.role == UserRole.OPERATOR else organization_id
    if not target_org_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization_id requerido")
    
    message_service = MessageService()
    
    # Enviar mensaje según tipo de destinatario
    if message_data.target_type == TargetType.WORKSTATION:
        message = message_service.send_message_to_workstation(
            db, target_org_id, current_user.id, message_data.target_id, message_data.content,
            delivery_mode=DeliveryMode.ALL
        )
    elif message_data.target_type == TargetType.VLAN:
        message = message_service.send_message_to_vlan(
            db, target_org_id, current_user.id, message_data.target_id, message_data.content,
            delivery_mode=message_data.delivery_mode
        )
    else:  # ACCOUNT
        message = message_service.send_message_to_organization(
            db, target_org_id, current_user.id, message_data.content,
            delivery_mode=message_data.delivery_mode
        )
    
    # Push en tiempo real a workstations online
    try:
        sent_count = await message_service.push_message_to_online_workstations(db, message)
        logger.info(
            f"[MENSAJES] Mensaje creado y enviado: id={message.id}, "
            f"target_type={message_data.target_type.value}, "
            f"delivery_mode={message_data.delivery_mode.value}, "
            f"push_enviados={sent_count}"
        )
    except Exception as e:
        # No fallar la creación del mensaje si el push falla
        logger.error(f"[MENSAJES] Error en push WebSocket: {e}")
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_message_sent(
        db=db,
        message_id=str(message.id),
        sender_id=str(current_user.id),
        organization_id=str(target_org_id),
        target_type=message_data.target_type.value,
        target_id=str(message_data.target_id) if message_data.target_id else None,
        content_preview=message_data.content[:200],
        ip_address=get_client_ip(request)
    )
    
    # Refrescar para obtener datos actualizados
    db.refresh(message)
    return _build_message_response(db, message)


@router.get("/stats", response_model=MessageStatsResponse)
def get_message_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Obtener estadísticas de mensajes."""
    if current_user.role == UserRole.OPERATOR and not current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador sin cuenta asignada")
    
    org_id = current_user.organization_id if current_user.role == UserRole.OPERATOR else None
    
    base_query = db.query(Message)
    if org_id:
        base_query = base_query.filter(Message.organization_id == org_id)
    
    total_sent = base_query.count()
    
    delivered_query = db.query(Message)
    if org_id:
        delivered_query = delivered_query.filter(Message.organization_id == org_id)
    total_delivered = delivered_query.filter(Message.is_delivered == True).count()
    
    total_pending = total_sent - total_delivered
    delivery_rate = (total_delivered / total_sent * 100) if total_sent > 0 else 0.0
    
    return MessageStatsResponse(
        total_sent=total_sent,
        total_delivered=total_delivered,
        total_pending=total_pending,
        delivery_rate=delivery_rate
    )


@router.get("/{message_id}", response_model=MessageDetailResponse)
def get_message(
    message_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Obtener detalles de un mensaje con entregas individuales."""
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mensaje no encontrado")
    
    if current_user.role == UserRole.OPERATOR and message.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    # Obtener entregas con información de workstation
    message_service = MessageService()
    deliveries = message_service.get_deliveries_for_message(db, str(message_id))
    
    # Construir respuesta de entregas con datos de workstation
    delivery_responses = []
    for d in deliveries:
        ws = db.query(Workstation).filter_by(id=d.workstation_id).first()
        delivery_responses.append(MessageDeliveryResponse(
            id=d.id,
            message_id=d.message_id,
            workstation_id=d.workstation_id,
            status=d.status,
            delivered_at=d.delivered_at,
            workstation_hostname=ws.hostname if ws else None,
            workstation_ip=ws.ip_private if ws else None,
            workstation_is_online=ws.is_online if ws else None,
        ))
    
    # Resumen
    summary = message_service.get_delivery_summary(db, str(message_id))
    
    sender_name = message.sender.full_name if message.sender else None
    sender_email = message.sender.email if message.sender else None
    
    return MessageDetailResponse(
        id=message.id,
        organization_id=message.organization_id,
        sender_id=message.sender_id,
        target_type=message.target_type,
        target_id=message.target_id,
        content=message.content,
        delivery_mode=message.delivery_mode,
        is_delivered=message.is_delivered,
        sent_at=message.sent_at,
        delivered_at=message.delivered_at,
        total_deliveries=summary["total"],
        sent_deliveries=summary["sent"],
        pending_deliveries=summary["pending"],
        skipped_deliveries=summary["skipped"],
        sender_name=sender_name,
        sender_email=sender_email,
        deliveries=delivery_responses,
    )


@router.get("/{message_id}/deliveries", response_model=list[MessageDeliveryResponse])
def get_message_deliveries(
    message_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Obtener entregas individuales de un mensaje."""
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mensaje no encontrado")
    
    if current_user.role == UserRole.OPERATOR and message.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    message_service = MessageService()
    deliveries = message_service.get_deliveries_for_message(db, str(message_id))
    
    responses = []
    for d in deliveries:
        ws = db.query(Workstation).filter_by(id=d.workstation_id).first()
        responses.append(MessageDeliveryResponse(
            id=d.id,
            message_id=d.message_id,
            workstation_id=d.workstation_id,
            status=d.status,
            delivered_at=d.delivered_at,
            workstation_hostname=ws.hostname if ws else None,
            workstation_ip=ws.ip_private if ws else None,
            workstation_is_online=ws.is_online if ws else None,
        ))
    
    return responses
