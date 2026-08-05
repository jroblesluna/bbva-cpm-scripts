# Requirements Document

## Introduction

La funcionalidad **Knowledge Base Library** añade una biblioteca de artículos de conocimiento al sistema AlwaysPrint Cloud Manager. Los artículos contienen documentación técnica en formato Markdown (flujos de impresión, patrones de fallo conocidos, secuencias de autenticación, etc.) que se inyectan como contexto adicional en el prompt del LLM durante el análisis de sesiones de debugging.

Actualmente, los Debugging Profiles definen QUÉ capturar (logs, servicios, eventos, registro). El LLM analiza los datos capturados sin contexto de dominio específico. Con esta funcionalidad, los administradores pueden asociar artículos de conocimiento a cada perfil, proporcionando al LLM información de referencia que mejora la precisión del diagnóstico.

## Glossary

- **Knowledge_Article**: Entidad que almacena un artículo de conocimiento en formato Markdown, con título, descripción y contenido técnico de referencia.
- **Debugging_Profile**: Perfil de monitoreo existente (`DebuggingProfile`) que define qué datos capturar durante una sesión de debugging.
- **LLM_Prompt**: Texto completo enviado al modelo de lenguaje durante el análisis de datos de debugging, construido en `DebuggingAnalysisService._build_prompt()`.
- **Admin**: Usuario autenticado con rol de administrador en el Cloud Manager.
- **Organization**: Entidad tenant que agrupa workstations, perfiles y artículos (aislamiento via `organization_id`).
- **Association_Table**: Tabla intermedia many-to-many que vincula `DebuggingProfile` con `KnowledgeArticle`.
- **Backend**: Aplicación FastAPI (Python 3.12, SQLAlchemy, PostgreSQL) en `AlwaysPrintProject/Cloud/backend/`.
- **Frontend**: Aplicación Next.js 15 (TypeScript, React 18, Tailwind CSS) en `AlwaysPrintProject/Cloud/frontend/`.

## Requirements

### Requirement 1: Modelo de datos KnowledgeArticle

**User Story:** Como Admin, quiero almacenar artículos de conocimiento técnico, para que puedan servir de contexto al LLM durante el análisis de debugging.

#### Acceptance Criteria

1. THE Backend SHALL persist Knowledge_Article entities with the fields: id (UUID), title (string max 200), description (string max 500), content (text, Markdown), organization_id (UUID FK), created_at (timestamp), updated_at (timestamp).
2. THE Backend SHALL enforce tenant isolation by requiring organization_id as a non-nullable foreign key to the organizations table on every Knowledge_Article.
3. THE Backend SHALL import the SQLAlchemy Base class from `app.core.database`.
4. THE Backend SHALL generate a database migration using Alembic for the knowledge_articles table.

### Requirement 2: Relación Many-to-Many entre DebuggingProfile y KnowledgeArticle

**User Story:** Como Admin, quiero asociar múltiples artículos de conocimiento a un perfil de debugging, para que el LLM reciba el contexto relevante según el perfil activo.

#### Acceptance Criteria

1. THE Backend SHALL maintain an Association_Table named `profile_knowledge_articles` with columns: profile_id (UUID FK to debugging_profiles.id) and article_id (UUID FK to knowledge_articles.id).
2. THE Backend SHALL cascade deletion of association records when either the referenced Knowledge_Article or Debugging_Profile is deleted.
3. WHEN a Knowledge_Article is associated with a Debugging_Profile, THE Backend SHALL verify that both entities belong to the same Organization.
4. THE Backend SHALL allow a single Knowledge_Article to be associated with multiple Debugging_Profiles within the same Organization.

### Requirement 3: Inyección de artículos en el prompt LLM

**User Story:** Como Admin, quiero que el contenido de los artículos asociados a un perfil se incluya automáticamente en el prompt del LLM, para que el análisis de debugging tenga contexto de dominio específico.

#### Acceptance Criteria

1. WHEN the Backend constructs the LLM_Prompt for a debugging session, THE Backend SHALL retrieve all Knowledge_Articles associated with the active Debugging_Profile.
2. WHEN Knowledge_Articles are found for the active Debugging_Profile, THE Backend SHALL append their Markdown content as a dedicated section titled "Base de Conocimiento" in the LLM_Prompt.
3. WHILE the total LLM_Prompt size exceeds the configured maximum (MAX_TOTAL_PROMPT_SIZE), THE Backend SHALL truncate article content starting from the last article, preserving a warning note indicating truncation occurred.
4. IF no Knowledge_Articles are associated with the active Debugging_Profile, THEN THE Backend SHALL construct the LLM_Prompt without a "Base de Conocimiento" section.

### Requirement 4: API CRUD de Knowledge Articles

**User Story:** Como Admin, quiero gestionar artículos de conocimiento mediante endpoints REST, para poder crear, listar, editar y eliminar artículos desde el frontend.

#### Acceptance Criteria

