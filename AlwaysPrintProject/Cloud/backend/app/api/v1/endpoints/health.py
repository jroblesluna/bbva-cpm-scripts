"""
Endpoint de health check detallado para monitoreo multi-worker.

Expone métricas en tiempo real del worker actual: estado Redis,
conexiones WebSocket, cache hit ratio, latencia de registro y memoria.

Requirements: 7.5
"""

import os
import time
from collections import deque
from typing import Deque, Tuple

from fastapi import APIRouter

from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Timestamp de inicio del proceso (para calcular uptime)
_process_start_time: float = time.time()

# === CONTADORES DE MÉTRICAS (POR WORKER) ===
# Almacenamos timestamps de hits/misses para calcular ratio en ventana de 60s
_cache_hits: Deque[float] = deque()
_cache_misses: Deque[float] = deque()

# Latencias de registro en ventana de 60s: (timestamp, latency_ms)
_registration_latencies: Deque[Tuple[float, float]] = deque()


def record_cache_hit() -> None:
    """Registra un cache hit (llamar desde RegistrationCache)."""
    _cache_hits.append(time.time())


def record_cache_miss() -> None:
    """Registra un cache miss (llamar desde RegistrationCache)."""
    _cache_misses.append(time.time())


def record_registration_latency(latency_ms: float) -> None:
    """Registra latencia de registro de una workstation (llamar desde el handler)."""
    _registration_latencies.append((time.time(), latency_ms))


def _prune_window(dq: Deque, window_seconds: float = 60.0) -> None:
    """Elimina entradas más antiguas que la ventana temporal."""
    cutoff = time.time() - window_seconds
    while dq and dq[0] < cutoff:
        dq.popleft()


def _prune_latency_window(
    dq: Deque[Tuple[float, float]], window_seconds: float = 60.0
) -> None:
    """Elimina entradas de latencia más antiguas que la ventana temporal."""
    cutoff = time.time() - window_seconds
    while dq and dq[0][0] < cutoff:
        dq.popleft()


def _calculate_p95(latencies: Deque[Tuple[float, float]]) -> float:
    """Calcula el percentil 95 de las latencias en la ventana."""
    if not latencies:
        return 0.0
    values = sorted(lat for _, lat in latencies)
    idx = int(len(values) * 0.95)
    # Clamp al último índice válido
    idx = min(idx, len(values) - 1)
    return round(values[idx], 1)


@router.get("/health/detailed", tags=["Sistema"])
async def health_detailed():
    """
    Health check detallado con métricas del worker actual.

    Reporta: status, redis connectivity + latency, worker_id,
    connection counts, cache hit ratio, registration p95 latency,
    memory_mb y uptime_seconds.
    """
    from app.services.websocket_manager import connection_manager

    # Worker identity
    worker_id = f"worker_{os.getpid()}"

    # Conexiones locales
    counts = connection_manager.get_connection_count()

    # Redis connectivity + latencia (PING)
    redis_info = await _check_redis(connection_manager)

    # Cache hit ratio (últimos 60 segundos)
    _prune_window(_cache_hits)
    _prune_window(_cache_misses)
    hits = len(_cache_hits)
    misses = len(_cache_misses)
    total_cache = hits + misses
    hit_ratio_pct = round((hits / total_cache) * 100, 1) if total_cache > 0 else 0.0

    # Registration p95 latency (últimos 60 segundos)
    _prune_latency_window(_registration_latencies)
    p95_latency = _calculate_p95(_registration_latencies)
    total_registrations = len(_registration_latencies)

    # Memoria del proceso actual (MB)
    memory_mb = _get_process_memory_mb()

    # Uptime del proceso
    uptime_seconds = round(time.time() - _process_start_time, 0)

    # Determinar status
    status = "healthy"
    if not redis_info["connected"]:
        status = "degraded"

    return {
        "status": status,
        "worker_id": worker_id,
        "redis": redis_info,
        "connections": {
            "workstations": counts["workstations"],
            "operators": counts["operators"],
        },
        "cache": {
            "hits_last_minute": hits,
            "misses_last_minute": misses,
            "hit_ratio_pct": hit_ratio_pct,
        },
        "registration": {
            "p95_latency_ms": p95_latency,
            "total_last_minute": total_registrations,
        },
        "memory_mb": memory_mb,
        "uptime_seconds": int(uptime_seconds),
    }


