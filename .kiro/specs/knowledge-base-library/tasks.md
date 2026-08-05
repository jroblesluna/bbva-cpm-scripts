# Implementation Plan: Knowledge Base Library

## Overview

Implementación de una biblioteca de artículos de conocimiento técnico para el Cloud Manager de AlwaysPrint. Los artículos se almacenan en Markdown y se inyectan como contexto en el prompt del LLM durante el análisis de debugging. El plan cubre: modelo de datos + migración, service layer, API CRUD, asociaciones many-to-many con DebuggingProfile, inyección en prompt, frontend (página admin + selector multi-select), y tests.

## Tasks

- [x] 1. Modelo de datos y migración de base de datos
  - [x] 1.1 Crear modelo SQLAlchemy `KnowledgeArticle` y tabla de asociación
    - Crear archivo `AlwaysPrintProject/Cloud/backend/app/models/knowledge_article.py`
    - Definir clase `KnowledgeArticle` con campos: id (UUID), organization_id (UUID FK), title (String 200), description (String 500), content (Text), created_at, updated_at
    - Definir tabla de asociación `profile_knowledge_articles` con columns profile_id y article_id (ambas con ondelete CASCADE)
    - Importar `Base` desde `app.core.database` y `GUID` desde `app.models.organization`
    - Agregar índice en `organization_id`
    - Comentarios en español
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2_

  - [x] 1.2 Agregar relación `knowledge_articles` al modelo `DebuggingProfile`
    - Modificar `AlwaysPrintProject/Cloud/backend/app/models/debugging.py`
    - Agregar `knowledge_articles = relationship("KnowledgeArticle", secondary="profile_knowledge_articles", back_populates="profiles")`
    - _Requirements: 2.1, 2.4_

  - [x] 1.3 Crear migración Alembic para knowledge_articles y profile_knowledge_articles
    - Generar migración con `alembic revision --autogenerate -m "add_knowledge_articles_table"`
    - Verificar que la migración incluye ambas tablas (knowledge_articles + profile_knowledge_articles)
    - _Requirements: 1.4_

- [x] 2. Schemas Pydantic y service layer
  - [x] 2.1 Crear schemas Pydantic para KnowledgeArticle
    - Crear archivo `AlwaysPrintProject/Cloud/backend/app/schemas/knowledge_article.py`
    - Implementar: `KnowledgeArticleCreate` (title 3-200, description 10-500, content 1-500000), `KnowledgeArticleUpdate` (campos opcionales), `KnowledgeArticleResponse`, `KnowledgeArticleListItem`, `ProfileArticleAssociation` (article_ids max 10)
    - Validador custom para contenido no vacío (solo whitespace)
    - Comentarios en español
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 2.2 Write property test para validación de campos (Property 2)
    - **Property 2: Validación de longitudes de campos**
    - Usar Hypothesis para generar títulos/descripciones/contenido con longitudes aleatorias
    - Verificar que la validación Pydantic acepta/rechaza correctamente según los límites definidos
    - Archivo: `AlwaysPrintProject/Cloud/backend/tests/test_knowledge_article_properties.py`
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4**

  - [x] 2.3 Crear service `KnowledgeArticleService`
    - Crear archivo `AlwaysPrintProject/Cloud/backend/app/services/knowledge_article.py`
    - Implementar métodos: `create_article` (con límite 50/org), `list_articles`, `get_article`, `update_article`, `delete_article`
    - Implementar métodos de asociación: `associate_articles_to_profile` (verificar misma org, límite 10/perfil, ignorar duplicados), `remove_article_from_profile`, `get_articles_for_profile`
    - Todas las queries filtran por `organization_id` (tenant isolation)
    - Comentarios en español
    - _Requirements: 1.2, 2.2, 2.3, 2.4, 4.7, 5.4, 5.5, 8.5, 8.6_

  - [x] 2.4 Write property test para límite de artículos por organización (Property 6)
    - **Property 6: Límite de artículos por organización**
    - Usar Hypothesis para generar N artículos (N ∈ [45..55]) y verificar que el corte en 50 funciona correctamente
    - Archivo: `AlwaysPrintProject/Cloud/backend/tests/test_knowledge_article_properties.py`
    - **Validates: Requirements 8.5**

  - [x] 2.5 Write property test para límite de artículos por perfil (Property 7)
    - **Property 7: Límite de artículos por perfil**
    - Usar Hypothesis para generar N asociaciones (N ∈ [8..12]) y verificar que el corte en 10 funciona
    - Archivo: `AlwaysPrintProject/Cloud/backend/tests/test_knowledge_article_properties.py`
    - **Validates: Requirements 8.6**

  - [x] 2.6 Write property test para idempotencia de asociaciones (Property 4)
    - **Property 4: Idempotencia de asociaciones duplicadas**
    - Usar Hypothesis para generar asociaciones duplicadas aleatorias y verificar que no se crean duplicados
    - Archivo: `AlwaysPrintProject/Cloud/backend/tests/test_knowledge_article_properties.py`
    - **Validates: Requirements 5.5**

