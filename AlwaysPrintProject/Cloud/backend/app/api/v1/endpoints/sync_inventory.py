"""
Endpoints REST para sincronización de inventario.

Este módulo define:
- Dependencia `require_corporate_admin` para restringir acceso por dominio de email
- Schemas de respuesta para la ejecución de pasos de sincronización
- Endpoint POST /execute que ejecuta los 6 pasos de sync_inventory.py
- Router con prefijo /admin/sync-inventory
"""

import sys
import csv
import traceback
from io import StringIO
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_admin
from app.models.organization import Organization
from app.models.user import User
from app.scripts.sync_inventory import (
    step1_sync_vlans,
    step2_reassign_workstations,
    step3_upsert_devices,
    step4_assign_orphan_devices,
    step5_delete_empty_vlans,
    step6_cleanup_vlan_cidrs,
    extract_vlan_code_from_name,
)
from app.scripts.relocate_unknown_workstations import (
    step1_ensure_unknown_vlan,
    step2_relocate_non_standard_workstations,
)
from app.scripts.cleanup_non118_cidrs import cleanup_non118_cidrs
from app.scripts.reassign_from_special_vlans import reassign_from_special_vlans
from app.scripts.rescue_zzz_by_cidr import rescue_zzz_by_cidr
from app.scripts.cleanup_empty_vlans import cleanup_empty_vlans
from app.models.vlan import VLAN


# === DOMINIOS CORPORATIVOS AUTORIZADOS ===

ALLOWED_DOMAINS = ["@robles.ai", "@sistemas.com.pe"]

# === COLUMNAS REQUERIDAS EN EL CSV ===

REQUIRED_CSV_COLUMNS = [
    "VLAN_CODE", "VLAN_NAME", "IP", "MODELO", "SERIE",
    "UBICACION", "DIRECCION", "DISTRITO", "PROVINCIA",
    "DEPARTAMENTO", "TIPO",
]

# === NOMBRES DE PASOS ===

STEP_NAMES = {
    1: "Sincronizar VLANs",
    2: "Reasignar Workstations + CIDRs",
    3: "Upsert Devices (impresoras)",
    4: "Asignar Devices huérfanos por CIDR",
    5: "Eliminar VLANs vacías",
    6: "Limpiar CIDRs redundantes",
    7: "Reubicar workstations hostname no-estándar",
    8: "Mover CIDRs no-118.x a ZZZ",
    9: "Reasignar workstations de VLAN_xxxx",
    10: "Rescatar workstations de ZZZ por CIDR",
    11: "Eliminar VLANs vacías (final)",
}


# === DEPENDENCIA DE AUTORIZACIÓN ===


async def require_corporate_admin(
    current_user: User = Depends(require_admin),
) -> User:
    """
    Verifica que el admin autenticado pertenezca a un dominio corporativo autorizado.

    Encadena desde `require_admin` (ya verifica rol Admin), luego valida
    que el email del usuario termine en uno de los dominios permitidos.

    Raises:
        HTTPException 403: Si el dominio del email no está en ALLOWED_DOMAINS.
    """
    email = (current_user.email or "").lower()
    if not any(email.endswith(domain) for domain in ALLOWED_DOMAINS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores corporativos pueden ejecutar sincronización de inventario.",
        )
    return current_user


# === SCHEMAS DE RESPUESTA ===


class StepResult(BaseModel):
    """Resultado de la ejecución de un paso individual de sincronización."""

    step: int
    name: str
    success: bool
    output: str
    error: Optional[str] = None


class SyncExecutionResponse(BaseModel):
    """Respuesta completa de la ejecución de sincronización de inventario."""

    success: bool
    dry_run: bool
    steps_executed: List[StepResult]
    total_output: str


# === FUNCIONES AUXILIARES ===


