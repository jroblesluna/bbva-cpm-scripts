"""
Configuración de fixtures para pytest.

Proporciona fixtures compartidos para todos los tests unitarios:
- client: TestClient de FastAPI
- db: Sesión de base de datos SQLite en memoria (aislada por test)
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.main import app


@pytest.fixture
def client():
    """Cliente de prueba para FastAPI."""
    return TestClient(app)


@pytest.fixture
def db():
    """
    Sesión de base de datos SQLite en memoria para tests unitarios.

    Crea todas las tablas antes de cada test y las elimina después,
    garantizando aislamiento total entre tests.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
