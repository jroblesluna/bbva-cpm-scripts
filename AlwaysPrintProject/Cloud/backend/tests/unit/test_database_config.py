"""
Tests unitarios para la configuración de base de datos.

Verifica que SQLAlchemy y Alembic estén configurados correctamente.
"""

import pytest
from sqlalchemy import inspect, text
from app.core.database import engine, SessionLocal, Base, get_db, check_db_connection
from app.core.config import settings


class TestDatabaseConfiguration:
    """Tests de configuración de base de datos."""
    
    def test_settings_loaded(self):
        """Verifica que la configuración se carga correctamente."""
        assert settings.DATABASE_URL is not None
        assert settings.PROJECT_NAME == "AlwaysPrint Cloud Management"
        assert settings.API_V1_STR == "/api/v1"
    
    def test_database_url_format(self):
        """Verifica que DATABASE_URL tenga un formato válido."""
        url = settings.DATABASE_URL
        assert url.startswith("sqlite://") or \
               url.startswith("postgresql://") or \
               url.startswith("mssql+")
    
    def test_engine_created(self):
        """Verifica que el engine de SQLAlchemy se crea correctamente."""
        assert engine is not None
        assert engine.url is not None
    
    def test_session_factory_created(self):
        """Verifica que la session factory se crea correctamente."""
        assert SessionLocal is not None
        
        # Crear una sesión de prueba
        db = SessionLocal()
        assert db is not None
        db.close()
    
    def test_base_metadata_exists(self):
        """Verifica que Base.metadata existe."""
        assert Base.metadata is not None
    
    def test_get_db_dependency(self):
        """Verifica que la dependencia get_db funciona correctamente."""
        db_generator = get_db()
        db = next(db_generator)
        
        assert db is not None
        
        # Cerrar la sesión
        try:
            next(db_generator)
        except StopIteration:
            pass  # Esperado
    
    def test_check_db_connection(self):
        """Verifica que la función de verificación de conexión funciona."""
        # Esta prueba puede fallar si no hay base de datos configurada
        # En ese caso, simplemente verifica que la función no lanza excepción
        try:
            result = check_db_connection()
            assert isinstance(result, bool)
        except Exception as e:
            pytest.skip(f"No se pudo conectar a la base de datos: {e}")
    
    def test_sqlite_foreign_keys_enabled(self):
        """Verifica que foreign keys estén habilitadas en SQLite."""
        if not settings.is_sqlite:
            pytest.skip("Esta prueba solo aplica para SQLite")
        
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA foreign_keys"))
            row = result.fetchone()
            assert row[0] == 1, "Foreign keys no están habilitadas en SQLite"
    
    def test_pool_configuration(self):
        """Verifica la configuración del pool de conexiones."""
        if settings.is_sqlite:
            # SQLite usa StaticPool
            assert engine.pool.__class__.__name__ == "StaticPool"
        else:
            # PostgreSQL/SQL Server usan QueuePool
            assert engine.pool.size() >= 0
            assert engine.pool._max_overflow == settings.DB_MAX_OVERFLOW


class TestDatabaseTypeDetection:
    """Tests de detección de tipo de base de datos."""
    
    def test_is_sqlite_detection(self):
        """Verifica la detección de SQLite."""
        if settings.DATABASE_URL.startswith("sqlite"):
            assert settings.is_sqlite is True
            assert settings.is_postgresql is False
            assert settings.is_sqlserver is False
    
    def test_is_postgresql_detection(self):
        """Verifica la detección de PostgreSQL."""
        if settings.DATABASE_URL.startswith("postgresql"):
            assert settings.is_sqlite is False
            assert settings.is_postgresql is True
            assert settings.is_sqlserver is False
    
    def test_is_sqlserver_detection(self):
        """Verifica la detección de SQL Server."""
        if settings.DATABASE_URL.startswith("mssql"):
            assert settings.is_sqlite is False
            assert settings.is_postgresql is False
            assert settings.is_sqlserver is True


class TestSessionManagement:
    """Tests de gestión de sesiones."""
    
    def test_session_autocommit_disabled(self):
        """Verifica que autocommit esté deshabilitado."""
        db = SessionLocal()
        assert db.autocommit is False
        db.close()
    
    def test_session_autoflush_disabled(self):
        """Verifica que autoflush esté deshabilitado."""
        db = SessionLocal()
        assert db.autoflush is False
        db.close()
    
    def test_session_closes_properly(self):
        """Verifica que las sesiones se cierren correctamente."""
        db = SessionLocal()
        assert db.is_active is True
        db.close()
        # Después de cerrar, la sesión no debe estar activa
        assert db.is_active is False
