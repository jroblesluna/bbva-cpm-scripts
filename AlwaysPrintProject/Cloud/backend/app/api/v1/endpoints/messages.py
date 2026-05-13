"""
Endpoints de gestión de mensajes.

Este módulo define los endpoints para:
- Envío de mensajes a workstations
- Listado de mensajes
- Estadísticas de mensajes
"""

from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.models.message import Message, TargetType
from app.schemas import (
    MessageCreate,
    MessageResponse,
    MessageDetailResponse,
    MessageListResponse,
    MessageStatsResponse,
)
from app.services.message import MessageService
from app.services.audit import AuditService

router = APIRouter()


@router.get("/", response_model=MessageListResponse)
def list_messages(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    target_type: Optional[TargetType] = Query(None),
    is_delivered: Optional[bool] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Listar mensajes de la cuenta."""
    if current_user.role == UserRole.OPERATOR and not current_user.account_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador sin cuenta asignada")
    
    account_id = current_user.account_id if current_user.role == UserRole.OPERATOR else None
    
    query = db.query(Message)
    if account_id:
        query = query.filter(Message.account_id == account_id)
    if target_type:
        query = query.filter(Message.target_type == target_type)
    if is_delivered is not None:
        query = query.filter(Message.is_delivered == is_delivered)
    
    total = query.count()
    offset = (page - 1) * page_size
    messages = query.order_by(Message.sent_at.desc()).offset(offset).limit(page_size).all()
    
    return MessageListResponse(total=total, page=page, page_size=page_size, messages=messages)


@router.post("/", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def send_message(
    message_data: MessageCreate,
    account_id: Optional[UUID] = Query(None, description="ID de la cuenta destino (requerido para admin)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Enviar un mensaje a workstation(s)."""
    if current_user.role == UserRole.OPERATOR and not current_user.account_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador sin cuenta asignada")
    
    # Determinar account_id: operador usa su cuenta, admin debe especificar
    target_account_id = current_user.account_id if current_user.role == UserRole.OPERATOR else account_id
    if not target_account_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account_id requerido")
    
    message_service = MessageService()
    
    # Enviar mensaje según tipo de destinatario
    if message_data.target_type == TargetType.WORKSTATION:
        message = message_service.send_message_to_workstation(
            db, target_account_id, current_user.id, message_data.target_id, message_data.content
        )
    elif message_data.target_type == TargetType.VLAN:
        message = message_service.send_message_to_vlan(
            db, target_account_id, current_user.id, message_data.target_id, message_data.content
        )
    else:  # ACCOUNT
        message = message_service.send_message_to_account(
            db, target_account_id, current_user.id, message_data.content
        )
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_message_sent(
        db=db,
        message_id=str(message.id),
        sender_id=str(current_user.id),
        account_id=str(target_account_id),
        target_type=message_data.target_type.value,
        target_id=str(message_data.target_id) if message_data.target_id else None,
        content_preview=message_data.content[:200]
    )
    
    return message


@router.get("/stats", response_model=MessageStatsResponse)
def get_message_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Obtener estadísticas de mensajes."""
    if current_user.role == UserRole.OPERATOR and not current_user.account_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador sin cuenta asignada")
    
    account_id = current_user.account_id if current_user.role == UserRole.OPERATOR else None
    
    # Query base
    base_query = db.query(Message)
    if account_id:
        base_query = base_query.filter(Message.account_id == account_id)
    
    # Contar totales
    total_sent = base_query.count()
    
    # Contar entregados (crear nueva query desde base)
    delivered_query = db.query(Message)
    if account_id:
        delivered_query = delivered_query.filter(Message.account_id == account_id)
    total_delivered = delivered_query.filter(Message.is_delivered == True).count()
    
    # Calcular pendientes y tasa de entrega
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
    """Obtener detalles de un mensaje."""
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mensaje no encontrado")
    
    if current_user.role == UserRole.OPERATOR and message.account_id != current_user.account_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    # Agregar información del remitente
    sender_name = message.sender.full_name if message.sender else None
    sender_email = message.sender.email if message.sender else None
    
    return MessageDetailResponse(
        **message.__dict__,
        sender_name=sender_name,
        sender_email=sender_email
    )
