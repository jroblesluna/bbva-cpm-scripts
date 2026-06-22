"""Agregar campos de geolocalización a vlans y google_maps_api_key a organizations

Revision ID: 020_add_vlan_geolocation
Revises: 019_add_ws_config_version
Create Date: 2026-06-20 12:00:00.000000

Añade campos para georreferenciación de VLANs: address, latitude, longitude,
place_id y location_image_url. También agrega google_maps_api_key a organizations
para configurar la API Key de Google Maps por organización.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '020_add_vlan_geolocation'
down_revision: Union[str, None] = '019_add_ws_config_version'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agregar campos de geolocalización a vlans y API key de Google Maps a organizations."""
    # Campos de geolocalización en vlans
    op.add_column('vlans', sa.Column('address', sa.String(500), nullable=True))
    op.add_column('vlans', sa.Column('latitude', sa.Float, nullable=True))
    op.add_column('vlans', sa.Column('longitude', sa.Float, nullable=True))
    op.add_column('vlans', sa.Column('place_id', sa.String(100), nullable=True))
    op.add_column('vlans', sa.Column('location_image_url', sa.String(500), nullable=True))

    # API Key de Google Maps en organizations
    op.add_column('organizations', sa.Column('google_maps_api_key', sa.String(200), nullable=True))


def downgrade() -> None:
    """Eliminar campos de geolocalización de vlans y google_maps_api_key de organizations."""
    op.drop_column('vlans', 'location_image_url')
    op.drop_column('vlans', 'place_id')
    op.drop_column('vlans', 'longitude')
    op.drop_column('vlans', 'latitude')
    op.drop_column('vlans', 'address')
    op.drop_column('organizations', 'google_maps_api_key')
