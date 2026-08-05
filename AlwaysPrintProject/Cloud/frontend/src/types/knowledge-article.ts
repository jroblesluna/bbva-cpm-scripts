/**
 * Tipos relacionados con artículos de conocimiento (Knowledge Base Library).
 *
 * Los artículos almacenan documentación técnica en Markdown que se inyecta
 * como contexto adicional en el prompt del LLM durante el análisis de debugging.
 */

/**
 * Artículo de conocimiento completo (respuesta del backend).
 */
export interface KnowledgeArticle {
  /** Identificador único del artículo (UUID) */
  id: string
  /** Identificador de la organización propietaria (UUID) */
  organization_id: string
  /** Título del artículo (3-200 caracteres) */
  title: string
  /** Descripción breve del artículo (10-500 caracteres) */
  description: string
  /** Contenido en formato Markdown (máx 500KB) */
  content: string
  /** Fecha de creación (ISO 8601) */
  created_at: string
  /** Fecha de última actualización (ISO 8601) */
  updated_at: string
}

/**
 * Datos requeridos para crear un artículo de conocimiento.
 */
export interface KnowledgeArticleCreate {
  /** Título del artículo (3-200 caracteres) */
  title: string
  /** Descripción breve del artículo (10-500 caracteres) */
  description: string
  /** Contenido en formato Markdown (máx 500KB) */
  content: string
}

/**
 * Datos opcionales para actualizar un artículo existente.
 * Solo los campos proporcionados se actualizan.
 */
export interface KnowledgeArticleUpdate {
  /** Título del artículo (3-200 caracteres) */
  title?: string
  /** Descripción breve del artículo (10-500 caracteres) */
  description?: string
  /** Contenido en formato Markdown (máx 500KB) */
  content?: string
}

/**
 * Versión resumida de un artículo para listados (sin contenido completo).
 */
export interface KnowledgeArticleListItem {
  /** Identificador único del artículo (UUID) */
  id: string
  /** Título del artículo */
  title: string
  /** Descripción breve del artículo */
  description: string
  /** Fecha de creación (ISO 8601) */
  created_at: string
  /** Fecha de última actualización (ISO 8601) */
  updated_at: string
}

/**
 * Request para asociar artículos de conocimiento a un perfil de debugging.
 */
export interface ProfileArticleAssociation {
  /** Lista de IDs de artículos a asociar (UUID[], máximo 10) */
  article_ids: string[]
}
