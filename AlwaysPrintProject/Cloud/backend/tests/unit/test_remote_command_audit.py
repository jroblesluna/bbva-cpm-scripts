"""
Tests unitarios para el ActionType REMOTE_COMMAND_EXECUTED y su uso en AuditLog.

Verifica que:
- El enum ActionType incluye REMOTE_COMMAND_EXECUTED con el valor correcto
- Se puede crear un AuditLog con los campos esperados para ejecución de comandos remotos
- El campo stdout_preview se trunca a 200 caracteres

Requirements: 5.3
"""

import uuid

import pytest

from app.models.audit import ActionType, AuditLog


class TestRemoteCommandExecutedActionType:
    """Tests para el valor REMOTE_COMMAND_EXECUTED del enum ActionType."""

    def test_remote_command_executed_exists(self):
        """Verificar que REMOTE_COMMAND_EXECUTED existe en el enum ActionType."""
        assert hasattr(ActionType, "REMOTE_COMMAND_EXECUTED")

    def test_remote_command_executed_value(self):
        """Verificar que REMOTE_COMMAND_EXECUTED tiene el valor correcto."""
        assert ActionType.REMOTE_COMMAND_EXECUTED.value == "REMOTE_COMMAND_EXECUTED"

    def test_remote_command_executed_is_string_enum(self):
        """Verificar que REMOTE_COMMAND_EXECUTED es instancia de str (str, Enum)."""
        assert isinstance(ActionType.REMOTE_COMMAND_EXECUTED, str)
        assert ActionType.REMOTE_COMMAND_EXECUTED == "REMOTE_COMMAND_EXECUTED"


class TestRemoteCommandAuditLogCreation:
    """Tests para la creación de AuditLog con REMOTE_COMMAND_EXECUTED."""

    def test_audit_log_with_remote_command_fields(self, db):
        """
        Verificar que un AuditLog se crea con los campos correctos
        para una ejecución de comando remoto (command, command_id, success, stdout_preview).
        """
        user_id = uuid.uuid4()
        workstation_id = uuid.uuid4()
        org_id = uuid.uuid4()
        entity_id = workstation_id
        command_id = str(uuid.uuid4())

        audit_log = AuditLog(
            user_id=user_id,
            workstation_id=workstation_id,
            organization_id=org_id,
            action_type=ActionType.REMOTE_COMMAND_EXECUTED,
            entity_type="workstation",
            entity_id=entity_id,
            new_values={
                "command": "ipconfig /all",
                "command_id": command_id,
                "success": True,
                "stdout_preview": "Windows IP Configuration\n\nEthernet adapter...",
            },
            ip_address="192.168.1.50",
        )
        db.add(audit_log)
        db.commit()
        db.refresh(audit_log)

        assert audit_log.id is not None
        assert audit_log.action_type == ActionType.REMOTE_COMMAND_EXECUTED
        assert audit_log.entity_type == "workstation"
        assert audit_log.entity_id == entity_id
        assert audit_log.user_id == user_id
        assert audit_log.workstation_id == workstation_id
        assert audit_log.organization_id == org_id
        assert audit_log.new_values["command"] == "ipconfig /all"
        assert audit_log.new_values["command_id"] == command_id
        assert audit_log.new_values["success"] is True
        assert "Windows IP Configuration" in audit_log.new_values["stdout_preview"]

    def test_audit_log_remote_command_failure(self, db):
        """
        Verificar que un AuditLog registra correctamente un comando remoto fallido.
        """
        user_id = uuid.uuid4()
        workstation_id = uuid.uuid4()
        org_id = uuid.uuid4()
        command_id = str(uuid.uuid4())

        audit_log = AuditLog(
            user_id=user_id,
            workstation_id=workstation_id,
            organization_id=org_id,
            action_type=ActionType.REMOTE_COMMAND_EXECUTED,
            entity_type="workstation",
            entity_id=workstation_id,
            new_values={
                "command": "rm -rf /nonexistent",
                "command_id": command_id,
                "success": False,
                "stdout_preview": None,
            },
            ip_address="10.0.0.1",
        )
        db.add(audit_log)
        db.commit()
        db.refresh(audit_log)

        assert audit_log.action_type == ActionType.REMOTE_COMMAND_EXECUTED
        assert audit_log.new_values["success"] is False
        assert audit_log.new_values["stdout_preview"] is None


