# AlwaysPrint Cloud Management - Frontend

Frontend Next.js 15 para el sistema de gestión centralizada de estaciones AlwaysPrint.

## Tecnologías

- **Framework**: Next.js 15 (App Router)
- **UI**: shadcn/ui + Tailwind CSS
- **Estado**: React Query (TanStack Query)
- **Formularios**: React Hook Form + Zod
- **WebSocket**: Cliente WebSocket nativo
- **Gráficos**: Recharts
- **Iconos**: Lucide React

## Estructura del Proyecto

```
frontend/
├── src/
│   ├── app/                         # App Router de Next.js
│   │   ├── layout.tsx              # Layout raíz
│   │   ├── page.tsx                # Página principal
│   │   ├── login/                  # Página de login
│   │   └── dashboard/              # Dashboard y páginas protegidas
│   ├── components/                  # Componentes React
│   │   ├── ui/                     # Componentes shadcn/ui
│   │   ├── layout/                 # Componentes de layout
│   │   ├── workstations/           # Componentes de workstations
│   │   ├── config/                 # Componentes de configuración
│   │   └── messages/               # Componentes de mensajes
│   ├── lib/                        # Utilidades y helpers
│   │   ├── api.ts                  # Cliente API
│   │   ├── websocket.ts            # Cliente WebSocket
│   │   └── utils.ts                # Utilidades generales
│   ├── hooks/                      # Custom React hooks
│   │   ├── useAuth.ts              # Hook de autenticación
│   │   ├── useWebSocket.ts         # Hook de WebSocket
│   │   └── useWorkstations.ts      # Hook de workstations
│   └── types/                      # Tipos TypeScript
│       ├── user.ts
│       ├── account.ts
│       ├── workstation.ts
│       └── config.ts
├── public/                         # Archivos estáticos
├── package.json
├── tsconfig.json
├── tailwind.config.ts
└── next.config.js
```

## Instalación

### Requisitos Previos

- Node.js 20+
- npm o yarn

### Instalación de Dependencias

```bash
# Instalar dependencias
npm install
# o
yarn install
```

### Variables de Entorno

Crear archivo `.env.local` en la raíz del directorio frontend:

```env
# API Backend
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000

# Configuración de la aplicación
NEXT_PUBLIC_APP_NAME=AlwaysPrint Cloud Management
```

## Ejecución

### Modo Desarrollo

```bash
npm run dev
# o
yarn dev
```

La aplicación estará disponible en http://localhost:3000

### Build para Producción

```bash
# Crear build optimizado
npm run build

# Ejecutar build de producción
npm run start
```

## Linting y Formateo

```bash
# Ejecutar linter
npm run lint

# Formatear código
npm run format
```

## Testing

```bash
# Ejecutar tests
npm run test

# Ejecutar tests con cobertura
npm run test:coverage

# Ejecutar tests en modo watch
npm run test:watch
```

## Estructura de Rutas

- `/` - Redirección a dashboard
- `/login` - Página de autenticación
- `/dashboard` - Dashboard principal (métricas)
- `/dashboard/workstations` - Lista de workstations
- `/dashboard/workstations/[id]` - Detalle de workstation
- `/dashboard/vlans` - Gestión de VLANs
- `/dashboard/config` - Configuración global/VLAN/IP
- `/dashboard/messages` - Envío de mensajes
- `/dashboard/audit` - Búsqueda de auditoría
- `/dashboard/admin/accounts` - Gestión de cuentas (Admin)
- `/dashboard/admin/users` - Gestión de usuarios (Admin)


---

**Robles.AI**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI  
Prohibida la utilización sin autorización de Inversiones On Line SAC
