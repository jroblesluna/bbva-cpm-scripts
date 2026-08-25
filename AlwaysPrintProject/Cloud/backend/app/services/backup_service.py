"""
Servicio de generación de backup completo para migración entre cuentas AWS.

Genera 2 archivos ZIP (BD + imágenes) opcionalmente cifrados con AES-256,
los almacena en S3, y mantiene un archivo de status para tracking de progreso.

Estructura en S3:
  s3://{S3_ARTIFACTS_BUCKET}/backups/status.json      — Estado del proceso
  s3://{S3_ARTIFACTS_BUCKET}/backups/latest/db.zip    — Dump de BD
  s3://{S3_ARTIFACTS_BUCKET}/backups/latest/images.zip — Imágenes de VLANs
"""

import io
import json
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import boto3
import pyzipper
from botocore.exceptions import ClientError
from sqlalchemy import inspect, select, text
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
from app.models.knowledge_article import profile_knowledge_articles

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
    ("profile_knowledge_articles", profile_knowledge_articles),  # Tabla de asociación
    ("debugging_sessions", DebuggingSession),
    ("log_analyses", LogAnalysis),
    ("status_snapshots", StatusSnapshot),
    ("metric_records", MetricRecord),
    ("health_check_results", HealthCheckResult),
    ("container_metrics", ContainerMetric),
]

# Tablas de historial/telemetría — pueden ser enormes (telemetry_logs, audit_logs
# de organizaciones grandes) y no son necesarias para restaurar el estado operativo
# del sistema. Excluidas por defecto; el usuario las incluye a propósito.
OPTIONAL_TABLES: list[str] = [
    "telemetry_logs",
    "connectivity_results",
    "debugging_sessions",
    "log_analyses",
    "status_snapshots",
    "metric_records",
    "health_check_results",
    "container_metrics",
]


