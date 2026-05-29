"""
Property tests para la protección de concurrencia del StatusScheduler.

Verifica que el StatusScheduler ejecuta como máximo una recolección a la vez,
y que todas las solicitudes concurrentes recibidas mientras una recolección
está en progreso son rechazadas con una indicación de "already running" (HTTP 409).

**Validates: Requirements 3.6**

Feature: system-status-monitoring, Property 8: Concurrency protection
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from fastapi import HTTPException

from app.services.status_scheduler import StatusScheduler


# === ESTRATEGIAS DE GENERACIÓN ===

# Número de intentos concurrentes de recolección (2 a 10)
_concurrent_attempts = st.integers(min_value=2, max_value=10)

# Duración simulada de la recolección en segundos (0.05 a 0.3 para tests rápidos)
_collection_duration = st.floats(
    min_value=0.05, max_value=0.3, allow_nan=False, allow_infinity=False
)


def _create_scheduler_with_slow_collection(duration: float) -> StatusScheduler:
    """
    Crea una instancia de StatusScheduler con _execute_collection mockeado
    para simular una recolección lenta usando asyncio.sleep.

    Args:
        duration: Duración simulada de la recolección en segundos

    Returns:
        StatusScheduler configurado con mock lento
    """
    scheduler = StatusScheduler()

    # Mock del snapshot que retorna _execute_collection
    mock_snapshot = MagicMock()
    mock_snapshot.id = "test-snapshot-id"
    mock_snapshot.overall_status = "healthy"

    async def slow_collection(db):
        """Simula una recolección lenta."""
        await asyncio.sleep(duration)
        return mock_snapshot

    # Reemplazar _execute_collection con la versión lenta
    scheduler._execute_collection = slow_collection

    return scheduler


# === PROPERTY 8: CONCURRENCY PROTECTION ===


class TestConcurrencyProtection:
    """
    Property 8: Concurrency protection.

    Para cualquier secuencia de intentos concurrentes de trigger de recolección
    (manual o programada), el scheduler SHALL ejecutar como máximo una recolección
    a la vez, y todas las solicitudes concurrentes recibidas mientras una recolección
    está en progreso SHALL ser rechazadas con una indicación de "already running".

    **Validates: Requirements 3.6**
    """

    @given(
        num_concurrent=_concurrent_attempts,
        duration=_collection_duration,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_exactamente_una_recoleccion_exitosa_entre_concurrentes(
        self, num_concurrent: int, duration: float
    ):
        """
        De N intentos concurrentes de recolección manual, exactamente 1 debe
        completarse exitosamente y los demás deben ser rechazados con HTTP 409.

        **Validates: Requirements 3.6**
        """
        scheduler = _create_scheduler_with_slow_collection(duration)
        mock_db = MagicMock()

        # Lanzar múltiples recolecciones concurrentes
        tasks = [
            asyncio.create_task(
                self._safe_trigger(scheduler, mock_db)
            )
            for _ in range(num_concurrent)
        ]

        results = await asyncio.gather(*tasks)

        # Contar éxitos y rechazos
        successes = [r for r in results if r["status"] == "success"]
        rejections = [r for r in results if r["status"] == "rejected"]

        # Exactamente 1 debe tener éxito
        assert len(successes) == 1, (
            f"Se esperaba exactamente 1 éxito entre {num_concurrent} intentos concurrentes, "
            f"pero se obtuvieron {len(successes)} éxitos y {len(rejections)} rechazos"
        )

        # Todos los demás deben ser rechazados con 409
        assert len(rejections) == num_concurrent - 1, (
            f"Se esperaban {num_concurrent - 1} rechazos, "
            f"pero se obtuvieron {len(rejections)}"
        )

    @given(
        num_concurrent=_concurrent_attempts,
        duration=_collection_duration,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_rechazos_retornan_http_409(
        self, num_concurrent: int, duration: float
    ):
        """
        Todas las solicitudes rechazadas deben lanzar HTTPException con
        status_code 409 (Conflict) indicando que ya hay una ejecución en curso.

        **Validates: Requirements 3.6**
        """
        scheduler = _create_scheduler_with_slow_collection(duration)
        mock_db = MagicMock()

        # Lanzar múltiples recolecciones concurrentes
        tasks = [
            asyncio.create_task(
                self._safe_trigger(scheduler, mock_db)
            )
            for _ in range(num_concurrent)
        ]

        results = await asyncio.gather(*tasks)

        # Verificar que todos los rechazos tienen código 409
        rejections = [r for r in results if r["status"] == "rejected"]
        for rejection in rejections:
            assert rejection["status_code"] == 409, (
                f"Se esperaba status_code 409 para rechazo, "
                f"pero se obtuvo {rejection['status_code']}"
            )

    @given(
        num_concurrent=_concurrent_attempts,
        duration=_collection_duration,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_nunca_dos_recolecciones_simultaneas(
        self, num_concurrent: int, duration: float
    ):
        """
        En ningún momento deben ejecutarse 2 recolecciones simultáneamente.
        Se verifica que el contador de ejecuciones activas nunca supera 1.

        **Validates: Requirements 3.6**
        """
        scheduler = StatusScheduler()
        mock_db = MagicMock()

        # Contador atómico de ejecuciones simultáneas
        active_count = 0
        max_active = 0

        # Mock del snapshot
        mock_snapshot = MagicMock()
        mock_snapshot.id = "test-snapshot-id"
        mock_snapshot.overall_status = "healthy"

        async def tracked_collection(db):
            """Recolección que rastrea ejecuciones simultáneas."""
            nonlocal active_count, max_active
            active_count += 1
            if active_count > max_active:
                max_active = active_count
            await asyncio.sleep(duration)
            active_count -= 1
            return mock_snapshot

        scheduler._execute_collection = tracked_collection

        # Lanzar múltiples recolecciones concurrentes
        tasks = [
            asyncio.create_task(
                self._safe_trigger(scheduler, mock_db)
            )
            for _ in range(num_concurrent)
        ]

        await asyncio.gather(*tasks)

        # El máximo de ejecuciones simultáneas nunca debe superar 1
        assert max_active <= 1, (
            f"Se detectaron {max_active} recolecciones simultáneas. "
            f"El máximo permitido es 1."
        )

    @given(
        num_concurrent=_concurrent_attempts,
        duration=_collection_duration,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_scheduler_libre_despues_de_completar(
        self, num_concurrent: int, duration: float
    ):
        """
        Después de que una recolección completa, el scheduler debe estar
        libre para aceptar nuevas solicitudes (is_running == False).

        **Validates: Requirements 3.6**
        """
        scheduler = _create_scheduler_with_slow_collection(duration)
        mock_db = MagicMock()

        # Lanzar múltiples recolecciones concurrentes
        tasks = [
            asyncio.create_task(
                self._safe_trigger(scheduler, mock_db)
            )
            for _ in range(num_concurrent)
        ]

        await asyncio.gather(*tasks)

        # Después de completar todas las tareas, el scheduler debe estar libre
        assert not scheduler.is_running, (
            "El scheduler debería estar libre (is_running=False) "
            "después de completar todas las recolecciones"
        )
        assert not scheduler._lock.locked(), (
            "El lock del scheduler debería estar liberado "
            "después de completar todas las recolecciones"
        )

    async def _safe_trigger(self, scheduler: StatusScheduler, db) -> dict:
        """
        Ejecuta trigger_manual_collection capturando excepciones HTTP.

        Retorna un diccionario con el resultado:
        - {"status": "success", "snapshot": ...} si la recolección fue exitosa
        - {"status": "rejected", "status_code": 409} si fue rechazada

        Args:
            scheduler: Instancia del StatusScheduler
            db: Mock de sesión de base de datos

        Returns:
            Diccionario con el resultado de la operación
        """
        try:
            snapshot = await scheduler.trigger_manual_collection(db)
            return {"status": "success", "snapshot": snapshot}
        except HTTPException as e:
            return {"status": "rejected", "status_code": e.status_code}
