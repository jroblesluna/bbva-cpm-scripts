/**
 * Property test para evaluación de umbrales con inclusividad de frontera.
 *
 * **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7**
 *
 * Feature: system-status-metrics, Property 8: Threshold color evaluation with boundary inclusivity
 *
 * Para cualquier valor numérico y configuración de umbral {greenMax, yellowMax},
 * la función evaluateThreshold SHALL retornar:
 * - 'green' cuando value <= greenMax
 * - 'yellow' cuando greenMax < value <= yellowMax
 * - 'red' cuando value > yellowMax
 * - null cuando value es null
 *
 * En particular, para cualquier valor exactamente en una frontera (greenMax o yellowMax),
 * la función SHALL clasificarlo en la zona inferior (frontera inclusiva).
 */

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { evaluateThreshold, type ThresholdConfig } from '@/lib/utils/threshold'

// Generador de configuraciones de umbral válidas (greenMax < yellowMax)
// Usamos doubles para representar valores numéricos realistas
const thresholdConfigArb: fc.Arbitrary<ThresholdConfig> = fc
  .tuple(
    fc.double({ min: 0, max: 1_000_000, noNaN: true, noDefaultInfinity: true }),
    fc.double({ min: 0, max: 1_000_000, noNaN: true, noDefaultInfinity: true })
  )
  .filter(([a, b]) => a < b)
  .map(([a, b]) => ({ greenMax: a, yellowMax: b }))

describe('Feature: system-status-metrics, Property 8: Threshold color evaluation with boundary inclusivity', () => {
  it('para cualquier valor <= greenMax → retorna green', () => {
    fc.assert(
      fc.property(
        thresholdConfigArb.chain((config) =>
          fc
            .double({ min: -1_000_000, max: config.greenMax, noNaN: true, noDefaultInfinity: true })
            .map((value) => ({ config, value }))
        ),
        ({ config, value }) => {
          const resultado = evaluateThreshold(value, config)
          expect(resultado).toBe('green')
        }
      ),
      { numRuns: 100 }
    )
  })

  it('para cualquier valor en (greenMax, yellowMax] → retorna yellow', () => {
    fc.assert(
      fc.property(
        thresholdConfigArb
          .filter((c) => c.yellowMax - c.greenMax > 1e-10)
          .chain((config) => {
            // Generar un factor entre 0 (exclusivo) y 1 (inclusivo) para interpolar
            return fc
              .double({ min: 1e-10, max: 1, noNaN: true, noDefaultInfinity: true })
              .map((factor) => {
                // Interpolar entre greenMax y yellowMax, excluyendo greenMax
                const value = config.greenMax + factor * (config.yellowMax - config.greenMax)
                return { config, value }
              })
          }),
        ({ config, value }) => {
          // Solo verificar si está estrictamente en el rango (greenMax, yellowMax]
          if (value > config.greenMax && value <= config.yellowMax) {
            const resultado = evaluateThreshold(value, config)
            expect(resultado).toBe('yellow')
          }
        }
      ),
      { numRuns: 100 }
    )
  })

  it('para cualquier valor > yellowMax → retorna red', () => {
    fc.assert(
      fc.property(
        thresholdConfigArb.chain((config) =>
          fc
            .double({
              min: config.yellowMax + 1e-10,
              max: 2_000_000,
              noNaN: true,
              noDefaultInfinity: true,
            })
            .filter((v) => v > config.yellowMax)
            .map((value) => ({ config, value }))
        ),
        ({ config, value }) => {
          const resultado = evaluateThreshold(value, config)
          expect(resultado).toBe('red')
        }
      ),
      { numRuns: 100 }
    )
  })

  it('para valor null → retorna null', () => {
    fc.assert(
      fc.property(thresholdConfigArb, (config) => {
        const resultado = evaluateThreshold(null, config)
        expect(resultado).toBeNull()
      }),
      { numRuns: 100 }
    )
  })

  it('para valor exactamente igual a greenMax → retorna green (frontera inclusiva)', () => {
    fc.assert(
      fc.property(thresholdConfigArb, (config) => {
        // El valor es exactamente greenMax → debe ser 'green' (inclusivo inferior)
        const resultado = evaluateThreshold(config.greenMax, config)
        expect(resultado).toBe('green')
      }),
      { numRuns: 100 }
    )
  })

  it('para valor exactamente igual a yellowMax → retorna yellow (frontera inclusiva)', () => {
    fc.assert(
      fc.property(thresholdConfigArb, (config) => {
        // El valor es exactamente yellowMax → debe ser 'yellow' (inclusivo inferior)
        const resultado = evaluateThreshold(config.yellowMax, config)
        expect(resultado).toBe('yellow')
      }),
      { numRuns: 100 }
    )
  })
})
