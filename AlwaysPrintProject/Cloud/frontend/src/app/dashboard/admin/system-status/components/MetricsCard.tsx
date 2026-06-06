'use client'

/**
 * Componente MetricsCard para métricas de escalabilidad del sistema.
 *
 * Muestra las 5 métricas de escalabilidad (WebSocket, memoria Python,
 * file descriptors, tráfico de red, pool BD) con indicadores de color
 * según umbrales configurados. Consume el endpoint /api/v1/system/metrics.
 *
 * Maneja estados: loading (spinner), error (mensaje localizado),
 * métrica null (texto "no disponible" sin indicador de color).
 *
 * Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6
 */

import { useState, useEffect, useCallback } from 'react'
import { useTranslations } from 'next-intl'
import { RefreshCw, Loader2, AlertTriangle } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

import { apiClient } from '@/lib/api'
import type { ScalabilityMetrics } from '@/types/scalability-metrics'
import {
  evaluateThreshold,
  WS_TOTAL_THRESHOLD,
  MEMORY_PER_WS_THRESHOLD,
  FD_USAGE_THRESHOLD,
  DB_POOL_USAGE_THRESHOLD,
  TX_RATE_THRESHOLD,
  type ThresholdColor,
} from '@/lib/utils/threshold'

// === MAPA DE COLORES POR UMBRAL ===

const THRESHOLD_COLOR_CLASSES: Record<ThresholdColor, string> = {
  green: 'bg-green-500',
  yellow: 'bg-yellow-500',
  red: 'bg-red-500',
}

// === COMPONENTE PRINCIPAL ===

export default function MetricsCard() {
  const t = useTranslations('systemMetrics')

  const [metrics, setMetrics] = useState<ScalabilityMetrics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Fetch de métricas desde el endpoint protegido
  const fetchMetrics = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      const response = await apiClient.get<ScalabilityMetrics>('/system/metrics')
      setMetrics(response.data)
    } catch {
      setError(t('states.error'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    fetchMetrics()
  }, [fetchMetrics])

  // === RENDERIZADO: Estado de carga ===
  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t('title')}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            <span className="ml-3 text-muted-foreground">{t('states.loading')}</span>
          </div>
        </CardContent>
      </Card>
    )
  }

  // === RENDERIZADO: Estado de error ===
  if (error) {
    return (
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>{t('title')}</CardTitle>
          <Button variant="outline" size="sm" onClick={fetchMetrics}>
            <RefreshCw className="mr-2 h-4 w-4" />
            {t('refresh')}
          </Button>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-8 gap-3">
            <AlertTriangle className="h-8 w-8 text-yellow-500" />
            <p className="text-muted-foreground text-sm">{error}</p>
          </div>
        </CardContent>
      </Card>
    )
  }

  // === RENDERIZADO: Métricas disponibles ===
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>{t('title')}</CardTitle>
        <Button variant="outline" size="sm" onClick={fetchMetrics}>
          <RefreshCw className="mr-2 h-4 w-4" />
          {t('refresh')}
        </Button>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {/* Métrica 1: Conexiones WebSocket */}
          <MetricItem
            label={t('websocket.label')}
            value={metrics?.websocket?.total ?? null}
            unit=""
            thresholdColor={evaluateThreshold(
              metrics?.websocket?.total ?? null,
              WS_TOTAL_THRESHOLD
            )}
            t={t}
          />

          {/* Métrica 2: Memoria Python por workstation */}
          <MetricItem
            label={t('memory.perWorkstation')}
            value={metrics?.python_memory?.avg_per_workstation_mb ?? null}
            unit={t('memory.unit')}
            thresholdColor={evaluateThreshold(
              metrics?.python_memory?.avg_per_workstation_mb ?? null,
              MEMORY_PER_WS_THRESHOLD
            )}
            t={t}
          />

          {/* Métrica 3: File Descriptors (%) */}
          <MetricItem
            label={t('fileDescriptors.usage')}
            value={metrics?.file_descriptors?.usage_percent ?? null}
            unit="%"
            thresholdColor={evaluateThreshold(
              metrics?.file_descriptors?.usage_percent ?? null,
              FD_USAGE_THRESHOLD
            )}
            t={t}
          />

          {/* Métrica 4: Pool de BD (%) */}
          <MetricItem
            label={t('dbPool.usage')}
            value={metrics?.db_pool?.usage_percent ?? null}
            unit="%"
            thresholdColor={evaluateThreshold(
              metrics?.db_pool?.usage_percent ?? null,
              DB_POOL_USAGE_THRESHOLD
            )}
            t={t}
          />

          {/* Métrica 5: Tasa de transmisión de red (MB/s) */}
          <MetricItem
            label={t('network.txRate')}
            value={formatTxRate(metrics?.network?.tx_rate_bps ?? null)}
            unit="MB/s"
            thresholdColor={evaluateThreshold(
              formatTxRate(metrics?.network?.tx_rate_bps ?? null),
              TX_RATE_THRESHOLD
            )}
            t={t}
          />
        </div>
      </CardContent>
    </Card>
  )
}

// === SUBCOMPONENTES ===

interface MetricItemProps {
  label: string
  value: number | null
  unit: string
  thresholdColor: ThresholdColor | null
  t: ReturnType<typeof useTranslations>
}

/**
 * Renderiza una métrica individual con su label, valor, unidad e indicador de color.
 * Si value es null, muestra texto "no disponible" sin indicador de color.
 */
function MetricItem({ label, value, unit, thresholdColor, t }: MetricItemProps) {
  return (
    <div className="flex items-center gap-3 p-3 rounded-lg border">
      {/* Indicador de color (solo si hay valor) */}
      {thresholdColor !== null ? (
        <div
          className={`h-3 w-3 rounded-full shrink-0 ${THRESHOLD_COLOR_CLASSES[thresholdColor]}`}
        />
      ) : (
        <div className="h-3 w-3 shrink-0" />
      )}

      {/* Label y valor */}
      <div className="flex flex-col min-w-0">
        <span className="text-sm text-muted-foreground truncate">{label}</span>
        {value !== null ? (
          <span className="text-lg font-semibold">
            {value}
            {unit && <span className="text-sm font-normal text-muted-foreground ml-1">{unit}</span>}
          </span>
        ) : (
          <span className="text-sm italic text-muted-foreground">
            {t('states.unavailable')}
          </span>
        )}
      </div>
    </div>
  )
}

// === UTILIDADES ===

/**
 * Convierte tasa de transmisión de bytes/s a MB/s.
 * Retorna null si el valor de entrada es null.
 */
function formatTxRate(bps: number | null): number | null {
  if (bps === null) return null
  return Math.round((bps / (1024 * 1024)) * 100) / 100
}
