'use client';

/**
 * Página principal de monitoreo de estado del sistema.
 *
 * Muestra el estado actual de la infraestructura (CPU, RAM, Disco, Docker,
 * health checks) con indicadores visuales de color según umbrales, alertas
 * activas, y un botón de recolección manual con timeout de 30s.
 *
 * Acceso exclusivo para administradores. Redirige al dashboard principal
 * si un usuario sin rol admin accede directamente a la URL.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/hooks/useAuth';
import { useTranslations } from 'next-intl';
import { useToast } from '@/hooks/use-toast';
import {
  AlertTriangle,
  Activity,
  Server,
  Cpu,
  RefreshCw,
  Container,
  HeartPulse,
  Bell,
  Loader2,
  Database,
} from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

import {
  getSystemStatusCurrent,
  triggerCollection,
} from '@/lib/api/system-status';
import type {
  StatusSnapshot,
  ContainerMetrics,
  HealthCheck,
  Alert,
} from '@/types/system-status';
import HistoryTab from './components/HistoryTab';

// === CONSTANTES DE UMBRALES ===
const THRESHOLD_MEMORY = 80;
const THRESHOLD_DISK = 85;
const THRESHOLD_CPU = 90;
const COLLECTION_TIMEOUT_MS = 30000;
const MAX_VISIBLE_ALERTS = 10;

// === UTILIDADES DE COLOR ===

/**
 * Determina el color del gauge según el valor y tipo de métrica.
 * Verde: dentro de umbrales, Amarillo: warning, Rojo: crítico.
 */
function getMetricColor(value: number, type: 'cpu' | 'memory' | 'disk'): string {
  switch (type) {
    case 'cpu':
      if (value > THRESHOLD_CPU) return 'text-red-500';
      if (value > 70) return 'text-yellow-500';
      return 'text-green-500';
    case 'memory':
      if (value > THRESHOLD_MEMORY) return 'text-yellow-500';
      if (value > 90) return 'text-red-500';
      return 'text-green-500';
    case 'disk':
      if (value > THRESHOLD_DISK) return 'text-red-500';
      if (value > 70) return 'text-yellow-500';
      return 'text-green-500';
    default:
      return 'text-green-500';
  }
}

/**
 * Retorna el color del trazo SVG para el gauge circular.
 */
function getGaugeStrokeColor(value: number, type: 'cpu' | 'memory' | 'disk'): string {
  switch (type) {
    case 'cpu':
      if (value > THRESHOLD_CPU) return '#ef4444';
      if (value > 70) return '#eab308';
      return '#22c55e';
    case 'memory':
      if (value > THRESHOLD_MEMORY) return '#eab308';
      if (value > 90) return '#ef4444';
      return '#22c55e';
    case 'disk':
      if (value > THRESHOLD_DISK) return '#ef4444';
      if (value > 70) return '#eab308';
      return '#22c55e';
    default:
      return '#22c55e';
  }
}

// === COMPONENTE: GAUGE CIRCULAR ===

interface GaugeProps {
  value: number;
  label: string;
  type: 'cpu' | 'memory' | 'disk';
  size?: number;
}

