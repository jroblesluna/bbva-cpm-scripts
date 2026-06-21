"""
Colector de métricas de escalabilidad del sistema.

Este módulo implementa la clase ScalabilityMetricsCollector que recolecta
las 5 métricas de escalabilidad orientadas a soportar 5000 workstations
concurrentes:
- Conexiones WebSocket activas
- Memoria del proceso Python
- File descriptors
- Tráfico de red
- Estado del pool de base de datos

Mantiene estado in-memory para el cálculo de tasas de red (se pierde al reiniciar,
comportamiento aceptable — retorna null la primera vez).
"""

import asyncio
import logging
import os
import resource
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.scalability_metrics import (
    DbPoolResponse,
    FileDescriptorResponse,
    NetworkTrafficResponse,
    PythonMemoryResponse,
    ScalabilityMetricsResponse,
    WebSocketMetricsResponse,
)

logger = logging.getLogger(__name__)


def calculate_percent(numerator: int, denominator: int, decimals: int = 1) -> float:
    """
    Calcula el porcentaje de uso dado un numerador y denominador.

    Fórmula: round(numerator / denominator * 100, decimals)

    Args:
        numerator: Valor actual (no negativo).
        denominator: Valor máximo/límite (positivo, > 0).
        decimals: Número de decimales para redondeo (por defecto 1).

    Returns:
        Porcentaje redondeado a los decimales especificados.

    Raises:
        ZeroDivisionError: Si denominator es 0.
    """
    return round(numerator / denominator * 100, decimals)


@dataclass
class NetReading:
    """Lectura de bytes de red en un instante dado."""
    rx_bytes: int
    tx_bytes: int


@dataclass
class NetRates:
    """Tasas de transferencia de red calculadas."""
    rx_rate_bps: float
    tx_rate_bps: float


