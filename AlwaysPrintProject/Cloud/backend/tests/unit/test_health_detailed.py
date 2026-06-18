"""
Tests unitarios para el endpoint /api/v1/health/detailed.

Valida la estructura de respuesta y el cálculo de métricas
como cache hit ratio, p95 latency y memory.
"""

import time

import pytest

from app.api.v1.endpoints.health import (
    _calculate_p95,
    _prune_window,
    record_cache_hit,
    record_cache_miss,
    record_registration_latency,
    _cache_hits,
    _cache_misses,
    _registration_latencies,
)


class TestHealthDetailedEndpoint:
    """Verifica estructura y campos del endpoint /api/v1/health/detailed."""

    def test_endpoint_retorna_200_con_estructura_correcta(self, client):
        """El endpoint debe retornar 200 con todos los campos requeridos."""
        response = client.get("/api/v1/health/detailed")
        assert response.status_code == 200

        data = response.json()

        # Campos de primer nivel
        assert "status" in data
        assert "worker_id" in data
        assert "redis" in data
        assert "connections" in data
        assert "cache" in data
        assert "registration" in data
        assert "memory_mb" in data
        assert "uptime_seconds" in data

    def test_worker_id_contiene_pid(self, client):
        """El worker_id debe contener el PID del proceso."""
        import os

        response = client.get("/api/v1/health/detailed")
        data = response.json()
        assert data["worker_id"] == f"worker_{os.getpid()}"

    def test_redis_tiene_campos_conectividad(self, client):
        """La sección redis debe incluir connected, latency_ms y subscriptions."""
        response = client.get("/api/v1/health/detailed")
        data = response.json()

        redis = data["redis"]
        assert "connected" in redis
        assert "latency_ms" in redis
        assert "subscriptions" in redis
        assert isinstance(redis["connected"], bool)

    def test_connections_tiene_workstations_y_operators(self, client):
        """La sección connections debe incluir workstations y operators."""
        response = client.get("/api/v1/health/detailed")
        data = response.json()

        conns = data["connections"]
        assert "workstations" in conns
        assert "operators" in conns
        assert isinstance(conns["workstations"], int)
        assert isinstance(conns["operators"], int)

    def test_cache_tiene_hits_misses_ratio(self, client):
        """La sección cache debe incluir hits_last_minute, misses_last_minute y hit_ratio_pct."""
        response = client.get("/api/v1/health/detailed")
        data = response.json()

        cache = data["cache"]
        assert "hits_last_minute" in cache
        assert "misses_last_minute" in cache
        assert "hit_ratio_pct" in cache

    def test_registration_tiene_p95_y_total(self, client):
        """La sección registration debe incluir p95_latency_ms y total_last_minute."""
        response = client.get("/api/v1/health/detailed")
        data = response.json()

        reg = data["registration"]
        assert "p95_latency_ms" in reg
        assert "total_last_minute" in reg

    def test_memory_mb_es_numerico_positivo(self, client):
        """memory_mb debe ser un número >= 0."""
        response = client.get("/api/v1/health/detailed")
        data = response.json()
        assert data["memory_mb"] >= 0

    def test_uptime_seconds_es_entero_positivo(self, client):
        """uptime_seconds debe ser un entero >= 0."""
        response = client.get("/api/v1/health/detailed")
        data = response.json()
        assert isinstance(data["uptime_seconds"], int)
        assert data["uptime_seconds"] >= 0


class TestCacheMetrics:
    """Verifica cálculo de métricas de cache."""

    @pytest.fixture(autouse=True)
    def _clear_metrics(self):
        """Limpia contadores antes de cada test."""
        _cache_hits.clear()
        _cache_misses.clear()
        _registration_latencies.clear()
        yield
        _cache_hits.clear()
        _cache_misses.clear()
        _registration_latencies.clear()

    def test_record_cache_hit_incrementa_contador(self):
        """record_cache_hit debe agregar un timestamp al deque."""
        record_cache_hit()
        record_cache_hit()
        assert len(_cache_hits) == 2

    def test_record_cache_miss_incrementa_contador(self):
        """record_cache_miss debe agregar un timestamp al deque."""
        record_cache_miss()
        assert len(_cache_misses) == 1

    def test_prune_window_elimina_entradas_antiguas(self):
        """_prune_window debe eliminar entradas fuera de la ventana temporal."""
        from collections import deque

        dq = deque()
        # Agregar entrada de hace 120 segundos
        dq.append(time.time() - 120)
        # Agregar entrada reciente
        dq.append(time.time())

        _prune_window(dq, window_seconds=60.0)
        assert len(dq) == 1

    def test_calculate_p95_vacio_retorna_cero(self):
        """p95 de una lista vacía debe ser 0.0."""
        from collections import deque

        dq = deque()
        assert _calculate_p95(dq) == 0.0

    def test_calculate_p95_un_elemento(self):
        """p95 de un solo elemento debe retornar ese elemento."""
        from collections import deque

        dq = deque([(time.time(), 150.0)])
        assert _calculate_p95(dq) == 150.0

    def test_calculate_p95_multiples_elementos(self):
        """p95 de múltiples elementos debe retornar el percentil 95 correcto."""
        from collections import deque

        now = time.time()
        # 20 latencias de 100ms y 1 de 500ms — p95 debería ser 500
        dq = deque()
        for i in range(20):
            dq.append((now, 100.0))
        dq.append((now, 500.0))

        result = _calculate_p95(dq)
        # Con 21 elementos, índice 95% = int(21*0.95) = 19
        # Sorted: [100.0]*20 + [500.0] → idx 19 = 100.0 (el 20° elemento)
        assert result == 100.0

    def test_record_registration_latency_almacena_correctamente(self):
        """record_registration_latency debe agregar la latencia al deque."""
        record_registration_latency(250.5)
        assert len(_registration_latencies) == 1
        assert _registration_latencies[0][1] == 250.5
