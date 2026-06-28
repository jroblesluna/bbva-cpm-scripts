"""
Configuración de pytest para tests de propiedad (property-based testing).

Los property tests no necesitan la aplicación FastAPI completa ni la BD —
solo testean servicios individuales con mocks. El conftest del directorio
padre importa app.main que puede causar conflictos con Hypothesis cuando
hay múltiples tests en secuencia (filesystem database locking).

Solución: sobreescribir los fixtures del parent conftest con versiones vacías
para que no se importen módulos que crean event loops o conexiones.
"""

import pytest


@pytest.fixture
def client():
    """Override del fixture client del parent — no se usa en property tests."""
    raise NotImplementedError("Property tests no usan el fixture 'client'")


@pytest.fixture
def db():
    """Override del fixture db del parent — no se usa en property tests."""
    raise NotImplementedError("Property tests no usan el fixture 'db'")
