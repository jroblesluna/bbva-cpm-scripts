"""
Schemas Pydantic para Remote View.

Define el schema de configuración RemoteViewConfig con los 13 campos
requeridos y validación de rangos para la funcionalidad de vista remota.
"""

from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator


# Resoluciones válidas para captura
VALID_RESOLUTIONS = ["1920x1080", "1280x720", "854x480", "640x360"]

# Modos válidos de remote view
VALID_MODES = ["screenshot", "stream", "interactive"]

# Modos válidos de calidad
VALID_QUALITY_MODES = ["auto", "manual"]


class RemoteViewConfig(BaseModel):
    """
    Configuración de vista remota por organización.

    Contiene los 13 campos de configuración del feature Remote View.
    Cada campo tiene valores por defecto seguros (feature deshabilitado,
    modos restrictivos, consent requerido).

    **Validates: Requirements 1.1, 1.2, 12.7**
    """

    # 1. Habilita/deshabilita el feature completo
    enabled: bool = Field(default=False, description="Habilita/deshabilita el feature de vista remota")

    # 2. Modos disponibles para la organización
    modes_allowed: list[str] = Field(
        default=["screenshot"],
        description="Modos disponibles: screenshot, stream, interactive"
    )

    # 3. Modo inicial al conectar
    default_mode: str = Field(
        default="screenshot",
        description="Modo inicial al iniciar una sesión"
    )

    # 4. Permitir control remoto (mouse/teclado) en Interactive mode
    remote_control_enabled: bool = Field(
        default=False,
        description="Permitir mouse/teclado en Interactive mode"
    )

    # 5. Compartir clipboard bidireccional
    clipboard_sharing_enabled: bool = Field(
        default=False,
        description="Compartir clipboard bidireccional entre admin y workstation"
    )

    # 6. Mostrar popup de consentimiento al usuario de la workstation
    require_user_consent: bool = Field(
        default=True,
        description="Mostrar popup de consentimiento al usuario de la workstation"
    )

    # 7. Máximo de sesiones simultáneas por admin/operador (0=ilimitado)
    max_concurrent_sessions: int = Field(
        default=4,
        ge=0,
        le=50,
        description="Máx sesiones simultáneas por admin/operador (0=ilimitado)"
    )

    # 8. Timeout por inactividad del admin (minutos)
    session_timeout_minutes: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Timeout por inactividad del admin (minutos, 1-60)"
    )

    # 9. Modo de calidad: auto o manual
    quality_mode: str = Field(
        default="auto",
        description="Modo de calidad: auto (ajuste por RTT) o manual (valores fijos)"
    )

    # 10. Resolución de captura cuando quality_mode=manual
    capture_resolution: str = Field(
        default="1280x720",
        description="Resolución de captura (ej: 1920x1080, 1280x720, 854x480, 640x360)"
    )

    # 11. Porcentaje de calidad JPEG/bitrate cuando quality_mode=manual (1-100)
    compression_quality: int = Field(
        default=70,
        ge=1,
        le=100,
        description="Calidad de compresión JPEG (1-100%)"
    )

    # 12. Reducir resolución de envío al tamaño del viewport del admin
    viewport_adaptive_downscale: bool = Field(
        default=True,
        description="Reducir resolución al tamaño del viewport del admin"
    )

    # 13. FPS máximo para Stream/Interactive mode (1-10)
    stream_max_fps: int = Field(
        default=5,
        ge=1,
        le=10,
        description="FPS máximo para Stream/Interactive mode (1-10)"
    )

    @field_validator("modes_allowed")
    @classmethod
    def validate_modes_allowed(cls, v: list[str]) -> list[str]:
        """Valida que los modos sean válidos y no esté vacía la lista."""
        if not v:
            raise ValueError("modes_allowed no puede estar vacío")
        invalid = [m for m in v if m not in VALID_MODES]
        if invalid:
            raise ValueError(
                f"Modos inválidos: {invalid}. Válidos: {VALID_MODES}"
            )
        # Eliminar duplicados manteniendo orden
        seen = set()
        result = []
        for mode in v:
            if mode not in seen:
                seen.add(mode)
                result.append(mode)
        return result

    @field_validator("default_mode")
    @classmethod
    def validate_default_mode(cls, v: str) -> str:
        """Valida que el modo por defecto sea un modo válido."""
        if v not in VALID_MODES:
            raise ValueError(
                f"default_mode inválido: '{v}'. Válidos: {VALID_MODES}"
            )
        return v

    @field_validator("quality_mode")
    @classmethod
    def validate_quality_mode(cls, v: str) -> str:
        """Valida que quality_mode sea auto o manual."""
        if v not in VALID_QUALITY_MODES:
            raise ValueError(
                f"quality_mode inválido: '{v}'. Válidos: {VALID_QUALITY_MODES}"
            )
        return v

    @field_validator("capture_resolution")
    @classmethod
    def validate_capture_resolution(cls, v: str) -> str:
        """Valida que la resolución sea una de las permitidas."""
        if v not in VALID_RESOLUTIONS:
            raise ValueError(
                f"capture_resolution inválida: '{v}'. Válidas: {VALID_RESOLUTIONS}"
            )
        return v

    @model_validator(mode="after")
    def validate_default_mode_in_allowed(self) -> "RemoteViewConfig":
        """Valida que default_mode esté dentro de modes_allowed."""
        if self.default_mode not in self.modes_allowed:
            raise ValueError(
                f"default_mode '{self.default_mode}' no está en modes_allowed: {self.modes_allowed}"
            )
        return self


