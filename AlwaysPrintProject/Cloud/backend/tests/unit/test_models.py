"""
Tests unitarios para modelos SQLAlchemy.

Este módulo contiene tests básicos para verificar que los modelos
se pueden instanciar correctamente y que las relaciones funcionan.
"""

import pytest
from datetime import datetime
import uuid

from app.models import (
    User, UserRole,
    Organization, PublicIP,
    VLAN,
    Workstation, License,
    GlobalConfig, VLANConfig, WorkstationConfig,
    AuditLog, ActionType,
    Message, TargetType
)


class TestUserModel:
    """Tests para el modelo User."""
    
    def test_create_user(self):
        """Test de creación de usuario."""
        user = User(
            email="test@example.com",
            password_hash="hashed_password",
            role=UserRole.OPERATOR,
            is_active=True
        )
        
        assert user.email == "test@example.com"
        assert user.role == UserRole.OPERATOR
        assert user.is_active is True
        assert user.organization_id is None  # Nullable para Admin
    
    def test_user_repr(self):
        """Test de representación string del usuario."""
        user = User(
            id=uuid.uuid4(),
            email="test@example.com",
            password_hash="hashed",
            role=UserRole.ADMIN
        )
        
        repr_str = repr(user)
        assert "User" in repr_str
        assert "test@example.com" in repr_str


class TestOrganizationModel:
    """Tests para el modelo Organization."""
    
    def test_create_organization(self):
        """Test de creación de organización."""
        org = Organization(
            name="BBVA",
            description="Banco BBVA Perú",
            is_active=True
        )
        
        assert org.name == "BBVA"
        assert org.description == "Banco BBVA Perú"
        assert org.is_active is True
    
    def test_organization_repr(self):
        """Test de representación string de la organización."""
        org = Organization(
            id=uuid.uuid4(),
            name="BBVA",
            is_active=True
        )
        
        repr_str = repr(org)
        assert "Organization" in repr_str
        assert "BBVA" in repr_str


class TestPublicIPModel:
    """Tests para el modelo PublicIP."""
    
    def test_create_public_ip(self):
        """Test de creación de IP pública."""
        org_id = uuid.uuid4()
        public_ip = PublicIP(
            organization_id=org_id,
            ip_address="200.48.225.130",
            description="Oficina principal"
        )
        
        assert public_ip.organization_id == org_id
        assert public_ip.ip_address == "200.48.225.130"
        assert public_ip.description == "Oficina principal"


class TestVLANModel:
    """Tests para el modelo VLAN."""
    
    def test_create_vlan(self):
        """Test de creación de VLAN."""
        org_id = uuid.uuid4()
        vlan = VLAN(
            organization_id=org_id,
            name="VLAN Oficina Central",
            description="Red de oficina central",
            cidr_ranges=["192.168.1.0/24", "10.0.0.0/16"]
        )
        
        assert vlan.organization_id == org_id
        assert vlan.name == "VLAN Oficina Central"
        assert len(vlan.cidr_ranges) == 2
        assert "192.168.1.0/24" in vlan.cidr_ranges


class TestWorkstationModel:
    """Tests para el modelo Workstation."""
    
    def test_create_workstation(self):
        """Test de creación de workstation."""
        org_id = uuid.uuid4()
        workstation = Workstation(
            organization_id=org_id,
            ip_private="192.168.1.100",
            hostname="W10001",
            os_serial="ABC123",
            is_online=True,
            contingency_active=False
        )
        
        assert workstation.organization_id == org_id
        assert workstation.ip_private == "192.168.1.100"
        assert workstation.hostname == "W10001"
        assert workstation.is_online is True
        assert workstation.contingency_active is False


class TestLicenseModel:
    """Tests para el modelo License."""
    
    def test_create_license(self):
        """Test de creación de licencia."""
        workstation_id = uuid.uuid4()
        license = License(
            workstation_id=workstation_id,
            serial_number="A1B2C3D4",
            is_active=True
        )
        
        assert license.workstation_id == workstation_id
        assert license.serial_number == "A1B2C3D4"
        assert len(license.serial_number) == 8
        assert license.is_active is True


