"""
Servicio de restauración de backup para migración entre cuentas AWS.

Descarga los 2 archivos ZIP (BD + imágenes) previamente subidos a S3
por el frontend, los valida, limpia la BD, restaura tabla por tabla
respetando FK, sube imágenes al bucket de destino, y reconstruye URLs.

Estructura esperada en S3:
  s3://{S3_ARTIFACTS_BUCKET}/backups/restore-upload/db.zip
  s3://{S3_ARTIFACTS_BUCKET}/backups/restore-upload/images.zip
  s3://{S3_ARTIFACTS_BUCKET}/backups/restore_status.json  — Estado del proceso
"""

import io
import json
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import boto3
import psutil
import pyzipper
from botocore.exceptions import ClientError
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import (
    ActionConfig,
    AuditLog,
    ConnectivityResult,
    ContainerMetric,
    DebuggingProfile,
    DebuggingSession,
    Device,
    Document,
    GlobalConfig,
    HealthCheckResult,
    KnowledgeArticle,
    License,
    LogAnalysis,
    Message,
    MessageDelivery,
    MetricRecord,
    Organization,
    PublicIP,
    StatusSnapshot,
    TelemetryLog,
    User,
    VLAN,
    VLANConfig,
    Workstation,
    WorkstationConfig,
)
from app.models.audit import ActionType
from app.models.debugging import DebuggingSessionStatus
from app.models.knowledge_article import profile_knowledge_articles
from app.models.message import DeliveryMode, TargetType
from app.models.message_delivery import DeliveryStatus
from app.models.system_status import OverallStatus
from app.models.user import UserRole

logger = logging.getLogger(__name__)


# === MAPEO DE TABLAS A MODELOS (ORDEN DE DEPENDENCIAS FK) ===

TABLE_MODEL_MAP: list[tuple[str, Any]] = [
    ("organizations", Organization),
    ("users", User),
    ("vlans", VLAN),
    ("devices", Device),
    ("workstations", Workstation),
    ("licenses", License),
    ("global_configs", GlobalConfig),
    ("vlan_configs", VLANConfig),
    ("workstation_configs", WorkstationConfig),
    ("action_configs", ActionConfig),
    ("public_ips", PublicIP),
    ("messages", Message),
    ("message_deliveries", MessageDelivery),
    ("telemetry_logs", TelemetryLog),
    ("connectivity_results", ConnectivityResult),
    ("audit_logs", AuditLog),
    ("documents", Document),
    ("debugging_profiles", DebuggingProfile),
    ("knowledge_articles", KnowledgeArticle),
    ("profile_knowledge_articles", profile_knowledge_articles),
    ("debugging_sessions", DebuggingSession),
    ("log_analyses", LogAnalysis),
    ("status_snapshots", StatusSnapshot),
    ("metric_records", MetricRecord),
    ("health_check_results", HealthCheckResult),
    ("container_metrics", ContainerMetric),
]

# Orden de tablas para inserción (misma lista, solo nombres)
TABLE_ORDER = [name for name, _ in TABLE_MODEL_MAP]

# Mapeo de nombre de tabla → modelo/tabla para acceso rápido
TABLE_NAME_TO_MODEL: dict[str, Any] = {name: model for name, model in TABLE_MODEL_MAP}

# === MAPEO DE ENUMS POR COLUMNA ===
# Mapea (tabla, columna) → clase Enum para conversión durante restore
ENUM_MAP: dict[tuple[str, str], type] = {
    ("users", "role"): UserRole,
    ("audit_logs", "action_type"): ActionType,
    ("messages", "target_type"): TargetType,
    ("messages", "delivery_mode"): DeliveryMode,
    ("message_deliveries", "status"): DeliveryStatus,
    ("debugging_sessions", "status"): DebuggingSessionStatus,
    ("status_snapshots", "overall_status"): OverallStatus,
    ("health_check_results", "status"): OverallStatus,
}


