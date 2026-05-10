/**
 * Utilidades para formateo de fechas con timezone.
 * 
 * Formato estándar: yyyy-MM-dd HH:mm:ss UTC±X
 * Ejemplo: 2026-05-09 18:30:45 UTC-5
 */

/**
 * Formatea una fecha en formato yyyy-MM-dd HH:mm:ss con timezone.
 * 
 * @param date - Fecha a formatear (string ISO o Date)
 * @param timezone - Zona horaria (ej: "America/Lima", "UTC")
 * @returns Fecha formateada con timezone (ej: "2026-05-09 18:30:45 UTC-5")
 */
export function formatDateWithTimezone(
  date: string | Date | null | undefined,
  timezone: string = 'UTC'
): string {
  if (!date) return 'N/A'
  
  let dateObj: Date
  
  if (typeof date === 'string') {
    // Si la fecha es string y no tiene 'Z' al final, agregarla para indicar UTC
    // Esto es necesario porque el backend devuelve fechas sin 'Z'
    if (!date.endsWith('Z') && !date.includes('+') && !date.includes('T')) {
      // Formato: "2026-05-09 22:22:42" -> agregar T y Z
      dateObj = new Date(date.replace(' ', 'T') + 'Z')
    } else if (!date.endsWith('Z') && date.includes('T') && !date.includes('+')) {
      // Formato: "2026-05-09T22:22:42" -> agregar Z
      dateObj = new Date(date + 'Z')
    } else {
      dateObj = new Date(date)
    }
  } else {
    dateObj = date
  }
  
  // Verificar si la fecha es válida
  if (isNaN(dateObj.getTime())) return 'Fecha inválida'
  
  try {
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
  } catch (error) {
    console.error('Error al formatear fecha:', error)
    return dateObj.toISOString()
  }
}

/**
 * Obtiene el offset de un timezone en formato UTC±X.
 * 
 * @param date - Fecha de referencia
 * @param timezone - Zona horaria
 * @returns Offset en formato UTC±X (ej: "UTC-5", "UTC+2", "UTC+0")
 */
function getTimezoneOffset(date: Date, timezone: string): string {
  try {
    // Obtener el offset en minutos
    const utcDate = new Date(date.toLocaleString('en-US', { timeZone: 'UTC' }))
    const tzDate = new Date(date.toLocaleString('en-US', { timeZone: timezone }))
    const offsetMinutes = (tzDate.getTime() - utcDate.getTime()) / (1000 * 60)
    const offsetHours = Math.floor(Math.abs(offsetMinutes) / 60)
    const offsetMins = Math.abs(offsetMinutes) % 60
    
    if (offsetMinutes === 0) {
      return 'UTC+0'
    }
    
    const sign = offsetMinutes > 0 ? '+' : '-'
    
    if (offsetMins === 0) {
      return `UTC${sign}${offsetHours}`
    } else {
      return `UTC${sign}${offsetHours}:${offsetMins.toString().padStart(2, '0')}`
    }
  } catch (error) {
    console.error('Error al obtener offset:', error)
    return 'UTC'
  }
}

/**
 * Formatea solo la fecha (sin hora) en formato yyyy-MM-dd.
 * 
 * @param date - Fecha a formatear
 * @param timezone - Zona horaria
 * @returns Fecha formateada (ej: "2026-05-09")
 */
export function formatDate(
  date: string | Date | null | undefined,
  timezone: string = 'UTC'
): string {
  if (!date) return 'N/A'
  
  const dateObj = typeof date === 'string' ? new Date(date) : date
  
  if (isNaN(dateObj.getTime())) return 'Fecha inválida'
  
  try {
    const formatter = new Intl.DateTimeFormat('es-PE', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      timeZone: timezone,
    })
    
    const parts = formatter.formatToParts(dateObj)
    const year = parts.find(p => p.type === 'year')?.value
    const month = parts.find(p => p.type === 'month')?.value
    const day = parts.find(p => p.type === 'day')?.value
    
    return `${year}-${month}-${day}`
  } catch (error) {
    console.error('Error al formatear fecha:', error)
    return dateObj.toISOString().split('T')[0]
  }
}