function CircularGauge({ value, label, type, size = 120 }: GaugeProps) {
  const strokeWidth = 10;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const progress = Math.min(Math.max(value, 0), 100);
  const strokeDashoffset = circumference - (progress / 100) * circumference;
  const color = getMetricColor(value, type);
  const strokeColor = getGaugeStrokeColor(value, type);

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative" style={{ width: size, height: size }}>
        <svg
          width={size}
          height={size}
          className="transform -rotate-90"
          aria-label={`${label}: ${value}%`}
        >
          {/* Fondo del gauge */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="currentColor"
            strokeWidth={strokeWidth}
            className="text-muted/20"
          />
          {/* Progreso del gauge */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={strokeColor}
            strokeWidth={strokeWidth}
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            className="transition-all duration-500"
          />
        </svg>
        {/* Valor central */}
        <div className="absolute inset-0 flex items-center justify-center">
          <span className={`text-xl font-bold ${color}`}>
            {value.toFixed(1)}%
          </span>
        </div>
      </div>
      <span className="text-sm font-medium text-muted-foreground">{label}</span>
    </div>
  );
}

// === COMPONENTE PRINCIPAL ===

export default function SystemStatusPage() {
  const t = useTranslations('systemStatus');
  const tCommon = useTranslations('common');
  const { toast } = useToast();
  const router = useRouter();
  const { isAdmin, isLoading: authLoading, isAuthenticated } = useAuth();

  const [snapshot, setSnapshot] = useState<StatusSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [collecting, setCollecting] = useState(false);
  const [activeTab, setActiveTab] = useState('current');
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Redirigir a dashboard principal si el usuario no es admin
  useEffect(() => {
    if (!authLoading && isAuthenticated && !isAdmin()) {
      router.push('/dashboard');
    }
  }, [authLoading, isAuthenticated, isAdmin, router]);

  // Cargar datos iniciales
  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const data = await getSystemStatusCurrent();
      setSnapshot(data);
    } catch {
      toast({
        title: tCommon('error'),
        description: t('collectErrorDesc'),
        variant: 'destructive',
      });
    } finally {
      setLoading(false);
    }
  }, [t, tCommon, toast]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Limpiar timeout al desmontar
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  // Recolección manual con timeout de 30s
  const handleCollect = async () => {
    setCollecting(true);

    // Configurar timeout de 30 segundos
    const timeoutPromise = new Promise<never>((_, reject) => {
      timeoutRef.current = setTimeout(() => {
        reject(new Error('TIMEOUT'));
      }, COLLECTION_TIMEOUT_MS);
    });

    try {
      const result = await Promise.race([
        triggerCollection(),
        timeoutPromise,
      ]);

      // Limpiar timeout si la recolección terminó antes
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }

      setSnapshot(result);
      toast({
        title: t('collectSuccess'),
        description: t('collectSuccessDesc'),
      });
    } catch (error: unknown) {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }

      if (error instanceof Error && error.message === 'TIMEOUT') {
        toast({
          title: t('collectTimeout'),
          description: t('collectTimeoutDesc'),
          variant: 'destructive',
        });
      } else if (
        error !== null &&
        typeof error === 'object' &&
        'response' in error &&
        (error as { response?: { status?: number } }).response?.status === 409
      ) {
        toast({
          title: t('collectConflict'),
          description: t('collectConflictDesc'),
          variant: 'destructive',
        });
      } else {
        toast({
          title: t('collectError'),
          description: t('collectErrorDesc'),
          variant: 'destructive',
        });
      }
    } finally {
      setCollecting(false);
    }
  };

  // Formatear timestamp en zona horaria del usuario
  const formatTimestamp = (timestamp: string): string => {
    return new Date(timestamp).toLocaleString(undefined, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  // Obtener badge de estado del contenedor
  // Contenedores del sistema que no son parte de la aplicación
  const SYSTEM_CONTAINERS = ['ecs-agent', 'amazon-ssm-agent', 'aws-otel-collector'];

  // Obtener badge de estado del contenedor
  const getContainerStatusBadge = (status: ContainerMetrics['status'], name: string) => {
    switch (status) {
      case 'running':
        return <Badge className="bg-green-100 text-green-800">{t('containerRunning')}</Badge>;
      case 'stopped':
        // Contenedores del sistema en gris, los de la app en rojo
        if (SYSTEM_CONTAINERS.some(sc => name.includes(sc))) {
          return <Badge className="bg-gray-100 text-gray-600">{t('containerStopped')}</Badge>;
        }
        return <Badge variant="destructive">{t('containerStopped')}</Badge>;
      case 'restarting':
        return <Badge className="bg-yellow-100 text-yellow-800">{t('containerRestarting')}</Badge>;
    }
  };

  // Renderizar estado de carga
  if (authLoading || (!isAdmin() && isAuthenticated)) {
    return (
      <div className="container mx-auto py-6 flex items-center justify-center min-h-[400px]">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          <p className="text-muted-foreground">{tCommon('loading')}</p>
        </div>
      </div>
    );
  }

  // No renderizar contenido si no es admin (se redirigirá)
  if (!isAdmin()) {
    return null;
  }

  if (loading) {
    return (
      <div className="container mx-auto py-6 flex items-center justify-center min-h-[400px]">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          <p className="text-muted-foreground">{tCommon('loading')}</p>
        </div>
      </div>
    );
  }

  // Renderizar estado vacío
  if (!snapshot) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <PageHeader t={t} />
        <Card>
          <CardContent className="py-16">
            <div className="text-center space-y-4">
              <Database className="mx-auto h-16 w-16 text-muted-foreground" />
              <h2 className="text-xl font-semibold">{t('emptyTitle')}</h2>
              <p className="text-muted-foreground max-w-md mx-auto">
                {t('emptyMessage')}
              </p>
              <Button onClick={handleCollect} disabled={collecting} size="lg">
                {collecting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    {t('collecting')}
                  </>
                ) : (
                  <>
                    <RefreshCw className="mr-2 h-4 w-4" />
                    {t('collectBtn')}
                  </>
                )}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Banner crítico fijo */}
      {snapshot.overall_status === 'critical' && (
        <div className="sticky top-0 z-50 bg-red-600 text-white px-4 py-3 rounded-lg flex items-center gap-3 shadow-lg">
          <AlertTriangle className="h-5 w-5 shrink-0" />
          <span className="font-medium">
            {t('criticalBanner', { count: snapshot.alerts.length })}
          </span>
        </div>
      )}

      {/* Encabezado */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">{t('title')}</h1>
          <p className="text-muted-foreground mt-1">{t('subtitle')}</p>
        </div>
        <div className="flex items-center gap-3">
          <OverallStatusBadge status={snapshot.overall_status} t={t} />
          <Button onClick={handleCollect} disabled={collecting} variant="outline">
            {collecting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {t('collecting')}
              </>
            ) : (
              <>
                <RefreshCw className="mr-2 h-4 w-4" />
                {t('collectBtn')}
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Última recolección */}
      <p className="text-sm text-muted-foreground">
        {t('lastCollection', { time: formatTimestamp(snapshot.timestamp) })}
      </p>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="current">
            <Activity className="mr-2 h-4 w-4" />
            {t('tabCurrent')}
          </TabsTrigger>
          <TabsTrigger value="history">
            <Server className="mr-2 h-4 w-4" />
            {t('tabHistory')}
          </TabsTrigger>
        </TabsList>

        {/* Tab: Estado Actual */}
        <TabsContent value="current" className="space-y-6">
          {/* Gauges de métricas */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Cpu className="h-5 w-5" />
                {t('sectionMetrics')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap justify-center gap-8 md:gap-16">
                <CircularGauge
                  value={snapshot.os_metrics.cpu_percent}
                  label={t('cpu')}
                  type="cpu"
                />
                <CircularGauge
                  value={snapshot.os_metrics.memory_percent}
                  label={t('memory')}
                  type="memory"
                />
                <CircularGauge
                  value={snapshot.os_metrics.disk_percent}
                  label={t('disk')}
                  type="disk"
                />
              </div>
            </CardContent>
          </Card>

          {/* Contenedores Docker */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Container className="h-5 w-5" />
                {t('sectionDocker')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {snapshot.docker_metrics.length === 0 ? (
                <p className="text-center text-muted-foreground py-4">
                  {t('noContainers')}
                </p>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {snapshot.docker_metrics.map((container) => (
                    <ContainerCard
                      key={container.name}
                      container={container}
                      t={t}
                      getStatusBadge={getContainerStatusBadge}
                    />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Health Checks */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <HeartPulse className="h-5 w-5" />
                {t('sectionHealth')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {snapshot.health_checks.length === 0 ? (
                <p className="text-center text-muted-foreground py-4">
                  {t('noHealthChecks')}
                </p>
              ) : (
                <HealthChecksTable
                  healthChecks={snapshot.health_checks}
                  t={t}
                />
              )}
            </CardContent>
          </Card>

          {/* Alertas */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Bell className="h-5 w-5" />
                {t('sectionAlerts')}
                {snapshot.alerts.length > 0 && (
                  <Badge variant="destructive" className="ml-2">
                    {t('alertsCount', { count: snapshot.alerts.length })}
                  </Badge>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {snapshot.alerts.length === 0 ? (
                <p className="text-center text-muted-foreground py-4">
                  {t('noAlerts')}
                </p>
              ) : (
                <AlertsList alerts={snapshot.alerts} t={t} />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Tab: Histórico */}
        <TabsContent value="history">
          <HistoryTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// === SUBCOMPONENTES ===

interface PageHeaderProps {
  t: ReturnType<typeof useTranslations>;
}

function PageHeader({ t }: PageHeaderProps) {
  return (
    <div>
      <h1 className="text-3xl font-bold">{t('title')}</h1>
      <p className="text-muted-foreground mt-1">{t('subtitle')}</p>
    </div>
  );
}

interface OverallStatusBadgeProps {
  status: StatusSnapshot['overall_status'];
  t: ReturnType<typeof useTranslations>;
}

function OverallStatusBadge({ status, t }: OverallStatusBadgeProps) {
  switch (status) {
    case 'healthy':
      return (
        <Badge className="bg-green-100 text-green-800 text-sm px-3 py-1">
          {t('statusHealthy')}
        </Badge>
      );
    case 'degraded':
      return (
        <Badge className="bg-yellow-100 text-yellow-800 text-sm px-3 py-1">
          {t('statusDegraded')}
        </Badge>
      );
    case 'critical':
      return (
        <Badge variant="destructive" className="text-sm px-3 py-1">
          {t('statusCritical')}
        </Badge>
      );
  }
}

interface ContainerCardProps {
  container: ContainerMetrics;
  t: ReturnType<typeof useTranslations>;
  getStatusBadge: (status: ContainerMetrics['status'], name: string) => React.ReactNode;
}

function ContainerCard({ container, t, getStatusBadge }: ContainerCardProps) {
  return (
    <Card className="border">
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-3">
          <span className="font-medium text-sm truncate">{container.name}</span>
          {getStatusBadge(container.status, container.name)}
        </div>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div>
            <span className="text-muted-foreground">{t('containerCpu')}:</span>
            <span className="ml-1 font-medium">{container.cpu_percent.toFixed(1)}%</span>
          </div>
          <div>
            <span className="text-muted-foreground">{t('containerMemory')}:</span>
            <span className="ml-1 font-medium">{container.memory_used_mb.toFixed(0)} MB</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

interface HealthChecksTableProps {
  healthChecks: HealthCheck[];
  t: ReturnType<typeof useTranslations>;
}

function HealthChecksTable({ healthChecks, t }: HealthChecksTableProps) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t('serviceName')}</TableHead>
            <TableHead>{t('serviceStatus')}</TableHead>
            <TableHead>{t('serviceLatency')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {healthChecks.map((check) => (
            <TableRow key={check.service_name}>
              <TableCell className="font-medium">{check.service_name}</TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <div
                    className={`h-3 w-3 rounded-full ${
                      check.is_available ? 'bg-green-500' : 'bg-red-500'
                    }`}
                  />
                  <span className="text-sm">
                    {check.is_available ? t('serviceAvailable') : t('serviceUnavailable')}
                  </span>
                </div>
              </TableCell>
              <TableCell>
                {check.latency_ms !== null ? `${check.latency_ms.toFixed(0)} ms` : '—'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

interface AlertsListProps {
  alerts: Alert[];
  t: ReturnType<typeof useTranslations>;
}

function AlertsList({ alerts, t }: AlertsListProps) {
  const visibleAlerts = alerts.slice(0, MAX_VISIBLE_ALERTS);
  const remainingCount = alerts.length - MAX_VISIBLE_ALERTS;

  return (
    <div className="space-y-3">
      {visibleAlerts.map((alert, index) => (
        <div
          key={`${alert.metric_name}-${index}`}
          className={`flex items-center justify-between p-3 rounded-lg border ${
            alert.severity === 'critical'
              ? 'border-red-200 bg-red-50'
              : 'border-yellow-200 bg-yellow-50'
          }`}
        >
          <div className="flex items-center gap-3">
            <AlertTriangle
              className={`h-4 w-4 shrink-0 ${
                alert.severity === 'critical' ? 'text-red-500' : 'text-yellow-500'
              }`}
            />
            <div>
              <span className="font-medium text-sm">{alert.metric_name}</span>
              <div className="flex gap-3 text-xs text-muted-foreground mt-0.5">
                <span>{t('alertCurrent', { value: alert.current_value.toFixed(1) })}</span>
                <span>{t('alertThreshold', { threshold: alert.threshold })}</span>
              </div>
            </div>
          </div>
          <Badge
            variant={alert.severity === 'critical' ? 'destructive' : 'secondary'}
            className={
              alert.severity === 'critical'
                ? ''
                : 'bg-yellow-100 text-yellow-800'
            }
          >
            {alert.severity === 'critical' ? t('severityCritical') : t('severityWarning')}
          </Badge>
        </div>
      ))}
      {remainingCount > 0 && (
        <p className="text-sm text-muted-foreground text-center pt-2">
          {t('alertsMore', { count: remainingCount })}
        </p>
      )}
    </div>
  );
}