- [x] 3. API endpoints CRUD y asociaciones
  - [x] 3.1 Crear endpoints CRUD de Knowledge Articles
    - Crear archivo `AlwaysPrintProject/Cloud/backend/app/api/v1/endpoints/knowledge_articles.py`
    - Implementar: POST `/knowledge-articles` (crear), GET `/knowledge-articles` (listar), GET `/knowledge-articles/{article_id}` (detalle), PUT `/knowledge-articles/{article_id}` (actualizar), DELETE `/knowledge-articles/{article_id}` (eliminar)
    - Todos los endpoints requieren JWT auth y filtran por organization_id del usuario autenticado
    - Retornar HTTP 404 si artículo no encontrado o de otra org, HTTP 422 en validación, HTTP 409 en límites
    - Comentarios en español
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [x] 3.2 Crear endpoints de asociación artículo-perfil
    - En el mismo archivo o sub-router, implementar: POST `/debugging-profiles/{profile_id}/knowledge-articles` (asociar lista), DELETE `/debugging-profiles/{profile_id}/knowledge-articles/{article_id}` (desasociar), GET `/debugging-profiles/{profile_id}/knowledge-articles` (listar asociados)
    - Verificar que artículos y perfil pertenecen a la misma organización (HTTP 404 si no)
    - Ignorar duplicados silenciosamente
    - Comentarios en español
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 3.3 Registrar router en `app/api/v1/router.py`
    - Agregar import del nuevo router de knowledge_articles
    - Incluir el router con prefix `/knowledge-articles` y tags apropiados
    - Incluir el sub-router de asociaciones en debugging-profiles si es separado
    - _Requirements: 4.1, 5.1_

- [x] 4. Checkpoint - Verificar backend compila y tests pasan
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Inyección de artículos en prompt LLM
  - [x] 5.1 Modificar `DebuggingAnalysisService._build_prompt()` para inyectar artículos
    - Modificar `AlwaysPrintProject/Cloud/backend/app/services/debugging_analysis.py`
    - Agregar parámetro `knowledge_articles` a `_build_prompt()`
    - Si hay artículos, agregar sección "## Base de Conocimiento" con contenido Markdown de cada artículo
    - Implementar truncación progresiva: si el total excede MAX_TOTAL_PROMPT_SIZE, truncar desde el último artículo y agregar nota de truncación
    - Si no hay artículos, no agregar la sección
    - Comentarios en español
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 5.2 Modificar método `analyze()` para consultar artículos antes de construir prompt
    - En `DebuggingAnalysisService.analyze()`, antes de llamar a `_build_prompt()`, consultar artículos via `KnowledgeArticleService.get_articles_for_profile()`
    - Si la consulta falla (error de BD, timeout), loggear WARNING y continuar sin artículos
    - Pasar artículos a `_build_prompt()` como nuevo parámetro
    - Comentarios en español
    - _Requirements: 3.1, 3.4_

  - [x] 5.3 Write property test para inyección condicional en prompt (Property 8)
    - **Property 8: Inyección condicional en prompt**
    - Usar Hypothesis para generar perfiles con 0..N artículos y verificar presencia/ausencia de sección "Base de Conocimiento"
    - Archivo: `AlwaysPrintProject/Cloud/backend/tests/test_knowledge_article_properties.py`
    - **Validates: Requirements 3.1, 3.2, 3.4**

  - [x] 5.4 Write property test para truncación de prompt (Property 9)
    - **Property 9: Truncación preserva orden y warning**
    - Usar Hypothesis para generar artículos con contenido de tamaño variable y verificar que la truncación preserva orden y nota de advertencia
    - Archivo: `AlwaysPrintProject/Cloud/backend/tests/test_knowledge_article_properties.py`
    - **Validates: Requirements 3.3**

