/**
 * Validación client-side de los ZIPs de backup (db.zip / images.zip) ANTES de subirlos a S3.
 *
 * Espeja las mismas reglas que RestoreService._validate_manifest_fields() en el backend
 * (backend/app/services/restore_service.py), para avisar al usuario de inmediato si el
 * archivo/password está mal, sin gastar tiempo subiendo un ZIP grande equivocado.
 * El backend sigue validando igual — esto es solo feedback rápido, no un reemplazo.
 */
import { BlobReader, TextWriter, ZipReader, ERR_INVALID_PASSWORD } from '@zip.js/zip.js'

export type BackupZipKind = 'db' | 'images'

export type BackupZipErrorCode =
  | 'MISSING_MANIFEST'
  | 'BAD_PASSWORD'
  | 'CORRUPT'
  | 'INVALID_JSON'
  | 'MISSING_VERSION'
  | 'MISSING_TABLES'
  | 'MISSING_TOTAL_RECORDS'
  | 'MISSING_FILES'
  | 'UNKNOWN'

/** Resumen legible del manifest.json de un ZIP de backup ya validado. */
export interface BackupZipManifestSummary {
  version: string
  generatedAt: string | null
  // db.zip
  tableCount?: number
  totalRecords?: number
  // images.zip
  totalImages?: number
  totalSize?: number
}

export interface BackupZipValidationResult {
  valid: boolean
  error?: BackupZipErrorCode
  /** Detalle extra para el mensaje de error, ej. lista de archivos encontrados o carpeta envolvente detectada. */
  detail?: string
  manifest?: BackupZipManifestSummary
}

class ZipValidationError extends Error {
  code: BackupZipErrorCode
  detail?: string
  constructor(code: BackupZipErrorCode, detail?: string) {
    super(code)
    this.code = code
    this.detail = detail
  }
}

/**
 * Detecta si todas las entradas del ZIP están anidadas dentro de una misma carpeta
 * (típico de "Enviar a > Carpeta comprimida" de Windows sobre una carpeta ya extraída).
 * Retorna el nombre de esa carpeta, o null si los archivos están en la raíz.
 */
function detectWrappingFolder(entries: { filename: string }[]): string | null {
  if (entries.length === 0) return null
  const slashIdx = entries[0].filename.indexOf('/')
  if (slashIdx === -1) return null
  const prefix = entries[0].filename.slice(0, slashIdx + 1)
  return entries.every((e) => e.filename.startsWith(prefix)) ? prefix.slice(0, -1) : null
}

async function readManifest(file: File, password?: string): Promise<unknown> {
  const zipReader = new ZipReader(new BlobReader(file))
  try {
    const entries = await zipReader.getEntries()
    const manifestEntry = entries.find((e) => e.filename === 'manifest.json')
    if (!manifestEntry || manifestEntry.directory) {
      const wrappingFolder = detectWrappingFolder(entries)
      if (wrappingFolder) {
        throw new ZipValidationError('MISSING_MANIFEST', `wrapped:${wrappingFolder}`)
      }
      const found = entries.filter((e) => !e.directory).slice(0, 5).map((e) => e.filename).join(', ')
      throw new ZipValidationError('MISSING_MANIFEST', found ? `found:${found}` : undefined)
    }

    let text: string
    try {
      text = await manifestEntry.getData(new TextWriter(), password ? { password } : undefined)
    } catch (e) {
      if (e instanceof Error && e.message === ERR_INVALID_PASSWORD) {
        throw new ZipValidationError('BAD_PASSWORD')
      }
      throw new ZipValidationError('CORRUPT')
    }

    try {
      return JSON.parse(text)
    } catch {
      throw new ZipValidationError('INVALID_JSON')
    }
  } finally {
    await zipReader.close()
  }
}

function validateFields(manifest: unknown, kind: BackupZipKind): BackupZipErrorCode | null {
  const m = manifest as Record<string, unknown> | null
  if (typeof m?.version !== 'string') return 'MISSING_VERSION'

  if (kind === 'db') {
    if (typeof m.tables !== 'object' || m.tables === null || Array.isArray(m.tables)) {
      return 'MISSING_TABLES'
    }
    if (typeof m.total_records !== 'number') return 'MISSING_TOTAL_RECORDS'
  } else if (!Array.isArray(m.files)) {
    return 'MISSING_FILES'
  }

  return null
}

function summarizeManifest(manifest: unknown, kind: BackupZipKind): BackupZipManifestSummary {
  const m = manifest as Record<string, unknown>
  const summary: BackupZipManifestSummary = {
    version: typeof m.version === 'string' ? m.version : '?',
    generatedAt: typeof m.generated_at === 'string' ? m.generated_at : null,
  }
  if (kind === 'db') {
    summary.tableCount = Object.keys(m.tables as Record<string, unknown>).length
    summary.totalRecords = m.total_records as number
  } else {
    summary.totalImages = typeof m.total_images === 'number' ? m.total_images : (m.files as unknown[]).length
    summary.totalSize = typeof m.total_size === 'number' ? m.total_size : undefined
  }
  return summary
}

export async function validateBackupZip(
  file: File,
  password: string | undefined,
  kind: BackupZipKind
): Promise<BackupZipValidationResult> {
  try {
    const manifest = await readManifest(file, password)
    const fieldError = validateFields(manifest, kind)
    if (fieldError) return { valid: false, error: fieldError }
    return { valid: true, manifest: summarizeManifest(manifest, kind) }
  } catch (e) {
    if (e instanceof ZipValidationError) {
      return { valid: false, error: e.code, detail: e.detail }
    }
    return { valid: false, error: 'UNKNOWN' }
  }
}
