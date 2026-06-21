"""
Servicio de recolección de métricas del sistema.

Este módulo implementa la clase SystemStatusCollector que recolecta
métricas del sistema operativo (RAM, disco, CPU, swap, uptime) usando
la librería psutil, métricas de contenedores Docker usando el Docker SDK,
y verifica la disponibilidad de servicios críticos (backend, frontend,
nginx, redis, RDS, SSL).

Diseñado para ejecutarse directamente en la instancia EC2 donde corre el backend.

Características:
- Conversión de bytes a MB (bytes / 1048576)
- Porcentajes redondeados a 1 decimal
- Resiliencia ante fallos parciales: si una métrica falla, se registra
  el error y se continúa con las demás
- Timeout de 10 segundos para operaciones Docker
- Si Docker daemon no disponible, retorna docker_available=False sin interrumpir
- Health checks independientes con timeout de 10 segundos por servicio
- Verificación de certificado SSL con clasificación por días restantes
"""

import json
import logging
import ssl
import socket
import subprocess
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, List, Dict

import docker
import docker.errors
import httpx
import psutil
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.system_status import (
    ContainerMetric,
    HealthCheckResult,
    MetricRecord,
    OverallStatus,
    StatusSnapshot,
)
from app.schemas.scalability_metrics import ScalabilityMetricsResponse
from app.schemas.system_status import (
    AlertResponse,
    ContainerMetricsResponse,
    HealthCheckResponse,
    OsMetricsResponse,
)
from app.services.scalability_metrics import scalability_collector


# Configurar logger para el módulo
logger = logging.getLogger(__name__)

# Constante para conversión de bytes a megabytes
BYTES_TO_MB = 1048576