class RestoreService:
    """
    Servicio de restauración desde backup.

    Descarga ZIPs subidos por el usuario a S3, los valida, limpia la BD,
    inserta registros tabla por tabla respetando FK, sube imágenes al bucket
    de destino, y reconstruye URLs de imágenes. El progreso se persiste en S3.
    """

    STAGES = [
        ("validating", "Validando archivos", 0, 10),
        ("cleaning", "Limpiando base de datos", 10, 15),
        ("restoring_db", "Restaurando base de datos", 15, 70),
        ("restoring_images", "Restaurando imágenes", 70, 85),
        ("rebuilding_urls", "Reconstruyendo URLs de imágenes", 85, 90),
        ("verifying", "Verificando integridad", 90, 100),
    ]

    # Un dict de Python con claves cortas + valores string/UUID suele pesar
    # 3-5x su tamaño en JSON crudo (overhead de objetos CPython) — usamos 4x
    # como estimado conservador, no es un cálculo exacto.
    JSON_TO_PYTHON_MEMORY_RATIO = 4
    # No usar más del 50% de la RAM disponible para cargar una sola tabla —
    # deja margen para el resto del proceso (otros workers, buffers de la
    # conexión a la BD) y para el margen de error del estimado de arriba.
    MAX_TABLE_MEMORY_FRACTION = 0.5

    def __init__(self):
        """Inicializa clientes S3 con la configuración del proyecto."""
        session = boto3.Session(
            region_name=settings.AWS_REGION,
            profile_name=settings.AWS_PROFILE or None,
        )
        self._s3 = session.client("s3")
        self._artifacts_bucket = settings.S3_ARTIFACTS_BUCKET
        self._docs_bucket = settings.S3_DOCS_BUCKET

    # =========================================================================
    # MÉTODO PRINCIPAL
    # =========================================================================

    def restore(self, password: Optional[str] = None) -> None:
        """
        Ejecuta la restauración completa.

        Sin código async real adentro (SQLAlchemy y boto3 son síncronos) — el
        endpoint la lanza en un thread aparte (loop.run_in_executor) en vez de
        asyncio.create_task, para no bloquear el event loop del servidor entero
        mientras dura (puede ser minutos con backups grandes).

        Etapas:
        1. Descarga ZIPs desde S3 (restore-upload/)
        2. Valida password, estructura e integridad
        3. Valida compatibilidad de Alembic revision
        4. Limpia BD (TRUNCATE CASCADE o delete en orden inverso)
        5. Inserta registros tabla por tabla en orden FK
        6. Sube imágenes al bucket de docs
        7. Reconstruye URLs de imágenes en VLANs
        8. Verifica integridad (conteos vs manifest)
        9. Limpia archivos temporales de restore-upload/

        Si falla después de la limpieza, hace TRUNCATE de todas las tablas.
        """
        cleaning_done = False

        logger.info("#" * 60)
        logger.info("#### INICIO RESTORE ####")
        logger.info("#" * 60)

        try:
            logger.info("Iniciando proceso de restauración...")
            self._update_restore_status("restoring", "Descargando archivos", 0)

            # --- Descargar ZIPs desde S3 ---
            db_zip_bytes = self._download_restore_file("backups/restore-upload/db.zip")
            images_zip_bytes = self._download_restore_file("backups/restore-upload/images.zip")

            if db_zip_bytes is None:
                raise ValueError("No se encontró db.zip en S3 (backups/restore-upload/db.zip)")
            if images_zip_bytes is None:
                raise ValueError("No se encontró images.zip en S3 (backups/restore-upload/images.zip)")

            logger.info(
                "ZIPs descargados: db.zip=%d bytes, images.zip=%d bytes",
                len(db_zip_bytes), len(images_zip_bytes),
            )

            # --- Etapa 1: Validar ZIPs ---
            logger.info("[1/6] Validando archivos (password, estructura, integridad)...")
            self._update_restore_status(
                "restoring", self.STAGES[0][1], self.STAGES[0][2]
            )

            # Validar estructura del DB_ZIP — solo manifest.json es obligatorio.
            # Los .json de cada tabla son opcionales: _extract_table() ya trata
            # una tabla ausente como vacía (con warning), así que no tiene sentido
            # abortar el restore completo por, ej., un telemetry_logs.json faltante.
            self._validate_zip(db_zip_bytes, password, ["manifest.json"])

            # Extraer manifest y validar que tenga los campos esperados (version, tables, total_records)
            manifest = self._extract_manifest(db_zip_bytes, password)
            self._validate_manifest_fields(manifest, "db")

            # Validar compatibilidad de Alembic revision
            self._validate_alembic_compatibility(manifest)

            # Validar Images_ZIP (al menos manifest.json) y sus campos (version, files)
            self._validate_zip(images_zip_bytes, password, ["manifest.json"])
            images_manifest = self._extract_images_manifest(images_zip_bytes, password)
            self._validate_manifest_fields(images_manifest, "images")

            logger.info("Validación OK: %d registros esperados según manifest", manifest.get("total_records", 0))

            # --- Etapa 2: Limpiar BD ---
            logger.info("[2/6] Limpiando base de datos...")
            self._update_restore_status(
                "restoring", self.STAGES[1][1], self.STAGES[1][2]
            )

            db = SessionLocal()
            try:
                self._clean_database(db)
                db.commit()
                cleaning_done = True
            finally:
                db.close()
            logger.info("Base de datos limpiada")

            # --- Etapa 3: Restaurar BD tabla por tabla ---
            # Cada tabla se extrae del ZIP dentro del mismo loop de inserción, una
            # a la vez (no las 26 de golpe antes de insertar la primera): con
            # backups de ~1.6M registros, acumular todo el JSON parseado en
            # memoria antes de tocar la BD puede exceder la RAM del worker y
            # matarlo a mitad de restore, dejando la BD truncada y vacía.
            logger.info("[3/6] Restaurando base de datos tabla por tabla...")
            self._update_restore_status(
                "restoring", self.STAGES[2][1], self.STAGES[2][2]
            )

            restored_counts: dict[str, int] = {}
            tables_detail: list[dict[str, Any]] = []
            missing_tables: set[str] = set()

            db = SessionLocal()
            try:
                # Deshabilitar FK constraints durante la inserción: vlans.default_device_id
                # → devices.id y devices.vlan_id → vlans.id son una dependencia circular
                # imposible de resolver solo con el orden de TABLE_ORDER.
                if not settings.is_sqlite:
                    db.execute(text("SET session_replication_role = 'replica'"))

                total_tables = len(TABLE_ORDER)
                with pyzipper.AESZipFile(io.BytesIO(db_zip_bytes), "r") as zf:
                    if password:
                        zf.setpassword(password.encode("utf-8"))
                    for idx, table_name in enumerate(TABLE_ORDER):
                        self._check_memory_budget(zf, table_name)
                        records = self._extract_table(zf, table_name, missing_tables)
                        count = self._restore_table(db, table_name, records)
                        del records
                        restored_counts[table_name] = count
                        tables_detail.append({"table": table_name, "count": count})

                        # Actualizar progreso proporcionalmente entre 15% y 70%
                        stage_progress = self.STAGES[2][2] + int(
                            (idx + 1) / total_tables * (self.STAGES[2][3] - self.STAGES[2][2])
                        )
                        logger.info(
                            "  (%d/%d) %s: %d registros [%d%%]",
                            idx + 1, total_tables, table_name, count, stage_progress,
                        )
                        self._update_restore_status(
                            "restoring",
                            f"Restaurando: {table_name} ({count} registros)",
                            stage_progress,
                            extra={
                                "tables_total": total_tables,
                                "tables_done": idx + 1,
                                "current_table": table_name,
                                "tables_detail": tables_detail,
                            },
                        )

                # Re-habilitar FK constraints antes del commit final
                if not settings.is_sqlite:
                    db.execute(text("SET session_replication_role = 'origin'"))
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
            logger.info(
                "Base de datos restaurada: %d tablas, %d registros",
                len(restored_counts), sum(restored_counts.values()),
            )

            # --- Etapa 4: Restaurar imágenes ---
            logger.info("[4/6] Restaurando imágenes...")
            self._update_restore_status(
                "restoring", self.STAGES[3][1], self.STAGES[3][2]
            )
            uploaded_images = self._upload_images_to_s3(images_zip_bytes, password)
            logger.info("Imágenes restauradas: %d", uploaded_images)

            # --- Etapa 5: Reconstruir URLs ---
            logger.info("[5/6] Reconstruyendo URLs de imágenes...")
            self._update_restore_status(
                "restoring", self.STAGES[4][1], self.STAGES[4][2]
            )

            db = SessionLocal()
            try:
                self._rebuild_image_urls(db)
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

            # --- Etapa 6: Verificar integridad ---
            logger.info("[6/6] Verificando integridad...")
            self._update_restore_status(
                "restoring", self.STAGES[5][1], self.STAGES[5][2]
            )

            db = SessionLocal()
            try:
                self._verify_integrity(db, manifest, restored_counts, missing_tables)
            finally:
                db.close()
            logger.info("Verificación de integridad OK")

            # --- Finalizar: Limpiar archivos temporales y actualizar status ---
            self._cleanup_restore_uploads()

            completed_at = datetime.now(timezone.utc).isoformat()
            self._update_restore_status(
                "completed",
                stage=None,
                progress=100,
                error=None,
                extra={
                    "completed_at": completed_at,
                    "tables_restored": len(restored_counts),
                    "total_records": sum(restored_counts.values()),
                    "images_uploaded": uploaded_images,
                },
            )

            logger.info(
                "Restauración completada exitosamente: %d tablas, %d registros, %d imágenes",
                len(restored_counts),
                sum(restored_counts.values()),
                uploaded_images,
            )
            logger.info("#" * 60)
            logger.info("#### FIN RESTORE — OK ####")
            logger.info("#" * 60)

        except Exception as e:
            logger.error("Error en restauración: %s", str(e), exc_info=True)

            # Si ya se limpió la BD y falló después, hacer TRUNCATE total
            if cleaning_done:
                try:
                    logger.warning("Fallo post-limpieza, ejecutando TRUNCATE de seguridad...")
                    db = SessionLocal()
                    try:
                        self._clean_database(db)
                        db.commit()
                    finally:
                        db.close()
                except Exception as cleanup_err:
                    logger.error(
                        "Error adicional durante TRUNCATE de seguridad: %s",
                        str(cleanup_err),
                    )

            self._update_restore_status("failed", stage=None, progress=None, error=str(e))
            logger.info("#" * 60)
            logger.info("#### FIN RESTORE — FAILED ####")
            logger.info("#" * 60)

    # =========================================================================
    # DESCARGA DE ARCHIVOS DESDE S3
    # =========================================================================

    def _download_restore_file(self, key: str) -> Optional[bytes]:
        """
        Descarga un archivo del bucket de artifacts.

        Args:
            key: Key del archivo en S3.

        Returns:
            Bytes del archivo, o None si no existe.
        """
        try:
            response = self._s3.get_object(
                Bucket=self._artifacts_bucket,
                Key=key,
            )
            return response["Body"].read()
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("NoSuchKey", "404"):
                return None
            raise

    # =========================================================================
    # VALIDACIÓN DE ZIPs
    # =========================================================================

    def _validate_zip(
        self,
        zip_bytes: bytes,
        password: Optional[str],
        expected_files: list[str],
    ) -> None:
        """
        Valida un archivo ZIP: verifica password, estructura e integridad.

        Args:
            zip_bytes: Contenido del ZIP.
            password: Password para descifrarlo (None = sin cifrado).
            expected_files: Lista de archivos esperados dentro del ZIP.

        Raises:
            ValueError: Si password es incorrecto, estructura inválida o ZIP corrupto.
        """
        import io

        try:
            buffer = io.BytesIO(zip_bytes)
            with pyzipper.AESZipFile(buffer, "r") as zf:
                if password:
                    zf.setpassword(password.encode("utf-8"))

                # Verificar que se puede leer (password correcto)
                namelist = zf.namelist()

                # Verificar estructura: todos los archivos esperados deben existir
                missing = [f for f in expected_files if f not in namelist]
                if missing:
                    raise ValueError(
                        f"Estructura inválida del ZIP. Archivos faltantes: {', '.join(missing)}"
                    )

                # Verificar integridad: intentar leer el primer archivo
                test_file = expected_files[0]
                zf.read(test_file)

        except RuntimeError as e:
            # pyzipper lanza RuntimeError para password incorrecto
            if "password" in str(e).lower() or "Bad password" in str(e):
                raise ValueError(
                    "Contraseña incorrecta. No se puede abrir el archivo ZIP."
                ) from e
            raise ValueError(f"Error al validar ZIP: {str(e)}") from e
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f"ZIP corrupto o ilegible: {str(e)}") from e

    def _extract_manifest(self, db_zip_bytes: bytes, password: Optional[str]) -> dict:
        """
        Extrae y parsea manifest.json del DB_ZIP.

        Returns:
            Diccionario con el contenido del manifest.
        """
        return self._read_manifest_json(db_zip_bytes, password, "db.zip")

    def _extract_images_manifest(self, images_zip_bytes: bytes, password: Optional[str]) -> dict:
        """
        Extrae y parsea manifest.json del Images_ZIP.

        Returns:
            Diccionario con el contenido del manifest.
        """
        return self._read_manifest_json(images_zip_bytes, password, "images.zip")

    def _read_manifest_json(
        self, zip_bytes: bytes, password: Optional[str], filename: str
    ) -> dict:
        """Lee manifest.json de un ZIP y lo parsea, con mensaje de error claro si el JSON es inválido."""
        import io

        buffer = io.BytesIO(zip_bytes)
        with pyzipper.AESZipFile(buffer, "r") as zf:
            if password:
                zf.setpassword(password.encode("utf-8"))
            manifest_bytes = zf.read("manifest.json")

        try:
            return json.loads(manifest_bytes.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"{filename} inválido: manifest.json no es JSON válido ({e}).") from e

    def _validate_manifest_fields(self, manifest: dict, kind: str) -> None:
        """
        Valida que el manifest tenga los campos requeridos con el tipo correcto.

        Args:
            manifest: Diccionario ya parseado del manifest.json.
            kind: "db" o "images" — determina qué campos son obligatorios.

        Raises:
            ValueError: Con mensaje específico del campo faltante o inválido.
        """
        filename = "db.zip" if kind == "db" else "images.zip"

        if not isinstance(manifest.get("version"), str):
            raise ValueError(
                f"{filename} inválido: manifest.json no tiene campo 'version' válido."
            )

        if kind == "db":
            if not isinstance(manifest.get("tables"), dict):
                raise ValueError(
                    f"{filename} inválido: manifest.json no tiene campo 'tables' válido. "
                    "No es un backup de base de datos."
                )
            if not isinstance(manifest.get("total_records"), int):
                raise ValueError(
                    f"{filename} inválido: manifest.json no tiene campo 'total_records' válido."
                )
        else:
            if not isinstance(manifest.get("files"), list):
                raise ValueError(
                    f"{filename} inválido: manifest.json no tiene campo 'files' válido. "
                    "No es un backup de imágenes."
                )

    def _validate_alembic_compatibility(self, manifest: dict) -> None:
        """
        Valida que la revisión de Alembic del backup es compatible con la BD actual.

        Compara manifest.alembic_revision con la revisión actual en la BD.
        Si no coinciden, aborta la restauración.
        """
        backup_revision = manifest.get("alembic_revision")
        if not backup_revision:
            logger.warning(
                "El manifest no incluye alembic_revision — omitiendo validación de compatibilidad"
            )
            return

        current_revision = self._get_alembic_head()
        if not current_revision:
            logger.warning(
                "No se pudo obtener la revisión actual de Alembic — omitiendo validación"
            )
            return

        if backup_revision != current_revision:
            raise ValueError(
                f"Incompatibilidad de schema: el backup fue generado con revisión "
                f"'{backup_revision}' pero la BD actual está en '{current_revision}'. "
                f"Ejecute las migraciones necesarias antes de restaurar."
            )

        logger.info("Compatibilidad de Alembic verificada: %s", current_revision)

    def _get_alembic_head(self) -> Optional[str]:
        """
        Obtiene la revisión actual de Alembic desde la tabla alembic_version.

        Returns:
            String con la revision head, o None si no se puede determinar.
        """
        db = SessionLocal()
        try:
            result = db.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )
            row = result.fetchone()
            if row:
                return row[0]
            return None
        except Exception as e:
            logger.warning("No se pudo obtener revisión de Alembic: %s", str(e))
            return None
        finally:
            db.close()

    # =========================================================================
    # LIMPIEZA DE BD
    # =========================================================================

    def _clean_database(self, db: Session) -> None:
        """
        Limpia toda la BD antes del restore.

        Para PostgreSQL: usa TRUNCATE ... CASCADE en todas las tablas.
        Para SQLite: elimina datos en orden inverso de FK.
        """
        if settings.is_sqlite:
            # SQLite no soporta TRUNCATE CASCADE — eliminar en orden inverso
            self._clean_database_sqlite(db)
        else:
            # PostgreSQL: TRUNCATE CASCADE eficiente
            self._clean_database_postgresql(db)

    def _clean_database_postgresql(self, db: Session) -> None:
        """
        Limpia BD PostgreSQL con TRUNCATE CASCADE.

        Antes de TRUNCATE, termina cualquier otra conexión abierta a la BD
        (mismo patrón que factory_reset en backup.py). Sin esto, una conexión
        "idle in transaction" (ej. un request anterior que dejó una sesión sin
        cerrar) puede bloquear el TRUNCATE indefinidamente esperando el lock.
        """
        import time

        db.execute(text(
            "SELECT pg_terminate_backend(pid) "
            "FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid != pg_backend_pid()"
        ))
        db.commit()
        time.sleep(0.5)

        table_names = [name for name in TABLE_ORDER if name != "profile_knowledge_articles"]
        # Incluir tabla de asociación
        table_names.append("profile_knowledge_articles")

        # TRUNCATE todas las tablas de una vez (más eficiente y maneja FK)
        tables_str = ", ".join(table_names)
        db.execute(text(f"TRUNCATE TABLE {tables_str} CASCADE"))
        logger.info("TRUNCATE CASCADE ejecutado en %d tablas", len(table_names))

    def _clean_database_sqlite(self, db: Session) -> None:
        """Limpia BD SQLite eliminando datos en orden inverso de FK."""
        # Desactivar FK temporalmente para poder eliminar sin problemas
        db.execute(text("PRAGMA foreign_keys=OFF"))

        for table_name in reversed(TABLE_ORDER):
            db.execute(text(f"DELETE FROM {table_name}"))
            logger.debug("Eliminados registros de tabla %s (SQLite)", table_name)

        # Reactivar FK
        db.execute(text("PRAGMA foreign_keys=ON"))
        logger.info("Limpieza SQLite completada: %d tablas", len(TABLE_ORDER))

    # =========================================================================
    # EXTRACCIÓN DE DATOS DEL ZIP
    # =========================================================================

    def _check_memory_budget(self, zf: "pyzipper.AESZipFile", table_name: str) -> None:
        """
        Aborta con un error claro si no hay RAM suficiente para cargar esta
        tabla completa, en vez de intentarlo y arriesgarse a que el kernel
        mate el worker sin avisar (OOM-kill).

        Un OOM-kill real no se puede "atrapar": el proceso muere de golpe, sin
        ejecutar ningún except, dejando restore_status.json congelado en
        "restoring" para siempre (así quedó dev el 2026-08-25 con
        telemetry_logs). La única forma de convertir eso en un error visible
        es adelantarse: chequear el tamaño de la tabla contra la RAM
        disponible ANTES de leerla, y fallar de forma controlada si no entra.
        Esta excepción la atrapa el except general de restore() más abajo,
        que ya marca status="failed" con el motivo y limpia la BD.

        No aplica a SQLite (tests locales) ni si la tabla no está en el ZIP.
        """
        if settings.is_sqlite:
            return
        try:
            info = zf.getinfo(f"{table_name}.json")
        except KeyError:
            return  # tabla ausente del ZIP — _extract_table ya lo maneja

        estimated_bytes = info.file_size * self.JSON_TO_PYTHON_MEMORY_RATIO
        available_bytes = psutil.virtual_memory().available
        budget_bytes = available_bytes * self.MAX_TABLE_MEMORY_FRACTION

        if estimated_bytes > budget_bytes:
            raise MemoryError(
                f"No hay memoria suficiente para restaurar la tabla '{table_name}': "
                f"pesa {info.file_size / 1024 / 1024:.0f}MB sin comprimir "
                f"(~{estimated_bytes / 1024 / 1024:.0f}MB estimados en memoria), "
                f"pero el presupuesto seguro es {budget_bytes / 1024 / 1024:.0f}MB "
                f"({available_bytes / 1024 / 1024:.0f}MB disponibles en el sistema). "
                f"Excluí esta tabla del backup (tablas opcionales) o restaurá en una "
                f"instancia con más RAM."
            )

    def _extract_table(
        self, zf: "pyzipper.AESZipFile", table_name: str, missing_tables: set[str]
    ) -> list[dict]:
        """
        Extrae y parsea el JSON de una sola tabla desde el ZIP ya abierto.

        Se llama una tabla a la vez desde el loop de restauración (ver
        `restore()`), no de una sola vez para las 26 tablas, para no acumular
        ~1.6M registros en memoria antes de empezar a insertar.
        """
        filename = f"{table_name}.json"
        try:
            raw = zf.read(filename)
        except KeyError:
            # Tabla no encontrada en el ZIP — se asume excluida a propósito
            logger.warning(
                "Tabla %s no encontrada en el ZIP — se omite (0 registros)", table_name
            )
            missing_tables.add(table_name)
            return []
        return json.loads(raw.decode("utf-8"))

    # =========================================================================
    # RESTAURACIÓN DE TABLAS
    # =========================================================================

    def _restore_table(self, db: Session, table_name: str, records: list[dict]) -> int:
        """
        Inserta registros en una tabla con conversión de tipos.

        Para tablas ORM regulares, usa db.execute(insert(model.__table__)).
        Para tablas de asociación (profile_knowledge_articles), usa db.execute(insert(table)).

        Args:
            db: Sesión de SQLAlchemy.
            table_name: Nombre de la tabla.
            records: Lista de dicts con los datos a insertar.

        Returns:
            Cantidad de registros insertados.
        """
        if not records:
            return 0

        model_or_table = TABLE_NAME_TO_MODEL.get(table_name)
        if model_or_table is None:
            logger.warning("Tabla %s no tiene modelo asociado — omitiendo", table_name)
            return 0

        if table_name == "profile_knowledge_articles":
            # Tabla de asociación (SQLAlchemy Table, no modelo ORM)
            return self._restore_association_table(db, model_or_table, records)
        else:
            # Tabla ORM regular
            return self._restore_orm_table(db, table_name, model_or_table, records)

    def _restore_orm_table(
        self, db: Session, table_name: str, model_class, records: list[dict]
    ) -> int:
        """
        Inserta registros en una tabla ORM con conversión de tipos.

        Detecta columnas UUID, datetime y Enum usando SQLAlchemy inspect,
        y convierte los valores string del JSON a los tipos nativos.
        """
        from app.models.audit import GUID as AuditGUID

        mapper = inspect(model_class)
        column_info = {}

        for col in mapper.columns:
            col_type = type(col.type)
            # Detectar tipo GUID (UUID)
            is_guid = col_type.__name__ == "GUID" or hasattr(col.type, "impl")
            # Verificar si es DateTime
            is_datetime = col_type.__name__ in ("DateTime",)
            # Verificar si es Enum
            is_enum = col_type.__name__ in ("Enum",)

            # Verificar GUID de forma más robusta
            try:
                from sqlalchemy import TypeDecorator
                if isinstance(col.type, TypeDecorator):
                    is_guid = True
            except ImportError:
                pass

            column_info[col.key] = {
                "is_guid": is_guid,
                "is_datetime": is_datetime,
                "is_enum": is_enum,
                "nullable": col.nullable,
            }

        # Buscar enums aplicables a esta tabla
        table_enums = {
            col_name: enum_class
            for (tbl, col_name), enum_class in ENUM_MAP.items()
            if tbl == table_name
        }

        if not records:
            return 0

        table = model_class.__table__
        batch_size = 500
        total = 0
        # Convierte e inserta en lotes sin armar antes una segunda lista con la
        # tabla entera convertida — eso duplicaba en memoria una tabla que ya
        # puede ser grande de por sí (records viene de _extract_table, ya
        # materializada completa desde el JSON del backup). Además vamos
        # "pop"-eando records al procesar cada lote para que Python libere
        # cada dict ya insertado en vez de mantener la lista completa hasta
        # terminar toda la tabla. El orden de inserción no importa: las FK
        # quedan deshabilitadas (session_replication_role='replica') durante
        # toda la etapa 3 del restore.
        # ponytail: esto reduce el pico de memoria a ~2x el tamaño de la tabla
        # (JSON parseado + un lote de 500), no lo elimina — una tabla cuyo
        # JSON parseado por sí solo ya no entra en RAM (ver incidente OOM con
        # telemetry_logs) necesita parseo incremental del ZIP (ijson) o pasar
        # el backup a JSONL, no solo esto.
        records.reverse()
        while records:
            batch = []
            for _ in range(min(batch_size, len(records))):
                batch.append(self._convert_record(records.pop(), column_info, table_enums))
            db.execute(table.insert(), batch)
            total += len(batch)

        logger.debug("Restaurada tabla %s: %d registros", table_name, total)
        return total

    def _convert_record(
        self, record: dict, column_info: dict[str, dict], table_enums: dict[str, type]
    ) -> dict:
        """Convierte un registro (dict crudo del JSON) a tipos nativos según column_info."""
        converted = {}
        for key, value in record.items():
            if key not in column_info:
                # Columna no existe en el modelo actual — omitir
                continue

            info = column_info[key]

            if value is None:
                converted[key] = None
            elif info["is_guid"]:
                converted[key] = self._convert_to_uuid(value)
            elif info["is_datetime"]:
                converted[key] = self._convert_to_datetime(value)
            elif info["is_enum"] and key in table_enums:
                converted[key] = self._convert_to_enum(value, table_enums[key])
            else:
                converted[key] = value
        return converted

    def _restore_association_table(
        self, db: Session, table, records: list[dict]
    ) -> int:
        """
        Inserta registros en una tabla de asociación (SQLAlchemy Table).

        Convierte columnas UUID de string a uuid.UUID.
        """
        if not records:
            return 0

        # Las columnas de la tabla de asociación son todas GUID (FK)
        converted_records = []
        column_names = [col.name for col in table.columns]

        for record in records:
            converted = {}
            for col_name in column_names:
                value = record.get(col_name)
                if value is not None:
                    converted[col_name] = self._convert_to_uuid(value)
                else:
                    converted[col_name] = None
            converted_records.append(converted)

        if converted_records:
            db.execute(table.insert(), converted_records)

        logger.debug(
            "Restaurada tabla de asociación profile_knowledge_articles: %d registros",
            len(converted_records),
        )
        return len(converted_records)

    # =========================================================================
    # CONVERSIÓN DE TIPOS
    # =========================================================================

    def _convert_to_uuid(self, value: Any) -> Optional[uuid.UUID]:
        """Convierte string a uuid.UUID. Retorna None si vacío."""
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError):
            logger.warning("No se pudo convertir a UUID: %s", value)
            return None

    def _convert_to_datetime(self, value: Any) -> Optional[datetime]:
        """
        Convierte string ISO 8601 a datetime.

        Soporta formatos con y sin zona horaria.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            # Intentar parsear ISO 8601
            dt_str = str(value)
            # Manejar formato con 'Z' como UTC
            if dt_str.endswith("Z"):
                dt_str = dt_str[:-1] + "+00:00"
            return datetime.fromisoformat(dt_str)
        except (ValueError, TypeError):
            logger.warning("No se pudo convertir a datetime: %s", value)
            return None

    def _convert_to_enum(self, value: Any, enum_class: type) -> Any:
        """
        Convierte string a instancia de Enum.

        Intenta primero por valor, luego por nombre.
        """
        if value is None:
            return None
        if isinstance(value, enum_class):
            return value
        try:
            return enum_class(value)
        except (ValueError, KeyError):
            try:
                return enum_class[str(value).upper()]
            except (KeyError, AttributeError):
                logger.warning(
                    "No se pudo convertir '%s' a Enum %s", value, enum_class.__name__
                )
                return value

    # =========================================================================
    # RESTAURACIÓN DE IMÁGENES
    # =========================================================================

    def _upload_images_to_s3(
        self, images_zip_bytes: bytes, password: Optional[str]
    ) -> int:
        """
        Extrae imágenes del Images_ZIP y las sube al bucket de docs/imágenes.

        Lee el manifest del ZIP para obtener la lista de archivos, luego
        sube cada imagen al bucket S3_DOCS_BUCKET.

        Args:
            images_zip_bytes: Contenido del ZIP de imágenes.
            password: Password del ZIP (None = sin cifrado).

        Returns:
            Cantidad de imágenes subidas exitosamente.
        """
        import io

        buffer = io.BytesIO(images_zip_bytes)
        uploaded_count = 0

        with pyzipper.AESZipFile(buffer, "r") as zf:
            if password:
                zf.setpassword(password.encode("utf-8"))

            # Leer manifest de imágenes
            manifest_bytes = zf.read("manifest.json")
            manifest = json.loads(manifest_bytes.decode("utf-8"))

            files_list = manifest.get("files", [])

            for entry in files_list:
                filename = entry.get("filename")
                size = entry.get("size", 0)

                # Solo procesar archivos con datos (size > 0)
                if not filename or size == 0:
                    continue

                try:
                    image_data = zf.read(filename)

                    # Determinar content type
                    content_type = self._get_image_content_type(filename)

                    self._s3.put_object(
                        Bucket=self._docs_bucket,
                        Key=filename,
                        Body=image_data,
                        ContentType=content_type,
                    )
                    uploaded_count += 1
                    logger.debug("Imagen subida: %s (%d bytes)", filename, len(image_data))

                except Exception as e:
                    logger.warning(
                        "Error subiendo imagen %s: %s", filename, str(e)
                    )

        logger.info("Imágenes restauradas: %d de %d", uploaded_count, len(files_list))
        return uploaded_count

    def _get_image_content_type(self, filename: str) -> str:
        """Determina el content type de una imagen por su extensión."""
        lower = filename.lower()
        if lower.endswith(".png"):
            return "image/png"
        elif lower.endswith(".gif"):
            return "image/gif"
        elif lower.endswith(".webp"):
            return "image/webp"
        elif lower.endswith(".svg"):
            return "image/svg+xml"
        else:
            # Default: JPEG (más común para fotos de VLANs)
            return "image/jpeg"

    # =========================================================================
    # RECONSTRUCCIÓN DE URLs DE IMÁGENES
    # =========================================================================

    def _rebuild_image_urls(self, db: Session) -> None:
        """
        Reconstruye location_image_url en VLANs usando bucket/región actuales.

        Busca VLANs donde location_image_url es un path relativo
        (empieza con "vlan-images/") y reconstruye la URL absoluta
        con el bucket y región configurados.

        Formato resultante:
            https://{S3_DOCS_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{relative_path}
        """
        vlans = (
            db.query(VLAN)
            .filter(VLAN.location_image_url.isnot(None))
            .filter(VLAN.location_image_url != "")
            .all()
        )

        updated_count = 0
        for vlan in vlans:
            relative_path = vlan.location_image_url
            # Solo reconstruir si parece un path relativo
            if relative_path and (
                relative_path.startswith("vlan-images/")
                or not relative_path.startswith("http")
            ):
                new_url = (
                    f"https://{self._docs_bucket}.s3.{settings.AWS_REGION}"
                    f".amazonaws.com/{relative_path}"
                )
                vlan.location_image_url = new_url
                updated_count += 1

        logger.info("URLs de imágenes reconstruidas: %d VLANs", updated_count)

    # =========================================================================
    # VERIFICACIÓN DE INTEGRIDAD
    # =========================================================================

    def _verify_integrity(
        self,
        db: Session,
        manifest: dict,
        restored_counts: dict[str, int],
        missing_tables: set[str],
    ) -> None:
        """
        Verifica que los conteos restaurados coincidan con el manifest.

        Compara la cantidad de registros insertados vs lo esperado en el manifest.
        Las tablas ausentes del ZIP (missing_tables) se excluyen del total esperado:
        si el usuario quitó a propósito el .json de una tabla, eso no debe contar
        como "datos perdidos" — se resta su conteo del manifest antes de comparar.
        Si hay discrepancias significativas en tablas que sí estaban presentes,
        se registran como warning.
        """
        tables_info = manifest.get("tables", {})
        discrepancies: list[str] = []

        for table_name, info in tables_info.items():
            if table_name in missing_tables:
                continue  # Ausencia intencional/conocida — ya se logueó al extraer

            expected = info.get("count", 0)
            actual = restored_counts.get(table_name, 0)

            if actual != expected:
                discrepancies.append(
                    f"{table_name}: esperado={expected}, restaurado={actual}"
                )

        if discrepancies:
            details = "; ".join(discrepancies)
            logger.warning(
                "Discrepancias en verificación de integridad: %s", details
            )
            # No abortar por discrepancias menores — solo logear
            # (puede haber tablas nuevas no presentes en backup antiguo)
        else:
            logger.info("Verificación de integridad OK: todos los conteos coinciden")

        # Verificación adicional: contar registros reales en BD, descontando del
        # total esperado las tablas que no estaban en el ZIP (excluidas a propósito).
        excluded_records = sum(
            tables_info.get(t, {}).get("count", 0) for t in missing_tables
        )
        total_expected = manifest.get("total_records", 0) - excluded_records
        total_restored = sum(restored_counts.values())

        if missing_tables:
            logger.info(
                "Tablas excluidas del ZIP: %s (%d registros descontados del total esperado)",
                ", ".join(sorted(missing_tables)), excluded_records,
            )

        if total_restored < total_expected * 0.9:
            # Si se restauró menos del 90% de lo que SÍ estaba en el ZIP, algo salió mal
            raise ValueError(
                f"Verificación de integridad falló: se esperaban {total_expected} "
                f"registros pero solo se restauraron {total_restored} "
                f"({total_restored * 100 // max(total_expected, 1)}%)"
            )

    # =========================================================================
    # STATUS EN S3
    # =========================================================================

    def _update_restore_status(
        self,
        status: str,
        stage: Optional[str] = None,
        progress: Optional[int] = None,
        error: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> None:
        """
        Escribe backups/restore_status.json en S3 con el estado actual del restore.

        El archivo persiste en S3 para sobrevivir reinicios del contenedor
        y ser consultado por el frontend sin autenticación.
        """
        status_data: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        if stage is not None:
            status_data["stage"] = stage
        if progress is not None:
            status_data["progress"] = progress
        if error is not None:
            status_data["error"] = error
        if extra:
            status_data.update(extra)

        try:
            self._s3.put_object(
                Bucket=self._artifacts_bucket,
                Key="backups/restore_status.json",
                Body=json.dumps(status_data, ensure_ascii=False).encode("utf-8"),
                ContentType="application/json",
            )
        except Exception as e:
            # Si no podemos actualizar el status, logear pero no abortar el restore
            logger.error("Error actualizando restore_status en S3: %s", str(e))

    # =========================================================================
    # LIMPIEZA
    # =========================================================================

    def _cleanup_restore_uploads(self) -> None:
        """
        Elimina archivos temporales de restore-upload/ en S3.

        Se ejecuta después de un restore exitoso para liberar espacio.
        """
        try:
            response = self._s3.list_objects_v2(
                Bucket=self._artifacts_bucket,
                Prefix="backups/restore-upload/",
            )

            objects = response.get("Contents", [])
            if objects:
                delete_keys = [{"Key": obj["Key"]} for obj in objects]
                self._s3.delete_objects(
                    Bucket=self._artifacts_bucket,
                    Delete={"Objects": delete_keys},
                )
                logger.info(
                    "Archivos temporales de restore eliminados: %d", len(delete_keys)
                )

        except Exception as e:
            # No abortar si falla la limpieza
            logger.warning("Error limpiando archivos de restore-upload: %s", str(e))
