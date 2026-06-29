"""
Servicio de análisis de datos de debugging.

Pipeline completo:
1. Descomprimir ZIP recibido del cliente
2. Leer index.json para entender estructura
3. Generar diffs (services_initial vs services_final, registry_initial vs registry_final)
4. Construir prompt con: objetivo, motivo, instrucciones, diffs, log extracts, eventos
5. Invocar LLM (respetando config de org: openai_api_key o bedrock)
6. Generar PDF con fpdf2
7. Upload PDF a S3
8. Cleanup directorio temporal
"""

import io
import json
import logging
import os
import tempfile
import time
import zipfile
from datetime import datetime
from typing import Optional

import boto3

from app.core.config import settings
from app.models.debugging import DebuggingSession, DebuggingSessionStatus
from app.models.organization import Organization

logger = logging.getLogger(__name__)

# Tamaño máximo de contenido por archivo para incluir en el prompt LLM (evitar exceder context window)
MAX_FILE_CONTENT_FOR_PROMPT = 50_000  # 50KB por archivo
MAX_TOTAL_PROMPT_SIZE = 200_000  # 200KB total del prompt


class DebuggingAnalysisError(Exception):
    """Error durante el pipeline de análisis de debugging."""
    pass


class DebuggingAnalysisService:
    """
    Pipeline de análisis de datos de debugging.
    Descomprime ZIP, lee índice, construye prompt, invoca LLM, genera PDF.
    """

    async def analyze(
        self,
        session: DebuggingSession,
        zip_data: bytes,
        org: Organization,
        workstation=None,
    ) -> str:
        """
        Ejecuta el pipeline completo de análisis.
        Retorna la S3 key del PDF generado.

        Args:
            workstation: Modelo Workstation con hostname, ip_private, current_user, etc.

        Raises:
            DebuggingAnalysisError: Si falla cualquier paso del pipeline.
        """
        start_time = time.time()
        temp_dir = None

        try:
            # 1. Descomprimir ZIP en directorio temporal
            temp_dir = tempfile.mkdtemp(prefix=f"debug_{session.id}_")
            self._extract_zip(zip_data, temp_dir)

            # 2. Leer index.json
            index_path = os.path.join(temp_dir, "index.json")
            if not os.path.exists(index_path):
                raise DebuggingAnalysisError("El ZIP no contiene index.json")

            with open(index_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)

            # 3. Generar diffs entre snapshots inicial/final
            diffs = self._generate_diffs(temp_dir)

            # 4. Leer extractos de archivos
            extracts = self._read_extracts(temp_dir, index_data)

            # 5. Construir prompt
            prompt = self._build_prompt(session, index_data, diffs, extracts)

            # 6. Invocar LLM
            analysis_text = await self._invoke_llm(prompt, org)

            # 7. Generar PDF
            pdf_bytes = self._generate_pdf(analysis_text, session, index_data, workstation)

            # 8. Upload ZIP original a S3 (para descarga posterior)
            zip_s3_key = f"debugging/{session.organization_id}/{session.id}/data.zip"
            self._upload_to_s3(zip_data, zip_s3_key)

            # 9. Upload PDF a S3
            s3_key = f"debugging/{session.organization_id}/{session.id}/report.pdf"
            self._upload_to_s3(pdf_bytes, s3_key)

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(
                "[DEBUGGING_ANALYSIS] Pipeline completado: session=%s, duration=%dms, "
                "s3_key=%s, pdf_size=%d bytes",
                session.id, duration_ms, s3_key, len(pdf_bytes),
            )

            return s3_key

        except DebuggingAnalysisError:
            raise
        except Exception as e:
            logger.error(
                "[DEBUGGING_ANALYSIS] Error en pipeline: session=%s, error=%s",
                session.id, e,
            )
            raise DebuggingAnalysisError(f"Error durante el análisis: {e}") from e
        finally:
            # Cleanup directorio temporal
            if temp_dir and os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _extract_zip(self, zip_data: bytes, target_dir: str) -> None:
        """Descomprime ZIP en el directorio target."""
        try:
            with zipfile.ZipFile(io.BytesIO(zip_data), "r") as zf:
                # Validar que no hay paths maliciosos (path traversal)
                for name in zf.namelist():
                    if name.startswith("/") or ".." in name:
                        raise DebuggingAnalysisError(
                            f"ZIP contiene path potencialmente malicioso: {name}"
                        )
                zf.extractall(target_dir)
        except zipfile.BadZipFile:
            raise DebuggingAnalysisError("El archivo subido no es un ZIP válido")

    def _generate_diffs(self, temp_dir: str) -> dict:
        """
        Genera diffs entre snapshots inicial y final.
        Retorna un dict con 'services_diff' y 'registry_diff'.
        """
        diffs = {"services_diff": "", "registry_diff": ""}

        # Diff de servicios
        initial_services_path = os.path.join(temp_dir, "services_initial.json")
        final_services_path = os.path.join(temp_dir, "services_final.json")

        if os.path.exists(initial_services_path) and os.path.exists(final_services_path):
            with open(initial_services_path, "r", encoding="utf-8") as f:
                initial_services = json.load(f)
            with open(final_services_path, "r", encoding="utf-8") as f:
                final_services = json.load(f)

            diff_lines = []
            initial_map = {
                s["service_name"]: s for s in initial_services.get("services", [])
            }
            final_map = {
                s["service_name"]: s for s in final_services.get("services", [])
            }

            for svc_name in set(list(initial_map.keys()) + list(final_map.keys())):
                initial_status = initial_map.get(svc_name, {}).get("status", "N/A")
                final_status = final_map.get(svc_name, {}).get("status", "N/A")
                if initial_status != final_status:
                    diff_lines.append(
                        f"  {svc_name}: {initial_status} → {final_status} [CAMBIÓ]"
                    )
                else:
                    diff_lines.append(f"  {svc_name}: {initial_status} (sin cambios)")

            diffs["services_diff"] = "\n".join(diff_lines)

        # Diff de registro
        initial_registry_path = os.path.join(temp_dir, "registry_initial.json")
        final_registry_path = os.path.join(temp_dir, "registry_final.json")

        if os.path.exists(initial_registry_path) and os.path.exists(final_registry_path):
            with open(initial_registry_path, "r", encoding="utf-8") as f:
                initial_registry = json.load(f)
            with open(final_registry_path, "r", encoding="utf-8") as f:
                final_registry = json.load(f)

            diff_lines = []

            # Indexar por key_path
            initial_keys = {
                k["key_path"]: {v["name"]: v for v in k.get("values", [])}
                for k in initial_registry.get("keys", [])
            }
            final_keys = {
                k["key_path"]: {v["name"]: v for v in k.get("values", [])}
                for k in final_registry.get("keys", [])
            }

            for key_path in set(list(initial_keys.keys()) + list(final_keys.keys())):
                initial_vals = initial_keys.get(key_path, {})
                final_vals = final_keys.get(key_path, {})

                for val_name in set(list(initial_vals.keys()) + list(final_vals.keys())):
                    initial_data = initial_vals.get(val_name, {}).get("data")
                    final_data = final_vals.get(val_name, {}).get("data")
                    if initial_data != final_data:
                        diff_lines.append(
                            f"  {key_path}\\{val_name}: "
                            f"'{initial_data}' → '{final_data}' [CAMBIÓ]"
                        )

            diffs["registry_diff"] = "\n".join(diff_lines) if diff_lines else "(sin cambios)"

        return diffs

    def _read_extracts(self, temp_dir: str, index_data: dict) -> dict:
        """Lee el contenido de los archivos de extractos referenciados en el índice."""
        extracts = {}
        total_size = 0

        for file_info in index_data.get("files", []):
            filename = file_info.get("filename", "")
            # Saltar los JSON de snapshot (ya los procesamos como diffs)
            if filename in (
                "services_initial.json", "services_final.json",
                "registry_initial.json", "registry_final.json",
                "index.json",
            ):
                continue

            file_path = os.path.join(temp_dir, filename)
            if not os.path.exists(file_path):
                continue

            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(MAX_FILE_CONTENT_FOR_PROMPT)

                # Si el archivo fue truncado, indicarlo
                file_size = os.path.getsize(file_path)
                if file_size > MAX_FILE_CONTENT_FOR_PROMPT:
                    content += f"\n\n[... truncado, archivo original: {file_size} bytes]"

                total_size += len(content)
                if total_size > MAX_TOTAL_PROMPT_SIZE:
                    content = content[:1000] + "\n\n[... contenido truncado por límite total del prompt]"
                    extracts[filename] = content
                    break

                extracts[filename] = content
            except Exception as e:
                extracts[filename] = f"[Error leyendo archivo: {e}]"

        return extracts

    def _build_prompt(
        self,
        session: DebuggingSession,
        index_data: dict,
        diffs: dict,
        extracts: dict,
    ) -> str:
        """
        Construye el prompt completo para el LLM.
        """
        # Obtener datos del perfil desde el índice
        profile_name = index_data.get("profile_name", "N/A")
        start_time = index_data.get("start_time", "N/A")
        end_time = index_data.get("end_time", "N/A")
        duration = index_data.get("duration_seconds", "N/A")
        errors = index_data.get("errors", [])

        sections = []

        # Contexto del sistema
        sections.append(
            "Eres un experto en diagnóstico de sistemas Windows, impresión corporativa "
            "y servicios de red. Analiza los datos de debugging recopilados y genera "
            "un reporte claro con hallazgos, causa raíz probable, y recomendaciones."
        )

        # Metadata de la sesión
        sections.append(f"\n## Información de la Sesión de Debugging\n")
        sections.append(f"- **Perfil**: {profile_name}")
        sections.append(f"- **Período**: {start_time} a {end_time} ({duration}s)")
        sections.append(f"- **Targets monitoreados**: {json.dumps(index_data.get('targets', {}), indent=2)}")

        # Objetivo/descripción (del perfil, viene en la session via profile)
        if session.profile and session.profile.description:
            sections.append(f"\n## Objetivo del Debugging\n{session.profile.description}")

        # Motivo del admin/oper
        if session.motivo:
            sections.append(f"\n## Motivo Reportado por el Administrador\n{session.motivo}")

        # Instrucciones adicionales
        if session.additional_instructions:
            sections.append(
                f"\n## Instrucciones Adicionales para el Análisis\n"
                f"{session.additional_instructions}"
            )

        # Errores durante la captura
        if errors:
            sections.append("\n## Errores Durante la Captura")
            for err in errors:
                sections.append(f"- Target: {err.get('target', 'N/A')}, Error: {err.get('error', 'N/A')}")

        # Diff de servicios
        if diffs.get("services_diff"):
            sections.append(f"\n## Estado de Servicios (Inicial → Final)\n{diffs['services_diff']}")

        # Diff de registro
        if diffs.get("registry_diff"):
            sections.append(f"\n## Cambios en Registro Windows\n{diffs['registry_diff']}")

        # Extractos de logs y eventos
        for filename, content in extracts.items():
            description = filename
            # Buscar descripción en el índice
            for f_info in index_data.get("files", []):
                if f_info.get("filename") == filename:
                    description = f_info.get("description", filename)
                    break
            sections.append(f"\n## Extracto: {description}\n```\n{content}\n```")

        # Solicitud final
        sections.append(
            "\n## Solicitud de Análisis\n"
            "Genera un reporte estructurado con:\n"
            "1. **Resumen Ejecutivo** (2-3 oraciones)\n"
            "2. **Hallazgos Principales** (lista de problemas encontrados con evidencia)\n"
            "3. **Análisis de Causa Raíz** (correlación entre servicios, logs, eventos y registro)\n"
            "4. **Recomendaciones** (acciones específicas para resolver los problemas)\n"
            "5. **Riesgo** (nivel de urgencia: bajo/medio/alto/crítico)\n\n"
            "Sé específico y referencia líneas de log o eventos concretos cuando sea posible."
        )

        return "\n".join(sections)

    async def _invoke_llm(self, prompt: str, org: Organization) -> str:
        """Invoca el LLM usando la configuración de la organización."""
        from app.services.llm_service import LLMService, LLMServiceError, OpenAIProvider

        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                if org.openai_api_key:
                    provider = OpenAIProvider()
                    provider.api_key = org.openai_api_key
                    if org.llm_model_id and any(
                        org.llm_model_id.startswith(p) for p in ("gpt-", "o1-", "o3-", "chatgpt-")
                    ):
                        provider.model = org.llm_model_id
                    response_text, input_tokens, output_tokens = await provider.invoke(
                        prompt, settings.LOG_ANALYZER_LLM_MAX_TOKENS
                    )
                else:
                    llm_service = LLMService()
                    response_text, input_tokens, output_tokens = await llm_service.invoke(
                        prompt, model_id=org.llm_model_id
                    )

                logger.info(
                    "[DEBUGGING_ANALYSIS] LLM completado: tokens_in=%d, tokens_out=%d, attempt=%d",
                    input_tokens, output_tokens, attempt + 1,
                )
                return response_text

            except LLMServiceError as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        "[DEBUGGING_ANALYSIS] LLM error (attempt %d/%d): %s. Reintentando en %ds...",
                        attempt + 1, max_retries, e, retry_delay,
                    )
                    import asyncio
                    await asyncio.sleep(retry_delay)
                else:
                    raise DebuggingAnalysisError(
                        f"Error del LLM tras {max_retries} intentos: {e}"
                    ) from e

        raise DebuggingAnalysisError("Error inesperado en invocación LLM")

    def _generate_pdf(
        self,
        analysis_text: str,
        session: DebuggingSession,
        index_data: dict,
        workstation=None,
    ) -> bytes:
        """Genera un PDF con el análisis del LLM y metadata de la sesión."""
        from fpdf import FPDF

        # Ruta al logo (relativa al módulo)
        static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
        logo_path = os.path.join(static_dir, "alwaysprint_logo.png")

        class DebuggingPDF(FPDF):
            """PDF con footer de copyright en cada página."""
            def footer(self):
                self.set_y(-15)
                self.set_font("Helvetica", "I", 7)
                self.set_text_color(150, 150, 150)
                year = datetime.utcnow().year
                self.cell(0, 10,
                    f"(c) {year} Inversiones On Line S.A.C. - Todos los derechos reservados",
                    align="C")

        pdf = DebuggingPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()

        # Sanitizar texto para compatibilidad con fuente Helvetica (Latin-1)
        def sanitize(text: str) -> str:
            """Reemplaza caracteres Unicode incompatibles con Latin-1."""
            replacements = {
                '\u2022': '-',   # bullet
                '\u2013': '-',   # en-dash
                '\u2014': '--',  # em-dash
                '\u2018': "'",   # left single quote
                '\u2019': "'",   # right single quote
                '\u201c': '"',   # left double quote
                '\u201d': '"',   # right double quote
                '\u2026': '...', # ellipsis
                '\u00b7': '-',   # middle dot
            }
            for char, replacement in replacements.items():
                text = text.replace(char, replacement)
            return text.encode('latin-1', errors='replace').decode('latin-1')

        # === Header con logos ===
        if os.path.exists(logo_path):
            pdf.image(logo_path, x=10, y=8, w=20)

        # Robles.AI a la derecha
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.set_xy(140, 10)
        pdf.cell(60, 4, "Robles.AI", align="R")
        pdf.set_font("Helvetica", "I", 7)
        pdf.set_xy(140, 14)
        pdf.cell(60, 4, "Familia de automatizacion", align="R")

        # Título centrado
        pdf.set_xy(10, 30)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "Reporte de Debugging - AlwaysPrint", ln=True, align="C")
        pdf.ln(3)

        # Separador
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)

        # Metadata
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(100, 100, 100)
        profile_name = index_data.get("profile_name", "N/A")
        start_time = index_data.get("start_time", "N/A")
        end_time = index_data.get("end_time", "N/A")
        duration = index_data.get("duration_seconds", "N/A")

        metadata_lines = [
            f"Debugging ID: {session.id}",
            f"Perfil: {profile_name}",
        ]

        # Datos de la workstation
        if workstation:
            ws_hostname = getattr(workstation, 'hostname', None) or 'N/A'
            ws_ip = getattr(workstation, 'ip_private', None) or 'N/A'
            ws_user = getattr(workstation, 'current_user', None) or 'N/A'
            ws_os = getattr(workstation, 'os_version', None) or ''
            metadata_lines.append(f"Workstation: {ws_hostname} ({ws_ip})")
            if ws_user != 'N/A':
                metadata_lines.append(f"Usuario: {ws_user}")
            if ws_os:
                metadata_lines.append(f"SO: {ws_os}")
        else:
            metadata_lines.append(f"Workstation ID: {session.workstation_id}")

        metadata_lines.extend([
            f"Periodo: {start_time} - {end_time} ({duration}s)",
            f"Generado: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        ])
        if session.motivo:
            metadata_lines.append(f"Motivo: {session.motivo}")

        for line in metadata_lines:
            pdf.cell(0, 5, sanitize(line), ln=True)

        pdf.ln(5)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)

        # === Resumen de Datos Recopilados ===
        effective_width = pdf.w - pdf.l_margin - pdf.r_margin

        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 7, "Resumen de Datos Recopilados", ln=True)
        pdf.ln(2)

        # Targets configurados
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 5, "Targets del Perfil:", ln=True)
        pdf.set_font("Helvetica", "", 9)

        targets = index_data.get("targets", {})
        ext_logs = targets.get("external_logs", [])
        evt_groups = targets.get("eventlog_groups", [])
        reg_keys = targets.get("registry_keys", [])
        mon_services = targets.get("monitored_services", [])

        if ext_logs:
            pdf.set_x(pdf.l_margin + 4)
            pdf.multi_cell(effective_width - 4, 4,
                sanitize(f"- Logs externos: {', '.join(ext_logs)}"))
        if evt_groups:
            pdf.set_x(pdf.l_margin + 4)
            pdf.multi_cell(effective_width - 4, 4,
                sanitize(f"- Eventos Windows: {', '.join(evt_groups)}"))
        if reg_keys:
            pdf.set_x(pdf.l_margin + 4)
            pdf.multi_cell(effective_width - 4, 4,
                sanitize(f"- Llaves de registro: {', '.join(reg_keys)}"))
        if mon_services:
            pdf.set_x(pdf.l_margin + 4)
            pdf.multi_cell(effective_width - 4, 4,
                sanitize(f"- Servicios monitoreados: {', '.join(mon_services)}"))

        pdf.ln(3)

        # Archivos recopilados
        files_list = index_data.get("files", [])
        total_files = index_data.get("total_files", len(files_list))
        total_size = index_data.get("total_size_bytes", 0)
        total_size_kb = total_size / 1024 if total_size else 0

        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 5,
            sanitize(f"Archivos recopilados: {total_files} ({total_size_kb:.1f} KB)"),
            ln=True)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(80, 80, 80)

        for f in files_list:
            fname = f.get("filename", "")
            fdesc = f.get("description", "")
            fsize = f.get("size_bytes", 0)
            pdf.set_x(pdf.l_margin + 4)
            pdf.multi_cell(effective_width - 4, 4,
                sanitize(f"- {fname} ({fsize} bytes) - {fdesc}"))

        # Errores de captura (si los hay, mostrar aquí también)
        errors = index_data.get("errors", [])
        if errors:
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(180, 50, 50)
            pdf.cell(0, 5, f"Advertencias de captura ({len(errors)}):", ln=True)
            pdf.set_font("Helvetica", "", 8)
            for err in errors:
                pdf.set_x(pdf.l_margin + 4)
                pdf.multi_cell(effective_width - 4, 4,
                    sanitize(f"- {err.get('target', 'N/A')}: {err.get('error', 'N/A')}"))

        pdf.ln(5)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)

        # === Análisis del LLM ===
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 7, "Analisis LLM", ln=True)
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 11)

        for line in analysis_text.split("\n"):
            line = sanitize(line)
            # Resetear posición X para evitar desplazamiento residual
            pdf.set_x(pdf.l_margin)
            # Detectar headers markdown
            if line.startswith("## "):
                pdf.ln(3)
                pdf.set_font("Helvetica", "B", 13)
                pdf.multi_cell(effective_width, 6, line[3:])
                pdf.set_font("Helvetica", "", 11)
            elif line.startswith("### "):
                pdf.ln(2)
                pdf.set_font("Helvetica", "B", 11)
                pdf.multi_cell(effective_width, 6, line[4:])
                pdf.set_font("Helvetica", "", 11)
            elif line.startswith("**") and line.endswith("**"):
                pdf.set_font("Helvetica", "B", 11)
                pdf.multi_cell(effective_width, 6, line.strip("*"))
                pdf.set_font("Helvetica", "", 11)
            elif line.startswith("- ") or line.startswith("* "):
                # Bullet con indentación: reducir ancho disponible
                pdf.set_x(pdf.l_margin + 4)
                bullet_width = effective_width - 4
                pdf.multi_cell(bullet_width, 5, f"- {line[2:]}")
            elif line.strip() == "":
                pdf.ln(3)
            else:
                pdf.multi_cell(effective_width, 5, line)

        # === Disclaimer ===
        pdf.ln(10)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(120, 120, 120)
        disclaimer = (
            "AVISO: Este reporte fue generado automaticamente a partir del analisis de logs "
            "y datos de sistema recopilados durante la sesion de debugging. Las conclusiones y "
            "recomendaciones se basan exclusivamente en la informacion disponible en los registros "
            "capturados. Situaciones adicionales no reflejadas en los logs podrian contribuir a "
            "los inconvenientes observados. Se recomienda siempre la revision por un especialista "
            "para confirmar el diagnostico antes de tomar acciones correctivas."
        )
        effective_width = pdf.w - pdf.l_margin - pdf.r_margin
        pdf.multi_cell(effective_width, 4, sanitize(disclaimer))

        return pdf.output()

    def _upload_to_s3(self, pdf_bytes: bytes, s3_key: str) -> None:
        """Sube el PDF a S3."""
        try:
            session = boto3.Session(region_name=settings.AWS_REGION)
            s3_client = session.client("s3")
            s3_client.put_object(
                Bucket=settings.S3_DOCS_BUCKET,
                Key=s3_key,
                Body=pdf_bytes,
                ContentType="application/pdf",
                ContentDisposition=f'attachment; filename="debugging_report.pdf"',
            )
            logger.info(
                "[DEBUGGING_ANALYSIS] PDF subido a S3: bucket=%s, key=%s, size=%d bytes",
                settings.S3_DOCS_BUCKET, s3_key, len(pdf_bytes),
            )
        except Exception as e:
            raise DebuggingAnalysisError(f"Error subiendo PDF a S3: {e}") from e