- [x] 6. Checkpoint - Verificar inyección en prompt funciona correctamente
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Frontend - Tipos, API client y página de administración
  - [x] 7.1 Crear tipos TypeScript para Knowledge Articles
    - Crear archivo `AlwaysPrintProject/Cloud/frontend/src/types/knowledge-article.ts`
    - Definir interfaces: `KnowledgeArticle`, `KnowledgeArticleCreate`, `KnowledgeArticleUpdate`, `KnowledgeArticleListItem`, `ProfileArticleAssociation`
    - Exportar desde `types/index.ts`
    - TypeScript strict, sin `any`
    - _Requirements: 6.7_

  - [x] 7.2 Crear funciones API client para Knowledge Articles
    - Crear archivo `AlwaysPrintProject/Cloud/frontend/src/lib/api/knowledge-articles.ts`
    - Implementar funciones: `getKnowledgeArticles()`, `getKnowledgeArticle(id)`, `createKnowledgeArticle(data)`, `updateKnowledgeArticle(id, data)`, `deleteKnowledgeArticle(id)`
    - Implementar funciones de asociación: `getProfileArticles(profileId)`, `associateArticlesToProfile(profileId, articleIds)`, `removeArticleFromProfile(profileId, articleId)`
    - Usar el patrón existente de `src/lib/api/client.ts`
    - TypeScript strict, sin `any`
    - _Requirements: 6.7_

  - [x] 7.3 Crear página de administración Knowledge Base
    - Crear directorio y archivo `AlwaysPrintProject/Cloud/frontend/src/app/dashboard/admin/knowledge-base/page.tsx`
    - Implementar listado de artículos (title, description, updated_at)
    - Implementar formulario crear/editar con campos: title, description, editor Markdown para content
    - Implementar dialog de confirmación para eliminar
    - Implementar tab de preview que renderiza Markdown como HTML
    - Usar componentes shadcn/ui importando desde `@radix-ui/react-*`
    - TypeScript strict, sin `any`
    - Textos de UI en español
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8_

- [x] 8. Frontend - Selector de artículos en formulario de Debugging Profile
  - [x] 8.1 Crear componente `KnowledgeArticleSelector`
    - Crear archivo `AlwaysPrintProject/Cloud/frontend/src/components/knowledge-article-selector.tsx`
    - Implementar multi-select con búsqueda/filtro por título
    - Mostrar artículos pre-seleccionados (actualmente asociados al perfil)
    - Usar componentes shadcn/ui
    - TypeScript strict, sin `any`
    - _Requirements: 7.1, 7.2, 7.4_

  - [x] 8.2 Integrar `KnowledgeArticleSelector` en formulario de DebuggingProfile
    - Modificar el formulario existente de crear/editar DebuggingProfile
    - Agregar el componente `KnowledgeArticleSelector` al formulario
    - Al guardar el formulario, enviar la lista actualizada de article_ids al backend
    - _Requirements: 7.1, 7.2, 7.3_

- [x] 9. Checkpoint final - Verificar integración completa
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marcadas con `*` son opcionales y pueden saltarse para un MVP más rápido
- Cada task referencia requirements específicos para trazabilidad
- Los checkpoints aseguran validación incremental
- Property tests validan propiedades universales de corrección (Hypothesis, ya configurado en el proyecto)
- Unit tests validan ejemplos específicos y edge cases
- Backend: Python 3.12, FastAPI, SQLAlchemy, PostgreSQL. Importar `Base` desde `app.core.database`
- Frontend: Next.js 15, TypeScript strict, React 18, Tailwind CSS, shadcn/ui
- Todos los comentarios de código en español
- Tenant isolation obligatorio: todas las queries filtran por `organization_id`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "7.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.2", "2.3", "7.2"] },
    { "id": 2, "tasks": ["2.4", "2.5", "2.6", "3.1", "3.2"] },
    { "id": 3, "tasks": ["3.3", "5.1"] },
    { "id": 4, "tasks": ["5.2", "5.3", "5.4"] },
    { "id": 5, "tasks": ["7.3", "8.1"] },
    { "id": 6, "tasks": ["8.2"] }
  ]
}
```
