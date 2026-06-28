"""
Property test para la decisión de descarga basada en diff.

Verifica que para cualquier par (local_state, push_message), la decisión
de descarga es SIEMPRE correcta:
- Config: descargar si y solo si push.config_hash != local.config_hash (case-insensitive)
- MSI: descargar si y solo si push.msi_version != local.msi_version
- Cert: descargar si y solo si push.cert_version > local.cert_version

Simula la lógica del cliente C# (PushMessageHandler) en Python con Hypothesis.

Feature: push-based-distribution, Property 5: Diff-based download decision

**Validates: Requirements 2.2, 2.3, 2.4, 3.2, 3.3, 3.4, 4.2, 4.3, 5.2, 6.1**
"""

from dataclasses import dataclass

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


# === Modelos que simulan el estado local y mensajes push ===


@dataclass
class LocalConfigState:
    """Estado local de configuración de la workstation."""

    config_hash: str | None  # None = primera vez (sin config local)


@dataclass
class LocalMsiState:
    """Estado local de MSI de la workstation."""

    msi_version: str | None  # None = primera vez


@dataclass
class LocalCertState:
    """Estado local de certificado de la workstation."""

    cert_version: int  # 0 = sin certificado local


@dataclass
class ConfigPushMessage:
    """Mensaje push de tipo action_config_changed."""

    config_hash: str
    download_url: str


@dataclass
class MsiPushMessage:
    """Mensaje push de tipo check_update."""

    version: str
    download_url: str
    file_size: int


@dataclass
class CertPushMessage:
    """Mensaje push de tipo cert_rotated."""

    cert_version: int
    cert_url: str


# === Lógica de decisión del cliente (simula PushMessageHandler.cs) ===


def should_download_config(
    local: LocalConfigState, push: ConfigPushMessage
) -> bool:
    """
    Decide si descargar una config basado en comparación de hashes.

    Replica la lógica de HandleConfigPush en C#:
    - Si local.config_hash es None o vacío → siempre descargar (primera vez)
    - Si push.config_hash == local.config_hash (case-insensitive) → NO descargar
    - Si difieren → descargar

    Args:
        local: Estado local de configuración.
        push: Mensaje push recibido.

    Returns:
        True si se debe descargar, False si no.
    """
    if not local.config_hash:
        # Primera vez: siempre descargar
        return True

    # Comparación case-insensitive (replica StringComparison.OrdinalIgnoreCase)
    return local.config_hash.lower() != push.config_hash.lower()


def should_download_msi(local: LocalMsiState, push: MsiPushMessage) -> bool:
    """
    Decide si descargar un MSI basado en comparación de versiones.

    Replica la lógica implícita del cliente C#:
    - Si local.msi_version es None → siempre descargar (primera vez)
    - Si push.version == local.msi_version → NO descargar
    - Si difieren → descargar

    Args:
        local: Estado local de MSI.
        push: Mensaje push recibido.

    Returns:
        True si se debe descargar, False si no.
    """
    if not local.msi_version:
        # Primera vez: siempre descargar
        return True

    return local.msi_version != push.version


def should_download_cert(local: LocalCertState, push: CertPushMessage) -> bool:
    """
    Decide si descargar un certificado basado en comparación de versiones.

    Replica la lógica de HandleCertPush en C#:
    - Si push.cert_version > local.cert_version → descargar
    - Si push.cert_version <= local.cert_version → NO descargar

    Args:
        local: Estado local de certificado.
        push: Mensaje push recibido.

    Returns:
        True si se debe descargar, False si no.
    """
    return push.cert_version > local.cert_version


# === Estrategias de generación de datos ===

# Hashes SHA256 cortos (8 chars hex) — formato real del sistema
_hex_hash = st.text(
    alphabet="0123456789abcdef", min_size=8, max_size=8
)

# Versiones semánticas (formato usado por MSI)
_semver = st.builds(
    lambda major, minor, patch: f"{major}.{minor}.{patch}",
    major=st.integers(min_value=0, max_value=99),
    minor=st.integers(min_value=0, max_value=99),
    patch=st.integers(min_value=0, max_value=99),
)

# URLs S3 de descarga (simuladas)
_s3_url = st.builds(
    lambda key: f"https://bucket.s3.us-east-1.amazonaws.com/{key}",
    key=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789/-.",
        min_size=10,
        max_size=60,
    ),
)

