/**
 * Funciones puras de filtrado de workstations.
 * Extraídas para facilitar testing y reutilización.
 */

import type { Workstation } from '@/types';

/**
 * Filtra una lista de workstations por VLAN ID.
 * Retorna solo las workstations cuyo vlan_id coincide con el filtro seleccionado.
 * Si no se especifica filtro (undefined o null), retorna todas las workstations.
 *
 * @param workstations - Lista completa de workstations
 * @param vlanId - ID de la VLAN seleccionada como filtro (undefined/null = sin filtro)
 * @returns Lista filtrada de workstations
 */
export function filterWorkstationsByVlan(
  workstations: Workstation[],
  vlanId: string | undefined | null
): Workstation[] {
  if (!vlanId) {
    return workstations;
  }
  return workstations.filter((ws) => ws.vlan_id === vlanId);
}
