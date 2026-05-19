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
import {
  RefreshCw,
  Package,
  Calendar,
  GitCommit,
  HardDrive,
  AlertTriangle,
  Building2,
  Pin,
  History,
  Download,
  Trash2,
} from 'lucide-react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
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
import { apiClient, organizationsApi } from '@/lib/api';
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

interface AutoUpdateToggleResponse {
  auto_update_enabled: boolean;
  organization_id: string;
  updated_at: string;
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

  const [msiInfo, setMsiInfo] = useState<MsiInfo | null>(null);
  const [organizations, setOrganizations] = useState<OrgAutoUpdateState[]>([]);
  const [versions, setVersions] = useState<MsiInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pinningOrg, setPinningOrg] = useState<string | null>(null);
  const [selectedVersions, setSelectedVersions] = useState<Set<string>>(new Set());
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteConfirmDialog, setDeleteConfirmDialog] = useState<{
    open: boolean;
    versions: string[];
  }>({ open: false, versions: [] });
  const [confirmDialog, setConfirmDialog] = useState<{
    open: boolean;
    orgId: string;
    orgName: string;
  }>({
    open: false,
    orgId: '',
    orgName: '',
  });

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
    } catch (err: unknown) {
      const errorMessage =
        err && typeof err === 'object' && 'detail' in err
          ? (err as { detail: string }).detail
          : 'Error al obtener información de actualizaciones';
      setError(errorMessage);
    } finally {
      setIsLoading(false);
    }
  }, [isAdmin, user?.organization_id]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Manejar toggle de auto-updates por organización
  const handleToggle = (orgId: string, orgName: string, checked: boolean) => {
    if (checked) {
      setConfirmDialog({ open: true, orgId, orgName });
    } else {
      performToggle(orgId, false);
    }
  };

  // Ejecutar el toggle contra el backend
  const performToggle = async (orgId: string, enabled: boolean) => {
    setOrganizations((prev) =>
      prev.map((org) => (org.orgId === orgId ? { ...org, isToggling: true } : org))
    );

    try {
      await apiClient.patch<AutoUpdateToggleResponse>(`/organizations/${orgId}/auto-update`, {
        enabled,
      });

      setOrganizations((prev) =>
        prev.map((org) =>
          org.orgId === orgId ? { ...org, autoUpdateEnabled: enabled, isToggling: false } : org
        )
      );

      const orgName = organizations.find((o) => o.orgId === orgId)?.orgName ?? orgId;
      toast({
        title: enabled
          ? 'Actualizaciones automáticas habilitadas'
          : 'Actualizaciones automáticas deshabilitadas',
        description: `Organización: ${orgName}`,
      });
    } catch (err: unknown) {
      const errorMessage =
        err && typeof err === 'object' && 'detail' in err
          ? (err as { detail: string }).detail
          : 'Error al actualizar configuración';
      toast({
        title: 'Error',
        description: errorMessage,
        variant: 'destructive',
      });
      setOrganizations((prev) =>
        prev.map((org) => (org.orgId === orgId ? { ...org, isToggling: false } : org))
      );
    } finally {
      setConfirmDialog({ open: false, orgId: '', orgName: '' });
    }
  };

  // Toggle de re-registro automático por organización
  const handleReregisterToggle = async (orgId: string, enabled: boolean) => {
    setOrganizations((prev) =>
      prev.map((org) => (org.orgId === orgId ? { ...org, isToggling: true } : org))
    );

    try {
      await apiClient.put(`/organizations/${orgId}`, {
        auto_reregister_enabled: enabled,
      });

      setOrganizations((prev) =>
        prev.map((org) =>
          org.orgId === orgId
            ? { ...org, autoReregisterEnabled: enabled, isToggling: false }
            : org
        )
      );

      const orgName = organizations.find((o) => o.orgId === orgId)?.orgName ?? orgId;
      toast({
        title: enabled
          ? 'Re-registro automático habilitado'
          : 'Re-registro automático deshabilitado',
        description: `Organización: ${orgName}`,
      });
    } catch {
      toast({
        title: 'Error',
        description: 'No se pudo actualizar la configuración de re-registro',
        variant: 'destructive',
      });
      setOrganizations((prev) =>
        prev.map((org) => (org.orgId === orgId ? { ...org, isToggling: false } : org))
      );
    }
  };

  // Asignar versión pineada para una organización
  const handlePinVersion = async (orgId: string, version: string | null) => {
    setPinningOrg(orgId);
    try {
      await apiClient.put(`/updates/pin/${orgId}`, { version });

      // Actualizar estado local
      setOrganizations((prev) =>
        prev.map((org) =>
          org.orgId === orgId ? { ...org, targetVersion: version } : org
        )
      );

      toast({
        title: version ? 'Versión pineada' : 'Versión despineada',
        description: version
          ? `La organización usará siempre la versión ${version}`
          : 'La organización usará la versión latest',
      });
    } catch {
      toast({
        title: 'Error',
        description: 'No se pudo actualizar la versión asignada',
        variant: 'destructive',
      });
    } finally {
      setPinningOrg(null);
    }
  };

  // Determinar qué versiones son elegibles para eliminación
  // No se puede eliminar: la versión latest ni versiones pineadas por alguna organización
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
  const handleDownloadVersion = (version: string) => {
    const token = localStorage.getItem('access_token');
    if (!token) {
      toast({
        title: 'Error',
        description: 'No autenticado. Inicia sesión nuevamente.',
        variant: 'destructive',
      });
      return;
    }
    // Abrir en nueva pestaña — el endpoint redirige a la presigned URL
    const baseUrl = apiClient.defaults.baseURL || '';
    window.open(`${baseUrl}/updates/download/${version}`, '_blank');
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
      const response = await apiClient.delete<DeleteVersionsResponse>('/updates/versions', {
        data: { versions: versionsToDelete },
      });

      const result = response.data;

      // Limpiar selección
      setSelectedVersions(new Set());

      // Mostrar resultado
      if (result.total_deleted > 0) {
        toast({
          title: `${result.total_deleted} versión(es) eliminada(s)`,
          description: result.total_skipped > 0
            ? `${result.total_skipped} versión(es) omitida(s)`
            : 'Todas las versiones seleccionadas fueron eliminadas',
        });
      } else {
        toast({
          title: 'No se eliminaron versiones',
          description: 'Todas las versiones seleccionadas fueron omitidas',
          variant: 'destructive',
        });
      }

      // Si hubo versiones omitidas, mostrar detalles
      if (result.skipped.length > 0) {
        const reasons = result.skipped
          .map((s) => `${s.version}: ${s.reason}`)
          .join(', ');
        toast({
          title: 'Versiones omitidas',
          description: reasons,
        });
      }

      // Refrescar datos
      await fetchData();
    } catch (err: unknown) {
      const errorMessage =
        err && typeof err === 'object' && 'detail' in err
          ? (err as { detail: string }).detail
          : 'Error al eliminar versiones';
      toast({
        title: 'Error',
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
          <h1 className="text-3xl font-bold">Actualizaciones Automáticas</h1>
          <p className="text-muted-foreground mt-1">
            Gestiona las actualizaciones del cliente AlwaysPrint por organización
          </p>
        </div>

        <Button variant="outline" onClick={fetchData} disabled={isLoading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
          Actualizar
        </Button>
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
              Cargando información de actualizaciones...
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
                    <CardTitle>Versión Latest</CardTitle>
                  </div>
                  <Badge variant="default">{msiInfo.version}</Badge>
                </div>
                <CardDescription>
                  Versión más reciente del instalador en S3. Se despliega a organizaciones sin
                  versión pineada.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="flex items-start gap-2">
                    <Calendar className="h-4 w-4 text-muted-foreground mt-0.5" />
                    <div>
                      <p className="text-xs text-muted-foreground">Fecha de Build</p>
                      <p className="text-sm font-medium">{msiInfo.buildDate || 'N/A'}</p>
                    </div>
                  </div>
                  <div className="flex items-start gap-2">
                    <GitCommit className="h-4 w-4 text-muted-foreground mt-0.5" />
                    <div>
                      <p className="text-xs text-muted-foreground">Commit</p>
                      <p className="text-sm font-mono">
                        {msiInfo.commitHash ? msiInfo.commitHash.substring(0, 8) : 'N/A'}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-start gap-2">
                    <HardDrive className="h-4 w-4 text-muted-foreground mt-0.5" />
                    <div>
                      <p className="text-xs text-muted-foreground">Tamaño</p>
                      <p className="text-sm font-medium">{formatFileSize(msiInfo.fileSize)}</p>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Configuración por organización */}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Building2 className="h-5 w-5 text-primary" />
                <CardTitle>Configuración por Organización</CardTitle>
              </div>
              <CardDescription>
                Cada organización puede tener actualizaciones automáticas habilitadas y
                opcionalmente una versión pineada. Si tiene versión pineada, siempre recibirá esa
                versión (aunque cambie la latest).
              </CardDescription>
            </CardHeader>
            <CardContent>
              {organizations.length === 0 ? (
                <p className="text-muted-foreground text-center py-4">
                  No se encontraron organizaciones.
                </p>
              ) : (
                <div className="space-y-4">
                  {organizations.map((org) => (
                    <div
                      key={org.orgId}
                      className="p-4 border rounded-lg space-y-3"
                    >
                      {/* Fila superior: nombre + toggle */}
                      <div className="flex items-center justify-between">
                        <div>
                          <Label className="text-base font-medium">{org.orgName}</Label>
                          <p className="text-sm text-muted-foreground">
                            {org.autoUpdateEnabled
                              ? 'Actualizaciones automáticas habilitadas'
                              : 'Actualizaciones automáticas deshabilitadas'}
                          </p>
                        </div>
                        <Switch
                          checked={org.autoUpdateEnabled}
                          onCheckedChange={(checked) =>
                            handleToggle(org.orgId, org.orgName, checked)
                          }
                          disabled={org.isToggling}
                        />
                      </div>

                      {/* Fila inferior: versión pineada */}
                      <div className="flex items-center gap-3 pl-1">
                        <Pin className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                        <div className="flex items-center gap-2 flex-1">
                          <span className="text-sm text-muted-foreground">Versión:</span>
                          <select
                            className="text-sm border rounded px-2 py-1 bg-background"
                            value={org.targetVersion ?? ''}
                            onChange={(e) => {
                              const value = e.target.value || null;
                              handlePinVersion(org.orgId, value);
                            }}
                            disabled={pinningOrg === org.orgId}
                          >
                            <option value="">Latest (automática)</option>
                            {versions.map((v) => (
                              <option key={v.version} value={v.version}>
                                {v.version}
                              </option>
                            ))}
                          </select>
                          {org.targetVersion && (
                            <Badge variant="secondary" className="text-xs">
                              <Pin className="h-3 w-3 mr-1" />
                              Pineada
                            </Badge>
                          )}
                          {!org.targetVersion && (
                            <Badge variant="outline" className="text-xs">
                              Usa latest
                            </Badge>
                          )}
                        </div>
                      </div>

                      {/* Explicación contextual */}
                      {org.autoUpdateEnabled && org.targetVersion && (
                        <p className="text-xs text-amber-600 pl-7">
                          Las workstations siempre descargarán la versión {org.targetVersion},
                          independientemente de la versión latest.
                        </p>
                      )}
                      {org.autoUpdateEnabled && !org.targetVersion && (
                        <p className="text-xs text-muted-foreground pl-7">
                          Las workstations se actualizarán automáticamente a la versión latest.
                        </p>
                      )}
                      {!org.autoUpdateEnabled && (
                        <p className="text-xs text-muted-foreground pl-7">
                          Las workstations no se actualizarán automáticamente.
                        </p>
                      )}

                      {/* Toggle de re-registro automático */}
                      <div className="flex items-center justify-between pt-2 border-t mt-3">
                        <div>
                          <Label className="text-sm font-medium">Re-registro automático</Label>
                          <p className="text-xs text-muted-foreground">
                            {org.autoReregisterEnabled
                              ? 'Workstations eliminadas se re-registran al enviar telemetría'
                              : 'Workstations eliminadas no se re-registran automáticamente'}
                          </p>
                        </div>
                        <Switch
                          checked={org.autoReregisterEnabled}
                          onCheckedChange={(checked) =>
                            handleReregisterToggle(org.orgId, checked)
                          }
                          disabled={org.isToggling}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Historial de versiones con acciones */}
          {isAdmin && versions.length > 0 && (
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <History className="h-5 w-5 text-primary" />
                    <CardTitle>Versiones Disponibles</CardTitle>
                  </div>
                  <Button
                    variant="destructive"
                    size="sm"
                    disabled={selectedVersions.size === 0 || isDeleting}
                    onClick={handleDeleteClick}
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    Eliminar ({selectedVersions.size})
                  </Button>
                </div>
                <CardDescription>
                  Todas las versiones del instalador almacenadas en S3. Selecciona versiones para
                  eliminarlas.
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
                              aria-label="Seleccionar todas las versiones elegibles"
                            />
                          )}
                        </th>
                        <th className="text-left py-2 px-3 font-medium">Versión</th>
                        <th className="text-left py-2 px-3 font-medium">Fecha Build</th>
                        <th className="text-left py-2 px-3 font-medium">Commit</th>
                        <th className="text-left py-2 px-3 font-medium">Tamaño</th>
                        <th className="text-left py-2 px-3 font-medium">Usada por</th>
                        <th className="text-left py-2 px-3 font-medium">Acciones</th>
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
                                  aria-label={`Seleccionar versión ${v.version}`}
                                />
                              ) : (
                                <span className="text-muted-foreground text-xs" title={
                                  isLatest ? 'No se puede eliminar la versión latest' :
                                  isPinned ? 'No se puede eliminar: pineada por una organización' : ''
                                }>—</span>
                              )}
                            </td>
                            <td className="py-2 px-3 font-mono">
                              {v.version}
                              {isLatest && (
                                <Badge variant="default" className="ml-2 text-xs">
                                  latest
                                </Badge>
                              )}
                              {isPinned && !isLatest && (
                                <Badge variant="secondary" className="ml-2 text-xs">
                                  <Pin className="h-3 w-3 mr-1" />
                                  pineada
                                </Badge>
                              )}
                            </td>
                            <td className="py-2 px-3 text-muted-foreground">
                              {v.buildDate || 'N/A'}
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
                                title={`Descargar versión ${v.version}`}
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

      {/* Diálogo de confirmación de auto-update */}
      <Dialog
        open={confirmDialog.open}
        onOpenChange={(open) => setConfirmDialog((prev) => ({ ...prev, open }))}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirmar Habilitación de Auto-Actualizaciones</DialogTitle>
            <DialogDescription>
              ¿Estás seguro de que deseas habilitar las actualizaciones automáticas para
              <strong> {confirmDialog.orgName}</strong>?
            </DialogDescription>
          </DialogHeader>

          <div className="py-4">
            <Alert>
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>
                Las workstations de esta organización que tengan habilitado el flag local
                comenzarán a actualizarse automáticamente. Asegúrate de que la versión actual del
                MSI ha sido probada correctamente.
              </AlertDescription>
            </Alert>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmDialog({ open: false, orgId: '', orgName: '' })}
            >
              Cancelar
            </Button>
            <Button onClick={() => performToggle(confirmDialog.orgId, true)}>Confirmar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Diálogo de confirmación de eliminación de versiones */}
      <Dialog
        open={deleteConfirmDialog.open}
        onOpenChange={(open) => setDeleteConfirmDialog((prev) => ({ ...prev, open }))}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirmar Eliminación de Versiones</DialogTitle>
            <DialogDescription>
              ¿Estás seguro de que deseas eliminar las siguientes versiones de S3? Esta acción no
              se puede deshacer.
            </DialogDescription>
          </DialogHeader>

          <div className="py-4 space-y-3">
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>
                Se eliminarán permanentemente los archivos MSI de estas versiones del bucket S3.
                Las workstations que tengan estas versiones instaladas no se verán afectadas, pero
                no podrán volver a descargarlas.
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
              Cancelar
            </Button>
            <Button variant="destructive" onClick={performDelete} disabled={isDeleting}>
              {isDeleting ? 'Eliminando...' : `Eliminar ${deleteConfirmDialog.versions.length} versión(es)`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