def _parse_csv_content(content: str) -> tuple[list[dict], dict[str, str]]:
    """
    Parsea el contenido del CSV y extrae filas + mapa de VLANs.

    Returns:
        Tuple de (csv_rows, csv_vlans) donde:
        - csv_rows: lista de dicts con cada fila del CSV
        - csv_vlans: mapa {VLAN_CODE: VLAN_NAME}

    Raises:
        HTTPException 422: Si faltan columnas requeridas o el CSV está vacío.
    """
    reader = csv.DictReader(StringIO(content))

    # Validar columnas presentes
    if reader.fieldnames is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El archivo CSV está vacío o no tiene encabezados.",
        )

    # Limpiar BOM y espacios de los nombres de columna
    actual_columns = [col.strip().lstrip('\ufeff') for col in reader.fieldnames]
    missing_columns = [col for col in REQUIRED_CSV_COLUMNS if col not in actual_columns]

    if missing_columns:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Columnas faltantes en el CSV: {', '.join(missing_columns)}",
        )

    # Parsear filas
    csv_rows: list[dict] = []
    for row in reader:
        # Limpiar claves del BOM
        cleaned_row = {k.strip().lstrip('\ufeff'): (v or "").strip() for k, v in row.items() if k}
        csv_rows.append(cleaned_row)

    if not csv_rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El archivo CSV no contiene filas de datos.",
        )

    # Extraer VLANs únicas
    csv_vlans: dict[str, str] = {}
    for row in csv_rows:
        code = row.get("VLAN_CODE", "").strip()
        name = row.get("VLAN_NAME", "").strip()
        if code and name:
            csv_vlans[code] = name

    return csv_rows, csv_vlans


def _compute_code_to_id(db: Session, org_id) -> dict[str, str]:
    """
    Calcula el mapa code_to_id a partir de las VLANs existentes en BD.
    Necesario cuando se ejecutan steps 2 o 3 individualmente sin paso previo 1.

    Returns:
        Mapa {VLAN_CODE: vlan_id} de las VLANs existentes.
    """
    existing_vlans = db.query(VLAN).filter(VLAN.organization_id == org_id).all()
    code_to_id: dict[str, str] = {}
    for vlan in existing_vlans:
        code = extract_vlan_code_from_name(vlan.name)
        if code:
            code_to_id[code] = str(vlan.id)
    return code_to_id


def _capture_step_output(step_func, *args, **kwargs):
    """
    Ejecuta una función de paso capturando stdout en un buffer.

    Returns:
        Tuple de (resultado_de_la_función, output_capturado)
    """
    buffer = StringIO()
    old_stdout = sys.stdout
    sys.stdout = buffer
    try:
        result = step_func(*args, **kwargs)
    finally:
        sys.stdout = old_stdout
    output = buffer.getvalue()
    return result, output


# === ROUTER ===

router = APIRouter(prefix="/admin/sync-inventory", tags=["Sync Inventory"])


# === ENDPOINT DE EJECUCIÓN ===


