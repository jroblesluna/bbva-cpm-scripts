'use client';

/**
 * Página de administración de actualizaciones automáticas.
 *
 * Permite a los administradores:
 * - Ver la versión latest del MSI disponible en S3
 * - Configurar auto-actualización y versión pineada por organización
 * - Ver historial de versiones disponibles
 * - Descargar versiones específicas
 * - Eliminar versiones antiguas de S3
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useTranslations } from 'next-intl';
import {
  RefreshCw,
  Package,
  Calendar,
  GitCommit,
  HardDrive,
  AlertTriangle,
  Pin,
  History,
  Download,
  Trash2,
  Upload,
} from 'lucide-react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useToast } from '@/hooks/use-toast';
import { useAuth } from '@/hooks/useAuth';
import { useUserTimezone } from '@/hooks/useUserTimezone';
import { formatDateWithTimezone } from '@/lib/dateUtils';
import { apiClient, organizationsApi } from '@/lib/api';
import { Input } from '@/components/ui/input';
import type { Organization } from '@/types';

// ============================================================================
// TIPOS
// ============================================================================

interface MsiInfo {
  version: string;
  buildDate: string;
  commitHash: string;
  fileSize: number;
}

interface UpdateCheckResponse {
  version: string;
  auto_update_enabled: boolean;
  file_size: number;
  build_date: string;
  commit_hash: string;
}

interface OrgAutoUpdateState {
  orgId: string;
  orgName: string;
  autoUpdateEnabled: boolean;
  targetVersion: string | null;
  autoReregisterEnabled: boolean;
  isToggling: boolean;
}

interface DeleteVersionsResponse {
  deleted: string[];
  skipped: { version: string; reason: string }[];
  total_deleted: number;
  total_skipped: number;
}

// ============================================================================
// HELPERS
// ============================================================================

function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const size = (bytes / Math.pow(1024, i)).toFixed(2);
  return `${size} ${units[i]}`;
}

// ============================================================================
// COMPONENTE PRINCIPAL
// ============================================================================

export default function UpdatesPage() {
  const { toast } = useToast();
  const { user } = useAuth();
  const timezone = useUserTimezone();
  const t = useTranslations('updates');
  const tCommon = useTranslations('common');

  const [msiInfo, setMsiInfo] = useState<MsiInfo | null>(null);
  const [organizations, setOrganizations] = useState<OrgAutoUpdateState[]>([]);
  const [versions, setVersions] = useState<MsiInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedVersions, setSelectedVersions] = useState<Set<string>>(new Set());
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteConfirmDialog, setDeleteConfirmDialog] = useState<{
    open: boolean;
    versions: string[];
  }>({ open: false, versions: [] });
  const [isUploading, setIsUploading] = useState(false);
  const [uploadDialog, setUploadDialog] = useState<{
    open: boolean;
    file: File | null;
    version: string;
  }>({ open: false, file: null, version: '' });

  const isAdmin = user?.role === 'admin';

  // Cargar información del MSI y organizaciones
  const fetchData = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      // Obtener info del MSI (latest) desde S3
      let msiData: MsiInfo | null = null;
      try {
        const checkResponse = await apiClient.get<UpdateCheckResponse>('/updates/check');
        const data = checkResponse.data;
        msiData = {
          version: data.version,
          buildDate: data.build_date,
          commitHash: data.commit_hash,
          fileSize: data.file_size,
        };
      } catch {
        msiData = null;
      }
      setMsiInfo(msiData);

      // Obtener lista de organizaciones con su estado de auto-update
      if (isAdmin) {
        const accounts = await organizationsApi.list();
        const orgStates: OrgAutoUpdateState[] = accounts.map((acc: Organization) => ({
          orgId: acc.id,
          orgName: acc.name,
          autoUpdateEnabled: acc.auto_update_enabled ?? false,
          targetVersion: acc.target_version ?? null,
          autoReregisterEnabled: acc.auto_reregister_enabled ?? false,
          isToggling: false,
        }));
        setOrganizations(orgStates);

        // Obtener historial de versiones
        try {
          const versionsResponse = await apiClient.get<MsiInfo[]>('/updates/versions');
          setVersions(
            versionsResponse.data.map((v: any) => ({
              version: v.version,
              buildDate: v.build_date,
              commitHash: v.commit_hash,
              fileSize: v.file_size,
            }))
          );
        } catch {
          setVersions([]);
        }
      } else if (user?.organization_id) {
        try {
          const acc = await organizationsApi.get(user.organization_id);
          setOrganizations([
            {
              orgId: acc.id,
              orgName: acc.name,
              autoUpdateEnabled: acc.auto_update_enabled ?? false,
              targetVersion: acc.target_version ?? null,
              autoReregisterEnabled: acc.auto_reregister_enabled ?? false,
              isToggling: false,
            },
          ]);
        } catch {
          setOrganizations([]);
        }
      }
    } catch {
      setError(t('errorFetch'));
    } finally {
      setIsLoading(false);
    }
  }, [isAdmin, user?.organization_id, t]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Subir MSI manualmente
  const handleUploadMsi = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith('.msi')) {
      toast({ title: 'Error', description: 'Solo se permiten archivos .msi', variant: 'destructive' });
      event.target.value = '';
      return;
    }

    // Sugerir versión basada en fecha actual
    const now = new Date();
    const suggested = `1.${String(now.getFullYear()).slice(2)}.${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}.${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}${String(now.getSeconds()).padStart(2, '0')}`;

    setUploadDialog({ open: true, file, version: suggested });
    event.target.value = '';
  };

  // Confirmar upload con versión
  const performUpload = async () => {
    const { file, version } = uploadDialog;
    if (!file || !version.trim()) return;

    setUploadDialog({ open: false, file: null, version: '' });
    setIsUploading(true);

    try {
      const formData = new FormData();
      formData.append('file', file);

      await apiClient.post(`/updates/upload?version=${encodeURIComponent(version.trim())}`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 120000,
      });

      toast({ title: 'MSI subido', description: `${file.name} (v${version.trim()}) subido exitosamente` });
      await fetchData();
    } catch (err: unknown) {
      const apiErr = err as { detail?: string };
      toast({
        title: 'Error al subir MSI',
        description: apiErr.detail || 'Error desconocido',
        variant: 'destructive',
      });
    } finally {
      setIsUploading(false);
    }
  };

  // Asignar versión pineada para una organización
  const handlePinVersion = async (orgId: string, version: string | null) => {
    try {
      await apiClient.put(`/updates/pin/${orgId}`, { version });

      // Actualizar estado local
      setOrganizations((prev) =>
        prev.map((org) =>
          org.orgId === orgId ? { ...org, targetVersion: version } : org
        )
      );

      toast({
        title: version ? t('pinSuccess') : t('unpinSuccess'),
        description: version
          ? t('pinSuccessDesc', { version })
          : t('unpinSuccessDesc'),
      });
    } catch {
      toast({
        title: tCommon('actions'),
        description: t('pinError'),
        variant: 'destructive',
      });
    }
  };

  // Determinar qué versiones son elegibles para eliminación
  const pinnedVersions = useMemo(() => {
    const pinned = new Set<string>();
    organizations.forEach((org) => {
      if (org.targetVersion) {
        pinned.add(org.targetVersion);
      }
    });
    return pinned;
  }, [organizations]);

  const eligibleVersions = useMemo(() => {
    return versions.filter((v) => {
      const isLatest = msiInfo?.version === v.version;
      const isPinned = pinnedVersions.has(v.version);
      return !isLatest && !isPinned;
    });
  }, [versions, msiInfo, pinnedVersions]);

  // Manejar selección individual de versión
  const handleVersionSelect = (version: string, checked: boolean) => {
    setSelectedVersions((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(version);
      } else {
        next.delete(version);
      }
      return next;
    });
  };

  // Manejar seleccionar/deseleccionar todas las versiones elegibles
  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedVersions(new Set(eligibleVersions.map((v) => v.version)));
    } else {
      setSelectedVersions(new Set());
    }
  };

  // Determinar estado del checkbox "Seleccionar todo"
  const selectAllState = useMemo(() => {
    if (eligibleVersions.length === 0) return { checked: false, indeterminate: false };
    const selectedCount = eligibleVersions.filter((v) => selectedVersions.has(v.version)).length;
    if (selectedCount === 0) return { checked: false, indeterminate: false };
    if (selectedCount === eligibleVersions.length) return { checked: true, indeterminate: false };
    return { checked: false, indeterminate: true };
  }, [eligibleVersions, selectedVersions]);

  // Descargar versión específica via endpoint admin
  const handleDownloadVersion = async (version: string) => {
    try {
      const response = await apiClient.get<{ download_url: string; version: string }>(
        `/updates/download/${version}`
      );
      window.open(response.data.download_url, '_blank');
    } catch {
      toast({
        title: tCommon('actions'),
        description: t('downloadError', { version }),
        variant: 'destructive',
      });
    }
  };

  // Confirmar eliminación de versiones seleccionadas
  const handleDeleteClick = () => {
    const versionsToDelete = Array.from(selectedVersions);
    if (versionsToDelete.length === 0) return;
    setDeleteConfirmDialog({ open: true, versions: versionsToDelete });
  };

  // Ejecutar eliminación de versiones
  const performDelete = async () => {
    const versionsToDelete = deleteConfirmDialog.versions;
    setIsDeleting(true);
    setDeleteConfirmDialog({ open: false, versions: [] });

    try {
      const response = await apiClient.post<DeleteVersionsResponse>('/updates/versions/delete', {
        versions: versionsToDelete,
      });

      const result = response.data;
      console.log('[DELETE VERSIONS] Resultado:', JSON.stringify(result));

      // Limpiar selección
      setSelectedVersions(new Set());

      // Mostrar resultado
      if (result.total_deleted > 0) {
        toast({
          title: t('deleteSuccess', { count: result.total_deleted }),
          description: result.total_skipped > 0
            ? t('deleteSkipped', { count: result.total_skipped })
            : t('deleteSuccessAll'),
        });
      } else {
        toast({
          title: t('deleteNone'),
          description: t('deleteNoneDesc'),
          variant: 'destructive',
        });
      }

      // Si hubo versiones omitidas, mostrar detalles
      if (result.skipped.length > 0) {
        const reasons = result.skipped
          .map((s) => `${s.version}: ${s.reason}`)
          .join(', ');
        toast({
          title: t('skippedTitle'),
          description: reasons,
        });
      }

      // Refrescar datos
      await fetchData();
    } catch (err: unknown) {
      console.error('[DELETE VERSIONS] Error:', err);
      const errorMessage =
        err && typeof err === 'object' && 'detail' in err
          ? (err as { detail: string }).detail
          : t('deleteError');
      toast({
        title: tCommon('actions'),
        description: errorMessage,
        variant: 'destructive',
      });
    } finally {
      setIsDeleting(false);
    }
  };

  // ============================================================================
  // RENDER
  // ============================================================================

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Encabezado */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold">{t('title')}</h1>
          <p className="text-muted-foreground mt-1">
            {t('subtitle')}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={fetchData} disabled={isLoading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
            {t('refresh')}
          </Button>

          {isAdmin && (
            <>
              <input
                type="file"
                id="msi-upload"
                accept=".msi"
                className="hidden"
                onChange={handleUploadMsi}
                disabled={isUploading}
              />
              <Button
                onClick={() => document.getElementById('msi-upload')?.click()}
                disabled={isUploading}
              >
                <Upload className={`mr-2 h-4 w-4 ${isUploading ? 'animate-spin' : ''}`} />
                {isUploading ? 'Subiendo...' : 'Subir MSI'}
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Estado de carga */}
      {isLoading && (
        <Card>
          <CardContent className="py-12">
            <p className="text-center text-muted-foreground">
              {t('loading')}
            </p>
          </CardContent>
        </Card>
      )}

      {!isLoading && (
        <>
          {/* Información del MSI latest */}
          {msiInfo && (
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Package className="h-5 w-5 text-primary" />
                    <CardTitle>{t('latestVersion')}</CardTitle>
                  </div>
                  <Badge variant="default">{msiInfo.version}</Badge>
                </div>
                <CardDescription>
                  {t('latestDesc')}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="flex items-start gap-2">
                    <Calendar className="h-4 w-4 text-muted-foreground mt-0.5" />
                    <div>
                      <p className="text-xs text-muted-foreground">{t('buildDate')}</p>
                      <p className="text-sm font-medium">
                        {msiInfo.buildDate
                          ? formatDateWithTimezone(msiInfo.buildDate, timezone)
                          : 'N/A'}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-start gap-2">
                    <GitCommit className="h-4 w-4 text-muted-foreground mt-0.5" />
                    <div>
                      <p className="text-xs text-muted-foreground">{t('commit')}</p>
                      <p className="text-sm font-mono">
                        {msiInfo.commitHash ? msiInfo.commitHash.substring(0, 8) : 'N/A'}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-start gap-2">
                    <HardDrive className="h-4 w-4 text-muted-foreground mt-0.5" />
                    <div>
                      <p className="text-xs text-muted-foreground">{t('size')}</p>
                      <p className="text-sm font-medium">{formatFileSize(msiInfo.fileSize)}</p>
                    </div>
                  </div>
                </div>
                <div className="mt-4 pt-4 border-t">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleDownloadVersion(msiInfo.version)}
                  >
                    <Download className="mr-2 h-4 w-4" />
                    {t('downloadMsi', { version: msiInfo.version })}
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Historial de versiones con acciones */}
          {isAdmin && versions.length > 0 && (
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <History className="h-5 w-5 text-primary" />
                    <CardTitle>{t('availableVersions')}</CardTitle>
                  </div>
                  <Button
                    variant="destructive"
                    size="sm"
                    disabled={selectedVersions.size === 0 || isDeleting}
                    onClick={handleDeleteClick}
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    {t('deleteSelected', { count: selectedVersions.size })}
                  </Button>
                </div>
                <CardDescription>
                  {t('availableVersionsDesc')}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b">
                        <th className="text-left py-2 px-3 font-medium w-10">
                          {eligibleVersions.length > 0 && (
                            <Checkbox
                              checked={selectAllState.checked}
                              indeterminate={selectAllState.indeterminate}
                              onChange={(e) => handleSelectAll(e.target.checked)}
                              aria-label={t('selectAllEligible')}
                            />
                          )}
                        </th>
                        <th className="text-left py-2 px-3 font-medium">{t('colVersion')}</th>
                        <th className="text-left py-2 px-3 font-medium">{t('colBuildDate')}</th>
                        <th className="text-left py-2 px-3 font-medium">{t('colCommit')}</th>
                        <th className="text-left py-2 px-3 font-medium">{t('colSize')}</th>
                        <th className="text-left py-2 px-3 font-medium">{t('colUsedBy')}</th>
                        <th className="text-left py-2 px-3 font-medium">{t('colActions')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {versions.map((v) => {
                        const orgsUsingThis = organizations.filter(
                          (o) => o.targetVersion === v.version
                        );
                        const isLatest = msiInfo?.version === v.version;
                        const isPinned = pinnedVersions.has(v.version);
                        const isEligible = !isLatest && !isPinned;
                        return (
                          <tr key={v.version} className="border-b hover:bg-muted/50">
                            <td className="py-2 px-3">
                              {isEligible ? (
                                <Checkbox
                                  checked={selectedVersions.has(v.version)}
                                  onChange={(e) =>
                                    handleVersionSelect(v.version, e.target.checked)
                                  }
                                  aria-label={t('selectVersion', { version: v.version })}
                                />
                              ) : (
                                <span className="text-muted-foreground text-xs" title={
                                  isLatest ? t('cannotDeleteLatest') :
                                  isPinned ? t('cannotDeletePinned') : ''
                                }>—</span>
                              )}
                            </td>
                            <td className="py-2 px-3 font-mono">
                              {v.version}
                              {isLatest && (
                                <Badge variant="default" className="ml-2 text-xs">
                                  {t('badgeLatest')}
                                </Badge>
                              )}
                              {isPinned && !isLatest && (
                                <Badge variant="secondary" className="ml-2 text-xs">
                                  <Pin className="h-3 w-3 mr-1" />
                                  {t('badgePinned')}
                                </Badge>
                              )}
                            </td>
                            <td className="py-2 px-3 text-muted-foreground">
                              {v.buildDate
                                ? formatDateWithTimezone(v.buildDate, timezone)
                                : 'N/A'}
                            </td>
                            <td className="py-2 px-3 font-mono text-muted-foreground">
                              {v.commitHash?.substring(0, 7) || 'N/A'}
                            </td>
                            <td className="py-2 px-3">{formatFileSize(v.fileSize)}</td>
                            <td className="py-2 px-3">
                              {orgsUsingThis.length > 0 ? (
                                <div className="flex flex-wrap gap-1">
                                  {orgsUsingThis.map((o) => (
                                    <Badge key={o.orgId} variant="secondary" className="text-xs">
                                      {o.orgName}
                                    </Badge>
                                  ))}
                                </div>
                              ) : (
                                <span className="text-muted-foreground text-xs">—</span>
                              )}
                            </td>
                            <td className="py-2 px-3">
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleDownloadVersion(v.version)}
                                title={t('downloadVersion', { version: v.version })}
                              >
                                <Download className="h-4 w-4" />
                              </Button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {/* Diálogo de confirmación de eliminación de versiones */}
      <Dialog
        open={deleteConfirmDialog.open}
        onOpenChange={(open) => setDeleteConfirmDialog((prev) => ({ ...prev, open }))}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('deleteConfirmTitle')}</DialogTitle>
            <DialogDescription>
              {t('deleteConfirmDesc')}
            </DialogDescription>
          </DialogHeader>

          <div className="py-4 space-y-3">
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>
                {t('deleteWarning')}
              </AlertDescription>
            </Alert>

            <div className="max-h-40 overflow-y-auto border rounded p-3">
              <ul className="space-y-1">
                {deleteConfirmDialog.versions.map((v) => (
                  <li key={v} className="text-sm font-mono flex items-center gap-2">
                    <Trash2 className="h-3 w-3 text-destructive flex-shrink-0" />
                    {v}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteConfirmDialog({ open: false, versions: [] })}
            >
              {tCommon('cancel')}
            </Button>
            <Button variant="destructive" onClick={performDelete} disabled={isDeleting}>
              {isDeleting
                ? t('deleting')
                : t('deleteBtn', { count: deleteConfirmDialog.versions.length })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Diálogo de versión para upload de MSI */}
      <Dialog
        open={uploadDialog.open}
        onOpenChange={(open) => { if (!open) setUploadDialog({ open: false, file: null, version: '' }); }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Subir MSI</DialogTitle>
            <DialogDescription>
              Archivo: {uploadDialog.file?.name} ({uploadDialog.file ? formatFileSize(uploadDialog.file.size) : ''})
            </DialogDescription>
          </DialogHeader>

          <div className="py-4 space-y-3">
            <label className="text-sm font-medium">Número de versión</label>
            <Input
              value={uploadDialog.version}
              onChange={(e) => setUploadDialog((prev) => ({ ...prev, version: e.target.value }))}
              placeholder="Ej: 1.26.0520.1234"
            />
            <p className="text-xs text-muted-foreground">
              Formato sugerido: Major.YY.MMDD.HHmmSS
            </p>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setUploadDialog({ open: false, file: null, version: '' })}
            >
              {tCommon('cancel')}
            </Button>
            <Button onClick={performUpload} disabled={!uploadDialog.version.trim()}>
              <Upload className="mr-2 h-4 w-4" />
              Subir
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