class BackupService:
    """
    Servicio de generación de backup completo.

    Exporta toda la BD en formato JSON + imágenes de VLANs en archivos ZIP,
    opcionalmente protegidos con AES-256. El progreso se persiste en S3.
    """

    STAGES = [
        ("exporting_db", "Exportando base de datos", 0, 40),
        ("downloading_images", "Descargando imágenes", 40, 60),
        ("creating_db_zip", "Generando ZIP de base de datos", 60, 70),
        ("creating_images_zip", "Generando ZIP de imágenes", 70, 80),
        ("uploading_to_s3", "Subiendo archivos a S3", 80, 100),
    ]

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

    def generate(
        self,
        password: Optional[str] = None,
        include_optional_tables: Optional[list[str]] = None,
    ) -> None:
        """
        Genera backup completo.

        Sin código async real adentro (SQLAlchemy y boto3 son síncronos) — el
        endpoint la lanza en un thread aparte (loop.run_in_executor) en vez de
        asyncio.create_task, para no bloquear el event loop del servidor entero
        mientras dura.

        Args:
            password: Password para cifrar los ZIP (None = sin cifrado).
            include_optional_tables: Nombres de OPTIONAL_TABLES a incluir. Por
                defecto (None/vacío) se excluyen todas — son tablas de
                historial/telemetría, potencialmente enormes, no necesarias para
                restaurar el estado operativo del sistema.

        Etapas:
        1. Limpia backup anterior
        2. Exporta BD tabla por tabla → JSON (solo obligatorias + opcionales incluidas)
        3. Descarga imágenes de VLANs desde S3
        4. Crea DB_ZIP (con password si aplica)
        5. Crea Images_ZIP (con password si aplica)
        6. Sube ZIPs a S3
        7. Actualiza status a completed

        Si falla en cualquier punto, actualiza status a failed con el error.
        """
        include_optional = set(include_optional_tables or []) & set(OPTIONAL_TABLES)

        try:
            logger.info(
                "Iniciando generación de backup... (tablas opcionales: %s)",
                ", ".join(sorted(include_optional)) or "ninguna",
            )
            self._update_status("generating", "Iniciando backup", 0)

            # Limpiar backup anterior
            self._cleanup_previous_backup()

            # --- Etapa 1: Exportar BD ---
            self._update_status(
                "generating", self.STAGES[0][1], self.STAGES[0][2]
            )
            db = SessionLocal()
            try:
                table_data, table_counts = self._export_all_tables(db, include_optional)
                alembic_revision = self._get_alembic_revision(db)
            finally:
                db.close()

            # --- Etapa 2: Descargar imágenes ---
            self._update_status(
                "generating", self.STAGES[1][1], self.STAGES[1][2]
            )
            db = SessionLocal()
            try:
                vlan_images = self._get_active_vlan_images(db)
            finally:
                db.close()

            image_files: dict[str, bytes] = {}
            images_manifest_entries: list[dict] = []
            total_images_size = 0

            for vlan_id, relative_path in vlan_images:
                image_data = self._download_s3_image(relative_path)
                if image_data:
                    image_files[relative_path] = image_data
                    total_images_size += len(image_data)
                    images_manifest_entries.append({
                        "vlan_id": str(vlan_id),
                        "filename": relative_path,
                        "size": len(image_data),
                    })
                else:
                    # Imagen referenciada pero no encontrada en S3
                    images_manifest_entries.append({
                        "vlan_id": str(vlan_id),
                        "filename": relative_path,
                        "size": 0,
                        "warning": "Imagen no encontrada en S3 al momento del export",
                    })
                    logger.warning(
                        "Imagen no encontrada en S3: %s (VLAN %s)",
                        relative_path, vlan_id,
                    )

            # --- Etapa 3: Crear DB_ZIP ---
            self._update_status(
                "generating", self.STAGES[2][1], self.STAGES[2][2]
            )

            # Construir manifest de BD
            manifest = self._build_manifest(
                table_counts=table_counts,
                alembic_revision=alembic_revision,
                has_password=password is not None,
            )

            # Preparar archivos JSON para el ZIP de BD
            db_files: dict[str, bytes] = {
                "manifest.json": json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
            }
            for table_name, records in table_data.items():
                db_files[f"{table_name}.json"] = json.dumps(
                    records, indent=2, ensure_ascii=False
                ).encode("utf-8")

            db_zip_bytes = self._create_zip_with_password(db_files, password)

            # --- Etapa 4: Crear Images_ZIP ---
            self._update_status(
                "generating", self.STAGES[3][1], self.STAGES[3][2]
            )

            # Manifest de imágenes
            images_manifest = {
                "version": "1.0",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_images": len([e for e in images_manifest_entries if e["size"] > 0]),
                "total_size": total_images_size,
                "files": images_manifest_entries,
            }

            images_zip_files: dict[str, bytes] = {
                "manifest.json": json.dumps(images_manifest, indent=2, ensure_ascii=False).encode("utf-8"),
            }
            images_zip_files.update(image_files)

            images_zip_bytes = self._create_zip_with_password(images_zip_files, password)

            # --- Etapa 5: Subir a S3 ---
            self._update_status(
                "generating", self.STAGES[4][1], self.STAGES[4][2]
            )

            self._s3.put_object(
                Bucket=self._artifacts_bucket,
                Key="backups/latest/db.zip",
                Body=db_zip_bytes,
                ContentType="application/zip",
            )
            self._s3.put_object(
                Bucket=self._artifacts_bucket,
                Key="backups/latest/images.zip",
                Body=images_zip_bytes,
                ContentType="application/zip",
            )

            # --- Finalizar: Actualizar status a completed ---
            generated_at = datetime.now(timezone.utc).isoformat()
            self._update_status(
                "completed",
                stage=None,
                progress=100,
                error=None,
                extra={
                    "db_zip_size": len(db_zip_bytes),
                    "images_zip_size": len(images_zip_bytes),
                    "generated_at": generated_at,
                    "has_password": password is not None,
                    "included_optional_tables": sorted(include_optional),
                },
            )

            logger.info(
                "Backup generado exitosamente: db_zip=%d bytes, images_zip=%d bytes",
                len(db_zip_bytes), len(images_zip_bytes),
            )

        except Exception as e:
            logger.error("Error generando backup: %s", str(e), exc_info=True)
            self._update_status("failed", stage=None, progress=None, error=str(e))

    # =========================================================================
    # EXPORTACIÓN DE BD
    # =========================================================================

    def _export_all_tables(
        self, db: Session, include_optional: set[str]
    ) -> tuple[dict[str, list[dict]], dict[str, int]]:
        """
        Exporta todas las tablas obligatorias, más las tablas opcionales incluidas
        en include_optional, en orden de dependencias FK.

        Las tablas opcionales no seleccionadas ni siquiera se consultan (para que
        excluir telemetry_logs, por ejemplo, también ahorre tiempo/memoria) y quedan
        fuera del manifest — RestoreService ya trata los .json ausentes como
        opcionales y no cuenta sus registros como esperados.

        Returns:
            Tupla con (datos por tabla, conteo por tabla) — solo tablas incluidas.
        """
        table_data: dict[str, list[dict]] = {}
        table_counts: dict[str, int] = {}

        for table_name, model_or_table in TABLE_MODEL_MAP:
            if table_name in OPTIONAL_TABLES and table_name not in include_optional:
                logger.debug("Tabla opcional %s excluida del backup", table_name)
                continue

            if table_name == "profile_knowledge_articles":
                # Tabla de asociación (no tiene modelo ORM)
                records = self._export_association_table(db, model_or_table)
            else:
                records = self._export_table(db, model_or_table)

            table_data[table_name] = records
            table_counts[table_name] = len(records)
            logger.debug("Exportada tabla %s: %d registros", table_name, len(records))

        return table_data, table_counts

    def _export_table(self, db: Session, model_class) -> list[dict]:
        """
        Exporta todos los registros de una tabla ORM como lista de dicts.

        Convierte cada fila a un diccionario usando las columnas del modelo,
        aplicando conversión de tipos para JSON-serializable.
        """
        records = db.query(model_class).all()
        mapper = inspect(model_class)

        # col.key es el nombre de columna de la tabla (usado también al insertar
        # en el restore vía table.insert()), y puede diferir del atributo Python
        # cuando el modelo usa un alias — ej. VLAN.vlan_metadata = Column("metadata", ...)
        # ("metadata" está reservado por Declarative, así que el atributo se
        # renombra). Leer con getattr(record, col.key) en ese caso devuelve el
        # MetaData de SQLAlchemy en vez del valor real de la columna. Hay que
        # resolver el atributo ORM correcto por columna antes de leer.
        col_to_attr = {
            col.key: prop.key
            for prop in mapper.column_attrs
            for col in prop.columns
        }

        result = []
        for record in records:
            row = {}
            for col in mapper.columns:
                attr_name = col_to_attr.get(col.key, col.key)
                value = getattr(record, attr_name)
                row[col.key] = self._convert_value(value)
            result.append(row)

        return result

    def _export_association_table(self, db: Session, table) -> list[dict]:
        """
        Exporta una tabla de asociación (SQLAlchemy Table, no modelo ORM).

        Usa db.execute(select(table)) y convierte cada fila a dict.
        """
        stmt = select(table)
        rows = db.execute(stmt).fetchall()

        result = []
        column_names = [col.name for col in table.columns]
        for row in rows:
            row_dict = {}
            for i, col_name in enumerate(column_names):
                row_dict[col_name] = self._convert_value(row[i])
            result.append(row_dict)

        return result

    def _convert_value(self, value: Any) -> Any:
        """
        Convierte valores SQLAlchemy a tipos JSON-serializable.

        Manejo de tipos:
        - UUID → str
        - datetime → ISO 8601 string
        - Enum → str (valor)
        - dict/list (JSON columns) → se mantiene tal cual
        - None → None (se serializa como null)
        - bytes → se omite (no se espera en este esquema)
        """
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, (int, float, bool, str)):
            return value
        # Fallback: convertir a string
        return str(value)

    # =========================================================================
    # IMÁGENES DE VLANs
    # =========================================================================

    def _get_active_vlan_images(self, db: Session) -> list[tuple[str, str]]:
        """
        Consulta VLANs con location_image_url no nulo y extrae paths relativos.

        Returns:
            Lista de tuplas (vlan_id, relative_path) para imágenes activas.
        """
        vlans = (
            db.query(VLAN)
            .filter(VLAN.location_image_url.isnot(None))
            .filter(VLAN.location_image_url != "")
            .all()
        )

        results = []
        for vlan in vlans:
            relative_path = self._convert_image_url_to_relative(vlan.location_image_url)
            if relative_path:
                results.append((str(vlan.id), relative_path))

        logger.info("VLANs con imágenes activas: %d", len(results))
        return results

    def _convert_image_url_to_relative(self, url: str) -> Optional[str]:
        """
        Extrae path relativo de una URL absoluta de S3.

        Ejemplo:
            Input:  "https://bucket.s3.us-west-2.amazonaws.com/vlan-images/abc123.jpg?v=123"
            Output: "vlan-images/abc123.jpg"

            Input:  "https://bucket.s3.amazonaws.com/vlan-images/abc123.jpg"
            Output: "vlan-images/abc123.jpg"
        """
        if not url:
            return None

        # Remover query string
        clean_url = url.split("?")[0]

        # Buscar "vlan-images/" en la URL y extraer desde ahí
        marker = "vlan-images/"
        idx = clean_url.find(marker)
        if idx != -1:
            return clean_url[idx:]

        # Fallback: intentar extraer path después del dominio S3
        # https://{bucket}.s3.{region}.amazonaws.com/{key}
        try:
            parts = clean_url.split(".amazonaws.com/", 1)
            if len(parts) == 2:
                return parts[1]
        except Exception:
            pass

        logger.warning("No se pudo extraer path relativo de URL: %s", url)
        return None

    def _download_s3_image(self, relative_path: str) -> Optional[bytes]:
        """
        Descarga una imagen del bucket de docs/images (S3_DOCS_BUCKET).

        Args:
            relative_path: Path relativo dentro del bucket (ej: "vlan-images/abc123.jpg")

        Returns:
            Bytes de la imagen, o None si no existe.
        """
        try:
            response = self._s3.get_object(
                Bucket=self._docs_bucket,
                Key=relative_path,
            )
            return response["Body"].read()
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("NoSuchKey", "404"):
                logger.warning("Imagen no encontrada en S3: %s/%s", self._docs_bucket, relative_path)
                return None
            logger.error("Error descargando imagen de S3: %s — %s", relative_path, str(e))
            return None

    # =========================================================================
    # GENERACIÓN DE ZIP
    # =========================================================================

    def _create_zip_with_password(
        self, files: dict[str, bytes], password: Optional[str]
    ) -> bytes:
        """
        Crea un archivo ZIP en memoria, opcionalmente cifrado con AES-256.

        Args:
            files: Diccionario {nombre_archivo: contenido_bytes}
            password: Password para cifrar (None = sin cifrado)

        Returns:
            Bytes del archivo ZIP generado.
        """
        buffer = io.BytesIO()

        if password:
            # ZIP con AES-256 encryption
            with pyzipper.AESZipFile(
                buffer,
                "w",
                compression=pyzipper.ZIP_DEFLATED,
                encryption=pyzipper.WZ_AES,
            ) as zf:
                zf.setpassword(password.encode("utf-8"))
                for filename, content in files.items():
                    zf.writestr(filename, content)
        else:
            # ZIP sin cifrado (compresión estándar)
            with pyzipper.AESZipFile(
                buffer,
                "w",
                compression=pyzipper.ZIP_DEFLATED,
            ) as zf:
                for filename, content in files.items():
                    zf.writestr(filename, content)

        return buffer.getvalue()

    # =========================================================================
    # MANIFEST
    # =========================================================================

    def _build_manifest(
        self,
        table_counts: dict[str, int],
        alembic_revision: Optional[str],
        has_password: bool,
    ) -> dict:
        """
        Construye el manifest.json del backup de BD.

        Incluye metadata del backup: versión del schema, fecha, conteos, etc.
        """
        total_records = sum(table_counts.values())

        return {
            "version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "alembic_revision": alembic_revision,
            "tables": {
                name: {"count": count}
                for name, count in table_counts.items()
            },
            "total_records": total_records,
            "has_password": has_password,
        }

    def _get_alembic_revision(self, db: Session) -> Optional[str]:
        """
        Obtiene la revisión actual de Alembic desde la tabla alembic_version.

        Returns:
            String con la revision head, o None si no se puede determinar.
        """
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

    # =========================================================================
    # STATUS EN S3
    # =========================================================================

    def _update_status(
        self,
        status: str,
        stage: Optional[str] = None,
        progress: Optional[int] = None,
        error: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> None:
        """
        Escribe backups/status.json en S3 con el estado actual del backup.

        El archivo persiste en S3 para sobrevivir reinicios del contenedor.
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
                Key="backups/status.json",
                Body=json.dumps(status_data, ensure_ascii=False).encode("utf-8"),
                ContentType="application/json",
            )
        except Exception as e:
            # Si no podemos actualizar el status, logear pero no abortar el backup
            logger.error("Error actualizando status en S3: %s", str(e))

    # =========================================================================
    # LIMPIEZA
    # =========================================================================

    def _cleanup_previous_backup(self) -> None:
        """
        Elimina archivos del backup anterior en S3.

        Limpia el prefijo backups/latest/ para dejar espacio al nuevo backup.
        """
        try:
            # Listar objetos bajo backups/latest/
            response = self._s3.list_objects_v2(
                Bucket=self._artifacts_bucket,
                Prefix="backups/latest/",
            )

            objects = response.get("Contents", [])
            if objects:
                delete_keys = [{"Key": obj["Key"]} for obj in objects]
                self._s3.delete_objects(
                    Bucket=self._artifacts_bucket,
                    Delete={"Objects": delete_keys},
                )
                logger.info("Backup anterior eliminado: %d archivos", len(delete_keys))
            else:
                logger.info("No hay backup anterior para eliminar")

        except Exception as e:
            # No abortar si falla la limpieza — el nuevo backup sobrescribirá
            logger.warning("Error limpiando backup anterior: %s", str(e))