/**
 * Formatea solo la hora en formato HH:mm:ss.
 * 
 * @param date - Fecha a formatear
 * @param timezone - Zona horaria
 * @returns Hora formateada (ej: "18:30:45")
 */
export function formatTime(
  date: string | Date | null | undefined,
  timezone: string = 'UTC'
): string {
  if (!date) return 'N/A'
  
  const dateObj = typeof date === 'string' ? new Date(date) : date
  
  if (isNaN(dateObj.getTime())) return 'Hora inválida'
  
  try {
    const formatter = new Intl.DateTimeFormat('es-PE', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
      timeZone: timezone,
    })
    
    const parts = formatter.formatToParts(dateObj)
    const hour = parts.find(p => p.type === 'hour')?.value
    const minute = parts.find(p => p.type === 'minute')?.value
    const second = parts.find(p => p.type === 'second')?.value
    
    return `${hour}:${minute}:${second}`
  } catch (error) {
    console.error('Error al formatear hora:', error)
    return dateObj.toTimeString().split(' ')[0]
  }
}

/**
 * Lista de timezones comunes para selección en formularios.
 * Ordenados por offset UTC (de menor a mayor) y luego alfabéticamente.
 */
export const COMMON_TIMEZONES = [
  // UTC-8 a UTC-5 (América Oeste y Centro)
  { value: 'America/Los_Angeles', label: 'América/Los Ángeles (USA Oeste, UTC-8/UTC-7)' },
  { value: 'America/Denver', label: 'América/Denver (USA Montaña, UTC-7/UTC-6)' },
  { value: 'America/Chicago', label: 'América/Chicago (USA Centro, UTC-6/UTC-5)' },
  { value: 'America/Mexico_City', label: 'América/Ciudad de México (UTC-6)' },
  { value: 'America/Bogota', label: 'América/Bogotá (Colombia, UTC-5)' },
  { value: 'America/Lima', label: 'América/Lima (Perú, UTC-5)' },
  { value: 'America/New_York', label: 'América/Nueva York (USA Este, UTC-5/UTC-4)' },
  
  // UTC-4 a UTC-3 (América Sur)
  { value: 'America/Santiago', label: 'América/Santiago (Chile, UTC-4/UTC-3)' },
  { value: 'America/Buenos_Aires', label: 'América/Buenos Aires (Argentina, UTC-3)' },
  { value: 'America/Sao_Paulo', label: 'América/São Paulo (Brasil, UTC-3)' },
  
  // UTC+0 a UTC+2 (Europa)
  { value: 'UTC', label: 'UTC - Tiempo Universal Coordinado (UTC+0)' },
  { value: 'Europe/London', label: 'Europa/Londres (UK, UTC+0/UTC+1)' },
  { value: 'Europe/Madrid', label: 'Europa/Madrid (España, UTC+1/UTC+2)' },
  { value: 'Europe/Paris', label: 'Europa/París (Francia, UTC+1/UTC+2)' },
  
  // UTC+4 a UTC+9 (Asia y Oceanía)
  { value: 'Asia/Dubai', label: 'Asia/Dubái (EAU, UTC+4)' },
  { value: 'Asia/Shanghai', label: 'Asia/Shanghái (China, UTC+8)' },
  { value: 'Asia/Tokyo', label: 'Asia/Tokio (Japón, UTC+9)' },
  
  // UTC+10 a UTC+11 (Oceanía)
  { value: 'Australia/Sydney', label: 'Australia/Sídney (UTC+10/UTC+11)' },
]

/**
 * Obtiene el nombre legible de un timezone.
 * 
 * @param timezone - Código del timezone (ej: "America/Lima")
 * @returns Nombre legible o el código si no se encuentra
 */
export function getTimezoneName(timezone: string): string {
  const tz = COMMON_TIMEZONES.find(t => t.value === timezone)
  return tz ? tz.label : timezone
}
