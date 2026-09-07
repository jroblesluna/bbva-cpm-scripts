/**
 * Prueba basada en propiedades (fast-check) para `formatDateTimeInOrgTz`
 * de StaleWorkstationsSection (Task 7.6).
 *
 * Feature: stale-stations-report-improvements, Property 5: conversion de timezone idempotente por zona
 *
 * La función pura `formatDateTimeInOrgTz(dateStr, timeZone)` convierte un timestamp
 * UTC (naive, sin sufijo 'Z') a la zona horaria de la ORGANIZACIÓN usando
 * `Intl.DateTimeFormat`. Nunca depende de la zona horaria del proceso/navegador,
 * porque el `timeZone` se pasa explícitamente al formateador.
 *
 * Propiedades verificadas (>=100 runs por cada `assert`):
 *  1. Idempotencia por zona: dos llamadas idénticas con el mismo (timestamp, zona)
 *     rinden exactamente la misma cadena.
 *  2. Independencia de la zona del navegador: el resultado para un (timestamp, zona)
 *     coincide con recomputar `Intl.DateTimeFormat` con esa misma zona, sin importar
 *     la zona del entorno de ejecución.
 *  3. Timestamps UTC iguales rinden cadenas iguales para la misma zona (determinismo):
 *     un timestamp con y sin sufijo 'Z' representan el MISMO instante y producen la
 *     misma salida.
 *
 * Validates: Requirements 6.4, 6.5, 6.6
 */

import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import { formatDateTimeInOrgTz } from '../StaleWorkstationsSection'

// ============================================================================
// GENERADORES
// ============================================================================

/**
 * Rango razonable de epoch en milisegundos: aprox. 2001-09-09 .. 2033-05-18.
 * Se evita el epoch 0 y valores extremos para mantener las cadenas estables
 * entre implementaciones de Intl.
 */
const EPOCH_MS_MIN = 1_000_000_000_000
const EPOCH_MS_MAX = 2_000_000_000_000

/** Zonas IANA muestreadas, distintas entre sí para cubrir varios offsets. */
const IANA_TIMEZONES = ['UTC', 'America/Lima', 'Europe/Madrid', 'Asia/Tokyo'] as const

/**
 * Convierte un epoch (ms) a la representación UTC naive que envía el backend
 * (ISO sin la 'Z' final): p. ej. "2026-09-10T04:45:00.000".
 */
function epochToBackendUtcNaive(epochMs: number): string {
  return new Date(epochMs).toISOString().replace(/Z$/, '')
}

/** Genera timestamps UTC naive dentro del rango razonable. */
const utcTimestampArb = fc
  .integer({ min: EPOCH_MS_MIN, max: EPOCH_MS_MAX })
  .map(epochToBackendUtcNaive)

/** Genera una zona IANA del conjunto muestreado. */
const timeZoneArb = fc.constantFrom(...IANA_TIMEZONES)

// ============================================================================
// TESTS
// ============================================================================

describe('formatDateTimeInOrgTz — Property 5: conversion de timezone idempotente por zona', () => {
  it('idempotencia por zona: dos llamadas iguales rinden la misma cadena', () => {
    // Feature: stale-stations-report-improvements, Property 5: conversion de timezone idempotente por zona
    fc.assert(
      fc.property(utcTimestampArb, timeZoneArb, (ts, tz) => {
        const a = formatDateTimeInOrgTz(ts, tz)
        const b = formatDateTimeInOrgTz(ts, tz)
        expect(a).toBe(b)
      }),
      { numRuns: 200 }
    )
  })

  it('independencia de la zona del navegador: el resultado depende solo de la zona de la organización', () => {
    // Feature: stale-stations-report-improvements, Property 5: conversion de timezone idempotente por zona
    // Recomputar con Intl usando la MISMA zona explícita debe coincidir con la
    // salida de la función. Como ambos pasan `timeZone` de forma explícita, el
    // resultado es independiente de la zona del proceso que corre el test.
    fc.assert(
      fc.property(utcTimestampArb, timeZoneArb, (ts, tz) => {
        const expected = new Intl.DateTimeFormat(undefined, {
          timeZone: tz,
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
        }).format(new Date(`${ts}Z`))

        expect(formatDateTimeInOrgTz(ts, tz)).toBe(expected)
      }),
      { numRuns: 200 }
    )
  })

  it('timestamps UTC iguales (con y sin sufijo Z) rinden la misma cadena para la misma zona', () => {
    // Feature: stale-stations-report-improvements, Property 5: conversion de timezone idempotente por zona
    // "ts" (naive) y "ts + 'Z'" representan el MISMO instante UTC: la función
    // añade la 'Z' cuando falta, por lo que ambas entradas deben coincidir.
    fc.assert(
      fc.property(utcTimestampArb, timeZoneArb, (ts, tz) => {
        const naive = formatDateTimeInOrgTz(ts, tz)
        const withZ = formatDateTimeInOrgTz(`${ts}Z`, tz)
        expect(naive).toBe(withZ)
      }),
      { numRuns: 200 }
    )
  })

  it('fallback a UTC: timeZone indefinida equivale a pasar "UTC" explícitamente', () => {
    // Feature: stale-stations-report-improvements, Property 5: conversion de timezone idempotente por zona
    fc.assert(
      fc.property(utcTimestampArb, (ts) => {
        expect(formatDateTimeInOrgTz(ts, undefined)).toBe(formatDateTimeInOrgTz(ts, 'UTC'))
      }),
      { numRuns: 200 }
    )
  })
})
