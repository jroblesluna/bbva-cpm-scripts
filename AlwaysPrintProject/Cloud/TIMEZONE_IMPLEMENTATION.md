# Implementación de Timezone y Formato de Fechas

**Fecha**: 9 de mayo de 2026  
**Estado**: Backend completado, Frontend pendiente

---

## ✅ Cambios Completados en Backend

### 1. Modelos Actualizados

**Account (Cliente)**:
- ✅ Agregado campo `timezone` (VARCHAR(50), default="UTC")
- ✅ Comentarios actualizados: "cuenta" → "cliente"

**User**:
- ✅ Agregado campo `timezone` (VARCHAR(50), nullable=True)
- ✅ Si es NULL, hereda el timezone del cliente

### 2. Schemas Actualizados

**AccountCreate/AccountUpdate/AccountResponse**:
- ✅ Campo `timezone` agregado con validación

**UserCreate/UserUpdate/UserResponse**:
- ✅ Campo `timezone` agregado (opcional)

### 3. Migración de Base de Datos

- ✅ Migración `002_add_timezone_fields.py` creada
- ✅ Campos agregados a la base de datos SQLite

---

## ⏳ Cambios Pendientes

### 1. Frontend - Actualizar Tipos TypeScript

**Archivo**: `AlwaysPrintProject/Cloud/frontend/src/types/account.ts`

```typescript
export interface Account {
  id: string
  name: string
  description?: string | null
  is_active: boolean
  timezone: string  // ← AGREGAR
  created_at: string
  updated_at: string
  public_ips?: PublicIP[]
}

export interface AccountCreate {
  name: string
  description?: string | null
  is_active?: boolean
  timezone?: string  // ← AGREGAR (default: "UTC")
}

export interface AccountUpdate {
  name?: string
  description?: string | null
  is_active?: boolean
  timezone?: string  // ← AGREGAR
}
```

**Archivo**: `AlwaysPrintProject/Cloud/frontend/src/types/user.ts`

```typescript
export interface User {
  id: string
  email: string
  full_name: string
  role: UserRole
  account_id: string | null
  timezone?: string | null  // ← AGREGAR
  is_active: boolean
  created_at: string
  updated_at: string
  account?: Account
}

export interface UserCreate {
  email: string
  password: string
  full_name: string
  role: UserRole
  account_id?: string | null
  timezone?: string | null  // ← AGREGAR
}

export interface UserUpdate {
  email?: string
  full_name?: string
  role?: UserRole
  account_id?: string | null
  is_active?: boolean
  timezone?: string | null  // ← AGREGAR
}
```

### 2. Frontend - Crear Utilidad de Formato de Fechas

**Archivo**: `AlwaysPrintProject/Cloud/frontend/src/lib/dateUtils.ts` (CREAR)

```typescript
/**
 * Utilidades para formateo de fechas con timezone.
 */

/**
 * Formatea una fecha en formato yyyy-MM-dd HH:mm:ss con timezone.
 * 
 * @param date - Fecha a formatear (string ISO o Date)
 * @param timezone - Zona horaria (ej: "America/Lima", "UTC")
 * @returns Fecha formateada con timezone
 */
export function formatDateWithTimezone(
  date: string | Date,
  timezone: string = 'UTC'
): string {
  const dateObj = typeof date === 'string' ? new Date(date) : date
  
  // Formatear fecha en el timezone especificado
  const formatter = new Intl.DateTimeFormat('es-PE', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: timezone,
  })
  
  const parts = formatter.formatToParts(dateObj)
  const year = parts.find(p => p.type === 'year')?.value
  const month = parts.find(p => p.type === 'month')?.value
  const day = parts.find(p => p.type === 'day')?.value
  const hour = parts.find(p => p.type === 'hour')?.value
  const minute = parts.find(p => p.type === 'minute')?.value
  const second = parts.find(p => p.type === 'second')?.value
  
  // Obtener offset del timezone
  const offset = getTimezoneOffset(dateObj, timezone)
  
  return `${year}-${month}-${day} ${hour}:${minute}:${second} ${offset}`
}

/**
 * Obtiene el offset de un timezone en formato UTC±HH:mm.
 * 
 * @param date - Fecha de referencia
 * @param timezone - Zona horaria
 * @returns Offset en formato UTC±HH:mm (ej: "UTC-5", "UTC+2")
 */
function getTimezoneOffset(date: Date, timezone: string): string {
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    timeZoneName: 'shortOffset',
  })
  
  const parts = formatter.formatToParts(date)
  const offsetPart = parts.find(p => p.type === 'timeZoneName')?.value || 'UTC'
  
  // Convertir GMT±X a UTC±X
  return offsetPart.replace('GMT', 'UTC')
}

/**
 * Lista de timezones comunes para selección.
 */
export const COMMON_TIMEZONES = [
  { value: 'UTC', label: 'UTC (Tiempo Universal Coordinado)' },
  { value: 'America/Lima', label: 'América/Lima (UTC-5)' },
  { value: 'America/New_York', label: 'América/Nueva York (UTC-5/UTC-4)' },
  { value: 'America/Los_Angeles', label: 'América/Los Ángeles (UTC-8/UTC-7)' },
  { value: 'America/Mexico_City', label: 'América/Ciudad de México (UTC-6)' },
  { value: 'America/Bogota', label: 'América/Bogotá (UTC-5)' },
  { value: 'America/Santiago', label: 'América/Santiago (UTC-4/UTC-3)' },
  { value: 'America/Buenos_Aires', label: 'América/Buenos Aires (UTC-3)' },
  { value: 'Europe/Madrid', label: 'Europa/Madrid (UTC+1/UTC+2)' },
  { value: 'Europe/London', label: 'Europa/Londres (UTC+0/UTC+1)' },
  { value: 'Asia/Tokyo', label: 'Asia/Tokio (UTC+9)' },
]
```

