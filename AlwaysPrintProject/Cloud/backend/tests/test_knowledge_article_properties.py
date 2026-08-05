"""
Property tests para validación de campos de KnowledgeArticle.

Verifica que la validación Pydantic del schema KnowledgeArticleCreate
acepta/rechaza correctamente según los límites definidos para cada campo.

Feature: knowledge-base-library, Property 2: Validación de longitudes de campos

**Validates: Requirements 8.1, 8.2, 8.3, 8.4**
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from pydantic import ValidationError

from app.schemas.knowledge_article import KnowledgeArticleCreate


# === Estrategias de generación ===

# Caracteres válidos para generar texto (excluir nulos y surrogates problemáticos)
_printable_chars = st.characters(
    whitelist_categories=("L", "N", "P", "S", "Z"),
    blacklist_characters="\x00",
)

# Título válido: 3-200 caracteres (no solo whitespace para que content no falle)
_valid_title = st.text(
    alphabet=_printable_chars, min_size=3, max_size=200
).filter(lambda s: len(s.strip()) > 0)

# Descripción válida: 10-500 caracteres
_valid_description = st.text(
    alphabet=_printable_chars, min_size=10, max_size=500
).filter(lambda s: len(s.strip()) > 0)

# Contenido válido: 1-500,000 caracteres, no solo whitespace
# Limitamos a 1000 para evitar lentitud en tests
_valid_content = st.text(
    alphabet=_printable_chars, min_size=1, max_size=1000
).filter(lambda s: len(s.strip()) > 0)


# === PROPERTY 2: VALIDACIÓN DE LONGITUDES DE CAMPOS ===


class TestValidacionLongitudesCampos:
    """
    Property 2: Validación de longitudes de campos.

    Para cualquier string de título con longitud < 3 o > 200 caracteres,
    o descripción con longitud < 10 o > 500 caracteres, o contenido
    vacío/solo whitespace o > 500,000 caracteres, la creación debe ser
    rechazada con ValidationError.

    Feature: knowledge-base-library, Property 2: Validación de longitudes de campos

    **Validates: Requirements 8.1, 8.2, 8.3, 8.4**
    """

    # --- Tests de aceptación: strings dentro de los límites ---

    @given(
        title=_valid_title,
        description=_valid_description,
        content=_valid_content,
    )
    @settings(max_examples=100)
    def test_campos_dentro_de_limites_son_aceptados(
        self, title: str, description: str, content: str
    ):
        """
        Para cualquier combinación de título (3-200 chars), descripción (10-500 chars)
        y contenido (1-500,000 chars, no solo whitespace), el schema debe aceptar
        la entrada sin error.

        **Validates: Requirements 8.1, 8.2, 8.3, 8.4**
        """
        # El schema no debe lanzar ValidationError
        article = KnowledgeArticleCreate(
            title=title,
            description=description,
            content=content,
        )
        assert article.title == title
        assert article.description == description
        assert article.content == content

    # --- Tests de rechazo: título fuera de límites ---

    @given(
        title=st.text(alphabet=_printable_chars, min_size=0, max_size=2),
        description=_valid_description,
        content=_valid_content,
    )
    @settings(max_examples=100)
    def test_titulo_demasiado_corto_es_rechazado(
        self, title: str, description: str, content: str
    ):
        """
        Para cualquier título con longitud < 3 caracteres, el schema debe
        rechazar con ValidationError.

        **Validates: Requirements 8.1**
        """
        # Asegurar que el título tiene menos de 3 caracteres
        assume(len(title) < 3)

        with pytest.raises(ValidationError) as exc_info:
            KnowledgeArticleCreate(
                title=title,
                description=description,
                content=content,
            )
        # Verificar que el error menciona el campo title
        errors = exc_info.value.errors()
        field_names = [e["loc"][0] for e in errors]
        assert "title" in field_names, (
            f"ValidationError esperado en campo 'title', "
            f"pero los campos con error son: {field_names}"
        )

    @given(
        title=st.text(alphabet=_printable_chars, min_size=201, max_size=300),
        description=_valid_description,
        content=_valid_content,
    )
    @settings(max_examples=100)
    def test_titulo_demasiado_largo_es_rechazado(
        self, title: str, description: str, content: str
    ):
        """
        Para cualquier título con longitud > 200 caracteres, el schema debe
        rechazar con ValidationError.

        **Validates: Requirements 8.1**
        """
        with pytest.raises(ValidationError) as exc_info:
            KnowledgeArticleCreate(
                title=title,
                description=description,
                content=content,
            )
        errors = exc_info.value.errors()
        field_names = [e["loc"][0] for e in errors]
        assert "title" in field_names, (
            f"ValidationError esperado en campo 'title', "
            f"pero los campos con error son: {field_names}"
        )

    # --- Tests de rechazo: descripción fuera de límites ---

    @given(
        title=_valid_title,
        description=st.text(alphabet=_printable_chars, min_size=0, max_size=9),
        content=_valid_content,
    )
    @settings(max_examples=100)
    def test_descripcion_demasiado_corta_es_rechazada(
        self, title: str, description: str, content: str
    ):
        """
        Para cualquier descripción con longitud < 10 caracteres, el schema debe
        rechazar con ValidationError.

        **Validates: Requirements 8.2**
        """
        assume(len(description) < 10)

        with pytest.raises(ValidationError) as exc_info:
            KnowledgeArticleCreate(
                title=title,
                description=description,
                content=content,
            )
        errors = exc_info.value.errors()
        field_names = [e["loc"][0] for e in errors]
        assert "description" in field_names, (
            f"ValidationError esperado en campo 'description', "
            f"pero los campos con error son: {field_names}"
        )

    @given(
        title=_valid_title,
        description=st.text(alphabet=_printable_chars, min_size=501, max_size=600),
        content=_valid_content,
    )
    @settings(max_examples=100)
    def test_descripcion_demasiado_larga_es_rechazada(
        self, title: str, description: str, content: str
    ):
        """
        Para cualquier descripción con longitud > 500 caracteres, el schema debe
        rechazar con ValidationError.

        **Validates: Requirements 8.2**
        """
        with pytest.raises(ValidationError) as exc_info:
            KnowledgeArticleCreate(
                title=title,
                description=description,
                content=content,
            )
        errors = exc_info.value.errors()
        field_names = [e["loc"][0] for e in errors]
        assert "description" in field_names, (
            f"ValidationError esperado en campo 'description', "
            f"pero los campos con error son: {field_names}"
        )

    # --- Tests de rechazo: contenido fuera de límites ---

    @given(
        title=_valid_title,
        description=_valid_description,
        whitespace_content=st.text(
            alphabet=st.sampled_from([" ", "\t", "\n", "\r"]),
            min_size=1,
            max_size=100,
        ),
    )
    @settings(max_examples=100)
    def test_contenido_solo_whitespace_es_rechazado(
        self, title: str, description: str, whitespace_content: str
    ):
        """
        Para cualquier contenido que sea solo espacios en blanco (espacios, tabs,
        newlines), el schema debe rechazar con ValidationError.

        **Validates: Requirements 8.3**
        """
        with pytest.raises(ValidationError) as exc_info:
            KnowledgeArticleCreate(
                title=title,
                description=description,
                content=whitespace_content,
            )
        errors = exc_info.value.errors()
        field_names = [e["loc"][0] for e in errors]
        assert "content" in field_names, (
            f"ValidationError esperado en campo 'content', "
            f"pero los campos con error son: {field_names}"
        )

    @given(
        title=_valid_title,
        description=_valid_description,
        # Generar contenido que excede 500,000 caracteres
        extra_length=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=100)
    def test_contenido_demasiado_largo_es_rechazado(
        self, title: str, description: str, extra_length: int
    ):
        """
        Para cualquier contenido con longitud > 500,000 caracteres, el schema debe
        rechazar con ValidationError.

        **Validates: Requirements 8.3**
        """
        # Generar un contenido que exceda el límite (500,000 + extra)
        long_content = "a" * (500_000 + extra_length)

        with pytest.raises(ValidationError) as exc_info:
            KnowledgeArticleCreate(
                title=title,
                description=description,
                content=long_content,
            )
        errors = exc_info.value.errors()
        field_names = [e["loc"][0] for e in errors]
        assert "content" in field_names, (
            f"ValidationError esperado en campo 'content', "
            f"pero los campos con error son: {field_names}"
        )


# === PROPERTY 6: LÍMITE DE ARTÍCULOS POR ORGANIZACIÓN ===

import uuid
from sqlalchemy import create_engine, Column, String, Text, DateTime, ForeignKey, Index, Table
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool

from app.services.knowledge_article import KnowledgeArticleService, MAX_ARTICLES_PER_ORG

# Base local para tests con SQLite in-memory (evita conflicto con la app)
_TestBase = declarative_base()

# Modelo mínimo de Organization para satisfacer FK
class _TestOrganization(_TestBase):
    __tablename__ = "organizations"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False, default="Test Org")


# Tabla de asociación replicada para el scope de test
_test_profile_knowledge_articles = Table(
    "profile_knowledge_articles",
    _TestBase.metadata,
    Column("profile_id", String(36), ForeignKey("debugging_profiles.id", ondelete="CASCADE"), primary_key=True),
    Column("article_id", String(36), ForeignKey("knowledge_articles.id", ondelete="CASCADE"), primary_key=True),
)


# Modelo mínimo de DebuggingProfile para satisfacer FK
class _TestDebuggingProfile(_TestBase):
    __tablename__ = "debugging_profiles"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    name = Column(String(200), nullable=False, default="Test Profile")


# Modelo de KnowledgeArticle compatible con SQLite para tests
class _TestKnowledgeArticle(_TestBase):
    __tablename__ = "knowledge_articles"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_knowledge_articles_org", "organization_id"),
    )


class TestLimiteArticulosPorOrganizacion:
    """
    Property 6: Límite de artículos por organización.

    Para cualquier organización con exactamente 50 artículos, un intento de crear
    el artículo 51 debe ser rechazado con ValueError. Para N <= 50 artículos,
    la creación debe ser exitosa.

    Feature: knowledge-base-library, Property 6: Límite de artículos por organización

    **Validates: Requirements 8.5**
    """

    def _create_db_session(self):
        """Crea una sesión con BD SQLite in-memory y tablas necesarias."""
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        _TestBase.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        return Session()

    def _create_org(self, db) -> str:
        """Crea una organización de prueba y retorna su ID."""
        org_id = str(uuid.uuid4())
        org = _TestOrganization(id=org_id, name="Test Org")
        db.add(org)
        db.commit()
        return org_id

    @given(n_articles=st.integers(min_value=45, max_value=55))
    @settings(max_examples=100)
    def test_limite_50_articulos_por_organizacion(self, n_articles: int):
        """
        Para cualquier N ∈ [45..55], la creación de artículos 1..50 debe ser exitosa,
        y la creación del artículo 51+ debe lanzar ValueError con mensaje descriptivo.

        **Validates: Requirements 8.5**
        """
        # Preparar BD in-memory fresca para cada ejemplo
        db = self._create_db_session()
        org_id = self._create_org(db)
        service = KnowledgeArticleService()

        created_count = 0
        error_raised = False
        error_message = ""

        try:
            for i in range(n_articles):
                try:
                    service.create_article(
                        db=db,
                        org_id=org_id,
                        title=f"Artículo de prueba #{i + 1}",
                        description=f"Descripción del artículo de prueba número {i + 1}",
                        content=f"Contenido del artículo #{i + 1}",
                    )
                    created_count += 1
                except ValueError as e:
                    error_raised = True
                    error_message = str(e)
                    break
        finally:
            db.close()

        # Verificar que se crearon exactamente min(N, 50) artículos
        expected_created = min(n_articles, MAX_ARTICLES_PER_ORG)
        assert created_count == expected_created, (
            f"Se esperaban {expected_created} artículos creados, "
            f"pero se crearon {created_count} (N={n_articles})"
        )

        # Si N > 50, debe haberse lanzado ValueError
        if n_articles > MAX_ARTICLES_PER_ORG:
            assert error_raised, (
                f"Con N={n_articles} artículos, se esperaba ValueError al exceder "
                f"el límite de {MAX_ARTICLES_PER_ORG}, pero no se lanzó"
            )
            assert "máximo 50" in error_message.lower() or "límite" in error_message.lower(), (
                f"El mensaje de error no es descriptivo: '{error_message}'"
            )
        else:
            # Si N <= 50, no debe haber error
            assert not error_raised, (
                f"Con N={n_articles} artículos (dentro del límite), "
                f"se lanzó ValueError inesperado: '{error_message}'"
            )


# === PROPERTY 4: IDEMPOTENCIA DE ASOCIACIONES DUPLICADAS ===

import uuid
from uuid import UUID
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.knowledge_article import KnowledgeArticle, profile_knowledge_articles
from app.models.debugging import DebuggingProfile
from app.models.organization import Organization, GUID
from app.services.knowledge_article import KnowledgeArticleService


class TestIdempotenciaAsociaciones:
    """
    Property 4: Idempotencia de asociaciones duplicadas.

    Para cualquier par (profile_id, article_id) que ya existe en
    `profile_knowledge_articles`, un intento de re-asociación debe
    completarse sin error y sin crear duplicados (la cantidad de
    registros no cambia).

    Feature: knowledge-base-library, Property 4: Idempotencia de asociaciones duplicadas

    **Validates: Requirements 5.5**
    """

    def _create_db_session(self):
        """Crea una sesión de BD SQLite in-memory con el esquema completo."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        # Habilitar foreign keys en SQLite
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        return TestSession()

    def _setup_fixtures(self, db):
        """
        Crea una organización, un perfil de debugging y 5 artículos de conocimiento.
        Retorna (org, profile, article_ids).
        """
        # Crear organización
        org_id = uuid.uuid4()
        org = Organization(id=org_id, name=f"Org-{org_id}")
        db.add(org)
        db.flush()

        # Crear perfil de debugging
        profile = DebuggingProfile(
            id=uuid.uuid4(),
            organization_id=org_id,
            name="Perfil Test",
            description="Perfil para testing de idempotencia",
            confirmation_message="Confirmar inicio de debugging",
        )
        db.add(profile)
        db.flush()

        # Crear 5 artículos de conocimiento
        article_ids = []
        for i in range(5):
            article = KnowledgeArticle(
                id=uuid.uuid4(),
                organization_id=org_id,
                title=f"Artículo {i+1}",
                description=f"Descripción del artículo número {i+1} para testing",
                content=f"Contenido completo del artículo {i+1} en formato Markdown.",
            )
            db.add(article)
            article_ids.append(article.id)
        db.flush()

        return org, profile, article_ids

    @given(
        # Generar un subconjunto aleatorio de índices (0-4) con posibles duplicados
        indices=st.lists(
            st.integers(min_value=0, max_value=4),
            min_size=1,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_asociacion_duplicada_no_crea_registros_extra(self, indices: list):
        """
        Para cualquier subconjunto de artículos (con posibles duplicados en la lista),
        asociarlos una vez y luego asociar la misma lista de nuevo debe ser idempotente:
        - No lanza error
        - La cantidad de asociaciones en la BD no cambia tras la segunda llamada

        **Validates: Requirements 5.5**
        """
        # Configurar BD y fixtures frescos para cada ejemplo
        db = self._create_db_session()
        try:
            org, profile, all_article_ids = self._setup_fixtures(db)

            # Seleccionar artículos por los índices generados (puede haber duplicados en la lista)
            selected_ids = [all_article_ids[i] for i in indices]
            # Deduplicar para la llamada al servicio (simula lo que llega de la API)
            unique_ids = list(dict.fromkeys(selected_ids))

            service = KnowledgeArticleService()

            # Primera asociación: crea las relaciones
            service.associate_articles_to_profile(
                db=db, profile=profile, article_ids=unique_ids, org_id=org.id
            )

            # Contar asociaciones después de la primera llamada
            count_after_first = db.query(func.count()).select_from(
                profile_knowledge_articles
            ).filter(
                profile_knowledge_articles.c.profile_id == profile.id
            ).scalar()

            # Segunda asociación con la misma lista: debe ser idempotente
            service.associate_articles_to_profile(
                db=db, profile=profile, article_ids=unique_ids, org_id=org.id
            )

            # Contar asociaciones después de la segunda llamada
            count_after_second = db.query(func.count()).select_from(
                profile_knowledge_articles
            ).filter(
                profile_knowledge_articles.c.profile_id == profile.id
            ).scalar()

            # Verificar idempotencia: la cantidad no debe cambiar
            assert count_after_second == count_after_first, (
                f"La re-asociación creó duplicados: "
                f"antes={count_after_first}, después={count_after_second}"
            )

            # Verificar que la cantidad corresponde a los IDs únicos
            assert count_after_first == len(unique_ids), (
                f"La primera asociación debió crear {len(unique_ids)} registros, "
                f"pero creó {count_after_first}"
            )
        finally:
            db.close()


# === PROPERTY 7: LÍMITE DE ARTÍCULOS POR PERFIL ===

from app.services.knowledge_article import MAX_ARTICLES_PER_PROFILE


class TestLimiteArticulosPorPerfil:
    """
    Property 7: Límite de artículos por perfil.

    Para cualquier DebuggingProfile con exactamente 10 artículos asociados,
    un intento de asociar un artículo adicional debe ser rechazado con ValueError.
    Para N <= 10 artículos, la asociación debe ser exitosa.

    Feature: knowledge-base-library, Property 7: Límite de artículos por perfil

    **Validates: Requirements 8.6**
    """

    def _create_db_session(self):
        """Crea una sesión con BD SQLite in-memory y tablas necesarias."""
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        _TestBase.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        return Session()

    def _create_org(self, db) -> str:
        """Crea una organización de prueba y retorna su ID."""
        org_id = str(uuid.uuid4())
        org = _TestOrganization(id=org_id, name="Test Org")
        db.add(org)
        db.commit()
        return org_id

    def _create_profile(self, db, org_id: str) -> _TestDebuggingProfile:
        """Crea un perfil de debugging de prueba."""
        profile = _TestDebuggingProfile(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            name="Perfil de prueba",
        )
        db.add(profile)
        db.commit()
        return profile

    def _create_article(self, db, org_id: str, index: int) -> str:
        """Crea un artículo de conocimiento de prueba y retorna su ID."""
        article_id = str(uuid.uuid4())
        article = _TestKnowledgeArticle(
            id=article_id,
            organization_id=org_id,
            title=f"Artículo #{index}",
            description=f"Descripción del artículo de prueba número {index}",
            content=f"Contenido del artículo #{index}",
        )
        db.add(article)
        db.commit()
        return article_id

    @given(n_articles=st.integers(min_value=8, max_value=12))
    @settings(max_examples=100)
    def test_limite_10_articulos_por_perfil(self, n_articles: int):
        """
        Para cualquier N ∈ [8..12], la asociación de artículos 1..10 debe ser exitosa,
        y la asociación del artículo 11+ debe lanzar ValueError con mensaje descriptivo.

        **Validates: Requirements 8.6**
        """
        # Preparar BD in-memory fresca para cada ejemplo
        db = self._create_db_session()
        org_id = self._create_org(db)
        profile = self._create_profile(db, org_id)
        service = KnowledgeArticleService()

        # Crear N artículos
        article_ids = []
        for i in range(n_articles):
            aid = self._create_article(db, org_id, i + 1)
            article_ids.append(aid)

        try:
            if n_articles <= MAX_ARTICLES_PER_PROFILE:
                # Todos deberían asociarse sin error
                service.associate_articles_to_profile(
                    db=db,
                    profile=profile,
                    article_ids=article_ids,
                    org_id=org_id,
                )
                # Verificar que se asociaron todos
                from sqlalchemy import func
                from app.models.knowledge_article import profile_knowledge_articles
                count = db.query(func.count()).select_from(
                    profile_knowledge_articles
                ).filter(
                    profile_knowledge_articles.c.profile_id == profile.id
                ).scalar()
                assert count == n_articles, (
                    f"Se esperaban {n_articles} asociaciones, pero hay {count}"
                )
            else:
                # Primero asociar los primeros 10 (debe funcionar)
                first_10 = article_ids[:MAX_ARTICLES_PER_PROFILE]
                service.associate_articles_to_profile(
                    db=db,
                    profile=profile,
                    article_ids=first_10,
                    org_id=org_id,
                )

                # Verificar que se asociaron 10
                from sqlalchemy import func
                from app.models.knowledge_article import profile_knowledge_articles
                count = db.query(func.count()).select_from(
                    profile_knowledge_articles
                ).filter(
                    profile_knowledge_articles.c.profile_id == profile.id
                ).scalar()
                assert count == MAX_ARTICLES_PER_PROFILE, (
                    f"Se esperaban {MAX_ARTICLES_PER_PROFILE} asociaciones, pero hay {count}"
                )

                # Intentar asociar el artículo #11 (debe fallar)
                extra_article = article_ids[MAX_ARTICLES_PER_PROFILE]
                with pytest.raises(ValueError) as exc_info:
                    service.associate_articles_to_profile(
                        db=db,
                        profile=profile,
                        article_ids=[extra_article],
                        org_id=org_id,
                    )

                # Verificar mensaje descriptivo
                error_message = str(exc_info.value)
                assert "máximo 10" in error_message.lower() or "límite" in error_message.lower(), (
                    f"El mensaje de error no es descriptivo: '{error_message}'"
                )

                # Verificar que sigue habiendo solo 10 asociaciones
                count_after = db.query(func.count()).select_from(
                    profile_knowledge_articles
                ).filter(
                    profile_knowledge_articles.c.profile_id == profile.id
                ).scalar()
                assert count_after == MAX_ARTICLES_PER_PROFILE, (
                    f"Después del error, se esperaban {MAX_ARTICLES_PER_PROFILE} "
                    f"asociaciones, pero hay {count_after}"
                )
        finally:
            db.close()


# === PROPERTY 8: INYECCIÓN CONDICIONAL EN PROMPT ===

import types

from app.services.debugging_analysis import DebuggingAnalysisService


def _make_mock_session():
    """Crea un mock de DebuggingSession con los atributos mínimos requeridos."""
    profile = types.SimpleNamespace(description="Perfil de prueba")
    session = types.SimpleNamespace(
        profile=profile,
        profile_id=uuid.uuid4(),
        motivo=None,
        additional_instructions=None,
        organization_id=uuid.uuid4(),
        workstation_id=uuid.uuid4(),
    )
    return session


def _make_mock_article(title: str, content: str):
    """Crea un mock de artículo de conocimiento con title y content."""
    return types.SimpleNamespace(title=title, content=content)


class TestInyeccionCondicionalPrompt:
    """
    Property 8: Inyección condicional en prompt.

    Para cualquier DebuggingProfile sin artículos asociados, el prompt
    construido por _build_prompt() NO debe contener la sección
    "Base de Conocimiento". Para cualquier perfil CON artículos asociados,
    el prompt DEBE contener esa sección con el contenido de los artículos.

    Feature: knowledge-base-library, Property 8: Inyección condicional en prompt

    **Validates: Requirements 3.1, 3.2, 3.4**
    """

    @given(
        n_articles=st.integers(min_value=0, max_value=5),
        titles=st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N", "P", "S"), blacklist_characters="\x00"),
                min_size=3,
                max_size=50,
            ).filter(lambda s: len(s.strip()) > 0),
            min_size=5,
            max_size=5,
        ),
        contents=st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N", "P", "S"), blacklist_characters="\x00"),
                min_size=10,
                max_size=200,
            ).filter(lambda s: len(s.strip()) > 0),
            min_size=5,
            max_size=5,
        ),
    )
    @settings(max_examples=100)
    def test_presencia_ausencia_seccion_base_conocimiento(
        self, n_articles: int, titles: list, contents: list
    ):
        """
        Genera perfiles con 0..5 artículos aleatorios y verifica:
        - Si N == 0: "Base de Conocimiento" NO aparece en el prompt
        - Si N > 0: "Base de Conocimiento" SÍ aparece, y cada título de artículo
          está presente en el prompt generado.

        **Validates: Requirements 3.1, 3.2, 3.4**
        """
        # Crear mock de sesión y datos mínimos para _build_prompt
        session = _make_mock_session()
        index_data = {
            "profile_name": "Perfil Test",
            "start_time": "2024-01-01 10:00:00",
            "end_time": "2024-01-01 10:05:00",
            "duration_seconds": 300,
            "errors": [],
            "targets": {},
            "files": [],
        }
        diffs = {}
        extracts = {}

        # Crear artículos según N generado por Hypothesis
        articles = []
        for i in range(n_articles):
            articles.append(_make_mock_article(title=titles[i], content=contents[i]))

        # Construir prompt
        service = DebuggingAnalysisService()
        prompt = service._build_prompt(
            session=session,
            index_data=index_data,
            diffs=diffs,
            extracts=extracts,
            knowledge_articles=articles if articles else None,
        )

        # Verificar presencia/ausencia de la sección
        if n_articles == 0:
            assert "Base de Conocimiento" not in prompt, (
                "Con 0 artículos, la sección 'Base de Conocimiento' "
                "NO debería aparecer en el prompt"
            )
        else:
            assert "Base de Conocimiento" in prompt, (
                f"Con {n_articles} artículos, la sección 'Base de Conocimiento' "
                "DEBE aparecer en el prompt"
            )
            # Verificar que cada título de artículo aparece en el prompt
            for i in range(n_articles):
                assert titles[i] in prompt, (
                    f"El título del artículo '{titles[i]}' no aparece en el prompt "
                    f"a pesar de haber sido incluido como artículo de conocimiento"
                )



# === PROPERTY 9: TRUNCACIÓN PRESERVA ORDEN Y WARNING ===

import types
import uuid

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.debugging_analysis import DebuggingAnalysisService, MAX_TOTAL_PROMPT_SIZE


def _make_mock_session():
    """Crea una sesión mock mínima para _build_prompt (presupuesto base pequeño)."""
    profile = types.SimpleNamespace(description="Perfil de prueba")
    session = types.SimpleNamespace(
        profile=profile,
        profile_id=uuid.uuid4(),
        motivo=None,
        additional_instructions=None,
        organization_id=uuid.uuid4(),
        workstation_id=uuid.uuid4(),
    )
    return session


def _make_mock_article(title: str, content: str):
    """Crea un artículo mock con título y contenido."""
    return types.SimpleNamespace(title=title, content=content)


class TestTruncacionPrompt:
    """
    Property 9: Truncación preserva orden y warning.

    Para cualquier conjunto de artículos cuyo contenido total sumado excede
    MAX_TOTAL_PROMPT_SIZE, el prompt resultante debe contener una nota de
    truncación, y los artículos incluidos deben estar en el orden original
    (primeros artículos priorizados sobre últimos).

    Feature: knowledge-base-library, Property 9: Truncación preserva orden y warning

    **Validates: Requirements 3.3**
    """

    @given(
        article_sizes=st.lists(
            st.integers(min_value=50_000, max_value=150_000),  # 50KB-150KB por artículo
            min_size=3,
            max_size=5,
        )
    )
    @settings(max_examples=100)
    def test_truncacion_incluye_warning_cuando_excede_presupuesto(self, article_sizes: list):
        """
        Dado un conjunto de artículos cuyo contenido total excede el presupuesto
        disponible (~194KB), el prompt debe contener el mensaje de truncación.

        **Validates: Requirements 3.3**
        """
        # Crear artículos con contenido lo suficientemente grande para exceder el presupuesto
        # El prompt base ocupa ~3-4KB y se reservan 2KB adicionales, dejando ~194KB de presupuesto.
        # Generamos artículos cuyo total exceda ese presupuesto.
        articles = []
        for i, size in enumerate(article_sizes):
            title = f"Artículo-{i+1}"
            content = "A" * size
            articles.append(_make_mock_article(title, content))

        # Solo nos interesa el caso en que la suma total excede el presupuesto (~194KB)
        total_content_size = sum(s for s in article_sizes)
        if total_content_size < 195_000:
            # Si el contenido total no es suficiente para forzar truncación, saltamos
            return

        # Construir prompt con artículos
        session = _make_mock_session()
        index_data = {
            "profile_name": "Test",
            "start_time": "2024-01-01T00:00:00",
            "end_time": "2024-01-01T00:01:00",
            "duration_seconds": 60,
            "errors": [],
            "targets": {},
            "files": [],
        }
        diffs = {}
        extracts = {}

        service = DebuggingAnalysisService()
        prompt = service._build_prompt(session, index_data, diffs, extracts, articles)

        # Verificar que aparece el mensaje de truncación
        assert "[... artículo truncado por límite de prompt" in prompt, (
            "El prompt excede el presupuesto pero NO contiene nota de truncación. "
            f"Tamaño total artículos: {total_content_size}, "
            f"Tamaño prompt: {len(prompt)}"
        )

    @given(
        article_sizes=st.lists(
            st.integers(min_value=50_000, max_value=150_000),
            min_size=3,
            max_size=5,
        )
    )
    @settings(max_examples=100)
    def test_truncacion_preserva_orden_de_articulos(self, article_sizes: list):
        """
        Los artículos que aparecen en el prompt truncado mantienen su orden
        original: el título del artículo i aparece antes que el título del
        artículo i+1 en el prompt.

        **Validates: Requirements 3.3**
        """
        # Generar artículos con contenido grande para forzar truncación
        articles = []
        for i, size in enumerate(article_sizes):
            title = f"Artículo-Orden-{i+1}"
            content = "B" * size
            articles.append(_make_mock_article(title, content))

        total_content_size = sum(s for s in article_sizes)
        if total_content_size < 195_000:
            return

        session = _make_mock_session()
        index_data = {
            "profile_name": "Test",
            "start_time": "2024-01-01T00:00:00",
            "end_time": "2024-01-01T00:01:00",
            "duration_seconds": 60,
            "errors": [],
            "targets": {},
            "files": [],
        }
        diffs = {}
        extracts = {}

        service = DebuggingAnalysisService()
        prompt = service._build_prompt(session, index_data, diffs, extracts, articles)

        # Verificar orden: para cada par de títulos consecutivos que aparecen
        # en el prompt, la posición del primero debe ser menor que la del segundo
        positions = []
        for i in range(len(articles)):
            title = f"### {articles[i].title}"
            pos = prompt.find(title)
            if pos != -1:
                positions.append((i, pos))

        # Verificar que los artículos presentes mantienen orden original
        for idx in range(len(positions) - 1):
            article_idx_a, pos_a = positions[idx]
            article_idx_b, pos_b = positions[idx + 1]
            assert article_idx_a < article_idx_b, (
                f"Artículo {article_idx_a} debería aparecer antes que {article_idx_b} "
                f"pero sus posiciones son: {pos_a} y {pos_b}"
            )
            assert pos_a < pos_b, (
                f"El título del artículo {article_idx_a} (pos={pos_a}) aparece DESPUÉS "
                f"del artículo {article_idx_b} (pos={pos_b}). El orden no se preserva."
            )

    @given(
        article_sizes=st.lists(
            st.integers(min_value=50_000, max_value=150_000),
            min_size=3,
            max_size=5,
        )
    )
    @settings(max_examples=100)
    def test_prompt_no_excede_significativamente_max_size(self, article_sizes: list):
        """
        El tamaño total del prompt con artículos truncados no debe exceder
        MAX_TOTAL_PROMPT_SIZE de forma significativa (tolerancia de 5KB por
        overhead de headers y mensajes de truncación).

        **Validates: Requirements 3.3**
        """
        articles = []
        for i, size in enumerate(article_sizes):
            title = f"Artículo-Size-{i+1}"
            content = "C" * size
            articles.append(_make_mock_article(title, content))

        session = _make_mock_session()
        index_data = {
            "profile_name": "Test",
            "start_time": "2024-01-01T00:00:00",
            "end_time": "2024-01-01T00:01:00",
            "duration_seconds": 60,
            "errors": [],
            "targets": {},
            "files": [],
        }
        diffs = {}
        extracts = {}

        service = DebuggingAnalysisService()
        prompt = service._build_prompt(session, index_data, diffs, extracts, articles)

        # El prompt no debe exceder MAX_TOTAL_PROMPT_SIZE + 5KB de tolerancia
        max_allowed = MAX_TOTAL_PROMPT_SIZE + 5_000
        assert len(prompt) <= max_allowed, (
            f"El prompt excede significativamente el límite: "
            f"tamaño={len(prompt)}, max_permitido={max_allowed} "
            f"(MAX_TOTAL_PROMPT_SIZE={MAX_TOTAL_PROMPT_SIZE})"
        )
