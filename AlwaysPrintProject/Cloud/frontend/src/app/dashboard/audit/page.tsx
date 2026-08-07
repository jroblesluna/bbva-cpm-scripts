'use client';

import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { auditApi } from '@/lib/api';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  FileText,
  Search,
  User,
  Activity,
  TrendingUp,
  ChevronRight,
  ChevronLeft,
  RotateCcw,
  Eye,
  X,
  Monitor,
  Mail,
  Globe,
  Server,
  Clock,
} from 'lucide-react';
import type { AuditLog, AuditLogDetail, AuditLogStats, AuditLogGlobalStats, ActionType } from '@/types/audit';
import { formatDateWithTimezone } from '@/lib/dateUtils';
import { useUserTimezone } from '@/hooks/useUserTimezone';

const PAGE_SIZE = 15;
const SILENT_REFRESH_INTERVAL_MS = 15_000;

export default function AuditPage() {
  const timezone = useUserTimezone();
  const t = useTranslations('audit');
  const tCommon = useTranslations('common');

  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [stats, setStats] = useState<AuditLogStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);

  const [cursorHistory, setCursorHistory] = useState<string[]>([]);
  const [currentCursor, setCurrentCursor] = useState<string | undefined>(undefined);

  const [searchTerm, setSearchTerm] = useState('');
  const [filterActionType, setFilterActionType] = useState<ActionType | null>(null);
  const [filterEntityType, setFilterEntityType] = useState<string>('');
  const [filterEntityName, setFilterEntityName] = useState('');
  const [filterStartDate, setFilterStartDate] = useState('');
  const [filterEndDate, setFilterEndDate] = useState('');

  const [breakdownOpen, setBreakdownOpen] = useState(false);
  const [entityBreakdownOpen, setEntityBreakdownOpen] = useState(false);

  const [globalStatsOpen, setGlobalStatsOpen] = useState(false);
  const [globalStatsRange, setGlobalStatsRange] = useState<'24h' | 'week'>('24h');
  const [globalStats, setGlobalStats] = useState<AuditLogGlobalStats | null>(null);
  const [globalStatsLoading, setGlobalStatsLoading] = useState(false);

  const [actionLogsOpen, setActionLogsOpen] = useState(false);
  const [actionLogsLoading, setActionLogsLoading] = useState(false);
  const [actionLogs, setActionLogs] = useState<AuditLog[]>([]);
  const [actionLogsLabel, setActionLogsLabel] = useState('');

  const [selectedLog, setSelectedLog] = useState<AuditLogDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [isMounted, setIsMounted] = useState(false);

  const isInitialLoad = logs.length === 0 && loading;

  const entityTypeOptions = Array.from(
    new Set(logs.map((log) => log.entity_type).filter(Boolean))
  ).sort((a, b) => a.localeCompare(b));

  const resolvedEntityTypeOptions =
    filterEntityType && !entityTypeOptions.includes(filterEntityType)
      ? [filterEntityType, ...entityTypeOptions]
      : entityTypeOptions;

  const loadLogs = useCallback(
    async (cursor?: string, silent = false) => {
      try {
        const startDate = filterStartDate ? `${filterStartDate}T00:00:00` : undefined;
        const endDate = filterEndDate ? `${filterEndDate}T23:59:59.999999` : undefined;

        const data = await auditApi.search({
          limit: PAGE_SIZE,
          cursor,
          ...(filterActionType ? { action_type: filterActionType } : {}),
          ...(filterEntityType ? { entity_type: filterEntityType } : {}),
          ...(startDate ? { start_date: startDate } : {}),
          ...(endDate ? { end_date: endDate } : {}),
        });

        setLogs(data.logs || []);
        setTotal(data.total || 0);
        setNextCursor(data.next_cursor || null);
        setHasMore(data.has_more || false);
      } catch (error) {
        console.error('Error al cargar logs de auditoría:', error);
      } finally {
        if (!silent) {
          setLoading(false);
        }
      }
    },
    [filterActionType, filterEntityType, filterStartDate, filterEndDate]
  );

  const loadStats = useCallback(async () => {
    try {
      const data = await auditApi.stats();
      setStats(data);
    } catch (error) {
      console.error('Error al cargar estadísticas:', error);
    }
  }, []);

  const loadGlobalStats = useCallback(async (period: '24h' | 'week') => {
    setGlobalStatsLoading(true);
    try {
      const data = await auditApi.globalStats(period);
      setGlobalStats(data);
    } catch (error) {
      console.error('Error al cargar estadísticas globales:', error);
    } finally {
      setGlobalStatsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (globalStatsOpen) {
      loadGlobalStats(globalStatsRange);
    }
  }, [globalStatsOpen, globalStatsRange, loadGlobalStats]);

  const rangeStartDate = (period: '24h' | 'week'): string => {
    const now = new Date();
    if (period === 'week') {
      const daysSinceMonday = (now.getDay() + 6) % 7;
      const start = new Date(now);
      start.setHours(0, 0, 0, 0);
      start.setDate(now.getDate() - daysSinceMonday);
      return start.toISOString();
    }
    return new Date(now.getTime() - 24 * 60 * 60 * 1000).toISOString();
  };

  const openActionLogs = async (entityType: string, actionKey: string) => {
    // "logout" es una clave sintética: en la BD se guarda como action_type=delete
    const realActionType = actionKey === 'logout' ? 'delete' : actionKey;

    setActionLogsLabel(`${entityType} — ${getActionTypeLabel(actionKey as ActionType)}`);
    setActionLogsOpen(true);
    setActionLogsLoading(true);
    try {
      const data = await auditApi.search({
        entity_type: entityType,
        action_type: realActionType as ActionType,
        start_date: rangeStartDate(globalStatsRange),
        limit: 100,
      });
      setActionLogs(data.logs || []);
    } catch (error) {
      console.error('Error al cargar logs de la acción:', error);
      setActionLogs([]);
    } finally {
      setActionLogsLoading(false);
    }
  };

  useEffect(() => {
    loadLogs(currentCursor);
  }, [currentCursor, loadLogs]);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  useEffect(() => {
    const intervalId = setInterval(() => {
      loadLogs(currentCursor, true);
      loadStats();
    }, SILENT_REFRESH_INTERVAL_MS);

    return () => clearInterval(intervalId);
  }, [currentCursor, loadLogs, loadStats]);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!isMounted) return;

    const { style } = document.body;
    const previousOverflow = style.overflow;

    if (detailOpen) {
      style.overflow = 'hidden';
    }

    return () => {
      style.overflow = previousOverflow;
    };
  }, [detailOpen, isMounted]);

  const goToNextPage = () => {
    if (!nextCursor) return;
    setCursorHistory((prev) => [...prev, currentCursor || '']);
    setCurrentCursor(nextCursor);
  };

  const goToPreviousPage = () => {
    if (cursorHistory.length === 0) return;
    const history = [...cursorHistory];
    const previousCursor = history.pop()!;
    setCursorHistory(history);
    setCurrentCursor(previousCursor || undefined);
  };

  const goToFirstPage = () => {
    setCursorHistory([]);
    setCurrentCursor(undefined);
  };

  const resetFilters = () => {
    setFilterActionType(null);
    setFilterEntityType('');
    setFilterEntityName('');
    setFilterStartDate('');
    setFilterEndDate('');
    setSearchTerm('');
    setCursorHistory([]);
    setCurrentCursor(undefined);
  };

  const filteredLogs = logs.filter((log) => {
    const entityNameFilter = filterEntityName.trim().toLowerCase();
    if (
      entityNameFilter &&
      !(log.entity_name || '').toLowerCase().includes(entityNameFilter)
    ) {
      return false;
    }

    const s = searchTerm.toLowerCase();
    if (!s) return true;
    return (
      log.entity_type.toLowerCase().includes(s) ||
      log.action_type.toLowerCase().includes(s) ||
      log.entity_id.toLowerCase().includes(s) ||
      (log.entity_name || '').toLowerCase().includes(s)
    );
  });

  const isLogoutEvent = (
    log?: Pick<AuditLog, 'action_type' | 'entity_type' | 'old_values'>
  ): boolean => {
    if (!log) return false;
    const action =
      typeof log.old_values === 'object' && log.old_values
        ? (log.old_values as Record<string, unknown>).action
        : null;

    return (
      log.action_type === 'delete' &&
      log.entity_type.toLowerCase() === 'session' &&
      action === 'logout'
    );
  };

  const getActionTypeLabel = (
    type: ActionType,
    log?: Pick<AuditLog, 'action_type' | 'entity_type' | 'old_values'>
  ): string => {
    if (isLogoutEvent(log)) {
      return t('logout');
    }

    const labels: Record<string, string> = {
      create: t('create'),
      update: t('update'),
      delete: t('delete'),
      config_change: t('configChange'),
      contingency_toggle: t('contingency'),
      message_sent: t('messageSent'),
      command_sent: t('commandSent'),
      login: t('login'),
      login_failed: t('loginFailed'),
      logout: t('logout'),
    };
    return labels[type] || type;
  };

  const getActionTypeBadgeColor = (type: ActionType): string => {
    const colors: Record<string, string> = {
      create: 'bg-green-100 text-green-800',
      update: 'bg-blue-100 text-blue-800',
      delete: 'bg-red-100 text-red-800',
      config_change: 'bg-yellow-100 text-yellow-800',
      contingency_toggle: 'bg-orange-100 text-orange-800',
      message_sent: 'bg-indigo-100 text-indigo-800',
      command_sent: 'bg-purple-100 text-purple-800',
      login: 'bg-teal-100 text-teal-800',
      login_failed: 'bg-red-100 text-red-800',
      logout: 'bg-gray-200 text-gray-800',
    };
    return colors[type] || 'bg-gray-100 text-gray-800';
  };

  const currentPageNumber = cursorHistory.length + 1;

  const openDetail = async (log: AuditLog) => {
    setDetailOpen(true);
    setDetailLoading(true);
    setSelectedLog(null);
    try {
      const detail = (await auditApi.get(log.id)) as AuditLogDetail;
      setSelectedLog(detail);
    } catch {
      // Si falla el detalle, mostrar lo que tenemos del listado
      setSelectedLog({ ...log, user_name: null, user_email: null, workstation_ip: null });
    } finally {
      setDetailLoading(false);
    }
  };

  const closeDetail = () => {
    setDetailOpen(false);
    setSelectedLog(null);
  };

  const detailPanel =
    detailOpen && isMounted
      ? createPortal(
          <div className="fixed inset-0 z-[9999] flex justify-end">
            {/* Overlay */}
            <button
              type="button"
              className="absolute inset-0 bg-black/30"
              onClick={closeDetail}
              aria-label={tCommon('close')}
            />

            {/* Panel */}
            <div className="relative w-full max-w-md bg-white shadow-2xl flex flex-col h-full">
              {/* Header */}
              <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
                <h2 className="text-lg font-semibold text-gray-900">{t('detailTitle')}</h2>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 w-8 p-0"
                  onClick={closeDetail}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>

              {/* Content */}
              <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
                {detailLoading ? (
                  <div className="flex items-center justify-center h-32">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
                  </div>
                ) : selectedLog ? (
                  <>
                    {/* Acción */}
                    <div>
                      <p className="text-xs font-medium text-gray-400 uppercase mb-1">
                        {t('colAction')}
                      </p>
                      <Badge className={getActionTypeBadgeColor(selectedLog.action_type)}>
                        {getActionTypeLabel(selectedLog.action_type, selectedLog)}
                      </Badge>
                    </div>

                    {/* Fecha */}
                    <div className="flex items-start gap-3">
                      <Clock className="h-4 w-4 text-gray-400 mt-0.5 flex-shrink-0" />
                      <div>
                        <p className="text-xs font-medium text-gray-400 uppercase mb-0.5">
                          {t('colDate')}
                        </p>
                        <p className="text-sm text-gray-900">
                          {formatDateWithTimezone(selectedLog.created_at, timezone)}
                        </p>
                      </div>
                    </div>

                    {/* Quién lo hizo */}
                    <div className="bg-blue-50 rounded-lg p-4 space-y-3">
                      <p className="text-xs font-semibold text-blue-700 uppercase">
                        {t('detailWho')}
                      </p>
                      <div className="flex items-start gap-3">
                        <User className="h-4 w-4 text-blue-500 mt-0.5 flex-shrink-0" />
                        <div>
                          <p className="text-xs text-gray-500">{t('detailUserName')}</p>
                          <p className="text-sm font-medium text-gray-900">
                            {selectedLog.user_name || (
                              <span className="text-gray-400 italic">{t('detailSystem')}</span>
                            )}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-start gap-3">
                        <Mail className="h-4 w-4 text-blue-500 mt-0.5 flex-shrink-0" />
                        <div>
                          <p className="text-xs text-gray-500">{t('detailUserEmail')}</p>
                          <p className="text-sm font-medium text-gray-900">
                            {selectedLog.user_email || (
                              <span className="text-gray-400 italic">—</span>
                            )}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-start gap-3">
                        <Globe className="h-4 w-4 text-blue-500 mt-0.5 flex-shrink-0" />
                        <div>
                          <p className="text-xs text-gray-500">{t('detailIpAddress')}</p>
                          <p className="text-sm font-mono text-gray-900">
                            {selectedLog.ip_address || (
                              <span className="text-gray-400 italic">—</span>
                            )}
                          </p>
                        </div>
                      </div>
                    </div>

                    {/* Entidad afectada */}
                    <div className="bg-gray-50 rounded-lg p-4 space-y-3">
                      <p className="text-xs font-semibold text-gray-500 uppercase">
                        {t('detailEntity')}
                      </p>
                      <div className="flex items-start gap-3">
                        <FileText className="h-4 w-4 text-gray-400 mt-0.5 flex-shrink-0" />
                        <div>
                          <p className="text-xs text-gray-500">{t('colEntity')}</p>
                          <p className="text-sm font-medium text-gray-900">
                            {selectedLog.entity_type}
                          </p>
                        </div>
                      </div>
                      {selectedLog.entity_name && (
                        <div className="flex items-start gap-3">
                          <FileText className="h-4 w-4 text-gray-400 mt-0.5 flex-shrink-0" />
                          <div>
                            <p className="text-xs text-gray-500">{t('detailEntityName')}</p>
                            <p className="text-sm font-medium text-gray-900">
                              {selectedLog.entity_name}
                            </p>
                          </div>
                        </div>
                      )}
                      {selectedLog.workstation_ip && (
                        <div className="flex items-start gap-3">
                          <Monitor className="h-4 w-4 text-gray-400 mt-0.5 flex-shrink-0" />
                          <div>
                            <p className="text-xs text-gray-500">{t('detailWorkstationIp')}</p>
                            <p className="text-sm font-mono text-gray-900">
                              {selectedLog.workstation_ip}
                            </p>
                          </div>
                        </div>
                      )}
                      <div className="flex items-start gap-3">
                        <Server className="h-4 w-4 text-gray-400 mt-0.5 flex-shrink-0" />
                        <div>
                          <p className="text-xs text-gray-500">{t('detailEntityId')}</p>
                          <p className="text-xs font-mono text-gray-500 break-all">
                            {selectedLog.entity_id}
                          </p>
                        </div>
                      </div>
                    </div>

                    {/* Cambios */}
                    {(selectedLog.old_values || selectedLog.new_values) && (
                      <div className="space-y-3">
                        <p className="text-xs font-semibold text-gray-500 uppercase">
                          {t('detailChanges')}
                        </p>
                        {selectedLog.old_values && (
                          <div>
                            <p className="text-xs font-medium text-red-500 mb-1">
                              {t('detailOldValues')}
                            </p>
                            <pre className="text-xs bg-red-50 border border-red-100 rounded p-3 overflow-auto max-h-40 text-gray-700 whitespace-pre-wrap break-all">
                              {JSON.stringify(selectedLog.old_values, null, 2)}
                            </pre>
                          </div>
                        )}
                        {selectedLog.new_values && (
                          <div>
                            <p className="text-xs font-medium text-green-600 mb-1">
                              {t('detailNewValues')}
                            </p>
                            <pre className="text-xs bg-green-50 border border-green-100 rounded p-3 overflow-auto max-h-40 text-gray-700 whitespace-pre-wrap break-all">
                              {JSON.stringify(selectedLog.new_values, null, 2)}
                            </pre>
                          </div>
                        )}
                      </div>
                    )}
                  </>
                ) : null}
              </div>
            </div>
          </div>,
          document.body
        )
      : null;

  const closeActionLogs = () => {
    setActionLogsOpen(false);
    setActionLogs([]);
  };

  if (isInitialLoad) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">{tCommon('loading')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
          <p className="mt-2 text-gray-600">{t('subtitle')}</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="mt-1 shrink-0"
          onClick={() => setGlobalStatsOpen(true)}
        >
          {t('viewGlobalInfo')}
        </Button>
      </div>

      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Card 1: Acciones últimas 24h + botón de desglose */}
          <div className="relative bg-white rounded-lg shadow p-6">
            <Button
              variant="outline"
              size="sm"
              className="absolute top-3 right-3"
              onClick={() => setBreakdownOpen(true)}
            >
              {t('viewBreakdown')}
            </Button>
            <div className="flex items-center">
              <div className="p-3 bg-green-100 rounded-lg">
                <Activity className="h-6 w-6 text-green-600" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">{t('last24h')}</p>
                <p className="text-2xl font-bold text-gray-900">
                  {stats.recent_activity_count}
                </p>
              </div>
            </div>
          </div>

          {/* Card 2: Recuento de tipos de acción en 24h */}
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="p-3 bg-yellow-100 rounded-lg">
                <TrendingUp className="h-6 w-6 text-yellow-600" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">{t('actionTypes24h')}</p>
                <p className="text-2xl font-bold text-gray-900">
                  {Object.keys(stats.actions_by_type_24h).length}
                </p>
              </div>
            </div>
          </div>

          {/* Card 3: Recuento de entidades en 24h + botón de desglose */}
          <div className="relative bg-white rounded-lg shadow p-6">
            <Button
              variant="outline"
              size="sm"
              className="absolute top-3 right-3"
              onClick={() => setEntityBreakdownOpen(true)}
            >
              {t('viewBreakdown')}
            </Button>
            <div className="flex items-center">
              <div className="p-3 bg-purple-100 rounded-lg">
                <Server className="h-6 w-6 text-purple-600" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">{t('entities24h')}</p>
                <p className="text-2xl font-bold text-gray-900">
                  {Object.keys(stats.entities_by_type_24h).length}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Popup: desglose de acciones por tipo en las últimas 24h */}
      <Dialog open={breakdownOpen} onOpenChange={setBreakdownOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('breakdownTitle')}</DialogTitle>
          </DialogHeader>
          {stats && Object.keys(stats.actions_by_type_24h).length > 0 ? (
            <div className="grid grid-cols-2 gap-4">
              {Object.entries(stats.actions_by_type_24h).map(([type, count]) => (
                <div key={type} className="text-center">
                  <Badge className={getActionTypeBadgeColor(type as ActionType)}>
                    {getActionTypeLabel(type as ActionType)}
                  </Badge>
                  <p className="mt-2 text-2xl font-bold text-gray-900">{count}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500 text-center py-4">{tCommon('noData')}</p>
          )}
        </DialogContent>
      </Dialog>

      {/* Popup: desglose de acciones por tipo de entidad en las últimas 24h */}
      <Dialog open={entityBreakdownOpen} onOpenChange={setEntityBreakdownOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('entityBreakdownTitle')}</DialogTitle>
          </DialogHeader>
          {stats && Object.keys(stats.entities_by_type_24h).length > 0 ? (
            <div className="grid grid-cols-2 gap-4">
              {Object.entries(stats.entities_by_type_24h).map(([type, count]) => (
                <div key={type} className="text-center">
                  <span className="text-xs font-medium text-gray-600 bg-gray-100 px-2 py-1 rounded">
                    {type}
                  </span>
                  <p className="mt-2 text-2xl font-bold text-gray-900">{count}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500 text-center py-4">{tCommon('noData')}</p>
          )}
        </DialogContent>
      </Dialog>

      {/* Popup: información global de auditoría, agrupada por entidad.
          Un mismo contenedor (track) desliza horizontalmente entre la vista
          de entidades y el listado de logs de una acción puntual. */}
      <Dialog
        open={globalStatsOpen}
        onOpenChange={(open) => {
          setGlobalStatsOpen(open);
          if (!open) closeActionLogs();
        }}
      >
        <DialogContent className="max-w-2xl max-h-[85vh] p-0 overflow-hidden flex flex-col">
          <DialogHeader className="px-6 pt-6 pb-2 flex-shrink-0">
            <DialogTitle className="flex items-center gap-2">
              {actionLogsOpen && (
                <button
                  type="button"
                  onClick={closeActionLogs}
                  className="p-1 -ml-1 rounded hover:bg-gray-100"
                  title={tCommon('back')}
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
              )}
              <span className="truncate">
                {actionLogsOpen ? actionLogsLabel : t('globalInfoTitle')}
              </span>
            </DialogTitle>
          </DialogHeader>

          <div className="flex items-center justify-between gap-2 px-6 pb-4 flex-shrink-0 border-b border-gray-200">
            <div className="flex items-center gap-2">
              <Button
                variant={globalStatsRange === '24h' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setGlobalStatsRange('24h')}
              >
                {t('rangeLast24h')}
              </Button>
              <Button
                variant={globalStatsRange === 'week' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setGlobalStatsRange('week')}
              >
                {t('rangeLastWeek')}
              </Button>
            </div>
            {!actionLogsOpen && globalStats && (
              <p className="text-sm text-gray-600 shrink-0">
                {t('globalInfoTotal', { total: globalStats.total_actions })}
              </p>
            )}
          </div>

          <div className="flex-1 min-h-0 overflow-hidden">
            <div
              className="flex h-full transition-transform duration-300 ease-in-out"
              style={{ width: '200%', transform: actionLogsOpen ? 'translateX(-50%)' : 'translateX(0%)' }}
            >
              {/* Vista 1: desglose por entidad */}
              <div className="w-1/2 px-6 pt-4 pb-6 overflow-y-auto">
                {globalStatsLoading ? (
                  <div className="flex items-center justify-center h-32">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
                  </div>
                ) : globalStats && Object.keys(globalStats.actions_by_entity_and_type).length > 0 ? (
                  <div className="space-y-4">
                    {Object.entries(globalStats.actions_by_entity_and_type)
                      .sort(([, a], [, b]) => {
                        const totalA = Object.values(a).reduce((sum, n) => sum + n, 0);
                        const totalB = Object.values(b).reduce((sum, n) => sum + n, 0);
                        return totalB - totalA;
                      })
                      .map(([entityType, actionCounts]) => {
                        const entityTotal = Object.values(actionCounts).reduce((sum, n) => sum + n, 0);
                        return (
                          <div key={entityType} className="border border-gray-200 rounded-lg p-3">
                            <div className="flex items-center justify-between mb-2">
                              <span className="text-sm font-semibold text-gray-900">{entityType}</span>
                              <span className="text-xs text-gray-500">
                                {t('globalInfoEntityTotal', { total: entityTotal })}
                              </span>
                            </div>
                            {Object.keys(actionCounts).length > 0 ? (
                              <div className="flex flex-wrap gap-2">
                                {Object.entries(actionCounts).map(([type, count]) => (
                                  <Badge
                                    key={type}
                                    className={`${getActionTypeBadgeColor(type as ActionType)} flex items-center gap-1.5 pr-1.5`}
                                  >
                                    {getActionTypeLabel(type as ActionType)}: {count}
                                    <button
                                      type="button"
                                      title={t('viewActionLogs')}
                                      onClick={() => openActionLogs(entityType, type)}
                                      className="rounded-full hover:bg-black/10 p-0.5 -mr-0.5"
                                    >
                                      <Eye className="h-3 w-3" />
                                    </button>
                                  </Badge>
                                ))}
                              </div>
                            ) : (
                              <p className="text-xs text-gray-400 italic">{t('globalInfoNoActivity')}</p>
                            )}
                          </div>
                        );
                      })}
                  </div>
                ) : (
                  <p className="text-sm text-gray-500 text-center py-4">{tCommon('noData')}</p>
                )}
              </div>

              {/* Vista 2: listado de logs de la acción/entidad seleccionada */}
              <div className="w-1/2 px-6 pt-4 pb-6 overflow-y-auto">
                {actionLogsLoading ? (
                  <div className="flex items-center justify-center h-32">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
                  </div>
                ) : actionLogs.length > 0 ? (
                  <div className="divide-y divide-gray-100">
                    {actionLogs.map((log) => (
                      <div key={log.id} className="flex items-center justify-between py-3">
                        <div className="min-w-0">
                          <p className="text-sm text-gray-900">
                            {formatDateWithTimezone(log.created_at, timezone)}
                          </p>
                          <p className="text-xs text-gray-500 truncate">
                            {log.entity_name || log.entity_id} · {log.ip_address || '-'}
                          </p>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 w-7 p-0 shrink-0"
                          title={t('viewDetails')}
                          onClick={() => openDetail(log)}
                        >
                          <Eye className="h-4 w-4 text-gray-400 hover:text-blue-600" />
                        </Button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-500 text-center py-4">{tCommon('noData')}</p>
                )}
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <div className="bg-white rounded-lg shadow p-4">
        <div className="grid grid-cols-1 md:grid-cols-7 gap-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-gray-400" />
            <Input
              type="text"
              placeholder={t('searchPlaceholder')}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-10"
            />
          </div>
          <select
            value={filterActionType || 'all'}
            onChange={(e) => {
              setFilterActionType(
                e.target.value === 'all' ? null : (e.target.value as ActionType)
              );
              setCursorHistory([]);
              setCurrentCursor(undefined);
            }}
            className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">{t('allTypes')}</option>
            <option value="create">{t('create')}</option>
            <option value="update">{t('update')}</option>
            <option value="delete">{t('delete')}</option>
            <option value="config_change">{t('configChange')}</option>
            <option value="contingency_toggle">{t('contingency')}</option>
            <option value="message_sent">{t('messageSent')}</option>
            <option value="command_sent">{t('commandSent')}</option>
            <option value="login">{t('login')}</option>
            <option value="login_failed">{t('loginFailed')}</option>
          </select>
          <select
            value={filterEntityType || 'all'}
            onChange={(e) => {
              setFilterEntityType(e.target.value === 'all' ? '' : e.target.value);
              setCursorHistory([]);
              setCurrentCursor(undefined);
            }}
            className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">{t('allEntityTypes')}</option>
            {resolvedEntityTypeOptions.map((entityType) => (
              <option key={entityType} value={entityType}>
                {entityType}
              </option>
            ))}
          </select>
          <Input
            type="text"
            placeholder={t('filterEntityName')}
            value={filterEntityName}
            onChange={(e) => setFilterEntityName(e.target.value)}
          />
          <Input
            type="date"
            aria-label={t('filterStartDate')}
            value={filterStartDate}
            onChange={(e) => {
              setFilterStartDate(e.target.value);
              setCursorHistory([]);
              setCurrentCursor(undefined);
            }}
          />
          <Input
            type="date"
            aria-label={t('filterEndDate')}
            value={filterEndDate}
            onChange={(e) => {
              setFilterEndDate(e.target.value);
              setCursorHistory([]);
              setCurrentCursor(undefined);
            }}
          />
          <Button variant="outline" onClick={resetFilters} className="flex items-center gap-2">
            <RotateCcw className="h-4 w-4" />
            {tCommon('reset')}
          </Button>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow overflow-hidden">
        {filteredLogs.length === 0 ? (
          <div className="text-center py-12">
            <FileText className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-2 text-sm font-medium text-gray-900">{t('emptyTitle')}</h3>
            <p className="mt-1 text-sm text-gray-500">
              {searchTerm ||
              filterActionType ||
              filterEntityType ||
              filterEntityName ||
              filterStartDate ||
              filterEndDate
                ? t('emptyFilterMessage')
                : t('emptyMessage')}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    {t('colDate')}
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    {t('colAction')}
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    {t('colEntity')}
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    {t('colEntityId')}
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    {t('colIp')}
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    {t('colDetails')}
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {filteredLogs.map((log) => (
                  <tr key={log.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {formatDateWithTimezone(log.created_at, timezone)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <Badge className={getActionTypeBadgeColor(log.action_type)}>
                        {getActionTypeLabel(log.action_type, log)}
                      </Badge>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="inline-flex items-center gap-1.5">
                        <span className="text-xs font-medium text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">
                          {log.entity_type}
                        </span>
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {log.entity_name ? (
                        <div>
                          <span className="text-sm font-medium text-gray-900">
                            {log.entity_name}
                          </span>
                          <span className="block text-xs text-gray-400 font-mono">
                            {log.entity_id.substring(0, 8)}
                          </span>
                        </div>
                      ) : (
                        <span className="text-sm text-gray-500 font-mono">
                          {log.entity_id.substring(0, 8)}...
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {log.ip_address || '-'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0"
                        onClick={() => openDetail(log)}
                        title={t('viewDetails')}
                      >
                        <Eye className="h-4 w-4 text-gray-400 hover:text-blue-600" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {(hasMore || cursorHistory.length > 0) && (
          <div className="bg-white px-4 py-3 flex items-center justify-between border-t border-gray-200 sm:px-6">
            <div className="flex-1 flex items-center justify-between">
              <p className="text-sm text-gray-700">
                {t('pagination', {
                  start: (currentPageNumber - 1) * PAGE_SIZE + 1,
                  end: Math.min(currentPageNumber * PAGE_SIZE, total),
                  total,
                })}
              </p>
              <div className="flex items-center gap-2">
                {cursorHistory.length > 0 && (
                  <Button variant="outline" size="sm" onClick={goToFirstPage}>
                    {tCommon('first')}
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={goToPreviousPage}
                  disabled={cursorHistory.length === 0}
                >
                  {tCommon('previous')}
                </Button>
                <span className="text-sm text-gray-600 px-2">
                  {t('pageNumber', { page: currentPageNumber })}
                </span>
                <Button variant="outline" size="sm" onClick={goToNextPage} disabled={!hasMore}>
                  {tCommon('next')}
                  <ChevronRight className="h-4 w-4 ml-1" />
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>

      {detailPanel}
    </div>
  );
}