### 3. Frontend - Actualizar Componentes

**Todos los lugares donde se muestran fechas deben usar `formatDateWithTimezone`**:

Ejemplos de archivos a actualizar:
- `src/app/dashboard/admin/accounts/page.tsx`
- `src/app/dashboard/workstations/page.tsx`
- `src/app/dashboard/admin/users/page.tsx` (cuando se implemente)
- Cualquier componente que muestre `created_at`, `updated_at`, `last_seen`, etc.

**Ejemplo de uso**:

```typescript
import { formatDateWithTimezone } from '@/lib/dateUtils'
import { useAuth } from '@/hooks/useAuth'

// En el componente:
const { user } = useAuth()
const userTimezone = user?.timezone || user?.account?.timezone || 'UTC'

// Al mostrar fechas:
<p>Creada: {formatDateWithTimezone(account.created_at, userTimezone)}</p>
```

### 4. Frontend - Formularios de Cliente y Usuario

**Formulario de Cliente** (`accounts/page.tsx`):
- ✅ Agregar selector de timezone
- ✅ Usar `COMMON_TIMEZONES` para opciones

**Formulario de Usuario** (cuando se implemente):
- ✅ Agregar selector de timezone (opcional)
- ✅ Mostrar mensaje: "Si no se especifica, se usará el timezone del cliente"
- ✅ Al crear usuario, si no se especifica timezone, heredar del cliente

### 5. Backend - Lógica de Herencia de Timezone

**Archivo**: `AlwaysPrintProject/Cloud/backend/app/api/v1/endpoints/users.py`

En el endpoint de creación de usuario, agregar lógica:

```python
@router.post("/", response_model=UserResponse)
def create_user(
    user_data: UserCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    # ... código existente ...
    
    # Si el usuario no tiene timezone y tiene account_id, heredar del cliente
    if user_data.timezone is None and user_data.account_id:
        account = db.query(Account).filter(Account.id == user_data.account_id).first()
        if account:
            timezone = account.timezone
        else:
            timezone = None
    else:
        timezone = user_data.timezone
    
    # Crear usuario con timezone
    user = User(
        email=user_data.email,
        password_hash=auth_service.hash_password(user_data.password),
        full_name=user_data.full_name,
        role=user_data.role,
        account_id=user_data.account_id,
        timezone=timezone  # ← AGREGAR
    )
    
    # ... resto del código ...
```

### 6. Frontend - Hook para Timezone del Usuario

**Archivo**: `AlwaysPrintProject/Cloud/frontend/src/hooks/useUserTimezone.ts` (CREAR)

```typescript
import { useAuth } from './useAuth'

/**
 * Hook para obtener el timezone efectivo del usuario actual.
 * 
 * Prioridad:
 * 1. Timezone del usuario (si está configurado)
 * 2. Timezone del cliente (si el usuario tiene cliente)
 * 3. UTC (por defecto)
 */
export function useUserTimezone(): string {
  const { user } = useAuth()
  
  if (user?.timezone) {
    return user.timezone
  }
  
  if (user?.account?.timezone) {
    return user.account.timezone
  }
  
  return 'UTC'
}
```

---

## 📋 Checklist de Implementación

### Backend
- [x] Agregar campo `timezone` a modelo Account
- [x] Agregar campo `timezone` a modelo User
- [x] Actualizar schemas de Account
- [x] Actualizar schemas de User
- [x] Crear migración de base de datos
- [x] Aplicar migración
- [ ] Agregar lógica de herencia de timezone en creación de usuario

### Frontend
- [ ] Actualizar tipos TypeScript (Account, User)
- [ ] Crear utilidad `dateUtils.ts`
- [ ] Crear hook `useUserTimezone.ts`
- [ ] Actualizar formulario de clientes (agregar selector timezone)
- [ ] Actualizar todos los componentes que muestran fechas
- [ ] Implementar formulario de usuarios con timezone
- [ ] Renombrar "Cuenta" → "Cliente" en toda la UI

---

## 🎯 Formato de Fechas Requerido

**Formato**: `yyyy-MM-dd HH:mm:ss UTC±X`

**Ejemplos**:
- `2026-05-09 18:30:45 UTC-5` (Lima, Perú)
- `2026-05-09 23:30:45 UTC+0` (Londres, UK)
- `2026-05-10 08:30:45 UTC+9` (Tokio, Japón)

---

## 🌍 Timezones Soportados

El sistema soporta todos los timezones de la base de datos IANA (tz database):
- América: `America/Lima`, `America/New_York`, `America/Los_Angeles`, etc.
- Europa: `Europe/Madrid`, `Europe/London`, `Europe/Paris`, etc.
- Asia: `Asia/Tokyo`, `Asia/Shanghai`, `Asia/Dubai`, etc.
- UTC: Tiempo Universal Coordinado

---

**Robles.AI**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados
