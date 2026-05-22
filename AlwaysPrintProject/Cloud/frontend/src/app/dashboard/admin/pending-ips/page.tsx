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
  const [authorizingIP, setAuthorizingIP] = useState<PendingIP | null>(null);
  const [selectedOrgId, setSelectedOrgId] = useState('');
  const [customDescription, setCustomDescription] = useState('');
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const [page, setPage] = useState(1);
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
      <div className="max-w-7xl mx-auto">
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
      <div className="max-w-7xl mx-auto">
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
    <div className="max-w-7xl mx-auto">
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

      {/* Búsqueda */}
      <Card className="mb-6">
        <CardContent className="p-4">
          <div className="flex items-center">
            <Search className="w-5 h-5 text-gray-400 mr-3" />
            <Input
              type="text"
              placeholder={t('searchPlaceholder')}
              value={searchTerm}
              onChange={(e) => { setSearchTerm(e.target.value); setPage(1); }}
              className="flex-1"
            />
          </div>
        </CardContent>
      </Card>

      {/* Lista de IPs pendientes */}
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
            <CardHeader>
              <CardTitle>{t('authorizeTitle')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Alert>
                <Globe className="h-4 w-4" />
                <AlertDescription>
                  <strong>{t('ipLabel')}</strong> {authorizingIP.ip_address}
                </AlertDescription>
              </Alert>

              {authorizeMutation.error && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>
                    {(authorizeMutation.error as any)?.response?.data?.detail ||
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
