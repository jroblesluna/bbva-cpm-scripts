'use client';

/**
 * Página de gestión de configuraciones de acciones administrativas.
 * 
 * Permite a los administradores:
 * - Subir archivos .alwaysconfig
 * - Ver configuraciones existentes
 * - Activar/desactivar propagación
 * - Eliminar configuraciones
 * - Ver estado de sincronización con workstations
 */

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSession } from 'next-auth/react';
import {
  Upload,
  FileText,
  CheckCircle2,
  XCircle,
  Trash2,
  Eye,
  Download,
  AlertCircle,
  Power,
  PowerOff,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';

import {
  uploadActionConfig,
  listActionConfigs,
  getActionConfigDetail,
  updateActionConfig,
  deleteActionConfig,
  calculateConfigHash,
  validateAlwaysConfig,
} from '@/lib/api/action-config';
import type { ActionConfig, ActionConfigDetail } from '@/types/action-config';

export default function ActionConfigsPage() {
  const { data: session } = useSession();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [detailDialogOpen, setDetailDialogOpen] = useState(false);
  const [selectedConfig, setSelectedConfig] = useState<ActionConfigDetail | null>(null);
  const [configJson, setConfigJson] = useState('');
  const [isActive, setIsActive] = useState(true);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  
  const organizationId = 1; // TODO: Obtener del usuario autenticado (session?.user?.organization_id)
  
  // Query para listar configuraciones
  const { data: configs, isLoading } = useQuery({
    queryKey: ['action-configs', organizationId],
    queryFn: () => listActionConfigs(organizationId!),
    enabled: !!organizationId,
  });
  
  // Mutation para subir configuración
  const uploadMutation = useMutation({
    mutationFn: (data: { config_json: string; is_active: boolean }) =>
      uploadActionConfig(organizationId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['action-configs', organizationId] });
      toast({
        title: 'Configuración subida',
        description: 'La configuración se ha subido exitosamente',
      });
      setUploadDialogOpen(false);
      setConfigJson('');
      setValidationErrors([]);
    },
    onError: (error: any) => {
      toast({
        title: 'Error',
        description: error.response?.data?.detail || 'Error subiendo configuración',
        variant: 'destructive',
      });
    },
  });
  
  // Mutation para actualizar configuración
  const updateMutation = useMutation({
    mutationFn: ({ configId, is_active }: { configId: number; is_active: boolean }) =>
      updateActionConfig(organizationId!, configId, { is_active }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['action-configs', organizationId] });
      toast({
        title: 'Configuración actualizada',
        description: 'El estado de la configuración se ha actualizado',
      });
    },
    onError: (error: any) => {
      toast({
        title: 'Error',
        description: error.response?.data?.detail || 'Error actualizando configuración',
        variant: 'destructive',
      });
    },
  });
  
  // Mutation para eliminar configuración
  const deleteMutation = useMutation({
    mutationFn: (configId: number) => deleteActionConfig(organizationId!, configId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['action-configs', organizationId] });
      toast({
        title: 'Configuración eliminada',
        description: 'La configuración se ha eliminado exitosamente',
      });
    },
    onError: (error: any) => {
      toast({
        title: 'Error',
        description: error.response?.data?.detail || 'Error eliminando configuración',
        variant: 'destructive',
      });
    },
  });
  
  // Handlers
  const handleFileUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    
    const reader = new FileReader();
    reader.onload = (e) => {
      const content = e.target?.result as string;
      setConfigJson(content);
      
      // Validar automáticamente
      const validation = validateAlwaysConfig(content);
      setValidationErrors(validation.errors);
    };
    reader.readAsText(file);
  };
  
  const handleUpload = async () => {
    // Validar antes de subir
    const validation = validateAlwaysConfig(configJson);
    if (!validation.valid) {
      setValidationErrors(validation.errors);
      return;
    }
    
    uploadMutation.mutate({
      config_json: configJson,
      is_active: isActive,
    });
  };
  
  const handleToggleActive = (config: ActionConfig) => {
    updateMutation.mutate({
      configId: config.id,
      is_active: !config.is_active,
    });
  };
  
  const handleDelete = (configId: number) => {
    if (confirm('¿Estás seguro de eliminar esta configuración? Esta acción no se puede deshacer.')) {
      deleteMutation.mutate(configId);
    }
  };
  
  const handleViewDetail = async (config: ActionConfig) => {
    try {
      const detail = await getActionConfigDetail(organizationId!, config.id);
      setSelectedConfig(detail);
      setDetailDialogOpen(true);
    } catch (error: any) {
      toast({
        title: 'Error',
        description: 'Error cargando detalles de la configuración',
        variant: 'destructive',
      });
    }
  };
  
  const handleDownloadConfig = (config: ActionConfigDetail) => {
    const blob = new Blob([config.config_json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${config.name}.alwaysconfig`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };
  
  const activeConfig = configs?.find(c => c.is_active);
  
  return (
    <div className="container mx-auto py-6 space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold">Configuraciones de Acciones</h1>
          <p className="text-muted-foreground mt-1">
            Gestiona las acciones administrativas que se ejecutan en las workstations
          </p>
        </div>
        
        <Button onClick={() => setUploadDialogOpen(true)}>
          <Upload className="mr-2 h-4 w-4" />
          Subir Configuración
        </Button>
      </div>
      
      {/* Configuración activa */}
      {activeConfig && (
        <Card className="border-green-200 bg-green-50">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-5 w-5 text-green-600" />
                <CardTitle>Configuración Activa</CardTitle>
              </div>
              <Badge variant="default" className="bg-green-600">
                Activa
              </Badge>
            </div>
            <CardDescription>
              Esta configuración se está propagando a las workstations
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <p className="text-sm text-muted-foreground">Nombre</p>
                <p className="font-medium">{activeConfig.name}</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Versión</p>
                <p className="font-medium">{activeConfig.version}</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Hash</p>
                <p className="font-mono text-sm">{activeConfig.config_hash}</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Creada</p>
                <p className="text-sm">
                  {new Date(activeConfig.created_at).toLocaleDateString()}
                </p>
              </div>
            </div>
            
            <div className="flex gap-2 mt-4">
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleViewDetail(activeConfig)}
              >
                <Eye className="mr-2 h-4 w-4" />
                Ver Detalles
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleToggleActive(activeConfig)}
              >
                <PowerOff className="mr-2 h-4 w-4" />
                Desactivar
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
      
      {/* Lista de configuraciones */}
      <Card>
        <CardHeader>
          <CardTitle>Todas las Configuraciones</CardTitle>
          <CardDescription>
            Historial de configuraciones subidas
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-center text-muted-foreground py-8">Cargando...</p>
          ) : !configs || configs.length === 0 ? (
            <div className="text-center py-12">
              <FileText className="mx-auto h-12 w-12 text-muted-foreground mb-4" />
              <p className="text-muted-foreground">No hay configuraciones</p>
              <Button
                variant="outline"
                className="mt-4"
                onClick={() => setUploadDialogOpen(true)}
              >
                Subir Primera Configuración
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              {configs.map((config) => (
                <div
                  key={config.id}
                  className="flex items-center justify-between p-4 border rounded-lg hover:bg-accent/50 transition-colors"
                >
                  <div className="flex-1">
                    <div className="flex items-center gap-3">
                      <h3 className="font-medium">{config.name}</h3>
                      <Badge variant={config.is_active ? 'default' : 'secondary'}>
                        {config.is_active ? 'Activa' : 'Inactiva'}
                      </Badge>
                      <span className="text-sm text-muted-foreground">
                        v{config.version}
                      </span>
                    </div>
                    {config.description && (
                      <p className="text-sm text-muted-foreground mt-1">
                        {config.description}
                      </p>
                    )}
                    <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                      <span>Hash: {config.config_hash}</span>
                      <span>
                        Creada: {new Date(config.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                  
                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleViewDetail(config)}
                    >
                      <Eye className="h-4 w-4" />
                    </Button>
                    
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleToggleActive(config)}
                      disabled={updateMutation.isPending}
                    >
                      {config.is_active ? (
                        <PowerOff className="h-4 w-4" />
                      ) : (
                        <Power className="h-4 w-4" />
                      )}
                    </Button>
                    
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDelete(config.id)}
                      disabled={deleteMutation.isPending}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
      
      {/* Dialog para subir configuración */}
      <Dialog open={uploadDialogOpen} onOpenChange={setUploadDialogOpen}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Subir Configuración de Acciones</DialogTitle>
            <DialogDescription>
              Sube un archivo .alwaysconfig con las acciones administrativas
            </DialogDescription>
          </DialogHeader>
          
          <div className="space-y-4">
            {/* Upload de archivo */}
            <div>
              <Label htmlFor="file-upload">Archivo .alwaysconfig</Label>
              <input
                id="file-upload"
                type="file"
                accept=".alwaysconfig,.json"
                onChange={handleFileUpload}
                className="mt-2 block w-full text-sm text-muted-foreground
                  file:mr-4 file:py-2 file:px-4
                  file:rounded-md file:border-0
                  file:text-sm file:font-semibold
                  file:bg-primary file:text-primary-foreground
                  hover:file:bg-primary/90"
              />
            </div>
            
            {/* Editor de JSON */}
            <div>
              <Label htmlFor="config-json">JSON de Configuración</Label>
              <Textarea
                id="config-json"
                value={configJson}
                onChange={(e) => {
                  setConfigJson(e.target.value);
                  const validation = validateAlwaysConfig(e.target.value);
                  setValidationErrors(validation.errors);
                }}
                placeholder='{"version": "1.0", "name": "Mi Configuración", ...}'
                className="mt-2 font-mono text-sm min-h-[300px]"
              />
            </div>
            
            {/* Errores de validación */}
            {validationErrors.length > 0 && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  <p className="font-semibold mb-2">Errores de validación:</p>
                  <ul className="list-disc list-inside space-y-1">
                    {validationErrors.map((error, index) => (
                      <li key={index}>{error}</li>
                    ))}
                  </ul>
                </AlertDescription>
              </Alert>
            )}
            
            {/* Switch para activar */}
            <div className="flex items-center space-x-2">
              <Switch
                id="is-active"
                checked={isActive}
                onCheckedChange={setIsActive}
              />
              <Label htmlFor="is-active">
                Activar inmediatamente (desactiva configuración previa)
              </Label>
            </div>
          </div>
          
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setUploadDialogOpen(false)}
            >
              Cancelar
            </Button>
            <Button
              onClick={handleUpload}
              disabled={
                !configJson ||
                validationErrors.length > 0 ||
                uploadMutation.isPending
              }
            >
              {uploadMutation.isPending ? 'Subiendo...' : 'Subir'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      
      {/* Dialog para ver detalles */}
      <Dialog open={detailDialogOpen} onOpenChange={setDetailDialogOpen}>
        <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{selectedConfig?.name}</DialogTitle>
            <DialogDescription>
              Versión {selectedConfig?.version} • Hash: {selectedConfig?.config_hash}
            </DialogDescription>
          </DialogHeader>
          
          {selectedConfig && (
            <div className="space-y-4">
              {selectedConfig.description && (
                <p className="text-sm text-muted-foreground">
                  {selectedConfig.description}
                </p>
              )}
              
              <div>
                <Label>JSON de Configuración</Label>
                <pre className="mt-2 p-4 bg-muted rounded-lg overflow-x-auto text-xs">
                  {JSON.stringify(JSON.parse(selectedConfig.config_json), null, 2)}
                </pre>
              </div>
              
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  onClick={() => handleDownloadConfig(selectedConfig)}
                >
                  <Download className="mr-2 h-4 w-4" />
                  Descargar
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
