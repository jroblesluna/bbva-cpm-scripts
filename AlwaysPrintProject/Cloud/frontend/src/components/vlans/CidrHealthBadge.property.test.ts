/**
 * Property test para el badge de salud CIDR.
 * Verifica que la función getCidrHealthLevel mapea correctamente
 * la cantidad de CIDRs al nivel de salud correspondiente.
 *
 * **Validates: Requirements 8.2, 8.3, 8.4**
 */
import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { getCidrHealthLevel } from './CidrHealthBadge'

describe('Property 9: CIDR Health Badge Mapping', () => {
  /**
   * Para cualquier entero no negativo que represente la cantidad de CIDRs
   * en una VLAN, la función getCidrHealthLevel DEBE retornar:
   * - 'green' cuando count es exactamente 1
   * - 'yellow' cuando count es exactamente 2
   * - 'red' cuando count es 3 o mayor
   *
   * **Validates: Requirements 8.2, 8.3, 8.4**
   */

  it('retorna "green" cuando cidrCount es exactamente 1', () => {
    // Caso determinista: count === 1 siempre produce 'green'
    expect(getCidrHealthLevel(1)).toBe('green')
  })

  it('retorna "yellow" cuando cidrCount es exactamente 2', () => {
    // Caso determinista: count === 2 siempre produce 'yellow'
    expect(getCidrHealthLevel(2)).toBe('yellow')
  })

  it('retorna "red" para cualquier cidrCount >= 3', () => {
    fc.assert(
      fc.property(
        // Genera enteros >= 3 (hasta un máximo razonable)
        fc.integer({ min: 3, max: 10000 }),
        (cidrCount) => {
          const resultado = getCidrHealthLevel(cidrCount)
          expect(resultado).toBe('red')
        }
      )
    )
  })

  it('mapea correctamente todos los valores posibles de cidrCount no negativos', () => {
    fc.assert(
      fc.property(
        // Genera enteros no negativos (0 incluido para cubrir edge case)
        fc.nat({ max: 10000 }),
        (cidrCount) => {
          const resultado = getCidrHealthLevel(cidrCount)

          if (cidrCount === 1) {
            // Requirement 8.2: exactamente 1 CIDR → verde
            expect(resultado).toBe('green')
          } else if (cidrCount === 2) {
            // Requirement 8.3: exactamente 2 CIDRs → amarillo
            expect(resultado).toBe('yellow')
          } else {
            // Requirement 8.4: 3 o más CIDRs → rojo
            // También cubre count === 0 (edge case, se trata como rojo)
            expect(resultado).toBe('red')
          }
        }
      )
    )
  })

  it('el resultado siempre es uno de los tres niveles válidos', () => {
    fc.assert(
      fc.property(
        fc.nat({ max: 10000 }),
        (cidrCount) => {
          const resultado = getCidrHealthLevel(cidrCount)
          // El resultado siempre debe ser un nivel válido
          expect(['green', 'yellow', 'red']).toContain(resultado)
        }
      )
    )
  })
})