# Estado local de config: puede ser None (primera vez) o un hash válido
_local_config_state = st.builds(
    LocalConfigState,
    config_hash=st.one_of(st.none(), st.just(""), _hex_hash),
)

# Mensaje push de config: siempre tiene hash válido y URL
_config_push_message = st.builds(
    ConfigPushMessage,
    config_hash=_hex_hash,
    download_url=_s3_url,
)

# Estado local de MSI: puede ser None (primera vez) o una versión válida
_local_msi_state = st.builds(
    LocalMsiState,
    msi_version=st.one_of(st.none(), _semver),
)

# Mensaje push de MSI: siempre tiene versión válida
_msi_push_message = st.builds(
    MsiPushMessage,
    version=_semver,
    download_url=_s3_url,
    file_size=st.integers(min_value=1024, max_value=100_000_000),
)

# Estado local de cert: versión >= 0
_local_cert_state = st.builds(
    LocalCertState,
    cert_version=st.integers(min_value=0, max_value=100),
)

# Mensaje push de cert: versión >= 1 (siempre hay al menos un cert)
_cert_push_message = st.builds(
    CertPushMessage,
    cert_version=st.integers(min_value=0, max_value=100),
    cert_url=_s3_url,
)


# === PROPERTY TESTS ===


class TestDiffBasedDownloadDecision:
    """
    Property 5: Diff-based download decision.

    Para cualquier par (local_state, push_message), la decisión de descarga
    es SIEMPRE correcta:
    - Config: download iff push.config_hash != local.config_hash
    - MSI: download iff push.msi_version != local.msi_version
    - Cert: download iff push.cert_version > local.cert_version

    Feature: push-based-distribution, Property 5: Diff-based download decision

    **Validates: Requirements 2.2, 2.3, 2.4, 3.2, 3.3, 3.4, 4.2, 4.3, 5.2, 6.1**
    """

    # ── Config decision tests ────────────────────────────────────────────

    @given(local=_local_config_state, push=_config_push_message)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_config_download_iff_hash_differs(
        self, local: LocalConfigState, push: ConfigPushMessage
    ):
        """
        Para cualquier par (local_config, config_push), la decisión de descarga
        es True si y solo si los hashes difieren (o local es None/vacío).

        **Validates: Requirements 2.2, 2.3, 2.4**
        """
        decision = should_download_config(local, push)

        if not local.config_hash:
            # Edge case: primera vez (sin hash local) → siempre descargar
            assert decision is True, (
                f"Con config_hash local=None/vacío, debería descargar siempre. "
                f"Push hash={push.config_hash}"
            )
        elif local.config_hash.lower() == push.config_hash.lower():
            # Hash coincide (case-insensitive) → NO descargar
            assert decision is False, (
                f"Con hashes iguales (case-insensitive), NO debería descargar. "
                f"Local={local.config_hash}, Push={push.config_hash}"
            )
        else:
            # Hash difiere → descargar
            assert decision is True, (
                f"Con hashes diferentes, debería descargar. "
                f"Local={local.config_hash}, Push={push.config_hash}"
            )

    @given(hash_val=_hex_hash, case_variant=st.sampled_from(["upper", "lower", "mixed"]))
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_config_comparison_is_case_insensitive(
        self, hash_val: str, case_variant: str
    ):
        """
        Verifica que la comparación de config_hash es case-insensitive.
        El mismo hash en diferente caso NO debe triggerear descarga.

        **Validates: Requirements 2.2, 2.4**
        """
        # Crear variante del mismo hash con diferente case
        if case_variant == "upper":
            push_hash = hash_val.upper()
        elif case_variant == "lower":
            push_hash = hash_val.lower()
        else:
            # Mixed case: alternar mayúsculas y minúsculas
            push_hash = "".join(
                c.upper() if i % 2 == 0 else c.lower()
                for i, c in enumerate(hash_val)
            )

        local = LocalConfigState(config_hash=hash_val)
        push = ConfigPushMessage(config_hash=push_hash, download_url="https://example.com/file")

        decision = should_download_config(local, push)

        assert decision is False, (
            f"Hashes iguales con diferente case NO deben triggerear descarga. "
            f"Local={hash_val}, Push={push_hash}, Case variant={case_variant}"
        )

    # ── MSI decision tests ────────────────────────────────────────────────

    @given(local=_local_msi_state, push=_msi_push_message)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_msi_download_iff_version_differs(
        self, local: LocalMsiState, push: MsiPushMessage
    ):
        """
        Para cualquier par (local_msi, msi_push), la decisión de descarga
        es True si y solo si las versiones difieren (o local es None).

        **Validates: Requirements 3.2, 3.3, 3.4**
        """
        decision = should_download_msi(local, push)

        if not local.msi_version:
            # Edge case: primera vez (sin versión local) → siempre descargar
            assert decision is True, (
                f"Con msi_version local=None, debería descargar siempre. "
                f"Push version={push.version}"
            )
        elif local.msi_version == push.version:
            # Versión coincide → NO descargar
            assert decision is False, (
                f"Con versiones iguales, NO debería descargar. "
                f"Local={local.msi_version}, Push={push.version}"
            )
        else:
            # Versión difiere → descargar
            assert decision is True, (
                f"Con versiones diferentes, debería descargar. "
                f"Local={local.msi_version}, Push={push.version}"
            )

    # ── Cert decision tests ──────────────────────────────────────────────

    @given(local=_local_cert_state, push=_cert_push_message)
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_cert_download_iff_remote_version_greater(
        self, local: LocalCertState, push: CertPushMessage
    ):
        """
        Para cualquier par (local_cert, cert_push), la decisión de descarga
        es True si y solo si push.cert_version > local.cert_version.

        **Validates: Requirements 4.2, 4.3**
        """
        decision = should_download_cert(local, push)

        if push.cert_version > local.cert_version:
            # Versión remota mayor → descargar
            assert decision is True, (
                f"Con cert_version remoto > local, debería descargar. "
                f"Local={local.cert_version}, Push={push.cert_version}"
            )
        else:
            # Versión remota igual o menor → NO descargar
            assert decision is False, (
                f"Con cert_version remoto <= local, NO debería descargar. "
                f"Local={local.cert_version}, Push={push.cert_version}"
            )

    # ── Registration enrichment decision test ─────────────────────────────

    @given(
        local_config=_local_config_state,
        local_msi=_local_msi_state,
        local_cert=_local_cert_state,
        push_config_hash=_hex_hash,
        push_msi_version=_semver,
        push_cert_version=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
    def test_registration_enrichment_download_decisions_are_independent(
        self,
        local_config: LocalConfigState,
        local_msi: LocalMsiState,
        local_cert: LocalCertState,
        push_config_hash: str,
        push_msi_version: str,
        push_cert_version: int,
    ):
        """
        Al recibir Registration_Enrichment con estado completo, cada recurso
        (config, MSI, cert) tiene una decisión de descarga INDEPENDIENTE.
        La decisión de un recurso no afecta a los demás.

        **Validates: Requirements 5.2, 6.1**
        """
        config_push = ConfigPushMessage(
            config_hash=push_config_hash, download_url="https://example.com/config"
        )
        msi_push = MsiPushMessage(
            version=push_msi_version, download_url="https://example.com/msi", file_size=1024
        )
        cert_push = CertPushMessage(
            cert_version=push_cert_version, cert_url="https://example.com/cert"
        )

        # Cada decisión se toma independientemente
        config_decision = should_download_config(local_config, config_push)
        msi_decision = should_download_msi(local_msi, msi_push)
        cert_decision = should_download_cert(local_cert, cert_push)

        # Verificar que las decisiones son coherentes con sus propias reglas
        # Config: descarga iff hashes difieren o local es None/vacío
        if not local_config.config_hash:
            assert config_decision is True
        elif local_config.config_hash.lower() == push_config_hash.lower():
            assert config_decision is False
        else:
            assert config_decision is True

        # MSI: descarga iff versiones difieren o local es None
        if not local_msi.msi_version:
            assert msi_decision is True
        elif local_msi.msi_version == push_msi_version:
            assert msi_decision is False
        else:
            assert msi_decision is True

        # Cert: descarga iff versión remota es mayor
        if push_cert_version > local_cert.cert_version:
            assert cert_decision is True
        else:
            assert cert_decision is False
