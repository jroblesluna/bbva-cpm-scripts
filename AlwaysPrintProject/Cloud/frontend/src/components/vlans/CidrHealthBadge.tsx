/**
 * Componente de badge de salud CIDR para VLANs.
 * Muestra un indicador visual del número de CIDRs asignados a una VLAN:
 * - Verde: exactamente 1 CIDR (configuración óptima)
 * - Amarillo: exactamente 2 CIDRs (advertencia)
 * - Rojo: 3 o más CIDRs (configuración anómala)
 */

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

/** Nivel de salud CIDR basado en la cantidad de rangos */
export type CidrHealthLevel = 'green' | 'yellow' | 'red'

interface CidrHealthBadgeProps {
  /** Número de CIDRs en la VLAN */
  cidrCount: number
}

/**
 * Determina el nivel de salud basado en la cantidad de CIDRs.
 * - 1 CIDR → verde (óptimo)
 * - 2 CIDRs → amarillo (advertencia)
 * - 3+ CIDRs → rojo (anómalo)
 */
export function getCidrHealthLevel(cidrCount: number): CidrHealthLevel {
  if (cidrCount === 1) return 'green'
  if (cidrCount === 2) return 'yellow'
  return 'red'
}

const healthConfig: Record<CidrHealthLevel, { className: string; label: (count: number) => string }> = {
  green: {
    className: 'bg-green-100 text-green-800 border-green-200',
    label: () => '1 CIDR ✓',
  },
  yellow: {
    className: 'bg-yellow-100 text-yellow-800 border-yellow-200',
    label: () => '2 CIDRs ⚠',
  },
  red: {
    className: 'bg-red-100 text-red-800 border-red-200',
    label: (count: number) => `${count} CIDRs ✗`,
  },
}

/**
 * Badge de salud CIDR que indica visualmente la cantidad de CIDRs en una VLAN.
 */
export function CidrHealthBadge({ cidrCount }: CidrHealthBadgeProps) {
  const level = getCidrHealthLevel(cidrCount)
  const config = healthConfig[level]

  return (
    <Badge className={cn(config.className)}>
      {config.label(cidrCount)}
    </Badge>
  )
}
