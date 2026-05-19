'use client';

/**
 * Página de administración de actualizaciones automáticas.
 *
 * Permite a los administradores:
 * - Ver la versión actual del MSI disponible en S3
 * - Habilitar/deshabilitar auto-updates por organización
 * - Confirmación antes de habilitar auto-updates
 */

import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Package, Calendar, GitCommit, HardDrive, AlertTriangle, Building2, Pin, PinOff, History } from 'lucide-react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
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
  isToggling: boolean;
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

function formatDate(isoDate: string): string {
  if (!isoDate) return 'No disponible';
  try {
    return new Date(isoDate).toLocaleString('es-ES', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return isoDate;
  }
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
  const [confirmDialog, setConfirmDialog] = useState<{ open: boolean; orgId: string; orgName: string }>({
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
      // Obtener info del MSI desde S3 via el endpoint de check
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
        // Si falla (ej. S3 no disponible), no es crítico
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
          isToggling: false,
        }));
        setOrganizations(orgStates);

        // Obtener historial de versiones
        try {
          const versionsResponse = await apiClient.get<MsiInfo[]>('/updates/versions');
          setVersions(versionsResponse.data.map((v: any) => ({
            version: v.version,
            buildDate: v.build_date,
            commitHash: v.commit_hash,
            fileSize: v.file_size,
          })));
        } catch {
          setVersions([]);
        }
      } else if (user?.organization_id) {
        // Operador: solo su organización
        try {
          const acc = await organizationsApi.get(user.organization_id);
          setOrganizations([{
            orgId: acc.id,
            orgName: acc.name,
            autoUpdateEnabled: acc.auto_update_enabled ?? false,
            targetVersion: acc.target_version ?? null,
            isToggling: false,
          }]);
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
      // Mostrar diálogo de confirmación antes de habilitar
      setConfirmDialog({ open: true, orgId, orgName });
    } else {
      // Deshabilitar directamente
      performToggle(orgId, false);
    }
  };

  // Ejecutar el toggle contra el backend
  const performToggle = async (orgId: string, enabled: boolean) => {
    // Marcar como toggling
    setOrganizations((prev) =>
      prev.map((org) => (org.orgId === orgId ? { ...org, isToggling: true } : org))
    );

    try {
      await apiClient.patch<AutoUpdateToggleResponse>(
        `/organizations/${orgId}/auto-update`,
        { enabled }
      );

      // Actualizar estado local
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
      // Revertir toggling state
      setOrganizations((prev) =>
        prev.map((org) => (org.orgId === orgId ? { ...org, isToggling: false } : org))
      );
    } finally {
      setConfirmDialog({ open: false, orgId: '', orgName: '' });
    }
  };

  // Asignar versión para una organización
  const handlePinVersion = async (orgId: string, version: string | null) => {
    setPinningOrg(orgId);
    try {
      await apiClient.put(`/updates/pin/${orgId}`, { version });
      toast({
        title: version ? 'Versión asignada' : 'Versión desasignada',
        description: version ? `Organización asignada a versión ${version}` : 'Organización usará la versión más reciente',
      });
      fetchData(); // Refrescar datos
    } catch {
      toast({ title: 'Error', description: 'No se pudo actualizar la versión asignada', variant: 'destructive' });
    } finally {
      setPinningOrg(null);
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
          {/* Información del MSI actual */}
          {msiInfo && (
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Package className="h-5 w-5 text-primary" />
                    <CardTitle>Versión Actual del Instalador</CardTitle>
                  </div>
                  <Badge variant="default">{msiInfo.version}</Badge>
                </div>
                <CardDescription>
                  Información del MSI disponible en S3 para las workstations
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
                      <p className="text-sm font-mono">{msiInfo.commitHash ? msiInfo.commitHash.substring(0, 8) : 'N/A'}</p>
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

          {/* Toggle por organización */}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Building2 className="h-5 w-5 text-primary" />
                <CardTitle>Auto-Actualización por Organización</CardTitle>
              </div>
              <CardDescription>
                Habilita o deshabilita las actualizaciones automáticas para cada organización.
                Las workstations solo se actualizarán si tanto el flag de organización como el flag local están habilitados.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {organizations.length === 0 ? (
                <p className="text-muted-foreground text-center py-4">
                  No se encontraron organizaciones.
                </p>
              ) : (
                <div className="space-y-3">
                  {organizations.map((org) => (
                    <div
                      key={org.orgId}
                      className="flex items-center justify-between p-4 border rounded-lg"
                    >
                      <div className="space-y-1">
                        <Label className="text-base font-medium">{org.orgName}</Label>
                        <p className="text-sm text-muted-foreground">
                          {org.autoUpdateEnabled
                            ? 'Actualizaciones automáticas habilitadas'
                            : 'Actualizaciones automáticas deshabilitadas'}
                        </p>
                        {org.targetVersion && (
                          <div className="flex items-center gap-2 mt-1">
                            <Badge variant="secondary" className="text-xs">
                              <Pin className="h-3 w-3 mr-1" />
                              Asignada: {org.targetVersion}
                            </Badge>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 px-2 text-xs text-destructive hover:text-destructive"
                              onClick={() => handlePinVersion(org.orgId, null)}
                              disabled={pinningOrg === org.orgId}
                            >
                              <PinOff className="h-3 w-3 mr-1" />
                              Desasignar
                            </Button>
                          </div>
                        )}
                      </div>
                      <Switch
                        checked={org.autoUpdateEnabled}
                        onCheckedChange={(checked) => handleToggle(org.orgId, org.orgName, checked)}
                        disabled={org.isToggling}
                      />
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
          {/* Historial de Versiones */}
          {isAdmin && versions.length > 0 && (
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <History className="h-5 w-5 text-primary" />
                  <CardTitle>Historial de Versiones</CardTitle>
                </div>
                <CardDescription>
                  Versiones disponibles en S3. Puedes asignar una versión específica a una organización.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b">
                        <th className="text-left py-2 px-3 font-medium">Versión</th>
                        <th className="text-left py-2 px-3 font-medium">Fecha Build</th>
                        <th className="text-left py-2 px-3 font-medium">Commit</th>
                        <th className="text-left py-2 px-3 font-medium">Tamaño</th>
                        <th className="text-left py-2 px-3 font-medium">Asignar a Organización</th>
                      </tr>
                    </thead>
                    <tbody>
                      {versions.map((v) => (
                        <tr key={v.version} className="border-b hover:bg-muted/50">
                          <td className="py-2 px-3 font-mono">{v.version}</td>
                          <td className="py-2 px-3 text-muted-foreground">{v.buildDate || 'N/A'}</td>
                          <td className="py-2 px-3 font-mono text-muted-foreground">{v.commitHash?.substring(0, 7) || 'N/A'}</td>
                          <td className="py-2 px-3">{formatFileSize(v.fileSize)}</td>
                          <td className="py-2 px-3">
                            <select
                              className="text-xs border rounded px-2 py-1"
                              defaultValue=""
                              onChange={(e) => {
                                if (e.target.value) {
                                  handlePinVersion(e.target.value, v.version);
                                  e.target.value = '';
                                }
                              }}
                              disabled={pinningOrg !== null}
                            >
                              <option value="">Seleccionar org...</option>
                              {organizations.map((org) => (
                                <option key={org.orgId} value={org.orgId}>
                                  {org.orgName}
                                </option>
                              ))}
                            </select>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Organizaciones con versión asignada */}
                {organizations.some(() => false) && null}
              </CardContent>
            </Card>
          )}
        </>
      )}

      {/* Diálogo de confirmación */}
      <Dialog open={confirmDialog.open} onOpenChange={(open) => setConfirmDialog((prev) => ({ ...prev, open }))}>
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
                comenzarán a actualizarse automáticamente. Asegúrate de que la versión actual
                del MSI ha sido probada correctamente.
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
            <Button onClick={() => performToggle(confirmDialog.orgId, true)}>
              Confirmar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
