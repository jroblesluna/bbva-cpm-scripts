/**
 * Property test para filtro de VLAN en listado de workstations.
 *
 * **Validates: Requirements 6.2**
 *
 * Property 10: VLAN Filter Correctness
 * Para cualquier VLAN seleccionada como filtro, la lista filtrada de workstations
 * SHALL contener solo workstations cuyo vlan_id coincide con la VLAN seleccionada,
 * y SHALL contener todas las workstations del dataset que tienen ese vlan_id.
 */

import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { filterWorkstationsByVlan } from '@/lib/workstation-filters';
import type { Workstation } from '@/types';

// Generador de UUIDs para IDs
const uuidArb = fc.uuid();

// Generador de VLAN IDs (pool limitado para aumentar colisiones)
const vlanIdArb = fc.oneof(
  fc.constant(null as string | null),
  fc.integer({ min: 1, max: 10 }).map((n) => `vlan-${n}`)
);

// Generador de workstations con campos mínimos necesarios para el filtro
const workstationArb: fc.Arbitrary<Workstation> = fc.record({
  id: uuidArb,
  organization_id: fc.integer({ min: 1, max: 3 }).map((n) => `org-${n}`),
  vlan_id: vlanIdArb,
  ip_private: fc.ipV4(),
  hostname: fc.option(fc.string({ minLength: 1, maxLength: 20 }), { nil: null }),
  os_serial: fc.constant(null),
  current_user: fc.constant(null),
  is_online: fc.boolean(),
  contingency_active: fc.boolean(),
  forced_contingency: fc.boolean(),
  worker_id: fc.option(fc.constant('worker_25'), { nil: null }),
  last_connection: fc.constant(null),
  first_seen: fc.constant('2024-01-01T00:00:00Z'),
  created_at: fc.constant('2024-01-01T00:00:00Z'),
  updated_at: fc.constant('2024-01-01T00:00:00Z'),
  cidr: fc.option(fc.constant('192.168.1.0/24'), { nil: null }),
  tray_version: fc.option(fc.string({ minLength: 1, maxLength: 10 }), { nil: null }),
  action_config_name: fc.constant(null as string | null),
  action_config_hash: fc.constant(null as string | null),
  action_config_version: fc.constant(null as string | null),
  default_printer_id: fc.constant(null as string | null),
});

// Generador de lista de workstations
const workstationListArb = fc.array(workstationArb, { minLength: 0, maxLength: 50 });

// Generador de VLAN ID para filtro (no null, siempre un valor válido)
const filterVlanIdArb = fc.integer({ min: 1, max: 10 }).map((n) => `vlan-${n}`);

describe('Property 10: VLAN Filter Correctness', () => {
  it('la lista filtrada contiene SOLO workstations cuyo vlan_id coincide con el filtro seleccionado', () => {
    fc.assert(
      fc.property(workstationListArb, filterVlanIdArb, (workstations, selectedVlanId) => {
        const resultado = filterWorkstationsByVlan(workstations, selectedVlanId);

        // Todas las workstations en el resultado deben tener el vlan_id seleccionado
        for (const ws of resultado) {
          expect(ws.vlan_id).toBe(selectedVlanId);
        }
      }),
      { numRuns: 200 }
    );
  });

  it('la lista filtrada contiene TODAS las workstations del dataset que tienen el vlan_id seleccionado', () => {
    fc.assert(
      fc.property(workstationListArb, filterVlanIdArb, (workstations, selectedVlanId) => {
        const resultado = filterWorkstationsByVlan(workstations, selectedVlanId);

        // Contar cuántas workstations en el dataset original tienen ese vlan_id
        const esperadas = workstations.filter((ws) => ws.vlan_id === selectedVlanId);

        // El resultado debe contener exactamente todas las workstations esperadas
        expect(resultado.length).toBe(esperadas.length);

        // Verificar que cada workstation esperada está en el resultado
        for (const esperada of esperadas) {
          expect(resultado.some((ws) => ws.id === esperada.id)).toBe(true);
        }
      }),
      { numRuns: 200 }
    );
  });

  it('sin filtro de VLAN (undefined), retorna todas las workstations sin modificar', () => {
    fc.assert(
      fc.property(workstationListArb, (workstations) => {
        const resultado = filterWorkstationsByVlan(workstations, undefined);

        // Sin filtro, debe retornar la lista completa
        expect(resultado.length).toBe(workstations.length);
        expect(resultado).toEqual(workstations);
      }),
      { numRuns: 100 }
    );
  });

  it('sin filtro de VLAN (null), retorna todas las workstations sin modificar', () => {
    fc.assert(
      fc.property(workstationListArb, (workstations) => {
        const resultado = filterWorkstationsByVlan(workstations, null);

        // Sin filtro, debe retornar la lista completa
        expect(resultado.length).toBe(workstations.length);
        expect(resultado).toEqual(workstations);
      }),
      { numRuns: 100 }
    );
  });

  it('el filtro es una partición exacta: resultado + no-resultado = total', () => {
    fc.assert(
      fc.property(workstationListArb, filterVlanIdArb, (workstations, selectedVlanId) => {
        const resultado = filterWorkstationsByVlan(workstations, selectedVlanId);
        const noCoinciden = workstations.filter((ws) => ws.vlan_id !== selectedVlanId);

        // La suma de filtradas + no filtradas debe ser el total
        expect(resultado.length + noCoinciden.length).toBe(workstations.length);
      }),
      { numRuns: 200 }
    );
  });
});
