---
inclusion: fileMatch
fileMatchPattern: "**/.kiro/specs/**/requirements.md"
---

# Estructura Canónica en Inglés para requirements.md

Los documentos de requisitos (`requirements.md`) DEBEN usar SIEMPRE los encabezados y etiquetas estructurales en **inglés canónico**, aunque todo el contenido esté en español. Esto es obligatorio para que `validate_spec_format` y `analyze_requirements` funcionen: ambas herramientas validan la estructura contra un patrón en inglés y fallan si las etiquetas están en español.

## Regla

El **contenido** (introducción, glosario, historias de usuario, criterios de aceptación) va en **español**. La **estructura** (encabezados y etiquetas) va en **inglés canónico**, sin excepción.

## Etiquetas estructurales obligatorias (en inglés)

| Elemento | Forma correcta (inglés) | NO usar (español) |
|---|---|---|
| Título del documento | `# Requirements Document` | `# Documento de Requisitos` |
| Sección introducción | `## Introduction` | `## Introducción` |
| Sección glosario | `## Glossary` | `## Glosario` |
| Sección requisitos | `## Requirements` | `## Requisitos` |
| Encabezado de requisito | `### Requirement N: <título>` | `### Requisito N:` |
| Etiqueta de historia | `**User Story:**` | `**Historia de Usuario:**` |
| Sección de criterios | `#### Acceptance Criteria` | `#### Criterios de Aceptación` |

El número `N` y el `<título>` del requisito pueden ir en español. El texto que sigue a `**User Story:**` va en español.

## Patrón que exige analyze_requirements

El analizador requiere que el documento cumpla esta estructura mínima (en este orden):

```
## Introduction
...
## Requirements
...
### Requirement 1: <título en español>

**User Story:** Como ... quiero ... para ...

#### Acceptance Criteria

1. THE ... SHALL ...
2. WHEN ... THE ... SHALL ...
```

## Criterios de aceptación en EARS (en español)

Los criterios se escriben en formato EARS, con las **palabras clave EARS en inglés/mayúsculas** (THE, WHEN, WHILE, WHERE, IF, THEN, SHALL) y el resto del texto en español:

```
1. THE Componente SHALL <comportamiento en español>.
2. WHEN <evento en español>, THE Componente SHALL <comportamiento en español>.
3. IF <condición en español>, THEN THE Componente SHALL <comportamiento en español>.
```

## Checklist al crear o editar un requirements.md

1. ¿El título es `# Requirements Document`?
2. ¿Existen `## Introduction`, `## Requirements` (y `## Glossary` si aplica) en inglés?
3. ¿Cada requisito usa `### Requirement N:` (no `Requisito`)?
4. ¿Cada historia usa `**User Story:**` (no `Historia de Usuario`)?
5. ¿Cada bloque de criterios usa `#### Acceptance Criteria` (no `Criterios de Aceptación`)?
6. ¿Los criterios están numerados y usan palabras clave EARS en mayúsculas?
7. ¿El contenido (historias, criterios, glosario) permanece en español?

Cumplir este checklist evita que `analyze_requirements` falle por un patrón de estructura no reconocido.

FIN DEL CONTENIDO.
