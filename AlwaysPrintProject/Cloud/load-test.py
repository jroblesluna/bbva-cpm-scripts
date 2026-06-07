#!/usr/bin/env python3
"""
AlwaysPrint Cloud — Script de simulación de carga WebSocket.

Simula N workstations conectadas simultáneamente al backend, enviando
registro y telemetría periódica como lo haría el cliente real.

Uso:
    python3 load-test.py [URL] [N_CONEXIONES] [DURACION_SEG]

Ejemplos:
    python3 load-test.py wss://alwaysprint.dev.iol.pe/ws/workstation 500 300
    python3 load-test.py ws://localhost:8000/ws/workstation 100 60

Requisitos:
    pip install websockets

Métricas reportadas cada 10 segundos:
    - Conexiones activas / fallidas / pendientes
    - Mensajes enviados / recibidos
    - Latencia promedio de registro
    - Memoria del proceso local
"""

import asyncio
import json
import random
import string
import sys
import time
import os
from dataclasses import dataclass, field
from typing import Optional

try:
    import websockets
except ImportError:
    print("ERROR: Instalar websockets — pip install websockets")
    sys.exit(1)


# === CONFIGURACIÓN ===

DEFAULT_URL = "wss://alwaysprint.dev.iol.pe/ws/workstation"
DEFAULT_CONNECTIONS = 500
DEFAULT_DURATION = 300  # 5 minutos
TELEMETRY_INTERVAL = 30  # segundos entre envíos de telemetría
CONNECT_RAMP_DELAY = 0.1  # segundos entre cada nueva conexión (evita pico simultáneo)
RECONNECT_DELAY = 5  # segundos antes de reintentar conexión fallida


# === MÉTRICAS ===

@dataclass
class Metrics:
    """Contadores globales de la simulación."""
    connected: int = 0
    failed: int = 0
    pending: int = 0
    messages_sent: int = 0
    messages_received: int = 0
    register_latencies: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    start_time: float = field(default_factory=time.time)

    def summary(self) -> str:
        elapsed = time.time() - self.start_time
        avg_latency = (
            sum(self.register_latencies[-100:]) / len(self.register_latencies[-100:])
            if self.register_latencies else 0
        )
        rss_mb = _get_rss_mb()
        return (
            f"[{elapsed:6.0f}s] "
            f"✓{self.connected} ✗{self.failed} ⏳{self.pending} | "
            f"TX:{self.messages_sent} RX:{self.messages_received} | "
            f"Latencia reg: {avg_latency*1000:.0f}ms | "
            f"RSS local: {rss_mb:.1f}MB"
        )


metrics = Metrics()


# === GENERACIÓN DE DATOS SIMULADOS ===

def _random_ip() -> str:
    """Genera una IP privada aleatoria en rango 192.168.x.x."""
    return f"192.168.{random.randint(1, 254)}.{random.randint(1, 254)}"


def _random_hostname() -> str:
    """Genera un hostname tipo workstation Windows."""
    num = random.randint(1, 9999)
    return f"W10-WS{num:04d}"


def _random_serial() -> str:
    """Genera un serial de SO simulado."""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=20))


def _random_user() -> str:
    """Genera un nombre de usuario simulado."""
    names = ["jrobles", "mlopez", "agarcia", "pdiaz", "lmorales",
             "cflores", "rnavarro", "fsilva", "dcastro", "evega"]
    return random.choice(names)


def _make_register_msg(idx: int) -> dict:
    """Crea mensaje de registro para la workstation simulada."""
    return {
        "type": "register",
        "ip_private": _random_ip(),
        "hostname": _random_hostname(),
        "os_serial": _random_serial(),
        "current_user": _random_user(),
        "locale": "es",
        "client_version": "1.26.607.1000",
        "workstation_id": None,
    }


def _make_telemetry_msg() -> dict:
    """Crea mensaje de telemetría simulado."""
    return {
        "type": "telemetry",
        "queue_status": random.choice(["ok", "ok", "ok", "missing"]),
        "contingency_active": random.random() < 0.02,  # 2% en contingencia
        "jobs_identified": random.randint(0, 20),
        "avg_release_time_ms": random.randint(500, 3000),
        "disconnection_log": [],
    }


def _get_rss_mb() -> float:
    """Obtiene RSS del proceso actual en MB."""
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reporta en bytes, Linux en KB
        if sys.platform == "darwin":
            return usage / (1024 * 1024)
        return usage / 1024
    except Exception:
        return 0.0


# === SIMULACIÓN DE UNA WORKSTATION ===