class SystemStatusCollector:
    """
    Recolecta métricas del sistema operativo, Docker y servicios.

    Utiliza psutil para obtener información de RAM, disco, CPU, swap
    y uptime del sistema. Cada métrica se recolecta de forma independiente
    para garantizar resiliencia ante fallos parciales.
    """

    def collect_os_metrics(self) -> OsMetricsResponse:
        """
        Recolecta métricas del sistema operativo usando psutil.

        Métricas recolectadas:
        - RAM: total, usada, disponible (MB) y porcentaje de uso
        - Disco: total, usado, disponible (MB) y porcentaje de uso
        - CPU: porcentaje promedio (intervalo de 1 segundo)
        - Swap: total, usado, disponible (MB)
        - Uptime: segundos desde el último arranque

        Si una métrica individual falla, se registra el error en el log
        y se asigna un valor por defecto (0.0 o 0) para continuar con
        las demás métricas sin interrumpir la recolección.

        Returns:
            OsMetricsResponse con todas las métricas del sistema operativo
        """
        # Valores por defecto en caso de fallo
        memory_total_mb: float = 0.0
        memory_used_mb: float = 0.0
        memory_available_mb: float = 0.0
        memory_percent: float = 0.0
        disk_total_mb: float = 0.0
        disk_used_mb: float = 0.0
        disk_available_mb: float = 0.0
        disk_percent: float = 0.0
        cpu_percent: float = 0.0
        swap_total_mb: float = 0.0
        swap_used_mb: float = 0.0
        swap_available_mb: float = 0.0
        uptime_seconds: int = 0

        # Recolectar métricas de memoria RAM
        try:
            mem = psutil.virtual_memory()
            memory_total_mb = round(mem.total / BYTES_TO_MB, 1)
            memory_used_mb = round(mem.used / BYTES_TO_MB, 1)
            memory_available_mb = round(mem.available / BYTES_TO_MB, 1)
            memory_percent = round(mem.percent, 1)
        except Exception as e:
            logger.error(f"Error al recolectar métricas de memoria RAM: {e}")

        # Recolectar métricas de disco
        try:
            disk = psutil.disk_usage('/')
            disk_total_mb = round(disk.total / BYTES_TO_MB, 1)
            disk_used_mb = round(disk.used / BYTES_TO_MB, 1)
            disk_available_mb = round(disk.free / BYTES_TO_MB, 1)
            disk_percent = round(disk.percent, 1)
        except Exception as e:
            logger.error(f"Error al recolectar métricas de disco: {e}")

        # Recolectar porcentaje de CPU (intervalo de 1 segundo para precisión)
        try:
            cpu_percent = round(psutil.cpu_percent(interval=1), 1)
        except Exception as e:
            logger.error(f"Error al recolectar porcentaje de CPU: {e}")

        # Recolectar métricas de swap
        try:
            swap = psutil.swap_memory()
            swap_total_mb = round(swap.total / BYTES_TO_MB, 1)
            swap_used_mb = round(swap.used / BYTES_TO_MB, 1)
            swap_available_mb = round(swap.free / BYTES_TO_MB, 1)
        except Exception as e:
            logger.error(f"Error al recolectar métricas de swap: {e}")

        # Recolectar uptime del sistema
        try:
            boot_time = psutil.boot_time()
            uptime_seconds = int(time.time() - boot_time)
        except Exception as e:
            logger.error(f"Error al recolectar uptime del sistema: {e}")

        return OsMetricsResponse(
            memory_total_mb=memory_total_mb,
            memory_used_mb=memory_used_mb,
            memory_available_mb=memory_available_mb,
            memory_percent=memory_percent,
            disk_total_mb=disk_total_mb,
            disk_used_mb=disk_used_mb,
            disk_available_mb=disk_available_mb,
            disk_percent=disk_percent,
            cpu_percent=cpu_percent,
            swap_total_mb=swap_total_mb,
            swap_used_mb=swap_used_mb,
            swap_available_mb=swap_available_mb,
            uptime_seconds=uptime_seconds,
        )

    async def collect_docker_metrics(self) -> Tuple[bool, List[ContainerMetricsResponse]]:
        """
        Recolecta métricas de todos los contenedores Docker.

        Utiliza el Docker SDK para conectarse al daemon local y obtener
        estadísticas por contenedor: CPU%, memoria usada/límite, network I/O,
        estado y uptime.

        El timeout del cliente Docker es de 10 segundos. Si el daemon no está
        disponible o no responde, se retorna docker_available=False con una
        lista vacía sin interrumpir el ciclo de recolección.

        Returns:
            Tupla (docker_available, lista de ContainerMetricsResponse):
            - docker_available: True si se pudo conectar al daemon Docker
            - lista: métricas de cada contenedor encontrado
        """
        try:
            # Conectar al daemon Docker con timeout de 10 segundos
            client = docker.from_env(timeout=10)
            # Verificar conexión con un ping
            client.ping()
        except (docker.errors.DockerException, ConnectionError, Exception) as e:
            logger.warning(f"Docker daemon no disponible: {e}")
            return (False, [])

        container_metrics: List[ContainerMetricsResponse] = []

        try:
            containers = client.containers.list(all=True)
        except (docker.errors.DockerException, Exception) as e:
            logger.warning(f"Error al listar contenedores Docker: {e}")
            return (False, [])

        for container in containers:
            try:
                metrics = self._collect_single_container_metrics(container)
                if metrics is not None:
                    container_metrics.append(metrics)
            except Exception as e:
                logger.error(
                    f"Error al recolectar métricas del contenedor "
                    f"'{container.name}': {e}"
                )

        return (True, container_metrics)

    def _collect_single_container_metrics(
        self, container
    ) -> Optional[ContainerMetricsResponse]:
        """
        Recolecta métricas de un contenedor Docker individual.

        Para contenedores detenidos, se retornan valores de 0 para CPU,
        memoria y red, ya que no tienen stats disponibles.

        Args:
            container: Objeto Container del Docker SDK

        Returns:
            ContainerMetricsResponse con las métricas del contenedor,
            o None si ocurre un error irrecuperable
        """
        name = container.name
        status = container.status  # running, exited, restarting, etc.

        # Normalizar estado: 'exited' -> 'stopped' para consistencia
        if status == "exited":
            status = "stopped"

        # Calcular uptime del contenedor
        uptime_seconds = 0
        try:
            started_at_str = container.attrs.get("State", {}).get("StartedAt", "")
            if started_at_str and started_at_str != "0001-01-01T00:00:00Z":
                # Parsear timestamp ISO 8601 de Docker
                # Docker usa formato: 2024-01-15T10:30:00.123456789Z
                started_at_str_clean = started_at_str.split(".")[0] + "+00:00"
                started_at = datetime.fromisoformat(started_at_str_clean)
                now = datetime.now(timezone.utc)
                uptime_seconds = max(0, int((now - started_at).total_seconds()))
        except Exception as e:
            logger.error(f"Error al calcular uptime del contenedor '{name}': {e}")

        # Si el contenedor no está corriendo, no hay stats disponibles
        if container.status != "running":
            return ContainerMetricsResponse(
                name=name,
                status=status,
                cpu_percent=0.0,
                memory_used_mb=0.0,
                memory_limit_mb=0.0,
                network_rx_bytes=0,
                network_tx_bytes=0,
                uptime_seconds=uptime_seconds,
            )

        # Obtener stats del contenedor (stream=False para una sola lectura)
        try:
            stats = container.stats(stream=False)
        except Exception as e:
            logger.error(f"Error al obtener stats del contenedor '{name}': {e}")
            return ContainerMetricsResponse(
                name=name,
                status=status,
                cpu_percent=0.0,
                memory_used_mb=0.0,
                memory_limit_mb=0.0,
                network_rx_bytes=0,
                network_tx_bytes=0,
                uptime_seconds=uptime_seconds,
            )

        # Calcular porcentaje de CPU
        cpu_percent = self._calculate_cpu_percent(stats)

        # Obtener métricas de memoria
        memory_stats = stats.get("memory_stats", {})
        memory_used_bytes = memory_stats.get("usage", 0)
        memory_limit_bytes = memory_stats.get("limit", 0)
        memory_used_mb = round(memory_used_bytes / BYTES_TO_MB, 1)
        memory_limit_mb = round(memory_limit_bytes / BYTES_TO_MB, 1)

        # Obtener métricas de red
        network_rx_bytes = 0
        network_tx_bytes = 0
        networks = stats.get("networks", {})
        if networks:
            # Sumar tráfico de todas las interfaces (eth0 es la principal)
            for iface_stats in networks.values():
                network_rx_bytes += iface_stats.get("rx_bytes", 0)
                network_tx_bytes += iface_stats.get("tx_bytes", 0)

        return ContainerMetricsResponse(
            name=name,
            status=status,
            cpu_percent=cpu_percent,
            memory_used_mb=memory_used_mb,
            memory_limit_mb=memory_limit_mb,
            network_rx_bytes=network_rx_bytes,
            network_tx_bytes=network_tx_bytes,
            uptime_seconds=uptime_seconds,
        )

    def _calculate_cpu_percent(self, stats: dict) -> float:
        """
        Calcula el porcentaje de CPU de un contenedor a partir de sus stats.

        Usa la fórmula oficial de Docker:
        cpu_delta = cpu_stats.cpu_usage.total_usage - precpu_stats.cpu_usage.total_usage
        system_delta = cpu_stats.system_cpu_usage - precpu_stats.system_cpu_usage
        cpu_percent = (cpu_delta / system_delta) * num_cpus * 100

        Args:
            stats: Diccionario de stats del contenedor Docker

        Returns:
            Porcentaje de CPU redondeado a 1 decimal
        """
        try:
            cpu_stats = stats.get("cpu_stats", {})
            precpu_stats = stats.get("precpu_stats", {})

            cpu_usage = cpu_stats.get("cpu_usage", {}).get("total_usage", 0)
            precpu_usage = precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
            cpu_delta = cpu_usage - precpu_usage

            system_usage = cpu_stats.get("system_cpu_usage", 0)
            presystem_usage = precpu_stats.get("system_cpu_usage", 0)
            system_delta = system_usage - presystem_usage

            if system_delta <= 0 or cpu_delta < 0:
                return 0.0

            # Número de CPUs disponibles
            num_cpus = len(
                cpu_stats.get("cpu_usage", {}).get("percpu_usage", [])
            ) or 1
            # Si percpu_usage está vacío, intentar con online_cpus
            if num_cpus == 1:
                num_cpus = cpu_stats.get("online_cpus", 1) or 1

            cpu_percent = (cpu_delta / system_delta) * num_cpus * 100.0
            return round(cpu_percent, 1)
        except Exception as e:
            logger.error(f"Error al calcular porcentaje de CPU del contenedor: {e}")
            return 0.0

    # =========================================================================
    # HEALTH CHECKS — Verificación de disponibilidad de servicios
    # =========================================================================

    async def collect_health_checks(
        self, db: Session, ssl_domain: str = "apps.iol.pe"
    ) -> Tuple[List[HealthCheckResponse], Dict[str, int]]:
        """
        Verifica la disponibilidad de todos los servicios críticos.

        Ejecuta verificaciones independientes para cada servicio. Si un
        servicio no responde dentro de 10 segundos, se marca como no
        disponible y se continúa con los demás.

        Servicios verificados:
        - Backend: HTTP GET a /api/v1/health (puerto 8000)
        - Frontend: HTTP GET al puerto 3000
        - Nginx: estado via systemctl
        - Redis: contenedor Docker en estado "running"
        - RDS: conectividad con PostgreSQL (query simple)
        - SSL: certificado del dominio, días restantes y clasificación

        Args:
            db: Sesión de SQLAlchemy para la verificación de RDS
            ssl_domain: Dominio para verificar el certificado SSL

        Returns:
            Tupla (lista de HealthCheckResponse, resumen):
            - lista: resultado de cada health check
            - resumen: dict con ok_count, warning_count, failed_count
        """
        results: List[HealthCheckResponse] = []

        # Verificar cada servicio de forma independiente
        results.append(await self._check_backend())
        results.append(await self._check_frontend())
        results.append(await self._check_nginx())
        results.append(self._check_redis())
        results.append(self._check_rds(db))
        results.append(self._check_ssl(ssl_domain))

        # Generar resumen de conteos
        ok_count = 0
        warning_count = 0
        failed_count = 0

        for result in results:
            if not result.is_available:
                failed_count += 1
            elif (
                result.details
                and result.details.get("classification") == "warning"
            ):
                warning_count += 1
            else:
                ok_count += 1

        summary = {
            "ok_count": ok_count,
            "warning_count": warning_count,
            "failed_count": failed_count,
        }

        return (results, summary)

    async def _check_backend(self) -> HealthCheckResponse:
        """
        Verifica disponibilidad del backend.

        Como este código se ejecuta DENTRO del backend, si estamos aquí
        el backend está funcionando. No hacemos HTTP a nosotros mismos
        porque con 1 worker se produce un deadlock (el worker está ocupado
        ejecutando esta recolección y no puede responder a la petición HTTP).

        En su lugar, verificamos que el proceso está respondiendo correctamente
        comprobando que podemos acceder a la base de datos (ya verificado por _check_rds)
        y que el proceso está activo.

        Returns:
            HealthCheckResponse indicando que el backend está disponible
        """
        start = time.time()
        # Si estamos ejecutando este código, el backend está vivo
        latency_ms = round((time.time() - start) * 1000, 1)
        return HealthCheckResponse(
            service_name="backend",
            is_available=True,
            latency_ms=latency_ms,
            error_message=None,
        )

    async def _check_frontend(self) -> HealthCheckResponse:
        """
        Verifica disponibilidad del frontend via HTTP GET al puerto 3000.

        El servicio se considera disponible si el status code es 200, 302 o 307.
        No sigue redirecciones para detectar correctamente 302/307.
        Timeout de 10 segundos.

        Returns:
            HealthCheckResponse con el resultado de la verificación
        """
        start = time.time()
        try:
            async with httpx.AsyncClient(
                timeout=10.0, follow_redirects=False
            ) as client:
                response = await client.get("http://frontend:3000")
            latency_ms = round((time.time() - start) * 1000, 1)
            is_available = response.status_code in (200, 302, 307)
            return HealthCheckResponse(
                service_name="frontend",
                is_available=is_available,
                latency_ms=latency_ms,
                error_message=(
                    None if is_available
                    else f"Status code inesperado: {response.status_code}"
                ),
            )
        except httpx.TimeoutException:
            latency_ms = round((time.time() - start) * 1000, 1)
            logger.warning("Health check frontend: timeout después de 10 segundos")
            return HealthCheckResponse(
                service_name="frontend",
                is_available=False,
                latency_ms=latency_ms,
                error_message="Timeout: el servicio no respondió en 10 segundos",
            )
        except Exception as e:
            latency_ms = round((time.time() - start) * 1000, 1)
            logger.warning(f"Health check frontend: error de conexión: {e}")
            return HealthCheckResponse(
                service_name="frontend",
                is_available=False,
                latency_ms=latency_ms,
                error_message=f"Error de conexión: {e}",
            )

    async def _check_nginx(self) -> HealthCheckResponse:
        """
        Verifica estado de Nginx via HTTP GET al host.

        Desde dentro del contenedor Docker, no se puede usar systemctl.
        En su lugar, se hace una petición HTTP al gateway del contenedor
        (host donde corre nginx) en el puerto 80.
        El servicio se considera disponible si responde con cualquier código HTTP.
        Timeout de 10 segundos.

        Returns:
            HealthCheckResponse con el resultado de la verificación
        """
        start = time.time()
        try:
            # Desde el contenedor, el host es accesible via host.docker.internal
            # (configurado con extra_hosts: host-gateway en docker-compose)
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "http://host.docker.internal:80",
                    follow_redirects=False,
                )
            latency_ms = round((time.time() - start) * 1000, 1)
            # Nginx responde si devuelve cualquier código (incluso 301/302 redirect a HTTPS)
            is_available = response.status_code < 500
            return HealthCheckResponse(
                service_name="nginx",
                is_available=is_available,
                latency_ms=latency_ms,
                error_message=(
                    None if is_available
                    else f"Nginx respondió con error: {response.status_code}"
                ),
            )
        except httpx.TimeoutException:
            latency_ms = round((time.time() - start) * 1000, 1)
            logger.warning("Health check nginx: timeout después de 10 segundos")
            return HealthCheckResponse(
                service_name="nginx",
                is_available=False,
                latency_ms=latency_ms,
                error_message="Timeout: nginx no respondió en 10 segundos",
            )
        except Exception as e:
            latency_ms = round((time.time() - start) * 1000, 1)
            logger.warning(f"Health check nginx: error de conexión: {e}")
            return HealthCheckResponse(
                service_name="nginx",
                is_available=False,
                latency_ms=latency_ms,
                error_message=f"Error al verificar nginx: {e}",
            )

    def _check_redis(self) -> HealthCheckResponse:
        """
        Verifica que el contenedor de Redis esté en estado "running".

        Busca un contenedor con "redis" en el nombre usando el Docker SDK.
        Timeout de 10 segundos para la conexión al daemon Docker.

        Returns:
            HealthCheckResponse con el resultado de la verificación
        """
        start = time.time()
        try:
            client = docker.from_env(timeout=10)
            # Buscar contenedor con "redis" en el nombre
            containers = client.containers.list(all=True)
            redis_container = None
            for container in containers:
                if "redis" in container.name.lower():
                    redis_container = container
                    break

            latency_ms = round((time.time() - start) * 1000, 1)

            if redis_container is None:
                return HealthCheckResponse(
                    service_name="redis",
                    is_available=False,
                    latency_ms=latency_ms,
                    error_message="No se encontró contenedor de Redis",
                )

            is_available = redis_container.status == "running"
            return HealthCheckResponse(
                service_name="redis",
                is_available=is_available,
                latency_ms=latency_ms,
                error_message=(
                    None if is_available
                    else f"Contenedor Redis en estado: {redis_container.status}"
                ),
            )
        except (docker.errors.DockerException, Exception) as e:
            latency_ms = round((time.time() - start) * 1000, 1)
            logger.warning(f"Health check redis: error al verificar contenedor: {e}")
            return HealthCheckResponse(
                service_name="redis",
                is_available=False,
                latency_ms=latency_ms,
                error_message=f"Error al verificar Redis: {e}",
            )

    def _check_rds(self, db: Session) -> HealthCheckResponse:
        """
        Verifica conectividad con PostgreSQL ejecutando una query simple.

        Ejecuta SELECT 1 para confirmar que la base de datos responde.
        Usa la sesión de SQLAlchemy proporcionada.

        Args:
            db: Sesión de SQLAlchemy activa

        Returns:
            HealthCheckResponse con el resultado de la verificación
        """
        start = time.time()
        try:
            db.execute(text("SELECT 1"))
            latency_ms = round((time.time() - start) * 1000, 1)
            return HealthCheckResponse(
                service_name="rds",
                is_available=True,
                latency_ms=latency_ms,
                error_message=None,
            )
        except Exception as e:
            latency_ms = round((time.time() - start) * 1000, 1)
            logger.warning(f"Health check RDS: error de conectividad: {e}")
            return HealthCheckResponse(
                service_name="rds",
                is_available=False,
                latency_ms=latency_ms,
                error_message=f"Error de conectividad con PostgreSQL: {e}",
            )

    def _check_ssl(self, domain: str) -> HealthCheckResponse:
        """
        Verifica el certificado SSL del dominio y calcula días restantes.

        Conecta al puerto 443 del dominio, obtiene el certificado y
        calcula los días hasta su expiración. Clasificación:
        - "valid": más de 14 días restantes
        - "warning": entre 1 y 14 días restantes
        - "expired": 0 o menos días restantes

        Args:
            domain: Dominio a verificar (ej: "apps.iol.pe")

        Returns:
            HealthCheckResponse con detalles de SSL (days_remaining, classification)
        """
        start = time.time()
        try:
            # Crear contexto SSL y conectar al dominio
            context = ssl.create_default_context()
            with socket.create_connection(
                (domain, 443), timeout=10
            ) as sock:
                with context.wrap_socket(sock, server_hostname=domain) as ssock:
                    cert = ssock.getpeercert()

            latency_ms = round((time.time() - start) * 1000, 1)

            # Parsear fecha de expiración del certificado
            not_after_str = cert.get("notAfter", "")
            # Formato típico: "Jan 15 12:00:00 2025 GMT"
            not_after = datetime.strptime(
                not_after_str, "%b %d %H:%M:%S %Y %Z"
            ).replace(tzinfo=timezone.utc)

            # Calcular días restantes
            now = datetime.now(timezone.utc)
            days_remaining = (not_after - now).days

            # Clasificar estado del certificado
            if days_remaining > 14:
                classification = "valid"
            elif days_remaining >= 1:
                classification = "warning"
            else:
                classification = "expired"

            # Determinar disponibilidad: expired = no disponible
            is_available = classification != "expired"

            return HealthCheckResponse(
                service_name="ssl",
                is_available=is_available,
                latency_ms=latency_ms,
                error_message=None if is_available else "Certificado SSL expirado",
                details={
                    "days_remaining": days_remaining,
                    "classification": classification,
                },
            )
        except socket.timeout:
            latency_ms = round((time.time() - start) * 1000, 1)
            logger.warning(
                f"Health check SSL: timeout al conectar a {domain}:443"
            )
            return HealthCheckResponse(
                service_name="ssl",
                is_available=False,
                latency_ms=latency_ms,
                error_message=f"Timeout: no se pudo conectar a {domain}:443 en 10 segundos",
            )
        except Exception as e:
            latency_ms = round((time.time() - start) * 1000, 1)
            logger.warning(f"Health check SSL: error al verificar certificado: {e}")
            return HealthCheckResponse(
                service_name="ssl",
                is_available=False,
                latency_ms=latency_ms,
                error_message=f"Error al verificar certificado SSL: {e}",
            )

    # =========================================================================
    # ESTADO GENERAL Y ALERTAS — Cálculo de umbrales y generación de alertas
    # =========================================================================

    def calculate_overall_status(
        self,
        os_metrics: OsMetricsResponse,
        health_checks: List[HealthCheckResponse],
        docker_metrics: List[ContainerMetricsResponse],
        scalability_metrics: Optional[ScalabilityMetricsResponse] = None,
    ) -> Tuple[str, List[AlertResponse]]:
        """
        Calcula el estado general del sistema y genera alertas por umbrales superados.

        Umbrales definidos:
        - Memoria > 80% → alerta severity "warning"
        - Disco > 85% → alerta severity "warning"
        - CPU > 90% → alerta severity "critical"
        - SSL < 14 días → alerta severity "warning"
        - Contenedor no running → alerta severity "warning"

        Umbrales de escalabilidad:
        - WebSocket total > 12000 → alerta severity "critical"
        - WebSocket total > 3000 → alerta severity "warning"
        - Memoria Python por workstation > 4 MB/ws → alerta severity "critical"
        - Memoria Python por workstation > 2 MB/ws → alerta severity "warning"
        - File descriptors > 80% → alerta severity "critical"
        - File descriptors > 60% → alerta severity "warning"
        - Pool BD > 80% → alerta severity "critical"
        - Pool BD > 60% → alerta severity "warning"
        - Tasa de transmisión de red > 80 MB/s → alerta severity "critical"
        - Tasa de transmisión de red > 50 MB/s → alerta severity "warning"

        Estado general:
        - "critical": si alguna alerta tiene severity "critical"
        - "degraded": si hay alertas pero ninguna es critical
        - "healthy": si no hay alertas

        Args:
            os_metrics: Métricas del sistema operativo
            health_checks: Lista de resultados de health checks
            docker_metrics: Lista de métricas de contenedores Docker
            scalability_metrics: Métricas de escalabilidad (opcional)

        Returns:
            Tupla (overall_status, alerts):
            - overall_status: "healthy", "degraded" o "critical"
            - alerts: lista de AlertResponse con las alertas generadas
        """
        alerts: List[AlertResponse] = []

        # Verificar umbral de memoria: > 80% genera alerta warning
        if os_metrics.memory_percent > 80.0:
            alerts.append(AlertResponse(
                metric_name="memory",
                current_value=os_metrics.memory_percent,
                threshold=80.0,
                severity="warning",
            ))

        # Verificar umbral de disco: > 85% genera alerta warning
        if os_metrics.disk_percent > 85.0:
            alerts.append(AlertResponse(
                metric_name="disk",
                current_value=os_metrics.disk_percent,
                threshold=85.0,
                severity="warning",
            ))

        # Verificar umbral de CPU: > 90% genera alerta critical
        if os_metrics.cpu_percent > 90.0:
            alerts.append(AlertResponse(
                metric_name="cpu",
                current_value=os_metrics.cpu_percent,
                threshold=90.0,
                severity="critical",
            ))

        # Verificar umbral de SSL: < 14 días genera alerta warning
        for check in health_checks:
            if check.service_name == "ssl" and check.details:
                days_remaining = check.details.get("days_remaining")
                if days_remaining is not None and days_remaining < 14:
                    alerts.append(AlertResponse(
                        metric_name="ssl",
                        current_value=float(days_remaining),
                        threshold=14.0,
                        severity="warning",
                    ))

        # Contenedores del sistema que no generan alertas (no son parte de la aplicación)
        _EXCLUDED_CONTAINERS = {"ecs-agent", "amazon-ssm-agent", "aws-otel-collector"}

        # Verificar contenedores no running: genera alerta warning por cada uno
        # (excluye contenedores del sistema que pueden estar detenidos normalmente)
        for container in docker_metrics:
            if container.status != "running":
                # No alertar por contenedores del sistema
                if container.name in _EXCLUDED_CONTAINERS:
                    continue
                alerts.append(AlertResponse(
                    metric_name=f"container_{container.name}",
                    current_value=0.0,
                    threshold=0.0,
                    severity="warning",
                ))

        # === MÉTRICAS DE ESCALABILIDAD ===
        # Verificar umbrales de las métricas de escalabilidad si están disponibles
        if scalability_metrics is not None:
            # WebSocket total: > 12000 critical, > 8000 warning
            if scalability_metrics.websocket is not None:
                ws_total = scalability_metrics.websocket.total
                if ws_total > 12000:
                    alerts.append(AlertResponse(
                        metric_name="ws_connections",
                        current_value=float(ws_total),
                        threshold=12000.0,
                        severity="critical",
                    ))
                elif ws_total > 8000:
                    alerts.append(AlertResponse(
                        metric_name="ws_connections",
                        current_value=float(ws_total),
                        threshold=8000.0,
                        severity="warning",
                    ))

            # Memoria Python por workstation: > 4 MB/ws critical, > 2 MB/ws warning
            # Solo evaluar si hay al menos 10 workstations conectadas (con pocas ws
            # el promedio no es representativo — incluye warm-up y caches del framework)
            if scalability_metrics.python_memory is not None:
                avg_mem = scalability_metrics.python_memory.avg_per_workstation_mb
                ws_count = (scalability_metrics.websocket.total
                            if scalability_metrics.websocket else 0)
                if avg_mem is not None and avg_mem > 0 and ws_count >= 10:
                    if avg_mem > 4.0:
                        alerts.append(AlertResponse(
                            metric_name="memory_per_ws",
                            current_value=avg_mem,
                            threshold=4.0,
                            severity="critical",
                        ))
                    elif avg_mem > 2.0:
                        alerts.append(AlertResponse(
                            metric_name="memory_per_ws",
                            current_value=avg_mem,
                            threshold=2.0,
                            severity="warning",
                        ))

            # File descriptors: > 80% critical, > 60% warning
            if scalability_metrics.file_descriptors is not None:
                fd_pct = scalability_metrics.file_descriptors.usage_percent
                if fd_pct is not None:
                    if fd_pct > 80.0:
                        alerts.append(AlertResponse(
                            metric_name="file_descriptors",
                            current_value=fd_pct,
                            threshold=80.0,
                            severity="critical",
                        ))
                    elif fd_pct > 60.0:
                        alerts.append(AlertResponse(
                            metric_name="file_descriptors",
                            current_value=fd_pct,
                            threshold=60.0,
                            severity="warning",
                        ))

            # Pool de BD: > 80% critical, > 60% warning
            if scalability_metrics.db_pool is not None:
                pool_pct = scalability_metrics.db_pool.usage_percent
                if pool_pct is not None:
                    if pool_pct > 80.0:
                        alerts.append(AlertResponse(
                            metric_name="db_pool_usage",
                            current_value=pool_pct,
                            threshold=80.0,
                            severity="critical",
                        ))
                    elif pool_pct > 60.0:
                        alerts.append(AlertResponse(
                            metric_name="db_pool_usage",
                            current_value=pool_pct,
                            threshold=60.0,
                            severity="warning",
                        ))

            # Tasa de transmisión de red: > 80 MB/s critical, > 50 MB/s warning
            if scalability_metrics.network is not None:
                tx_rate = scalability_metrics.network.tx_rate_bps
                if tx_rate is not None:
                    # Convertir bytes/s a MB/s para comparar con umbrales
                    tx_rate_mbs = tx_rate / (1024 * 1024)
                    if tx_rate_mbs > 80.0:
                        alerts.append(AlertResponse(
                            metric_name="network_tx_rate",
                            current_value=round(tx_rate_mbs, 2),
                            threshold=80.0,
                            severity="critical",
                        ))
                    elif tx_rate_mbs > 50.0:
                        alerts.append(AlertResponse(
                            metric_name="network_tx_rate",
                            current_value=round(tx_rate_mbs, 2),
                            threshold=50.0,
                            severity="warning",
                        ))

        # Determinar estado general según severidad de alertas
        has_critical = any(alert.severity == "critical" for alert in alerts)

        if has_critical:
            overall_status = "critical"
        elif len(alerts) > 0:
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        return (overall_status, alerts)

    # =========================================================================
    # LIMPIEZA DE DATOS — Eliminación de registros antiguos
    # =========================================================================

    def cleanup_old_snapshots(self, db: Session) -> int:
        """
        Elimina snapshots con más de 90 días de antigüedad.

        Los registros asociados (MetricRecords, HealthCheckResults,
        ContainerMetrics) se eliminan automáticamente por CASCADE
        definido en las foreign keys.

        Se ejecuta durante cada ciclo de recolección para mantener
        la base de datos dentro del período de retención definido.

        Args:
            db: Sesión de SQLAlchemy activa

        Returns:
            Número de snapshots eliminados
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            deleted = db.query(StatusSnapshot).filter(
                StatusSnapshot.timestamp < cutoff
            ).delete()
            db.commit()
            logger.info(
                f"Limpieza de datos antiguos completada: {deleted} snapshots eliminados "
                f"(anteriores a {cutoff.isoformat()})"
            )
            return deleted
        except Exception as e:
            db.rollback()
            logger.error(f"Error durante la limpieza de datos antiguos: {e}")
            return 0

    async def collect_all(
        self, db: Session, ssl_domain: str = "apps.iol.pe"
    ) -> dict:
        """
        Orquesta la recolección completa de todas las métricas del sistema.

        Ejecuta en orden:
        1. Recolección de métricas del sistema operativo
        2. Recolección de métricas de contenedores Docker
        3. Verificación de health checks de servicios
        4. Cálculo de estado general y generación de alertas
        5. Recolección de métricas de escalabilidad

        Args:
            db: Sesión de SQLAlchemy para verificaciones de RDS
            ssl_domain: Dominio para verificar certificado SSL

        Returns:
            Diccionario con todos los datos recolectados:
            - os_metrics: OsMetricsResponse
            - docker_available: bool
            - docker_metrics: lista de ContainerMetricsResponse
            - health_checks: lista de HealthCheckResponse
            - health_summary: dict con conteos ok/warning/failed
            - overall_status: str (healthy/degraded/critical)
            - alerts: lista de AlertResponse
            - scalability_metrics: ScalabilityMetricsResponse o None
            - scalability_metrics_json: str (JSON serializado) o None
        """
        logger.info("Iniciando recolección completa de métricas del sistema")

        # 1. Recolectar métricas del sistema operativo
        os_metrics = self.collect_os_metrics()
        logger.info("Métricas del sistema operativo recolectadas correctamente")

        # 2. Recolectar métricas de contenedores Docker
        docker_available, docker_metrics = await self.collect_docker_metrics()
        if docker_available:
            logger.info(
                f"Métricas Docker recolectadas: {len(docker_metrics)} contenedores"
            )
        else:
            logger.warning("Docker no disponible, métricas de contenedores omitidas")

        # 3. Verificar health checks de servicios
        health_checks, health_summary = await self.collect_health_checks(
            db, ssl_domain=ssl_domain
        )
        logger.info(
            f"Health checks completados: {health_summary['ok_count']} OK, "
            f"{health_summary['warning_count']} warning, "
            f"{health_summary['failed_count']} fallidos"
        )

        # 4. Recolectar métricas de escalabilidad
        scalability_metrics = None
        scalability_metrics_json = None
        try:
            scalability_metrics = await scalability_collector.collect_all_metrics(db=db)
            # Serializar como JSON para persistencia en el snapshot
            scalability_metrics_json = scalability_metrics.model_dump_json()
            logger.info("Métricas de escalabilidad recolectadas correctamente")
        except Exception as e:
            logger.error(
                "Error en recolección de métricas de escalabilidad",
                extra={
                    "error_type": type(e).__name__,
                    "error_detail": str(e),
                },
            )
            scalability_metrics = None
            scalability_metrics_json = None

        # 5. Calcular estado general y generar alertas (incluye escalabilidad)
        overall_status, alerts = self.calculate_overall_status(
            os_metrics, health_checks, docker_metrics,
            scalability_metrics=scalability_metrics,
        )
        logger.info(
            f"Estado general del sistema: {overall_status} "
            f"({len(alerts)} alertas activas)"
        )

        return {
            "os_metrics": os_metrics,
            "docker_available": docker_available,
            "docker_metrics": docker_metrics,
            "health_checks": health_checks,
            "health_summary": health_summary,
            "overall_status": overall_status,
            "alerts": alerts,
            "scalability_metrics": scalability_metrics,
            "scalability_metrics_json": scalability_metrics_json,
        }

    # =========================================================================
    # PERSISTENCIA — Almacenamiento de snapshots en PostgreSQL
    # =========================================================================

    def save_snapshot(
        self,
        db: Session,
        os_metrics: OsMetricsResponse,
        docker_available: bool,
        docker_metrics: List[ContainerMetricsResponse],
        health_checks: List[HealthCheckResponse],
        overall_status: str,
        alerts: List[AlertResponse],
        timestamp: datetime,
        scalability_metrics_json: Optional[str] = None,
    ) -> Optional[StatusSnapshot]:
        """
        Persiste un snapshot completo en PostgreSQL con transacción atómica.

        Almacena el StatusSnapshot junto con sus MetricRecords,
        HealthCheckResults y ContainerMetrics en una sola transacción.
        Si falla cualquier parte de la escritura, se revierte toda la
        transacción para evitar datos parciales.

        Lógica de reintentos: hasta 3 intentos con 5 segundos entre cada uno
        si PostgreSQL no está disponible o la escritura falla.

        Args:
            db: Sesión de SQLAlchemy
            os_metrics: Métricas del sistema operativo recolectadas
            docker_available: Si Docker estaba disponible durante la recolección
            docker_metrics: Lista de métricas de contenedores Docker
            health_checks: Lista de resultados de health checks
            overall_status: Estado general calculado (healthy/degraded/critical)
            alerts: Lista de alertas generadas por umbrales superados
            timestamp: Momento de la recolección (UTC)

        Returns:
            StatusSnapshot creado si la persistencia fue exitosa, None si falló
            después de agotar todos los reintentos
        """
        max_intentos = 3
        intervalo_reintentos = 5  # segundos

        for intento in range(1, max_intentos + 1):
            try:
                snapshot = self._persist_snapshot_transaction(
                    db=db,
                    os_metrics=os_metrics,
                    docker_available=docker_available,
                    docker_metrics=docker_metrics,
                    health_checks=health_checks,
                    overall_status=overall_status,
                    timestamp=timestamp,
                    scalability_metrics_json=scalability_metrics_json,
                )
                logger.info(
                    f"Snapshot persistido correctamente en intento {intento} "
                    f"(id={snapshot.id})"
                )
                return snapshot

            except Exception as e:
                # Rollback completo para evitar datos parciales
                db.rollback()
                logger.error(
                    f"Error al persistir snapshot (intento {intento}/{max_intentos}): {e}"
                )

                if intento < max_intentos:
                    logger.info(
                        f"Reintentando en {intervalo_reintentos} segundos..."
                    )
                    time.sleep(intervalo_reintentos)
                else:
                    logger.error(
                        "Se agotaron todos los reintentos para persistir el snapshot. "
                        "Los datos se perderán en el próximo ciclo."
                    )

        return None

    def _persist_snapshot_transaction(
        self,
        db: Session,
        os_metrics: OsMetricsResponse,
        docker_available: bool,
        docker_metrics: List[ContainerMetricsResponse],
        health_checks: List[HealthCheckResponse],
        overall_status: str,
        timestamp: datetime,
        scalability_metrics_json: Optional[str] = None,
    ) -> StatusSnapshot:
        """
        Ejecuta la transacción atómica de persistencia del snapshot.

        Crea todos los objetos (snapshot, metric records, health checks,
        container metrics) y los añade a la sesión en una sola transacción.
        Si cualquier parte falla, la excepción se propaga para que el
        llamador ejecute el rollback.

        Args:
            db: Sesión de SQLAlchemy
            os_metrics: Métricas del sistema operativo
            docker_available: Si Docker estaba disponible
            docker_metrics: Métricas de contenedores Docker
            health_checks: Resultados de health checks
            overall_status: Estado general del sistema
            timestamp: Momento de la recolección

        Returns:
            StatusSnapshot creado y persistido

        Raises:
            Exception: Si falla cualquier parte de la escritura
        """
        # Crear el snapshot principal
        snapshot = StatusSnapshot(
            timestamp=timestamp,
            overall_status=OverallStatus(overall_status),
            memory_percent=os_metrics.memory_percent,
            memory_total_mb=os_metrics.memory_total_mb,
            memory_used_mb=os_metrics.memory_used_mb,
            memory_available_mb=os_metrics.memory_available_mb,
            disk_percent=os_metrics.disk_percent,
            disk_total_mb=os_metrics.disk_total_mb,
            disk_used_mb=os_metrics.disk_used_mb,
            disk_available_mb=os_metrics.disk_available_mb,
            cpu_percent=os_metrics.cpu_percent,
            swap_used_mb=os_metrics.swap_used_mb,
            swap_total_mb=os_metrics.swap_total_mb,
            swap_available_mb=os_metrics.swap_available_mb,
            uptime_seconds=os_metrics.uptime_seconds,
            docker_available=docker_available,
            scalability_metrics_json=scalability_metrics_json,
        )
        db.add(snapshot)
        # Flush para obtener el ID del snapshot sin hacer commit
        db.flush()

        # Crear MetricRecords para cada métrica del sistema operativo
        # Calcular porcentaje de swap (evitar división por cero)
        swap_percent = (
            round((os_metrics.swap_used_mb / os_metrics.swap_total_mb) * 100, 1)
            if os_metrics.swap_total_mb > 0
            else 0.0
        )

        metric_definitions = [
            ("memory_percent", os_metrics.memory_percent, "percent"),
            ("memory_total_mb", os_metrics.memory_total_mb, "mb"),
            ("memory_used_mb", os_metrics.memory_used_mb, "mb"),
            ("memory_available_mb", os_metrics.memory_available_mb, "mb"),
            ("disk_percent", os_metrics.disk_percent, "percent"),
            ("disk_total_mb", os_metrics.disk_total_mb, "mb"),
            ("disk_used_mb", os_metrics.disk_used_mb, "mb"),
            ("disk_available_mb", os_metrics.disk_available_mb, "mb"),
            ("cpu_percent", os_metrics.cpu_percent, "percent"),
            ("swap_percent", swap_percent, "percent"),
            ("swap_total_mb", os_metrics.swap_total_mb, "mb"),
            ("swap_used_mb", os_metrics.swap_used_mb, "mb"),
            ("swap_available_mb", os_metrics.swap_available_mb, "mb"),
            ("uptime_seconds", float(os_metrics.uptime_seconds), "seconds"),
        ]

        for metric_name, value, unit in metric_definitions:
            metric_record = MetricRecord(
                snapshot_id=snapshot.id,
                metric_name=metric_name,
                value=value,
                unit=unit,
                timestamp=timestamp,
            )
            db.add(metric_record)

        # Crear HealthCheckResults a partir de los health checks
        for check in health_checks:
            # Serializar detalles como JSON string si existen
            details_json_str = None
            if check.details is not None:
                details_json_str = json.dumps(check.details)

            health_result = HealthCheckResult(
                snapshot_id=snapshot.id,
                service_name=check.service_name,
                is_available=check.is_available,
                latency_ms=check.latency_ms,
                error_message=check.error_message,
                details_json=details_json_str,
                timestamp=timestamp,
            )
            db.add(health_result)

        # Crear ContainerMetrics a partir de las métricas Docker
        for container in docker_metrics:
            container_metric = ContainerMetric(
                snapshot_id=snapshot.id,
                container_name=container.name,
                status=container.status,
                cpu_percent=container.cpu_percent,
                memory_used_mb=container.memory_used_mb,
                memory_limit_mb=container.memory_limit_mb,
                network_rx_bytes=container.network_rx_bytes,
                network_tx_bytes=container.network_tx_bytes,
                uptime_seconds=container.uptime_seconds,
            )
            db.add(container_metric)

        # Crear MetricRecords para métricas de escalabilidad (historial)
        if scalability_metrics_json:
            try:
                import json as _json
                sm = _json.loads(scalability_metrics_json)

                # Conexiones WebSocket totales
                ws = sm.get("websocket")
                if ws and ws.get("data_available"):
                    db.add(MetricRecord(
                        snapshot_id=snapshot.id,
                        metric_name="ws_connections_total",
                        value=float(ws.get("total", 0)),
                        unit="count",
                        timestamp=timestamp,
                    ))

                # Memoria promedio por workstation (MB/ws)
                mem = sm.get("python_memory")
                if mem and mem.get("avg_per_workstation_mb") is not None:
                    db.add(MetricRecord(
                        snapshot_id=snapshot.id,
                        metric_name="memory_per_ws_mb",
                        value=float(mem["avg_per_workstation_mb"]),
                        unit="mb",
                        timestamp=timestamp,
                    ))

                # RSS del proceso Python (MB)
                if mem and mem.get("rss_mb") is not None:
                    db.add(MetricRecord(
                        snapshot_id=snapshot.id,
                        metric_name="python_rss_mb",
                        value=float(mem["rss_mb"]),
                        unit="mb",
                        timestamp=timestamp,
                    ))

                # File descriptors (%)
                fd = sm.get("file_descriptors")
                if fd and fd.get("usage_percent") is not None:
                    db.add(MetricRecord(
                        snapshot_id=snapshot.id,
                        metric_name="fd_usage_percent",
                        value=float(fd["usage_percent"]),
                        unit="percent",
                        timestamp=timestamp,
                    ))

                # Pool de BD (%)
                pool = sm.get("db_pool")
                if pool and pool.get("usage_percent") is not None:
                    db.add(MetricRecord(
                        snapshot_id=snapshot.id,
                        metric_name="db_pool_percent",
                        value=float(pool["usage_percent"]),
                        unit="percent",
                        timestamp=timestamp,
                    ))

                # Tasa de transmisión de red (MB/s)
                net = sm.get("network")
                if net and net.get("tx_rate_bps") is not None:
                    tx_mbs = round(net["tx_rate_bps"] / (1024 * 1024), 2)
                    db.add(MetricRecord(
                        snapshot_id=snapshot.id,
                        metric_name="network_tx_mbs",
                        value=tx_mbs,
                        unit="mbs",
                        timestamp=timestamp,
                    ))
            except Exception:
                # Si falla el parseo de métricas de escalabilidad, no interrumpir la persistencia
                pass

        # Commit atómico: todo o nada
        db.commit()
        # Refrescar para obtener relaciones cargadas
        db.refresh(snapshot)

        return snapshot