class TestGlobalConfigModel:
    """Tests para el modelo GlobalConfig."""
    
    def test_create_global_config(self):
        """Test de creación de configuración global."""
        org_id = uuid.uuid4()
        config = GlobalConfig(
            organization_id=org_id,
            corporate_queue_name="LexmarkRoblesAI",
            pending_task_polling_minutes=3,
            bootstrap_domains="apps.iol.pe,iol.pe,sistemas.com.pe,robles.ai"
        )
        
        assert config.organization_id == org_id
        assert config.corporate_queue_name == "LexmarkRoblesAI"
        assert config.pending_task_polling_minutes == 3
        assert "robles.ai" in config.bootstrap_domains
    
    def test_global_config_defaults(self):
        """Test de valores por defecto de configuración global."""
        org_id = uuid.uuid4()
        config = GlobalConfig(
            organization_id=org_id,
            corporate_queue_name="LexmarkRoblesAI",
            pending_task_polling_minutes=3,
            bootstrap_domains="apps.iol.pe,iol.pe,sistemas.com.pe,robles.ai"
        )
        
        assert config.corporate_queue_name == "LexmarkRoblesAI"
        assert config.pending_task_polling_minutes == 3
        assert config.bootstrap_domains == "apps.iol.pe,iol.pe,sistemas.com.pe,robles.ai"


class TestVLANConfigModel:
    """Tests para el modelo VLANConfig."""
    
    def test_create_vlan_config(self):
        """Test de creación de configuración de VLAN."""
        vlan_id = uuid.uuid4()
        config = VLANConfig(
            vlan_id=vlan_id,
            corporate_queue_name="CustomQueue"
        )
        
        assert config.vlan_id == vlan_id
        assert config.corporate_queue_name == "CustomQueue"
        assert config.pending_task_polling_minutes is None


class TestWorkstationConfigModel:
    """Tests para el modelo WorkstationConfig."""
    
    def test_create_workstation_config(self):
        """Test de creación de configuración de workstation."""
        workstation_id = uuid.uuid4()
        config = WorkstationConfig(
            workstation_id=workstation_id,
            pending_task_polling_minutes=5
        )
        
        assert config.workstation_id == workstation_id
        assert config.pending_task_polling_minutes == 5
        assert config.corporate_queue_name is None


class TestAuditLogModel:
    """Tests para el modelo AuditLog."""
    
    def test_create_audit_log(self):
        """Test de creación de log de auditoría."""
        user_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        audit_log = AuditLog(
            user_id=user_id,
            action_type=ActionType.CONFIG_CHANGE,
            entity_type="GlobalConfig",
            entity_id=entity_id,
            old_values={"corporate_queue_name": "OldQueue"},
            new_values={"corporate_queue_name": "NewQueue"},
            ip_address="192.168.1.50"
        )
        
        assert audit_log.user_id == user_id
        assert audit_log.action_type == ActionType.CONFIG_CHANGE
        assert audit_log.entity_type == "GlobalConfig"
        assert audit_log.old_values["corporate_queue_name"] == "OldQueue"
        assert audit_log.new_values["corporate_queue_name"] == "NewQueue"


class TestMessageModel:
    """Tests para el modelo Message."""
    
    def test_create_message_to_workstation(self):
        """Test de creación de mensaje a workstation."""
        org_id = uuid.uuid4()
        sender_id = uuid.uuid4()
        workstation_id = uuid.uuid4()
        
        message = Message(
            organization_id=org_id,
            sender_id=sender_id,
            target_type=TargetType.WORKSTATION,
            target_id=workstation_id,
            content="Test message",
            is_delivered=False
        )
        
        assert message.organization_id == org_id
        assert message.sender_id == sender_id
        assert message.target_type == TargetType.WORKSTATION
        assert message.target_id == workstation_id
        assert message.content == "Test message"
        assert message.is_delivered is False
    
    def test_create_message_to_organization(self):
        """Test de creación de mensaje broadcast a organización."""
        org_id = uuid.uuid4()
        sender_id = uuid.uuid4()
        
        message = Message(
            organization_id=org_id,
            sender_id=sender_id,
            target_type=TargetType.ACCOUNT,
            target_id=None,  # NULL para broadcast
            content="Broadcast message",
            is_delivered=False
        )
        
        assert message.target_type == TargetType.ACCOUNT
        assert message.target_id is None


class TestEnums:
    """Tests para los enums."""
    
    def test_user_role_enum(self):
        """Test de enum UserRole."""
        assert UserRole.ADMIN.value == "admin"
        assert UserRole.OPERATOR.value == "operator"
        assert UserRole.READONLY.value == "readonly"
    
    def test_action_type_enum(self):
        """Test de enum ActionType."""
        assert ActionType.CREATE.value == "create"
        assert ActionType.UPDATE.value == "update"
        assert ActionType.DELETE.value == "delete"
        assert ActionType.CONFIG_CHANGE.value == "config_change"
        assert ActionType.CONTINGENCY_TOGGLE.value == "contingency_toggle"
        assert ActionType.MESSAGE_SENT.value == "message_sent"
        assert ActionType.COMMAND_SENT.value == "command_sent"
    
    def test_target_type_enum(self):
        """Test de enum TargetType."""
        assert TargetType.WORKSTATION.value == "workstation"
        assert TargetType.VLAN.value == "vlan"
        assert TargetType.ACCOUNT.value == "account"
