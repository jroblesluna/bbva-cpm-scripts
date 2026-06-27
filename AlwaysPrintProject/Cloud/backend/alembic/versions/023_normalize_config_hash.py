"""Recalcular config_hash con normalización JSON compacta

Revision ID: 023_normalize_config_hash
Revises: 022_add_audit_actions
Create Date: 2026-06-27 12:00:00.000000

Recalcula config_hash de todos los ActionConfigs existentes usando
json.dumps(json.loads(config_json), ensure_ascii=False, separators=(',',':'))
antes de hashear. Esto alinea el hash de la BD con el hash del envelope firmado.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import json
import hashlib

revision: str = '023_normalize_config_hash'
down_revision: Union[str, None] = '022_add_audit_actions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Recalcular config_hash con JSON normalizado."""
    conn = op.get_bind()

    # Leer todos los action_configs
    results = conn.execute(
        sa.text("SELECT id, config_json FROM action_configs")
    ).fetchall()

    for row in results:
        config_id = row[0]
        config_json = row[1]

        if not config_json:
            continue

        try:
            # Normalizar: parse + re-serialize compacto
            config_obj = json.loads(config_json)
            normalized = json.dumps(config_obj, ensure_ascii=False, separators=(',', ':'))

            # Calcular nuevo hash (primeros 8 chars del SHA256 hex)
            new_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:8]

            # Actualizar en BD
            conn.execute(
                sa.text("UPDATE action_configs SET config_hash = :hash WHERE id = :id"),
                {"hash": new_hash, "id": config_id}
            )
        except (json.JSONDecodeError, Exception):
            # Si el JSON es inválido, dejarlo como está
            pass


def downgrade() -> None:
    """Recalcular config_hash con formato original (sin normalizar)."""
    conn = op.get_bind()

    results = conn.execute(
        sa.text("SELECT id, config_json FROM action_configs")
    ).fetchall()

    for row in results:
        config_id = row[0]
        config_json = row[1]

        if not config_json:
            continue

        try:
            # Hash original: SHA256 del config_json tal cual
            old_hash = hashlib.sha256(config_json.encode('utf-8')).hexdigest()[:8]

            conn.execute(
                sa.text("UPDATE action_configs SET config_hash = :hash WHERE id = :id"),
                {"hash": old_hash, "id": config_id}
            )
        except Exception:
            pass
