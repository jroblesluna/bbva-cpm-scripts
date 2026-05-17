"""
Schemas Pydantic para el módulo de actualizaciones automáticas.

Define los schemas de response para el endpoint de verificación
de actualización disponible (GET /updates/check).
"""

from pydantic import BaseModel, Field


class UpdateCheckResponse(BaseModel):
    """
    Respuesta del endpoint GET /api/v1/updates/check.

    Contiene la información de la versión disponible del MSI en S3,
    el estado del flag de auto-actualización de la organización,
    y metadata adicional del build.
    """
    version: str = Field(..., description="Versión semántica del MSI disponible")
    auto_update_enabled: bool = Field(
        ..., description="Flag de auto-actualización de la organización"
    )
    file_size: int = Field(..., description="Tamaño del archivo MSI en bytes")
    build_date: str = Field(..., description="Fecha de compilación del MSI (ISO 8601)")
    commit_hash: str = Field(..., description="Hash corto del commit de Git")