async def simulate_workstation(idx: int, url: str, duration: float):
    """
    Simula una workstation: conecta, registra, envía telemetría periódica.
    Se mantiene viva durante 'duration' segundos respondiendo a pings.
    """
    metrics.pending += 1
    ws: Optional[websockets.WebSocketClientProtocol] = None

    try:
        # Conectar con timeout
        ws = await asyncio.wait_for(
            websockets.connect(url, ping_interval=None, close_timeout=5),
            timeout=30
        )
        metrics.pending -= 1

        # Enviar registro
        register_msg = _make_register_msg(idx)
        t0 = time.time()
        await ws.send(json.dumps(register_msg))
        metrics.messages_sent += 1

        # Esperar respuesta de registro
        response = await asyncio.wait_for(ws.recv(), timeout=15)
        latency = time.time() - t0
        metrics.messages_received += 1
        metrics.register_latencies.append(latency)
        metrics.connected += 1

        # Parsear respuesta para obtener workstation_id
        resp_data = json.loads(response)
        workstation_id = resp_data.get("workstation_id")

        # Loop de telemetría hasta que expire la duración
        end_time = time.time() + duration
        while time.time() < end_time:
            # Esperar intervalo de telemetría (con variación aleatoria ±5s)
            wait = TELEMETRY_INTERVAL + random.uniform(-5, 5)
            try:
                # Mientras esperamos, recibir pings del servidor
                msg = await asyncio.wait_for(ws.recv(), timeout=wait)
                metrics.messages_received += 1
                data = json.loads(msg)

                # Responder a pings del servidor
                if data.get("type") == "ping":
                    await ws.send(json.dumps({"type": "pong"}))
                    metrics.messages_sent += 1

            except asyncio.TimeoutError:
                # Timeout normal — hora de enviar telemetría
                pass

            # Enviar telemetría
            if time.time() < end_time:
                telemetry = _make_telemetry_msg()
                await ws.send(json.dumps(telemetry))
                metrics.messages_sent += 1

    except asyncio.TimeoutError:
        metrics.pending = max(0, metrics.pending - 1)
        metrics.failed += 1
        metrics.errors.append(f"WS-{idx}: timeout de conexión")
    except websockets.exceptions.ConnectionClosed as e:
        metrics.connected = max(0, metrics.connected - 1)
        metrics.errors.append(f"WS-{idx}: conexión cerrada ({e.code}: {e.reason})")
    except Exception as e:
        metrics.pending = max(0, metrics.pending - 1)
        metrics.failed += 1
        metrics.errors.append(f"WS-{idx}: {type(e).__name__}: {e}")
    finally:
        if ws:
            try:
                await ws.close()
            except Exception:
                pass
        metrics.connected = max(0, metrics.connected - 1)


# === MONITOR DE MÉTRICAS ===

async def metrics_reporter(interval: float = 10):
    """Imprime métricas cada N segundos."""
    while True:
        await asyncio.sleep(interval)
        print(metrics.summary())

        # Mostrar últimos errores si hay
        if metrics.errors:
            recent = metrics.errors[-3:]
            for err in recent:
                print(f"  ⚠ {err}")
            metrics.errors.clear()


# === MAIN ===

async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    n_connections = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_CONNECTIONS
    duration = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_DURATION

    print("=" * 70)
    print("  AlwaysPrint Cloud — Simulación de Carga WebSocket")
    print("=" * 70)
    print(f"  URL:          {url}")
    print(f"  Conexiones:   {n_connections}")
    print(f"  Duración:     {duration}s")
    print(f"  Telemetría:   cada {TELEMETRY_INTERVAL}s por ws")
    print(f"  Ramp-up:      {CONNECT_RAMP_DELAY}s entre conexiones ({n_connections * CONNECT_RAMP_DELAY:.0f}s total)")
    print("=" * 70)
    print()

    # Iniciar reporter de métricas
    reporter_task = asyncio.create_task(metrics_reporter(10))

    # Lanzar conexiones con ramp-up gradual
    tasks = []
    for i in range(n_connections):
        task = asyncio.create_task(simulate_workstation(i, url, duration))
        tasks.append(task)
        await asyncio.sleep(CONNECT_RAMP_DELAY)

    # Esperar a que todas terminen
    await asyncio.gather(*tasks, return_exceptions=True)

    # Cancelar reporter
    reporter_task.cancel()

    # Resumen final
    print()
    print("=" * 70)
    print("  RESUMEN FINAL")
    print("=" * 70)
    print(f"  Duración total:     {time.time() - metrics.start_time:.0f}s")
    print(f"  Conexiones exitosas: {len(metrics.register_latencies)}")
    print(f"  Conexiones fallidas: {metrics.failed}")
    print(f"  Mensajes enviados:   {metrics.messages_sent}")
    print(f"  Mensajes recibidos:  {metrics.messages_received}")
    if metrics.register_latencies:
        avg = sum(metrics.register_latencies) / len(metrics.register_latencies)
        mx = max(metrics.register_latencies)
        print(f"  Latencia registro:   avg={avg*1000:.0f}ms, max={mx*1000:.0f}ms")
    print(f"  RSS local:           {_get_rss_mb():.1f}MB")
    print("=" * 70)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nSimulación interrumpida por usuario.")
        print(metrics.summary())