@router.get("/health/workers", tags=["Sistema"])
async def health_workers():
    """
    Retorna métricas de TODOS los workers activos consultando Redis.
    No depende de round-robin — un solo request retorna info de todos.
    """
    import json as json_mod
    from app.services.websocket_manager import connection_manager

    local_worker_id = f"worker_{os.getpid()}"
    workers = []

    # Intentar obtener métricas globales de Redis
    redis_client = getattr(connection_manager, "_redis", None)
    redis_available = getattr(connection_manager, "_redis_available", False)

    if redis_client and redis_available:
        try:
            # Buscar todos los workers con heartbeat activo
            async for key in redis_client.scan_iter(match="workers:*:heartbeat"):
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                wid = key_str.split(":")[1]

                # Leer métricas del worker
                metrics_str = await redis_client.get(f"workers:{wid}:metrics")
                ws_count = 0
                rss_mb = 0.0

                if metrics_str:
                    metrics = json_mod.loads(metrics_str)
                    ws_count = metrics.get("ws", 0)
                    rss_mb = metrics.get("rss_mb", 0.0)

                # Leer TTL del heartbeat para estimar uptime
                ttl = await redis_client.ttl(f"workers:{wid}:heartbeat")

                # Ping Redis para latencia (una sola vez, aplicar a todos)
                redis_latency = 0.0
                try:
                    start = time.time()
                    await redis_client.ping()
                    redis_latency = round((time.time() - start) * 1000, 2)
                except Exception:
                    pass

                workers.append({
                    "worker_id": wid,
                    "status": "healthy",
                    "redis": {
                        "connected": True,
                        "latency_ms": redis_latency,
                        "subscriptions": ws_count,
                    },
                    "connections": {
                        "workstations": ws_count,
                        "operators": 0,
                    },
                    "cache": {"hits_last_minute": 0, "misses_last_minute": 0, "hit_ratio_pct": 0},
                    "registration": {"p95_latency_ms": 0, "total_last_minute": 0},
                    "memory_mb": rss_mb,
                    "uptime_seconds": max(0, 60 - ttl + 60) if ttl > 0 else 0,
                })

        except Exception as e:
            logger.warning("health.workers_redis_error", error=str(e))

    # Fallback: si no se encontró nada de Redis, retornar el worker local
    if not workers:
        counts = connection_manager.get_connection_count()
        memory_mb = _get_process_memory_mb()
        uptime = int(time.time() - _process_start_time)
        workers.append({
            "worker_id": local_worker_id,
            "status": "healthy",
            "redis": {"connected": redis_available, "latency_ms": 0, "subscriptions": 0},
            "connections": {"workstations": counts["workstations"], "operators": counts["operators"]},
            "cache": {"hits_last_minute": 0, "misses_last_minute": 0, "hit_ratio_pct": 0},
            "registration": {"p95_latency_ms": 0, "total_last_minute": 0},
            "memory_mb": memory_mb,
            "uptime_seconds": uptime,
        })

    return workers


async def _check_redis(connection_manager) -> dict:
    """
    Verifica conectividad Redis y mide latencia con PING.

    Retorna dict con connected, latency_ms y subscriptions.
    """
    redis_client = getattr(connection_manager, "_redis", None)
    redis_available = getattr(connection_manager, "_redis_available", False)

    if not redis_client or not redis_available:
        return {
            "connected": False,
            "latency_ms": 0.0,
            "subscriptions": 0,
        }

    try:
        # Medir latencia con PING
        start = time.time()
        await redis_client.ping()
        latency_ms = round((time.time() - start) * 1000, 2)

        # Número de suscripciones (canales ws:{id} + org:{id} + global)
        subscriptions = len(connection_manager.workstation_connections)

        return {
            "connected": True,
            "latency_ms": latency_ms,
            "subscriptions": subscriptions,
        }
    except Exception as e:
        logger.warning(
            "health.redis_check_failed",
            error=str(e),
        )
        return {
            "connected": False,
            "latency_ms": 0.0,
            "subscriptions": 0,
        }


def _get_process_memory_mb() -> float:
    """Obtiene el uso de memoria RSS del proceso actual en MB."""
    try:
        import resource
        # resource.getrusage retorna ru_maxrss en KB (Linux) o bytes (macOS)
        usage = resource.getrusage(resource.RUSAGE_SELF)
        import platform
        if platform.system() == "Darwin":
            # macOS: ru_maxrss está en bytes
            return round(usage.ru_maxrss / (1024 * 1024), 1)
        else:
            # Linux: ru_maxrss está en KB
            return round(usage.ru_maxrss / 1024, 1)
    except ImportError:
        pass

    # Fallback: leer /proc/self/status en Linux
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    # Formato: "VmRSS:    123456 kB"
                    kb = int(line.split()[1])
                    return round(kb / 1024, 1)
    except (FileNotFoundError, IOError):
        pass

    return 0.0