class ScalabilityMetricsCollector:
    """
    Recolecta las 5 métricas de escalabilidad del sistema.

    Mantiene estado in-memory para cálculo de tasas de red.
    Singleton a nivel de módulo.
    """

    def __init__(self):
        # Estado para cálculo de tasa de red
        self._prev_net_reading: Optional[NetReading] = None
        self._prev_net_timestamp: Optional[float] = None
        self._last_rates: Optional[NetRates] = None
        # Baseline RSS del proceso capturado al iniciar (antes de conexiones WS)
        self._baseline_rss_mb: Optional[float] = None

    def capture_baseline(self) -> None:
        """
        Captura el RSS actual como baseline de memoria del proceso.

        Debe invocarse una única vez al finalizar el startup del backend,
        antes de aceptar conexiones WebSocket. Así el cálculo de
        avg_per_workstation_mb refleja solo el overhead marginal por ws,
        no la memoria base del framework/código.
        """
        try:
            with open("/proc/self/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            vmrss_kb = int(parts[1])
                            self._baseline_rss_mb = round(vmrss_kb / 1024, 2)
                            logger.info(
                                "Baseline de memoria RSS capturado al inicio",
                                extra={
                                    "baseline_rss_mb": self._baseline_rss_mb,
                                },
                            )
                        break
        except (OSError, IOError) as e:
            logger.warning(
                "No se pudo capturar baseline de memoria RSS",
                extra={
                    "error_type": type(e).__name__,
                    "error_detail": str(e),
                },
            )
            self._baseline_rss_mb = None

    async def collect_all_metrics(self, db=None) -> ScalabilityMetricsResponse:
        """
        Recolecta todas las métricas de escalabilidad.

        Ejecuta los 5 sub-colectores. Los colectores síncronos (websocket, memoria,
        file descriptors, red) se ejecutan directamente ya que leen de /proc (I/O rápido).
        El colector de db_pool se ejecuta por separado ya que requiere sesión de BD.

        Para cada colector que falle, se asigna None al campo correspondiente
        y se registra el error con structured logging.

        Args:
            db: Sesión de SQLAlchemy opcional para métricas del pool de BD.

        Returns:
            ScalabilityMetricsResponse con las 5 métricas (o None para las que fallen).
        """
        # Resultados de los colectores
        websocket_result: Optional[WebSocketMetricsResponse] = None
        memory_result: Optional[PythonMemoryResponse] = None
        fd_result: Optional[FileDescriptorResponse] = None
        network_result: Optional[NetworkTrafficResponse] = None
        db_pool_result: Optional[DbPoolResponse] = None

        # Colector de conexiones WebSocket
        try:
            websocket_result = await self.collect_websocket_metrics()
        except Exception as e:
            logger.warning(
                "Fallo en recolección de métrica de escalabilidad",
                extra={
                    "metric_name": "websocket_connections",
                    "error_type": type(e).__name__,
                    "error_detail": str(e),
                },
            )
            websocket_result = None

        # Colector de memoria del proceso Python
        try:
            memory_result = await self.collect_python_memory()
        except Exception as e:
            logger.warning(
                "Fallo en recolección de métrica de escalabilidad",
                extra={
                    "metric_name": "python_memory",
                    "error_type": type(e).__name__,
                    "error_detail": str(e),
                },
            )
            memory_result = None

        # Colector de file descriptors
        try:
            fd_result = self.collect_file_descriptors()
        except Exception as e:
            logger.warning(
                "Fallo en recolección de métrica de escalabilidad",
                extra={
                    "metric_name": "file_descriptors",
                    "error_type": type(e).__name__,
                    "error_detail": str(e),
                },
            )
            fd_result = None

        # Colector de tráfico de red
        try:
            network_result = self.collect_network_traffic()
        except Exception as e:
            logger.warning(
                "Fallo en recolección de métrica de escalabilidad",
                extra={
                    "metric_name": "network_traffic",
                    "error_type": type(e).__name__,
                    "error_detail": str(e),
                },
            )
            network_result = None

        # Colector del pool de base de datos (requiere sesión de BD)
        if db is not None:
            try:
                db_pool_result = self.collect_db_pool_metrics(db)
            except Exception as e:
                logger.warning(
                    "Fallo en recolección de métrica de escalabilidad",
                    extra={
                        "metric_name": "db_pool",
                        "error_type": type(e).__name__,
                        "error_detail": str(e),
                    },
                )
                db_pool_result = None

        # Ensamblar respuesta con timestamp UTC
        return ScalabilityMetricsResponse(
            websocket=websocket_result,
            python_memory=memory_result,
            file_descriptors=fd_result,
            network=network_result,
            db_pool=db_pool_result,
            collected_at=datetime.utcnow(),
        )

    async def collect_websocket_metrics(self) -> WebSocketMetricsResponse:
        """
        Recolecta métricas de conexiones WebSocket del ConnectionManager singleton.

        Con multi-worker + Redis, consulta el conteo GLOBAL (todos los workers)
        via WorkerRegistry. Sin Redis, retorna solo las conexiones locales.

        Returns:
            WebSocketMetricsResponse con conteos de conexiones.
        """
        try:
            from app.services.websocket_manager import connection_manager

            # Usar conteo global si el manager soporta get_global_connection_count (Redis)
            if hasattr(connection_manager, 'get_global_connection_count'):
                counts = await connection_manager.get_global_connection_count()
            else:
                counts = connection_manager.get_connection_count()

            workstation_count = counts.get("workstations", 0)
            operator_count = counts.get("operators", 0)
            workers = counts.get("workers", 1)
            total = workstation_count + operator_count

            return WebSocketMetricsResponse(
                workstation_count=workstation_count,
                operator_count=operator_count,
                total=total,
                stale=0,
                workers=workers,
                data_available=True,
            )

        except Exception as e:
            logger.warning(
                "Fallo en recolección de métrica de escalabilidad",
                extra={
                    "metric_name": "websocket_connections",
                    "error_type": type(e).__name__,
                    "error_detail": str(e),
                },
            )
            return WebSocketMetricsResponse(
                workstation_count=0,
                operator_count=0,
                total=0,
                data_available=False,
            )

    async def collect_python_memory(self) -> Optional[PythonMemoryResponse]:
        """
        Recolecta métricas de memoria del proceso Python.

        Lee VmRSS de /proc/self/status y convierte de kB a MB.
        Obtiene memoria total del contenedor del SystemStatusCollector si está disponible.
        Calcula el promedio de memoria por workstation conectada.

        Returns:
            PythonMemoryResponse con rss_mb, container_total_mb y avg_per_workstation_mb,
            o None si la lectura de /proc/self/status falla.
        """
        try:
            # Leer VmRSS de /proc/self/status
            vmrss_kb = None
            with open("/proc/self/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        # Formato: "VmRSS:    12345 kB"
                        parts = line.split()
                        if len(parts) >= 2:
                            vmrss_kb = int(parts[1])
                        break

            # Si no se encontró VmRSS, retornar None
            if vmrss_kb is None:
                logger.warning(
                    "Fallo en recolección de métrica de escalabilidad",
                    extra={
                        "metric_name": "python_memory",
                        "error_type": "ValueError",
                        "error_detail": "Campo VmRSS no encontrado en /proc/self/status",
                    },
                )
                return None

            # Convertir kB a MB con 2 decimales
            rss_mb = round(vmrss_kb / 1024, 2)

            # Obtener memoria total del contenedor del SystemStatusCollector
            container_total_mb = None
            try:
                # Intentar leer el límite de memoria del cgroup v1
                with open("/sys/fs/cgroup/memory/memory.limit_in_bytes", "r") as f:
                    limit_bytes = int(f.read().strip())
                    # Valores muy altos indican "sin límite" (>= 2^62)
                    if limit_bytes < (2**62):
                        container_total_mb = round(limit_bytes / (1024 * 1024), 2)
            except Exception:
                # Si cgroup v1 no está disponible, intentar con cgroup v2
                try:
                    with open("/sys/fs/cgroup/memory.max", "r") as f:
                        content = f.read().strip()
                        if content != "max":
                            limit_bytes = int(content)
                            container_total_mb = round(limit_bytes / (1024 * 1024), 2)
                except Exception:
                    # No se pudo obtener la memoria del contenedor
                    pass

            # Calcular promedio por workstation
            # Usa el overhead marginal: (rss_actual - baseline) / ws_count
            # El baseline se captura al inicio antes de aceptar conexiones WS.
            # Si el RSS actual <= baseline, significa que las WS no agregan overhead
            # medible (o GC reclamó memoria), por lo que retornamos 0.
            avg_per_workstation_mb: float = 0.0
            try:
                from app.services.websocket_manager import connection_manager

                # Usar conteo global (todos los workers) si está disponible
                if hasattr(connection_manager, 'get_global_connection_count'):
                    counts = await connection_manager.get_global_connection_count()
                else:
                    counts = connection_manager.get_connection_count()
                ws_count = counts.get("workstations", 0)

                if ws_count > 0:
                    if self._baseline_rss_mb is not None:
                        # Overhead marginal = memoria actual - memoria base
                        overhead_mb = rss_mb - self._baseline_rss_mb
                        if overhead_mb > 0:
                            avg_per_workstation_mb = round(overhead_mb / ws_count, 2)
                        else:
                            # RSS no superó el baseline: overhead efectivo es 0
                            avg_per_workstation_mb = 0.0
                    else:
                        # Sin baseline (no se ejecutó capture_baseline): no calcular
                        avg_per_workstation_mb = 0.0
                else:
                    avg_per_workstation_mb = 0.0
            except Exception as e:
                logger.warning(
                    "No se pudo obtener conteo de workstations para cálculo de memoria por ws",
                    extra={
                        "error_type": type(e).__name__,
                        "error_detail": str(e),
                    },
                )
                avg_per_workstation_mb = 0.0

            logger.info(
                "Métricas de memoria del proceso Python recolectadas exitosamente",
                extra={
                    "metric_name": "python_memory",
                    "rss_mb": rss_mb,
                    "container_total_mb": container_total_mb,
                    "avg_per_workstation_mb": avg_per_workstation_mb,
                },
            )

            return PythonMemoryResponse(
                rss_mb=rss_mb,
                container_total_mb=container_total_mb,
                avg_per_workstation_mb=avg_per_workstation_mb,
            )

        except (OSError, IOError) as e:
            # /proc/self/status no es accesible
            logger.warning(
                "Fallo en recolección de métrica de escalabilidad",
                extra={
                    "metric_name": "python_memory",
                    "error_type": type(e).__name__,
                    "error_detail": str(e),
                },
            )
            return None

    def collect_file_descriptors(self) -> Optional[FileDescriptorResponse]:
        """
        Recolecta métricas de file descriptors del proceso Python.

        Cuenta las entradas en /proc/self/fd para obtener el conteo de
        descriptores abiertos y obtiene el soft limit del sistema.
        Calcula el porcentaje de uso si el límite es mayor a 0.

        Returns:
            FileDescriptorResponse con open_count, limit y usage_percent,
            o None si /proc/self/fd no es accesible.
        """
        try:
            # Contar entradas en /proc/self/fd para obtener open_count
            open_count = len(os.listdir("/proc/self/fd"))

            # Obtener soft limit de file descriptors
            limit = resource.getrlimit(resource.RLIMIT_NOFILE)[0]

            # Calcular porcentaje de uso
            if limit > 0:
                usage_percent = calculate_percent(open_count, limit, 1)
            else:
                # Si el límite es 0, no se puede calcular porcentaje
                usage_percent = None

            logger.info(
                "Métricas de file descriptors recolectadas exitosamente",
                extra={
                    "metric_name": "file_descriptors",
                    "open_count": open_count,
                    "limit": limit,
                    "usage_percent": usage_percent,
                },
            )

            return FileDescriptorResponse(
                open_count=open_count,
                limit=limit if limit > 0 else None,
                usage_percent=usage_percent,
            )

        except OSError as e:
            # /proc/self/fd no es accesible (puede ocurrir en sistemas no-Linux)
            logger.warning(
                "Fallo en recolección de métrica de escalabilidad",
                extra={
                    "metric_name": "file_descriptors",
                    "error_type": type(e).__name__,
                    "error_detail": str(e),
                },
            )
            return None

    def _parse_proc_net_dev(self) -> NetReading:
        """
        Parsea /proc/net/dev para obtener bytes totales rx/tx de interfaces no-loopback.

        Formato de /proc/net/dev:
        - Primeras 2 líneas son headers
        - Cada línea de interfaz: "  eth0: rx_bytes rx_packets ... tx_bytes tx_packets ..."
        - rx_bytes es columna índice 1 (tras el nombre de interfaz)
        - tx_bytes es columna índice 9

        Retorna la suma de rx_bytes y tx_bytes de todas las interfaces no-loopback.
        """
        total_rx = 0
        total_tx = 0

        with open("/proc/net/dev", "r") as f:
            lines = f.readlines()

        # Saltar las 2 líneas de header
        for line in lines[2:]:
            line = line.strip()
            if not line:
                continue

            # Separar nombre de interfaz de los datos
            # Formato: "eth0: 12345 ..."
            parts = line.split(":")
            if len(parts) != 2:
                continue

            iface_name = parts[0].strip()

            # Excluir interfaz loopback
            if iface_name == "lo":
                continue

            # Parsear los campos numéricos
            fields = parts[1].split()
            if len(fields) < 10:
                continue

            # rx_bytes es el primer campo (índice 0 de fields), tx_bytes es el campo 8 (índice 8)
            # Según formato: bytes, packets, errs, drop, fifo, frame, compressed, multicast (8 rx)
            #                bytes, packets, errs, drop, fifo, colls, carrier, compressed (8 tx)
            rx_bytes = int(fields[0])
            tx_bytes = int(fields[8])

            total_rx += rx_bytes
            total_tx += tx_bytes

        return NetReading(rx_bytes=total_rx, tx_bytes=total_tx)

    def collect_network_traffic(self) -> NetworkTrafficResponse:
        """
        Recolecta métricas de tráfico de red del contenedor.

        Lee /proc/net/dev, calcula tasas comparando con medición previa.
        - Primera invocación: almacena referencia y retorna null para tasas
        - Si delta_t < 0.5s: retorna tasas previas sin recalcular
        - Si current_bytes < prev_bytes (counter reset): descarta anterior, retorna null para tasas
        - Si delta_t >= 0.5s: calcula nuevas tasas rx_rate_bps y tx_rate_bps
        """
        try:
            current_reading = self._parse_proc_net_dev()
            current_time = time.time()

            # Primera invocación: almacenar referencia y retornar null para tasas
            if self._prev_net_reading is None or self._prev_net_timestamp is None:
                self._prev_net_reading = current_reading
                self._prev_net_timestamp = current_time
                self._last_rates = None

                logger.info(
                    "Primera lectura de tráfico de red almacenada como referencia",
                    extra={
                        "rx_bytes": current_reading.rx_bytes,
                        "tx_bytes": current_reading.tx_bytes,
                    }
                )

                return NetworkTrafficResponse(
                    rx_bytes=current_reading.rx_bytes,
                    tx_bytes=current_reading.tx_bytes,
                    rx_rate_bps=None,
                    tx_rate_bps=None,
                )

            delta_t = current_time - self._prev_net_timestamp

            # Si delta_t < 0.5s, retornar tasas previas sin recalcular
            if delta_t < 0.5:
                return NetworkTrafficResponse(
                    rx_bytes=current_reading.rx_bytes,
                    tx_bytes=current_reading.tx_bytes,
                    rx_rate_bps=self._last_rates.rx_rate_bps if self._last_rates else None,
                    tx_rate_bps=self._last_rates.tx_rate_bps if self._last_rates else None,
                )

            # Detectar counter reset (current_bytes < prev_bytes)
            if (current_reading.rx_bytes < self._prev_net_reading.rx_bytes or
                    current_reading.tx_bytes < self._prev_net_reading.tx_bytes):
                logger.warning(
                    "Reinicio de contadores de red detectado, descartando medición anterior",
                    extra={
                        "prev_rx": self._prev_net_reading.rx_bytes,
                        "prev_tx": self._prev_net_reading.tx_bytes,
                        "curr_rx": current_reading.rx_bytes,
                        "curr_tx": current_reading.tx_bytes,
                    }
                )
                # Descartar anterior, almacenar nueva referencia
                self._prev_net_reading = current_reading
                self._prev_net_timestamp = current_time
                self._last_rates = None

                return NetworkTrafficResponse(
                    rx_bytes=current_reading.rx_bytes,
                    tx_bytes=current_reading.tx_bytes,
                    rx_rate_bps=None,
                    tx_rate_bps=None,
                )

            # Calcular tasas de transferencia
            rx_rate = (current_reading.rx_bytes - self._prev_net_reading.rx_bytes) / delta_t
            tx_rate = (current_reading.tx_bytes - self._prev_net_reading.tx_bytes) / delta_t

            self._last_rates = NetRates(rx_rate_bps=rx_rate, tx_rate_bps=tx_rate)
            self._prev_net_reading = current_reading
            self._prev_net_timestamp = current_time

            return NetworkTrafficResponse(
                rx_bytes=current_reading.rx_bytes,
                tx_bytes=current_reading.tx_bytes,
                rx_rate_bps=rx_rate,
                tx_rate_bps=tx_rate,
            )

        except Exception as e:
            logger.warning(
                "Fallo en recolección de métrica de tráfico de red",
                extra={
                    "metric_name": "network_traffic",
                    "error_type": type(e).__name__,
                    "error_detail": str(e),
                }
            )
            raise

    def collect_db_pool_metrics(self, db: Session) -> DbPoolResponse:
        """
        Recolecta métricas del pool de conexiones SQLAlchemy y conexiones activas en PostgreSQL.

        Lee el estado del pool local (checked_out, idle, pool_size, overflow, max_overflow)
        y ejecuta una query a pg_stat_activity para obtener el conteo de conexiones activas.

        Args:
            db: Sesión de SQLAlchemy para ejecutar la query a pg_stat_activity.

        Returns:
            DbPoolResponse con las métricas del pool y conexiones PostgreSQL.

        Raises:
            Exception: Si no se puede acceder al pool de SQLAlchemy.
        """
        from app.core.database import engine
        from app.core.config import settings

        # Leer estado del pool SQLAlchemy
        pool = engine.pool
        checked_out = pool.checkedout()
        idle = pool.checkedin()
        # pool.size() retorna conexiones actualmente gestionadas (puede ser 0 en pool recién creado)
        # Para el tamaño configurado, usar settings.DB_POOL_SIZE directamente
        pool_size = settings.DB_POOL_SIZE if settings.is_postgresql else pool.size()
        overflow = pool.overflow()
        max_overflow = pool._max_overflow

        # Calcular porcentaje de uso del pool
        if pool_size > 0:
            usage_percent = calculate_percent(checked_out, pool_size, 1)
        else:
            usage_percent = None

        # Obtener conexiones activas de PostgreSQL vía pg_stat_activity
        pg_active_connections = None
        try:
            # Extraer usuario de la URL de base de datos
            db_url = settings.DATABASE_URL
            username = None
            if "://" in db_url:
                # Formato: postgresql://user:password@host:port/dbname
                after_scheme = db_url.split("://")[1]
                if "@" in after_scheme:
                    user_part = after_scheme.split("@")[0]
                    username = user_part.split(":")[0] if ":" in user_part else user_part

            if username and settings.is_postgresql:
                result = db.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE usename = :username AND state != 'idle'"
                    ),
                    {"username": username},
                )
                row = result.scalar()
                pg_active_connections = int(row) if row is not None else None

        except Exception as e:
            # Si la query a pg_stat_activity falla, retornar null para pg_active_connections
            logger.warning(
                "Fallo en consulta a pg_stat_activity",
                extra={
                    "metric_name": "db_pool_pg_stat_activity",
                    "error_type": type(e).__name__,
                    "error_detail": str(e),
                },
            )
            pg_active_connections = None

        logger.info(
            "Métricas del pool de base de datos recolectadas exitosamente",
            extra={
                "metric_name": "db_pool",
                "checked_out": checked_out,
                "idle": idle,
                "pool_size": pool_size,
                "overflow": overflow,
                "max_overflow": max_overflow,
                "pg_active_connections": pg_active_connections,
                "usage_percent": usage_percent,
            },
        )

        return DbPoolResponse(
            checked_out=checked_out,
            idle=idle,
            pool_size=pool_size,
            overflow=overflow,
            max_overflow=max_overflow,
            pg_active_connections=pg_active_connections,
            usage_percent=usage_percent,
        )


# Singleton a nivel de módulo
scalability_collector = ScalabilityMetricsCollector()