class RemoteViewConfigUpdate(BaseModel):
    """
    Schema para actualización parcial de configuración remote_view.

    Todos los campos son opcionales para permitir PATCH parcial.
    Las mismas validaciones de rango se aplican a los campos proporcionados.
    """

    enabled: Optional[bool] = None
    modes_allowed: Optional[list[str]] = None
    default_mode: Optional[str] = None
    remote_control_enabled: Optional[bool] = None
    clipboard_sharing_enabled: Optional[bool] = None
    require_user_consent: Optional[bool] = None
    max_concurrent_sessions: Optional[int] = Field(default=None, ge=0, le=50)
    session_timeout_minutes: Optional[int] = Field(default=None, ge=1, le=60)
    quality_mode: Optional[str] = None
    capture_resolution: Optional[str] = None
    compression_quality: Optional[int] = Field(default=None, ge=1, le=100)
    viewport_adaptive_downscale: Optional[bool] = None
    stream_max_fps: Optional[int] = Field(default=None, ge=1, le=10)

    @field_validator("modes_allowed")
    @classmethod
    def validate_modes_allowed(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        """Valida que los modos sean válidos."""
        if v is None:
            return v
        if not v:
            raise ValueError("modes_allowed no puede estar vacío")
        invalid = [m for m in v if m not in VALID_MODES]
        if invalid:
            raise ValueError(
                f"Modos inválidos: {invalid}. Válidos: {VALID_MODES}"
            )
        # Eliminar duplicados manteniendo orden
        seen = set()
        result = []
        for mode in v:
            if mode not in seen:
                seen.add(mode)
                result.append(mode)
        return result

    @field_validator("default_mode")
    @classmethod
    def validate_default_mode(cls, v: Optional[str]) -> Optional[str]:
        """Valida que el modo por defecto sea válido."""
        if v is None:
            return v
        if v not in VALID_MODES:
            raise ValueError(
                f"default_mode inválido: '{v}'. Válidos: {VALID_MODES}"
            )
        return v

    @field_validator("quality_mode")
    @classmethod
    def validate_quality_mode(cls, v: Optional[str]) -> Optional[str]:
        """Valida que quality_mode sea auto o manual."""
        if v is None:
            return v
        if v not in VALID_QUALITY_MODES:
            raise ValueError(
                f"quality_mode inválido: '{v}'. Válidos: {VALID_QUALITY_MODES}"
            )
        return v

    @field_validator("capture_resolution")
    @classmethod
    def validate_capture_resolution(cls, v: Optional[str]) -> Optional[str]:
        """Valida que la resolución sea válida."""
        if v is None:
            return v
        if v not in VALID_RESOLUTIONS:
            raise ValueError(
                f"capture_resolution inválida: '{v}'. Válidas: {VALID_RESOLUTIONS}"
            )
        return v
