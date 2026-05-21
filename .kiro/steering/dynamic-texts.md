---
inclusion: fileMatch
fileMatchPattern: "**/frontend/**/*.tsx"
---

# Textos Dinámicos con next-intl

Todo texto visible al usuario en el frontend debe ser dinámico usando `next-intl`. No se permiten strings hardcodeados en el JSX.

## Estructura de Mensajes

Los textos se definen en archivos JSON dentro de `messages/`:

```
AlwaysPrintProject/Cloud/frontend/
  messages/
    en.json    # Inglés
    es.json    # Español
```

Ambos archivos deben tener la misma estructura de keys. Cada sección del sistema tiene su namespace (ej: `common`, `workstations`, `vlans`, `dashboard`, etc.).

## Uso en Componentes

```tsx
// ✅ CORRECTO: usar useTranslations con el namespace correspondiente
import { useTranslations } from 'next-intl';

export default function WorkstationsPage() {
  const t = useTranslations('workstations');
  const tCommon = useTranslations('common');

  return (
    <div>
      <h1>{t('title')}</h1>
      <p>{t('subtitle')}</p>
      <Button>{tCommon('save')}</Button>
    </div>
  );
}

// ❌ INCORRECTO: texto hardcodeado
export default function WorkstationsPage() {
  return (
    <div>
      <h1>Estaciones de Trabajo</h1>
      <p>Gestiona las estaciones conectadas</p>
      <Button>Guardar</Button>
    </div>
  );
}
```

## Textos con Variables (Interpolación)

En los JSON se usan placeholders `{variable}`:

```json
{
  "editTitle": "Editar Estación: {ip}",
  "pagination": "Mostrando {start} a {end} de {total} registros",
  "lastUpdated": "Última actualización: {time}"
}
```

En el componente:

```tsx
// ✅ CORRECTO
<h2>{t('editTitle', { ip: workstation.ip })}</h2>
<span>{t('pagination', { start: 1, end: 10, total: 50 })}</span>
<span>{t('lastUpdated', { time: formattedTime })}</span>

// ❌ INCORRECTO: template literal inline
<h2>{`Editar Estación: ${workstation.ip}`}</h2>
<span>{`Mostrando ${start} a ${end} de ${total}`}</span>
```

## Pasar `t` como Prop a Subcomponentes

Cuando un subcomponente necesita traducciones, pasar `t` como prop con el tipo correcto:

```tsx
import { useTranslations } from 'next-intl';

interface CardProps {
  t: ReturnType<typeof useTranslations>;
  // ...
}

function WorkstationCard({ t, workstation }: CardProps) {
  return <span>{t('hostname')}</span>;
}
```

## Múltiples Namespaces

Si un componente necesita textos de varios namespaces, instanciar múltiples `useTranslations`:

```tsx
const t = useTranslations('vlans');
const tCommon = useTranslations('common');
const tDevices = useTranslations('devices');
```

## Qué SIEMPRE Debe Ser Dinámico

- Títulos y subtítulos de página
- Labels de formularios y placeholders de inputs
- Textos de botones
- Mensajes de error, validación y confirmación
- Textos de estados (badges)
- Headers de tablas
- Mensajes de estado vacío (empty states)
- Textos de notificaciones (toasts)
- Tooltips (`title` en botones icon-only)
- Opciones de selects y filtros

## Qué Puede Estar Hardcodeado (Excepciones)

- `className`, `id`, `data-testid`
- URLs de API y keys de localStorage
- Nombres de clases CSS (Tailwind)
- Valores técnicos: puertos, formatos de fecha, regex
- Nombres de iconos de lucide-react

## Checklist al Crear/Modificar un `.tsx`

1. ¿Hay strings literales visibles al usuario en el JSX? → Moverlos a `messages/es.json` y `messages/en.json`
2. ¿Se usa `useTranslations` con el namespace correcto?
3. ¿Los textos con valores dinámicos usan interpolación `{variable}` en lugar de template literals?
4. ¿Se agregó la key tanto en `en.json` como en `es.json`?
5. ¿Los textos comunes (Guardar, Cancelar, Eliminar, etc.) usan el namespace `common`?

## Agregar Nuevas Keys

Al agregar un texto nuevo:

1. Identificar el namespace correcto (o crear uno nuevo si es una sección nueva)
2. Agregar la key en `messages/es.json` con el texto en español
3. Agregar la key equivalente en `messages/en.json` con el texto en inglés
4. Usar `t('nuevaKey')` en el componente

## Namespaces Existentes

| Namespace | Uso |
|---|---|
| `common` | Textos compartidos (botones, estados, acciones genéricas) |
| `nav` | Navegación y sidebar |
| `login` | Página de login |
| `forgotPassword` | Recuperación de contraseña |
| `resetPassword` | Reset de contraseña |
| `dashboard` | Dashboard principal |
| `workstations` | Gestión de estaciones |
| `vlans` | Gestión de VLANs |
| `devices` | Gestión de dispositivos/impresoras |
| `messages` | Sistema de mensajes |
| `config` | Configuración del sistema |
| `audit` | Logs de auditoría |
| `users` | Gestión de usuarios |
| `accounts` | Gestión de organizaciones |
| `pendingIps` | IPs pendientes de autorización |
| `actionConfigs` | Configuraciones de acciones |
| `telemetry` | Telemetría |
| `updates` | Actualizaciones automáticas |
| `language` | Selector de idioma |
