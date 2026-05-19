---
inclusion: fileMatch
fileMatchPattern: "**/dashboard/**/*.tsx"
---

# Estándar de Vistas de Listado (Frontend)

Toda página del dashboard que muestre un listado de múltiples items con acciones (CRUD, comandos, etc.) debe seguir este patrón de diseño consistente.

## Estructura de Página

1. **Encabezado**: Título + subtítulo a la izquierda, botón de acción principal (Crear, Actualizar) a la derecha. Usar `flex flex-col sm:flex-row sm:items-center justify-between gap-4`.

2. **Tarjetas de estadísticas** (opcional): Grid `grid-cols-2 md:grid-cols-3` o `md:grid-cols-4` con `gap-4 md:gap-6`. Padding `p-4 md:p-6`. Iconos `w-8 h-8 md:w-12 md:h-12`.

3. **Barra de filtros**: Card con `p-4`. Filtros en `flex flex-col md:flex-row gap-4`. Incluir toggle de vista (tarjetas/tabla) alineado a la derecha con `LayoutGrid` y `List` de lucide-react.

4. **Contenido principal**: Renderizado condicional según `viewMode: 'cards' | 'table'`.

## Vista de Tarjetas (Card View)

- Contenedor: `space-y-4`
- Cada item: Card con `p-4 md:p-6`
- Layout interno:
  - **Desktop (md+)**: Info principal + acciones en la misma fila (`flex flex-col md:flex-row md:items-center md:justify-between gap-3`)
  - **Mobile**: Info apilada, acciones en fila separada abajo con borde superior
- Datos secundarios: `flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-600`
- Acciones desktop: `hidden md:flex items-center flex-wrap gap-1`
- Acciones mobile: `flex md:hidden flex-wrap gap-1 mt-3 pt-3 border-t border-gray-100`
- Botones de acción: icon-only `h-8 w-8 p-0` con `title` para tooltip
- No usar labels redundantes (ej: "Versión Tray:" → solo `v1.x.x.x`)

## Vista de Tabla (Table View)

- Contenedor: Card con `overflow-hidden`
- Tabla: `overflow-x-auto` wrapper + `w-full text-sm`
- Headers: `bg-gray-50 border-b`, `px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase`
- Celdas: `px-3 py-3 whitespace-nowrap`
- Acciones en tabla: botones `ghost` size `sm` con `h-7 w-7 p-0`
- Columnas ordenables (opcional): click en header para sort, icono `ArrowUpDown`

## Responsive

- **Nunca** overflow horizontal en la vista de tarjetas
- Tabla puede tener scroll horizontal (`overflow-x-auto`)
- Stats: `text-2xl md:text-3xl` para números
- Ocultar texto largo en mobile: `hidden sm:inline` o `truncate`
- Botón "Ver Detalles" con texto en desktop, solo icono en mobile

## Toggle de Vista

```tsx
const [viewMode, setViewMode] = useState<'cards' | 'table'>('cards');

// En la barra de filtros:
<div className="flex items-center gap-1 border rounded-md p-0.5">
  <Button variant={viewMode === 'cards' ? 'default' : 'ghost'} size="sm" onClick={() => setViewMode('cards')} className="h-8 w-8 p-0">
    <LayoutGrid className="w-4 h-4" />
  </Button>
  <Button variant={viewMode === 'table' ? 'default' : 'ghost'} size="sm" onClick={() => setViewMode('table')} className="h-8 w-8 p-0">
    <List className="w-4 h-4" />
  </Button>
</div>
```

## Paginación

Si el listado puede tener muchos items (>20), implementar paginación:
- Usar `page` y `pageSize` en el state
- Mostrar controles de paginación debajo del listado
- Formato: "Mostrando X-Y de Z" + botones Anterior/Siguiente
- `pageSize` por defecto: 20 para tabla, 10 para tarjetas

## Componentes a Usar

- `Card`, `CardContent` de shadcn/ui
- `Button` con variantes `outline`, `ghost`, `destructive`
- `Badge` para estados y tags
- `Input` para búsqueda
- Iconos de `lucide-react`
- `useToast` para feedback de acciones

## Ejemplo de Referencia

Ver `src/app/dashboard/workstations/page.tsx` como implementación canónica de este patrón.