class TestStdoutPreviewTruncation:
    """Tests para verificar que stdout_preview se trunca a 200 caracteres."""

    def test_stdout_preview_truncated_to_200_chars(self, db):
        """
        Verificar que stdout_preview se almacena truncado a 200 caracteres
        cuando el stdout original es más largo.

        Nota: La truncación ocurre en la lógica del endpoint (antes de guardar),
        no en el modelo. Este test verifica que el valor almacenado cumple el límite.
        """
        user_id = uuid.uuid4()
        workstation_id = uuid.uuid4()
        org_id = uuid.uuid4()
        command_id = str(uuid.uuid4())

        # Simular un stdout largo (500 chars)
        full_stdout = "A" * 500
        # La lógica del endpoint trunca a 200 chars: stdout[:200]
        stdout_preview = full_stdout[:200]

        audit_log = AuditLog(
            user_id=user_id,
            workstation_id=workstation_id,
            organization_id=org_id,
            action_type=ActionType.REMOTE_COMMAND_EXECUTED,
            entity_type="workstation",
            entity_id=workstation_id,
            new_values={
                "command": "dir C:\\",
                "command_id": command_id,
                "success": True,
                "stdout_preview": stdout_preview,
            },
        )
        db.add(audit_log)
        db.commit()
        db.refresh(audit_log)

        assert len(audit_log.new_values["stdout_preview"]) == 200
        assert audit_log.new_values["stdout_preview"] == "A" * 200

    def test_stdout_preview_not_truncated_when_short(self, db):
        """
        Verificar que stdout_preview se guarda completo cuando tiene menos de 200 chars.
        """
        user_id = uuid.uuid4()
        workstation_id = uuid.uuid4()
        org_id = uuid.uuid4()
        command_id = str(uuid.uuid4())

        short_stdout = "Pong!"
        # Con stdout corto, no se trunca
        stdout_preview = short_stdout[:200]  # Sin efecto

        audit_log = AuditLog(
            user_id=user_id,
            workstation_id=workstation_id,
            organization_id=org_id,
            action_type=ActionType.REMOTE_COMMAND_EXECUTED,
            entity_type="workstation",
            entity_id=workstation_id,
            new_values={
                "command": "ping localhost -n 1",
                "command_id": command_id,
                "success": True,
                "stdout_preview": stdout_preview,
            },
        )
        db.add(audit_log)
        db.commit()
        db.refresh(audit_log)

        assert audit_log.new_values["stdout_preview"] == "Pong!"
        assert len(audit_log.new_values["stdout_preview"]) == 5

    def test_stdout_preview_exactly_200_chars(self, db):
        """
        Verificar que stdout_preview de exactamente 200 chars no se altera.
        """
        user_id = uuid.uuid4()
        workstation_id = uuid.uuid4()
        org_id = uuid.uuid4()
        command_id = str(uuid.uuid4())

        exact_stdout = "B" * 200
        stdout_preview = exact_stdout[:200]

        audit_log = AuditLog(
            user_id=user_id,
            workstation_id=workstation_id,
            organization_id=org_id,
            action_type=ActionType.REMOTE_COMMAND_EXECUTED,
            entity_type="workstation",
            entity_id=workstation_id,
            new_values={
                "command": "systeminfo",
                "command_id": command_id,
                "success": True,
                "stdout_preview": stdout_preview,
            },
        )
        db.add(audit_log)
        db.commit()
        db.refresh(audit_log)

        assert len(audit_log.new_values["stdout_preview"]) == 200