1. THE Backend SHALL expose a POST endpoint at `/api/v1/knowledge-articles` that creates a Knowledge_Article within the authenticated Admin's Organization.
2. THE Backend SHALL expose a GET endpoint at `/api/v1/knowledge-articles` that lists all Knowledge_Articles belonging to the authenticated Admin's Organization.
3. THE Backend SHALL expose a GET endpoint at `/api/v1/knowledge-articles/{article_id}` that returns a single Knowledge_Article if it belongs to the authenticated Admin's Organization.
4. THE Backend SHALL expose a PUT endpoint at `/api/v1/knowledge-articles/{article_id}` that updates title, description, and content of an existing Knowledge_Article within the authenticated Admin's Organization.
5. THE Backend SHALL expose a DELETE endpoint at `/api/v1/knowledge-articles/{article_id}` that removes a Knowledge_Article and all its profile associations within the authenticated Admin's Organization.
6. THE Backend SHALL require JWT authentication for all Knowledge_Article endpoints.
7. THE Backend SHALL filter all queries by the authenticated Admin's organization_id.

### Requirement 5: API de asociación de artículos a perfiles

**User Story:** Como Admin, quiero asociar y desasociar artículos de conocimiento a perfiles de debugging, para controlar qué contexto recibe el LLM según cada perfil.

#### Acceptance Criteria

1. THE Backend SHALL expose a POST endpoint at `/api/v1/debugging-profiles/{profile_id}/knowledge-articles` that accepts a list of article_ids and creates the associations.
2. THE Backend SHALL expose a DELETE endpoint at `/api/v1/debugging-profiles/{profile_id}/knowledge-articles/{article_id}` that removes a single association.
3. THE Backend SHALL expose a GET endpoint at `/api/v1/debugging-profiles/{profile_id}/knowledge-articles` that lists all Knowledge_Articles associated with the specified Debugging_Profile.
4. WHEN an Admin attempts to associate a Knowledge_Article that belongs to a different Organization, THEN THE Backend SHALL return HTTP 404.
5. IF an association between a Debugging_Profile and a Knowledge_Article already exists, THEN THE Backend SHALL ignore the duplicate without returning an error.

### Requirement 6: Página de administración de Knowledge Articles (Frontend)

**User Story:** Como Admin, quiero una interfaz web para gestionar artículos de conocimiento, para poder crear, editar y eliminar artículos con un editor Markdown.

#### Acceptance Criteria

1. THE Frontend SHALL render a page at route `/dashboard/admin/knowledge-base` that lists all Knowledge_Articles of the current Organization.
2. THE Frontend SHALL display each Knowledge_Article's title, description, and last update timestamp in the list view.
3. WHEN the Admin clicks "Crear artículo", THE Frontend SHALL show a form with fields: title, description, and a Markdown text editor for content.
4. WHEN the Admin clicks "Editar" on an article, THE Frontend SHALL load the existing content into the form with the Markdown editor.
5. WHEN the Admin clicks "Eliminar" on an article, THE Frontend SHALL show a confirmation dialog before sending the DELETE request.
6. THE Frontend SHALL provide a preview tab that renders the Markdown content as formatted HTML.
7. THE Frontend SHALL use TypeScript strict mode with no usage of the `any` type.
8. THE Frontend SHALL use shadcn/ui components importing from `@radix-ui/react-*`.

### Requirement 7: Selector de artículos en formulario de Debugging Profile (Frontend)

**User Story:** Como Admin, quiero seleccionar qué artículos de conocimiento asociar a un perfil de debugging desde el formulario de creación/edición del perfil, para vincular contexto relevante de forma intuitiva.

#### Acceptance Criteria

1. WHEN the Admin creates or edits a Debugging_Profile, THE Frontend SHALL display a multi-select component listing all available Knowledge_Articles of the Organization.
2. THE Frontend SHALL show the currently associated Knowledge_Articles as pre-selected items in the multi-select.
3. WHEN the Admin saves the Debugging_Profile form, THE Frontend SHALL send the updated list of associated article_ids to the Backend.
4. THE Frontend SHALL allow searching and filtering Knowledge_Articles by title within the multi-select component.

### Requirement 8: Validación y límites

**User Story:** Como Admin, quiero que el sistema valide los datos de los artículos y aplique límites razonables, para mantener la calidad del contenido y evitar abusos.

#### Acceptance Criteria

1. THE Backend SHALL validate that the Knowledge_Article title has between 3 and 200 characters.
2. THE Backend SHALL validate that the Knowledge_Article description has between 10 and 500 characters.
3. THE Backend SHALL validate that the Knowledge_Article content is not empty and does not exceed 500,000 characters (approximately 500KB of Markdown text).
4. IF validation fails, THEN THE Backend SHALL return HTTP 422 with a descriptive error message indicating which field failed and why.
5. THE Backend SHALL limit the maximum number of Knowledge_Articles per Organization to 50.
6. THE Backend SHALL limit the maximum number of Knowledge_Articles associated with a single Debugging_Profile to 10.
