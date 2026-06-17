/**
 * Página de gestión de IPs públicas pendientes de autorización.
 *
 * Solo accesible para administradores.
 * Permite autorizar o rechazar IPs desde las cuales clientes intentaron conectarse.
 */

'use client';

import { useState, useEffect, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import {
  Globe,
  CheckCircle,
  XCircle,
  Clock,
  AlertCircle,
  RefreshCw,
  Search,
  Building2,
  ChevronLeft,
  ChevronRight,
  X,
  Monitor,
  User,
  Info,
  LayoutGrid,
  List,
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { formatDateWithTimezone } from '@/lib/dateUtils';
import { useUserTimezone } from '@/hooks/useUserTimezone';

interface PendingIP {
  id: string;
  ip_address: string;
  description: string | null;
  first_seen: string;
  created_at: string;
  last_hostname: string | null;
  last_user: string | null;
  request_count: number;
  first_payload: string | null;
}

interface Account {
  id: string;
  name: string;
  is_active: boolean;
}

export default function PendingIPsPage() {
  const queryClient = useQueryClient();
  const userTimezone = useUserTimezone();
  const t = useTranslations('pendingIps');
  const tCommon = useTranslations('common');
  const [searchTerm, setSearchTerm] = useState('');
  const [viewMode, setViewMode] = useState<'cards' | 'table'>('cards');
  const [authorizingIP, setAuthorizingIP] = useState<PendingIP | null>(null);
  const [selectedOrgId, setSelectedOrgId] = useState('');
  const [customDescription, setCustomDescription] = useState('');
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const [page, setPage] = useState(1);
  const [infoBanner, setInfoBanner] = useState<string | null>(null);
  const pageSize = 10;

  // Query para IPs pendientes
  const {
    data: pendingIPs,
    isLoading,
    isFetching,
    error,
  } = useQuery({
    queryKey: ['pending-ips'],
    queryFn: async () => {
      const response = await api.get('/organizations/public-ips/pending');
      return response.data as PendingIP[];
    },
  });

  // Query para cuentas (usada en el modal de autorización)
  const { data: accountsData } = useQuery({
    queryKey: ['accounts', 'list-for-pending-ips'],
    queryFn: async () => {
      const response = await api.get('/organizations/');
      return response.data;
    },
  });

  // Mutation para autorizar IP
  const authorizeMutation = useMutation({
    mutationFn: async ({
      ipId,
      accountId,
      description,
    }: {
      ipId: string;
      accountId: string;
      description?: string;
    }) => {
      const response = await api.post(`/organizations/public-ips/${ipId}/authorize`, {
        organization_id: accountId,
        description: description || undefined,
      });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pending-ips'] });
      queryClient.invalidateQueries({ queryKey: ['accounts'] });
      queryClient.invalidateQueries({ queryKey: ['accounts', 'list-for-pending-ips'] });
      setAuthorizingIP(null);
      setSelectedOrgId('');
      setCustomDescription('');
    },
    onError: (error: unknown) => {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '';
      if (detail.includes('ya está autorizada')) {
        // Otro admin ya la autorizó: refrescar lista y cerrar modal
        queryClient.invalidateQueries({ queryKey: ['pending-ips'] });
        setAuthorizingIP(null);
        setSelectedOrgId('');
        setCustomDescription('');
        setInfoBanner(`La IP ${authorizingIP?.ip_address} ya había sido autorizada por otro administrador. La lista fue actualizada.`);
      }
    },
  });

  // Mutation para rechazar IP
  const rejectMutation = useMutation({
    mutationFn: async (ipId: string) => {
      await api.delete(`/organizations/public-ips/${ipId}/reject`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pending-ips'] });
    },
  });

  const handleAuthorize = () => {
    if (!authorizingIP || !selectedOrgId) return;

    authorizeMutation.mutate({
      ipId: authorizingIP.id,
      accountId: selectedOrgId,
      description: customDescription || undefined,
    });
  };

  const handleReject = (ip: PendingIP) => {
    if (confirm(t('rejectConfirm', { ip: ip.ip_address }))) {
      rejectMutation.mutate(ip.id);
    }
  };

  // Filtrar IPs por búsqueda
  const filteredIPs =
    pendingIPs?.filter((ip) =>
      ip.ip_address.toLowerCase().includes(searchTerm.toLowerCase())
    ) || [];

  const totalFiltered = filteredIPs.length;
  const totalPages = Math.ceil(totalFiltered / pageSize);
  const paginatedIPs = filteredIPs.slice((page - 1) * pageSize, page * pageSize);
  const paginationStart = (page - 1) * pageSize + 1;
  const paginationEnd = Math.min(page * pageSize, totalFiltered);

  const accounts = accountsData?.items || [];

  // Actualizar timestamp cuando los datos se cargan exitosamente
  useEffect(() => {
    if (pendingIPs && !isFetching) {
      setLastUpdated(new Date());
    }
  }, [pendingIPs, isFetching]);

  const handleRefresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['pending-ips'] });
  }, [queryClient]);

  if (isLoading) {
    return (
      <div className="max-w-screen-2xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-8">{t('title')}</h1>
        <div className="animate-pulse space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-32 bg-gray-200 rounded-lg"></div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-screen-2xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-8">{t('title')}</h1>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Error al cargar IPs pendientes. Por favor, intenta de nuevo.
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="max-w-screen-2xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-gray-900">{t('title')}</h1>
          <p className="text-sm text-gray-600 mt-1">{t('subtitle')}</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500 whitespace-nowrap">
            {formatDateWithTimezone(lastUpdated, userTimezone)}
          </span>
          <Button
            size="sm"
            onClick={handleRefresh}
            disabled={isFetching}
          >
            <RefreshCw className={`w-4 h-4 mr-1 ${isFetching ? 'animate-spin' : ''}`} />
            {tCommon('refresh')}
          </Button>
        </div>
      </div>

      {/* Estadísticas */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">{t('totalPending')}</p>
                <p className="text-3xl font-bold text-gray-900">{pendingIPs?.length || 0}</p>
              </div>
              <Clock className="w-12 h-12 text-amber-600" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">{t('activeAccounts')}</p>
                <p className="text-3xl font-bold text-gray-900">
                  {accounts.filter((a: Account) => a.is_active).length}
                </p>
              </div>
              <Building2 className="w-12 h-12 text-blue-600" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">{t('filtered')}</p>
                <p className="text-3xl font-bold text-gray-900">{filteredIPs.length}</p>
              </div>
              <Search className="w-12 h-12 text-green-600" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Banner: IP ya autorizada por otro admin */}
      {infoBanner && (
        <Alert className="mb-4 border-amber-300 bg-amber-50 text-amber-800">
          <Info className="h-4 w-4 text-amber-600" />
          <AlertDescription className="flex items-center justify-between">
            <span>{infoBanner}</span>
            <Button variant="ghost" size="sm" onClick={() => setInfoBanner(null)} className="h-6 w-6 p-0 ml-3 text-amber-600 hover:text-amber-800 hover:bg-amber-100">
              <X className="h-4 w-4" />
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {/* Búsqueda y toggle de vista */}
      <Card className="mb-6">
        <CardContent className="p-4">
          <div className="flex items-center gap-3">
            <Search className="w-5 h-5 text-gray-400 shrink-0" />
            <Input
              type="text"
              placeholder={t('searchPlaceholder')}
              value={searchTerm}
              onChange={(e) => { setSearchTerm(e.target.value); setPage(1); }}
              className="flex-1"
            />
            <div className="flex items-center gap-1 border rounded-md p-0.5">
              <Button variant={viewMode === 'cards' ? 'default' : 'ghost'} size="sm" onClick={() => setViewMode('cards')} className="h-8 w-8 p-0">
                <LayoutGrid className="w-4 h-4" />
              </Button>
              <Button variant={viewMode === 'table' ? 'default' : 'ghost'} size="sm" onClick={() => setViewMode('table')} className="h-8 w-8 p-0">
                <List className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Lista de IPs pendientes */}
      {viewMode === 'cards' ? (
        <div className="space-y-4">
          {filteredIPs.length > 0 ? (
            paginatedIPs.map((ip) => (
              <Card key={ip.id} className="hover:shadow-md transition">
                <CardContent className="p-4 sm:p-6">
                  <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
                    <div className="flex items-start flex-1 min-w-0">
                      <div className="rounded-full p-2 bg-amber-100 mr-3 shrink-0">
                        <Globe className="w-5 h-5 text-amber-600" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2 mb-1">
                          <h3 className="text-base font-semibold text-gray-900">
                            {ip.ip_address}
                          </h3>
                          <Badge variant="secondary" className="text-xs">
                            <Clock className="w-3 h-3 mr-1" />
                            {t('pending')}
                          </Badge>
                        </div>

                        {ip.description && (
                          <p className="text-sm text-gray-600 mb-1">{ip.description}</p>
                        )}

                        {(ip.last_hostname || ip.last_user) && (
                          <div className="flex flex-wrap gap-3 mb-1">
                            {ip.last_hostname && (
                              <span className="flex items-center gap-1 text-xs text-gray-600 bg-gray-100 px-2 py-0.5 rounded">
                                <Monitor className="w-3 h-3 text-gray-500" />
                                {ip.last_hostname}
                              </span>
                            )}
                            {ip.last_user && (
                              <span className="flex items-center gap-1 text-xs text-gray-600 bg-gray-100 px-2 py-0.5 rounded">
                                <User className="w-3 h-3 text-gray-500" />
                                {ip.last_user}
                              </span>
                            )}
                            <span className="flex items-center gap-1 text-xs text-gray-600 bg-blue-50 px-2 py-0.5 rounded">
                              {t('requestCount', { count: ip.request_count })}
                            </span>
                          </div>
                        )}

                        {ip.first_payload && (
                          <details className="mb-1">
                            <summary className="text-xs text-blue-600 cursor-pointer hover:text-blue-800">
                              {t('viewPayload')}
                            </summary>
                            <pre className="text-xs bg-gray-50 border rounded p-2 mt-1 overflow-x-auto max-w-lg whitespace-pre-wrap">
                              {JSON.stringify(JSON.parse(ip.first_payload), null, 2)}
                            </pre>
                          </details>
                        )}

                        <div className="text-xs text-gray-500">
                          <span>{t('firstSeen')} {formatDateWithTimezone(ip.first_seen, userTimezone)}</span>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 sm:ml-4 sm:shrink-0">
                      <Button
                        variant="default"
                        size="sm"
                        onClick={() => setAuthorizingIP(ip)}
                        disabled={authorizeMutation.isPending || rejectMutation.isPending}
                      >
                        <CheckCircle className="w-4 h-4 mr-1" />
                        {t('authorize')}
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => handleReject(ip)}
                        disabled={authorizeMutation.isPending || rejectMutation.isPending}
                      >
                        <XCircle className="w-4 h-4 mr-1" />
                        {t('reject')}
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))
          ) : (
            <Card>
              <CardContent className="p-12 text-center">
                <Globe className="w-16 h-16 text-gray-300 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-gray-900 mb-2">{t('emptyTitle')}</h3>
                <p className="text-gray-600 mb-4">
                  {searchTerm ? t('emptyFilter') : t('emptyMessage')}
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      ) : (
        /* Vista de tabla */
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('tableHeaderIp')}</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('tableHeaderHostname')}</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('tableHeaderUser')}</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('tableHeaderRequests')}</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('tableHeaderFirstSeen')}</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('tableHeaderActions')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {paginatedIPs.length > 0 ? (
                  paginatedIPs.map((ip) => (
                    <tr key={ip.id} className="hover:bg-gray-50">
                      <td className="px-3 py-3 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-gray-900">{ip.ip_address}</span>
                          {ip.first_payload && (
                            <details className="inline">
                              <summary className="text-xs text-blue-600 cursor-pointer hover:text-blue-800">
                                <Info className="w-3 h-3 inline" />
                              </summary>
                              <pre className="absolute z-10 text-xs bg-white border rounded p-2 mt-1 shadow-lg max-w-md whitespace-pre-wrap">
                                {JSON.stringify(JSON.parse(ip.first_payload), null, 2)}
                              </pre>
                            </details>
                          )}
                        </div>
                        {ip.description && (
                          <p className="text-xs text-gray-500 truncate max-w-[200px]">{ip.description}</p>
                        )}
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap">
                        {ip.last_hostname ? (
                          <span className="flex items-center gap-1 text-xs text-gray-700">
                            <Monitor className="w-3 h-3 text-gray-400" />
                            {ip.last_hostname}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap">
                        {ip.last_user ? (
                          <span className="flex items-center gap-1 text-xs text-gray-700">
                            <User className="w-3 h-3 text-gray-400" />
                            {ip.last_user}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap">
                        <Badge variant="secondary" className="text-xs">
                          {ip.request_count}
                        </Badge>
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap text-xs text-gray-600">
                        {formatDateWithTimezone(ip.first_seen, userTimezone)}
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap">
                        <div className="flex items-center gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0"
                            title={t('authorize')}
                            onClick={() => setAuthorizingIP(ip)}
                            disabled={authorizeMutation.isPending || rejectMutation.isPending}
                          >
                            <CheckCircle className="w-4 h-4 text-green-600" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 p-0"
                            title={t('reject')}
                            onClick={() => handleReject(ip)}
                            disabled={authorizeMutation.isPending || rejectMutation.isPending}
                          >
                            <XCircle className="w-4 h-4 text-red-600" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={6} className="px-3 py-12 text-center">
                      <Globe className="w-12 h-12 text-gray-300 mx-auto mb-3" />
                      <p className="text-sm text-gray-600">
                        {searchTerm ? t('emptyFilter') : t('emptyMessage')}
                      </p>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Paginación */}
      {totalFiltered > 0 && totalPages > 1 && (
        <div className="bg-white rounded-lg shadow px-4 py-3 flex items-center justify-between border border-gray-200 mt-4 sm:px-6">
          <div className="flex-1 flex items-center justify-between">
            <p className="text-sm text-gray-700">
              {t('pagination', { start: paginationStart, end: paginationEnd, total: totalFiltered })}
            </p>
            <div className="flex items-center gap-2">
              {page > 1 && (
                <Button variant="outline" size="sm" onClick={() => setPage(1)}>
                  {tCommon('first')}
                </Button>
              )}
              <Button variant="outline" size="sm" onClick={() => setPage(page - 1)} disabled={page <= 1}>
                <ChevronLeft className="h-4 w-4 mr-1" />
                {tCommon('previous')}
              </Button>
              <span className="text-sm text-gray-600 px-2">
                {t('pageNumber', { page })}
              </span>
              <Button variant="outline" size="sm" onClick={() => setPage(page + 1)} disabled={page >= totalPages}>
                {tCommon('next')}
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Modal de autorización */}
      {authorizingIP && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <Card className="max-w-md w-full">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>{t('authorizeTitle')}</CardTitle>
              <Button variant="ghost" size="sm" onClick={() => setAuthorizingIP(null)} className="h-8 w-8 p-0">
                <X className="h-5 w-5" />
              </Button>
            </CardHeader>
            <CardContent className="space-y-4">
              <Alert>
                <Globe className="h-4 w-4" />
                <AlertDescription className="space-y-1">
                  <div><strong>{t('ipLabel')}</strong> {authorizingIP.ip_address}</div>
                  {authorizingIP.last_hostname && (
                    <div className="flex items-center gap-1 text-sm">
                      <Monitor className="w-3 h-3" />
                      <span>{authorizingIP.last_hostname}</span>
                    </div>
                  )}
                  {authorizingIP.last_user && (
                    <div className="flex items-center gap-1 text-sm">
                      <User className="w-3 h-3" />
                      <span>{authorizingIP.last_user}</span>
                    </div>
                  )}
                </AlertDescription>
              </Alert>

              {authorizeMutation.error != null && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>
                    {(authorizeMutation.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
                      'Error al autorizar IP'}
                  </AlertDescription>
                </Alert>
              )}

              <div className="space-y-2">
                <Label htmlFor="account">{t('accountLabel')}</Label>
                <select
                  id="account"
                  value={selectedOrgId}
                  onChange={(e) => setSelectedOrgId(e.target.value)}
                  className="w-full px-3 py-2 border rounded-md"
                  disabled={authorizeMutation.isPending}
                >
                  <option value="">{t('selectAccount')}</option>
                  {accounts
                    .filter((account: Account) => account.is_active)
                    .map((account: Account) => (
                      <option key={account.id} value={account.id}>
                        {account.name}
                      </option>
                    ))}
                </select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="description">{t('descriptionLabel')}</Label>
                <Input
                  id="description"
                  type="text"
                  placeholder={t('descriptionPlaceholder')}
                  value={customDescription}
                  onChange={(e) => setCustomDescription(e.target.value)}
                  disabled={authorizeMutation.isPending}
                />
              </div>

              <div className="flex justify-end space-x-3">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setAuthorizingIP(null);
                    setSelectedOrgId('');
                    setCustomDescription('');
                  }}
                  disabled={authorizeMutation.isPending}
                >
                  {tCommon('cancel')}
                </Button>
                <Button
                  type="button"
                  onClick={handleAuthorize}
                  disabled={!selectedOrgId || authorizeMutation.isPending}
                >
                  {authorizeMutation.isPending ? t('authorizing') : t('authorize')}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
