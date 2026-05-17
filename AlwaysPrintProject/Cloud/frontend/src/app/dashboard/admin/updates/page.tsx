'use client';

/**
 * Página de administración de actualizaciones automáticas.
 *
 * Permite a los administradores:
 * - Ver la versión actual del MSI disponible en S3
 * - Ver fecha de build y commit hash
 * - Habilitar/deshabilitar auto-updates para la organización
 * - Confirmación antes de habilitar auto-updates
 */

import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Package, Calendar, GitCommit, HardDrive, AlertTriangle } from 'lucide-react';

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
import { apiClient } from '@/lib/api';

// ============================================================================
// TIPOS
// ============================================================================

interface UpdateInfo {
  version: string;
  buildDate: string;
  commitHash: string;
  fileSize: number;
  autoUpdateEnabled: boolean;
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

// ============================================================================
// HELPERS
// ============================================================================

/**
 * Formatea el tamaño de archivo en unidades legibles.
 */
function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const size = (bytes / Math.pow(1024, i)).toFixed(2);
  return `${size} ${units[i]}`;
}

/**
 * Formatea una fecha ISO a formato legible en español.
 */
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

  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isToggling, setIsToggling] = useState(false);
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false);

  const organizationId = user?.account_id;

  // Obtener información de actualización desde el backend
  const fetchUpdateInfo = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await apiClient.get<UpdateCheckResponse>('/updates/check');
      const data = response.data;

      setUpdateInfo({
        version: data.version,
        buildDate: data.build_date,
        commitHash: data.commit_hash,
        fileSize: data.file_size,
        autoUpdateEnabled: data.auto_update_enabled,
      });
    } catch (err: unknown) {
      const errorMessage =
        err && typeof err === 'object' && 'detail' in err
          ? (err as { detail: string }).detail
          : 'Error al obtener información de actualizaciones';
      setError(errorMessage);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUpdateInfo();
  }, [fetchUpdateInfo]);

  // Manejar toggle de auto-updates
  const handleToggleAutoUpdate = (checked: boolean) => {
    if (checked) {
      // Mostrar diálogo de confirmación antes de habilitar
      setConfirmDialogOpen(true);
    } else {
      // Deshabilitar directamente sin confirmación
      performToggle(false);
    }
  };

  // Ejecutar el toggle contra el backend
  const performToggle = async (enabled: boolean) => {
    if (!organizationId) {
      toast({
        title: 'Error',
        description: 'No se pudo determinar la organización del usuario',
        variant: 'destructive',
      });
      return;
    }

    setIsToggling(true);

    try {
      await apiClient.patch<AutoUpdateToggleResponse>(
        `/organizations/${organizationId}/auto-update`,
        { enabled }
      );

      setUpdateInfo((prev) =>
        prev ? { ...prev, autoUpdateEnabled: enabled } : prev
      );

      toast({
        title: enabled
          ? 'Actualizaciones automáticas habilitadas'
          : 'Actualizaciones automáticas deshabilitadas',
        description: enabled
          ? 'Las workstations de la organización se actualizarán automáticamente'
          : 'Las workstations no recibirán actualizaciones automáticas',
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
    } finally {
      setIsToggling(false);
      setConfirmDialogOpen(false);
    }
  };

  // Confirmar habilitación desde el diálogo
  const handleConfirmEnable = () => {
    performToggle(true);
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
            Gestiona las actualizaciones del cliente AlwaysPrint para la organización
          </p>
        </div>

        <Button
          variant="outline"
          onClick={fetchUpdateInfo}
          disabled={isLoading}
        >
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
      {isLoading && !updateInfo && (
        <Card>
          <CardContent className="py-12">
            <p className="text-center text-muted-foreground">
              Cargando información de actualizaciones...
            </p>
          </CardContent>
        </Card>
      )}

      {/* Información del MSI actual */}
      {updateInfo && (
        <>
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Package className="h-5 w-5 text-primary" />
                  <CardTitle>Versión Actual del Instalador</CardTitle>
                </div>
                <Badge variant="default">v{updateInfo.version}</Badge>
              </div>
              <CardDescription>
                Información del MSI disponible para las workstations
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* Versión */}
                <div className="flex items-start gap-3">
                  <Package className="h-5 w-5 text-muted-foreground mt-0.5" />
                  <div>
                    <p className="text-sm text-muted-foreground">Versión</p>
                    <p className="font-medium text-lg">{updateInfo.version}</p>
                  </div>
                </div>

                {/* Fecha de build */}
                <div className="flex items-start gap-3">
                  <Calendar className="h-5 w-5 text-muted-foreground mt-0.5" />
                  <div>
                    <p className="text-sm text-muted-foreground">Fecha de Build</p>
                    <p className="font-medium">{formatDate(updateInfo.buildDate)}</p>
                  </div>
                </div>

                {/* Commit hash */}
                <div className="flex items-start gap-3">
                  <GitCommit className="h-5 w-5 text-muted-foreground mt-0.5" />
                  <div>
                    <p className="text-sm text-muted-foreground">Commit Hash</p>
                    <p className="font-mono text-sm">{updateInfo.commitHash}</p>
                  </div>
                </div>

                {/* Tamaño del archivo */}
                <div className="flex items-start gap-3">
                  <HardDrive className="h-5 w-5 text-muted-foreground mt-0.5" />
                  <div>
                    <p className="text-sm text-muted-foreground">Tamaño del Archivo</p>
                    <p className="font-medium">{formatFileSize(updateInfo.fileSize)}</p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Toggle de auto-updates */}
          <Card>
            <CardHeader>
              <CardTitle>Configuración de Auto-Actualización</CardTitle>
              <CardDescription>
                Controla si las workstations de la organización se actualizan automáticamente
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between p-4 border rounded-lg">
                <div className="space-y-1">
                  <Label htmlFor="auto-update-toggle" className="text-base font-medium">
                    Actualizaciones Automáticas
                  </Label>
                  <p className="text-sm text-muted-foreground">
                    {updateInfo.autoUpdateEnabled
                      ? 'Las workstations descargarán e instalarán actualizaciones automáticamente'
                      : 'Las workstations no recibirán actualizaciones automáticas'}
                  </p>
                </div>
                <Switch
                  id="auto-update-toggle"
                  checked={updateInfo.autoUpdateEnabled}
                  onCheckedChange={handleToggleAutoUpdate}
                  disabled={isToggling}
                />
              </div>

              {updateInfo.autoUpdateEnabled && (
                <Alert className="mt-4">
                  <AlertDescription>
                    Las workstations verificarán actualizaciones cada 24 horas. La actualización
                    se aplicará de forma silenciosa cuando ambos flags (organización y local) estén
                    habilitados.
                  </AlertDescription>
                </Alert>
              )}
            </CardContent>
          </Card>
        </>
      )}

      {/* Diálogo de confirmación para habilitar auto-updates */}
      <Dialog open={confirmDialogOpen} onOpenChange={setConfirmDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirmar Habilitación de Auto-Actualizaciones</DialogTitle>
            <DialogDescription>
              ¿Estás seguro de que deseas habilitar las actualizaciones automáticas para toda la
              organización? Las workstations que tengan el flag local habilitado comenzarán a
              actualizarse automáticamente.
            </DialogDescription>
          </DialogHeader>

          <div className="py-4">
            <Alert>
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>
                Esta acción afectará a todas las workstations de la organización que tengan
                habilitadas las actualizaciones automáticas localmente. Asegúrate de que la
                versión actual del MSI ha sido probada correctamente.
              </AlertDescription>
            </Alert>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmDialogOpen(false)}
              disabled={isToggling}
            >
              Cancelar
            </Button>
            <Button
              onClick={handleConfirmEnable}
              disabled={isToggling}
            >
              {isToggling ? 'Habilitando...' : 'Confirmar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
