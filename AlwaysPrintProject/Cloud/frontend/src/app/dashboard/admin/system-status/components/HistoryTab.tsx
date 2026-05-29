'use client'

/**
 * Tab de histórico del sistema con gráficos de evolución temporal.
 *
 * Muestra gráficos de línea para memoria, disco, CPU y swap con datos
 * de los últimos 7, 14 o 30 días. Incluye estadísticas agregadas,
 * historial de disponibilidad por servicio, y cobertura de datos.
 *
 * Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
 */

import { useState, useEffect, useCallback } from 'react'
import { useTranslations } from 'next-intl'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Dot,
} from 'recharts'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Activity,
  HardDrive,
  Cpu,
  MemoryStick,
  Server,
  Loader2,
  AlertTriangle,
} from 'lucide-react'
import {
  getSystemStatusHistory,
  getServicesUptime,
} from '@/lib/api/system-status'
import type {
  HistoryResponse,
  HistoryDataPoint,
  MetricStats,
  ServiceUptime,
} from '@/types/system-status'

// === CONSTANTES ===

/** Umbrales predefinidos para cada métrica */
const THRESHOLDS: Record<string, number> = {
  memory_percent: 80,
  disk_percent: 85,
  cpu_percent: 90,
  swap_percent: 80,
}

/** Colores para cada métrica en los gráficos */
const METRIC_COLORS: Record<string, string> = {
  memory_percent: '#8b5cf6',
  disk_percent: '#f59e0b',
  cpu_percent: '#3b82f6',
  swap_percent: '#10b981',
}

/** Opciones de rango de días */
const RANGE_OPTIONS = [7, 14, 30] as const
type RangeOption = (typeof RANGE_OPTIONS)[number]

/** Mapeo de métrica a nombre de API */
const METRIC_API_NAMES: Record<string, string> = {
  memory_percent: 'memory',
  disk_percent: 'disk',
  cpu_percent: 'cpu',
  swap_percent: 'swap',
}

// === TIPOS INTERNOS ===

interface ChartDataPoint {
  timestamp: string
  value: number
  formattedTime: string
  aboveThreshold: boolean
}

interface MetricChartData {
  metric: string
  data: ChartDataPoint[]
  stats: MetricStats
  unit: string
}

// === COMPONENTE PRINCIPAL ===