@router.post("/execute", response_model=SyncExecutionResponse)
async def execute_sync_step(
    step: int = Form(..., ge=1, le=12, description="Paso a ejecutar (1-11 individual, 12 = todos)"),
    dry_run: bool = Form(True, description="Solo mostrar cambios sin ejecutar"),
    organization_id: UUID = Form(..., description="ID de la organización target"),
    csv_file: Optional[UploadFile] = File(None, description="Archivo CSV canónico (requerido para pasos 1-3)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_corporate_admin),
) -> SyncExecutionResponse:
    """
    Ejecuta uno o todos los pasos de sincronización de inventario.

    Pasos disponibles:
    - 1: Sincronizar VLANs (crear faltantes, renombrar existentes)
    - 2: Reasignar Workstations + CIDRs
    - 3: Upsert Devices (impresoras) desde CSV
    - 4: Asignar Devices huérfanos por CIDR
    - 5: Eliminar VLANs vacías
    - 6: Limpiar CIDRs redundantes en VLANs de agencia
    - 7: Reubicar workstations con hostname no-estándar a ZZZ
    - 8: Mover CIDRs no-118.x de agencias a ZZZ
    - 9: Reasignar workstations de VLAN_xxxx a agencias
    - 10: Rescatar workstations de ZZZ por coincidencia CIDR
    - 11: Eliminar VLANs vacías (limpieza final)
    - 12: Ejecutar todos los pasos (1-11) secuencialmente

    El CSV es requerido para pasos 1-3 y para "run all" (step=12).
    Dry-run está habilitado por defecto para seguridad.
    """
    # Validar que la organización existe
    org = db.query(Organization).filter(Organization.id == str(organization_id)).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organización con id '{organization_id}' no encontrada.",
        )

    org_id = org.id

    # Determinar si el CSV es requerido
    csv_required_steps = {1, 2, 3, 12}
    csv_is_required = step in csv_required_steps

    # Validar presencia del CSV
    csv_rows: list[dict] = []
    csv_vlans: dict[str, str] = {}

    if csv_is_required:
        if csv_file is None or csv_file.filename == "":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"El archivo CSV es requerido para el paso {step}.",
            )

        # Leer y parsear el CSV
        raw_content = await csv_file.read()
        # Detectar encoding: UTF-8 (con/sin BOM) primero, luego CP1252 (Excel Windows español)
        content = None
        for enc in ("utf-8-sig", "cp1252"):
            try:
                content = raw_content.decode(enc)
                break
            except (UnicodeDecodeError, ValueError):
                continue
        if content is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Error de codificación: no se pudo decodificar el archivo CSV (esperado UTF-8 o CP1252).",
            )

        csv_rows, csv_vlans = _parse_csv_content(content)
    elif csv_file is not None and csv_file.filename:
        # CSV proporcionado opcionalmente para pasos 4+ (no requerido pero se puede parsear)
        try:
            raw_content = await csv_file.read()
            content = None
            for enc in ("utf-8-sig", "cp1252"):
                try:
                    content = raw_content.decode(enc)
                    break
                except (UnicodeDecodeError, ValueError):
                    continue
            if content:
                csv_rows, csv_vlans = _parse_csv_content(content)
        except Exception:
            # Si falla el parseo en pasos opcionales, ignorar silenciosamente
            pass

    # Determinar qué pasos ejecutar
    steps_to_run = list(range(1, 12)) if step == 12 else [step]

    # Ejecutar pasos
    results: list[StepResult] = []
    all_output: list[str] = []
    overall_success = True

    # Variable compartida entre pasos: code_to_id
    code_to_id: dict[str, str] = {}

    for current_step in steps_to_run:
        step_name = STEP_NAMES.get(current_step, f"Paso {current_step}")

        try:
            if current_step == 1:
                result_data, output = _capture_step_output(
                    step1_sync_vlans, db, org_id, csv_vlans, dry_run
                )
                # step1 retorna code_to_id para uso en pasos 2 y 3
                code_to_id = result_data or {}

            elif current_step == 2:
                # Si no tenemos code_to_id del paso 1, calcularlo desde BD
                if not code_to_id:
                    code_to_id = _compute_code_to_id(db, org_id)
                _, output = _capture_step_output(
                    step2_reassign_workstations, db, org_id, code_to_id, dry_run
                )

            elif current_step == 3:
                # Si no tenemos code_to_id del paso 1, calcularlo desde BD
                if not code_to_id:
                    code_to_id = _compute_code_to_id(db, org_id)
                _, output = _capture_step_output(
                    step3_upsert_devices, db, org_id, csv_rows, code_to_id, dry_run
                )

            elif current_step == 4:
                _, output = _capture_step_output(
                    step4_assign_orphan_devices, db, org_id, dry_run
                )

            elif current_step == 5:
                _, output = _capture_step_output(
                    step5_delete_empty_vlans, db, org_id, dry_run
                )

            elif current_step == 6:
                _, output = _capture_step_output(
                    step6_cleanup_vlan_cidrs, db, org_id, dry_run
                )

            elif current_step == 7:
                # Reubicar workstations con hostname no-estándar a ZZZ
                def _run_relocate(db, org_id, dry_run):
                    target_vlan_id = step1_ensure_unknown_vlan(db, org_id, dry_run)
                    step2_relocate_non_standard_workstations(db, org_id, target_vlan_id, dry_run)
                _, output = _capture_step_output(
                    _run_relocate, db, org_id, dry_run
                )

            elif current_step == 8:
                _, output = _capture_step_output(
                    cleanup_non118_cidrs, db, org_id, dry_run
                )

            elif current_step == 9:
                _, output = _capture_step_output(
                    reassign_from_special_vlans, db, org_id, dry_run
                )

            elif current_step == 10:
                _, output = _capture_step_output(
                    rescue_zzz_by_cidr, db, org_id, dry_run
                )

            elif current_step == 11:
                _, output = _capture_step_output(
                    cleanup_empty_vlans, db, org_id, dry_run
                )

            else:
                output = ""

            results.append(StepResult(
                step=current_step,
                name=step_name,
                success=True,
                output=output,
            ))
            all_output.append(f"--- Paso {current_step}: {step_name} ---\n{output}")

        except Exception as e:
            # Rollback de la transacción del paso que falló
            db.rollback()

            error_output = f"[ERROR] {str(e)}\n{traceback.format_exc()}"
            results.append(StepResult(
                step=current_step,
                name=step_name,
                success=False,
                output=error_output,
                error=str(e),
            ))
            all_output.append(f"--- Paso {current_step}: {step_name} (ERROR) ---\n{error_output}")
            overall_success = False

            # Si estamos en "run all", detener la ejecución al primer error
            if step == 12:
                break

    return SyncExecutionResponse(
        success=overall_success,
        dry_run=dry_run,
        steps_executed=results,
        total_output="\n".join(all_output),
    )