export default function HistoryTab() {
  const t = useTranslations('systemStatus')

  const [selectedRange, setSelectedRange] = useState<RangeOption>(30)
  const [metricsData, setMetricsData] = useState<Record<string, MetricChartData>>({})
  const [servicesUptime, setServicesUptime] = useState<ServiceUptime[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Cargar datos al cambiar el rango
  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      // Cargar todas las métricas en paralelo
      const metricKeys = Object.keys(METRIC_API_NAMES)
      const [memoryRes, diskRes, cpuRes, swapRes, uptimeRes] = await Promise.all([
        getSystemStatusHistory(selectedRange, METRIC_API_NAMES.memory_percent),
        getSystemStatusHistory(selectedRange, METRIC_API_NAMES.disk_percent),
        getSystemStatusHistory(selectedRange, METRIC_API_NAMES.cpu_percent),
        getSystemStatusHistory(selectedRange, METRIC_API_NAMES.swap_percent),
        getServicesUptime(selectedRange),
      ])

      const responses: HistoryResponse[] = [memoryRes, diskRes, cpuRes, swapRes]
      const newMetricsData: Record<string, MetricChartData> = {}

      metricKeys.forEach((metricKey, index) => {
        const response = responses[index]
        const threshold = THRESHOLDS[metricKey]

        const chartData: ChartDataPoint[] = response.data_points.map(
          (point: HistoryDataPoint) => ({
            timestamp: point.timestamp,
            value: point.value,
            formattedTime: formatTimestamp(point.timestamp),
            aboveThreshold: point.value > threshold,
          })
        )

        newMetricsData[metricKey] = {
          metric: metricKey,
          data: chartData,
          stats: response.stats,
          unit: response.unit,
        }
      })

      setMetricsData(newMetricsData)
      setServicesUptime(uptimeRes)
    } catch (err) {
      setError(t('historyLoadError'))
    } finally {
      setLoading(false)
    }
  }, [selectedRange, t])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // === RENDERIZADO ===

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        <span className="ml-3 text-muted-foreground">{t('historyLoading')}</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3">
        <AlertTriangle className="h-10 w-10 text-yellow-500" />
        <p className="text-muted-foreground">{error}</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Selector de rango */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">{t('historyTitle')}</h3>
        <div className="flex items-center gap-1 border rounded-md p-0.5">
          {RANGE_OPTIONS.map((days) => (
            <button
              key={days}
              onClick={() => setSelectedRange(days)}
              className={`px-3 py-1.5 text-sm font-medium rounded-sm transition-colors ${
                selectedRange === days
                  ? 'bg-primary text-primary-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted'
              }`}
            >
              {t('historyDays', { days })}
            </button>
          ))}
        </div>
      </div>

      {/* Gráficos de métricas */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <MetricChart
          metricKey="memory_percent"
          data={metricsData.memory_percent}
          icon={<MemoryStick className="h-4 w-4" />}
          t={t}
        />
        <MetricChart
          metricKey="disk_percent"
          data={metricsData.disk_percent}
          icon={<HardDrive className="h-4 w-4" />}
          t={t}
        />
        <MetricChart
          metricKey="cpu_percent"
          data={metricsData.cpu_percent}
          icon={<Cpu className="h-4 w-4" />}
          t={t}
        />
        <MetricChart
          metricKey="swap_percent"
          data={metricsData.swap_percent}
          icon={<Activity className="h-4 w-4" />}
          t={t}
        />
      </div>

      {/* Estadísticas agregadas */}
      <div>
        <h3 className="text-lg font-semibold mb-4">{t('historyStatsTitle')}</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {Object.entries(metricsData).map(([key, data]) => (
            <StatsCard key={key} metricKey={key} stats={data.stats} t={t} />
          ))}
        </div>
      </div>

      {/* Historial de disponibilidad por servicio */}
      <div>
        <h3 className="text-lg font-semibold mb-4">{t('historyUptimeTitle')}</h3>
        <Card>
          <CardContent className="p-0">
            {servicesUptime.length === 0 ? (
              <div className="flex items-center justify-center py-8 text-muted-foreground">
                <Server className="h-5 w-5 mr-2" />
                {t('historyNoUptime')}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        {t('historyServiceName')}
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        {t('historyUptimePercent')}
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        {t('historyChecksTotal')}
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        {t('historyChecksOk')}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {servicesUptime.map((service) => (
                      <tr key={service.service_name} className="hover:bg-muted/50">
                        <td className="px-4 py-3 font-medium">
                          {service.service_name}
                        </td>
                        <td className="px-4 py-3">
                          <UptimeBadge percent={service.uptime_percent} />
                        </td>
                        <td className="px-4 py-3 text-muted-foreground">
                          {service.total_checks}
                        </td>
                        <td className="px-4 py-3 text-muted-foreground">
                          {service.successful_checks}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

// === SUBCOMPONENTES ===

/** Gráfico de línea temporal para una métrica */
function MetricChart({
  metricKey,
  data,
  icon,
  t,
}: {
  metricKey: string
  data: MetricChartData | undefined
  icon: React.ReactNode
  t: ReturnType<typeof useTranslations>
}) {
  if (!data || data.data.length === 0) {
    return (
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-2 mb-4">
            {icon}
            <span className="font-medium">{t(`metric_${metricKey}`)}</span>
          </div>
          <div className="flex flex-col items-center justify-center h-48 text-muted-foreground">
            <AlertTriangle className="h-6 w-6 mb-2" />
            <span className="text-sm">{t('historyNoData')}</span>
          </div>
        </CardContent>
      </Card>
    )
  }

  const threshold = THRESHOLDS[metricKey]
  const color = METRIC_COLORS[metricKey]
  const coverage = data.stats.data_coverage_percent

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            {icon}
            <span className="font-medium">{t(`metric_${metricKey}`)}</span>
          </div>
          <CoverageBadge percent={coverage} t={t} />
        </div>

        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data.data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
              <XAxis
                dataKey="formattedTime"
                tick={{ fontSize: 10 }}
                interval="preserveStartEnd"
                tickCount={6}
              />
              <YAxis
                domain={[0, 100]}
                tick={{ fontSize: 10 }}
                tickFormatter={(value: number) => `${value}%`}
                width={40}
              />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload || payload.length === 0) return null
                  const point = payload[0].payload as ChartDataPoint
                  return (
                    <div className="bg-popover border rounded-md shadow-md p-2 text-xs">
                      <p className="font-medium">{point.formattedTime}</p>
                      <p className={point.aboveThreshold ? 'text-red-600 font-semibold' : ''}>
                        {point.value.toFixed(1)}%
                      </p>
                    </div>
                  )
                }}
              />
              <ReferenceLine
                y={threshold}
                stroke="#ef4444"
                strokeDasharray="4 4"
                strokeWidth={1.5}
                label={{
                  value: `${threshold}%`,
                  position: 'right',
                  fontSize: 10,
                  fill: '#ef4444',
                }}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke={color}
                strokeWidth={2}
                dot={<ThresholdDot threshold={threshold} color={color} />}
                activeDot={{ r: 4, strokeWidth: 2 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}

/** Punto personalizado que resalta valores por encima del umbral */
function ThresholdDot({
  cx,
  cy,
  payload,
  threshold,
  color,
}: {
  cx?: number
  cy?: number
  payload?: ChartDataPoint
  threshold: number
  color: string
}) {
  if (cx === undefined || cy === undefined || !payload) return null

  // Solo mostrar puntos si superan el umbral
  if (payload.value > threshold) {
    return (
      <Dot
        cx={cx}
        cy={cy}
        r={4}
        fill="#ef4444"
        stroke="#fff"
        strokeWidth={2}
      />
    )
  }

  // No mostrar punto para valores normales (reduce ruido visual)
  return null
}

/** Tarjeta de estadísticas agregadas para una métrica */
function StatsCard({
  metricKey,
  stats,
  t,
}: {
  metricKey: string
  stats: MetricStats
  t: ReturnType<typeof useTranslations>
}) {
  const threshold = THRESHOLDS[metricKey]
  const isMaxAboveThreshold = stats.maximum > threshold

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-sm font-medium text-muted-foreground">
            {t(`metric_${metricKey}`)}
          </span>
        </div>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              <Minus className="h-3 w-3" />
              {t('historyAvg')}
            </span>
            <span className="text-sm font-medium">{stats.average.toFixed(1)}%</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              <TrendingUp className="h-3 w-3" />
              {t('historyMax')}
            </span>
            <span
              className={`text-sm font-medium ${isMaxAboveThreshold ? 'text-red-600' : ''}`}
            >
              {stats.maximum.toFixed(1)}%
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              <TrendingDown className="h-3 w-3" />
              {t('historyMin')}
            </span>
            <span className="text-sm font-medium">{stats.minimum.toFixed(1)}%</span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

/** Badge de cobertura de datos */
function CoverageBadge({
  percent,
  t,
}: {
  percent: number
  t: ReturnType<typeof useTranslations>
}) {
  let variant: 'success' | 'warning' | 'destructive' = 'success'
  if (percent < 50) variant = 'destructive'
  else if (percent < 80) variant = 'warning'

  return (
    <Badge variant={variant} className="text-xs">
      {t('historyCoverage', { percent: percent.toFixed(0) })}
    </Badge>
  )
}

/** Badge de uptime con color según porcentaje */
function UptimeBadge({ percent }: { percent: number }) {
  let variant: 'success' | 'warning' | 'destructive' = 'success'
  if (percent < 95) variant = 'destructive'
  else if (percent < 99) variant = 'warning'

  return (
    <Badge variant={variant}>
      {percent.toFixed(2)}%
    </Badge>
  )
}

// === UTILIDADES ===

/** Formatea un timestamp ISO a formato legible corto */
function formatTimestamp(isoString: string): string {
  const date = new Date(isoString)
  const month = (date.getMonth() + 1).toString().padStart(2, '0')
  const day = date.getDate().toString().padStart(2, '0')
  const hours = date.getHours().toString().padStart(2, '0')
  const minutes = date.getMinutes().toString().padStart(2, '0')
  return `${day}/${month} ${hours}:${minutes}`
}
