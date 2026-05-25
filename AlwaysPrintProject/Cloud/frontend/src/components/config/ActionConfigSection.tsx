/**
 * Sección de Configuraciones de Acciones Administrativas.
 * Se integra como un tópico dentro del editor de configuración por organización.
 */

'use client';

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import {
  Upload,
  FileText,
  CheckCircle2,
  Trash2,
  Eye,
  Download,
  AlertCircle,
  Power,
  PowerOff,
  Cog,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
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
import { apiClient } from '@/lib/api';

interface ActionConfigSectionProps {
  organizationId: string;
  /** Si se pasa, opera a nivel de VLAN en vez de org */
  vlanId?: string;
}

export function ActionConfigSection({ organizationId, vlanId }: ActionConfigSectionProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const t = useTranslations('actionConfigs');
  const tCommon = useTranslations('common');

  const scope = vlanId ? 'vlan' : 'org';

  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [detailDialogOpen, setDetailDialogOpen] = useState(false);
  const [selectedConfig, setSelectedConfig] = useState<ActionConfigDetail | null>(null);
  const [configJson, setConfigJson] = useState('');
  const [isActive, setIsActive] = useState(true);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [mandatory, setMandatory] = useState(false);
  const [togglingMandatory, setTogglingMandatory] = useState(false);

  // Cargar estado mandatory
  useEffect(() => {
    const loadMandatory = async () => {
      try {
        if (scope === 'org') {
          const res = await apiClient.get(`/organizations/${organizationId}`);
          setMandatory(res.data.action_config_mandatory ?? false);
        } else if (vlanId) {
          const res = await apiClient.get(`/vlans/${vlanId}`);
          setMandatory(res.data.action_config_mandatory ?? false);
        }
      } catch { setMandatory(false); }
    };
    loadMandatory();
  }, [organizationId, vlanId, scope]);

  // Query para listar configuraciones
  const { data: configs, isLoading } = useQuery({
    queryKey: ['action-configs', organizationId, scope, vlanId],
    queryFn: () => listActionConfigs(organizationId, scope, vlanId),
    enabled: !!organizationId,
  });

  // Mutation para subir configuración
  const uploadMutation = useMutation({
    mutationFn: (data: { config_json: string; is_active: boolean }) =>
      uploadActionConfig(organizationId, data, scope, vlanId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['action-configs', organizationId, scope, vlanId] });
      toast({ title: t('uploadSuccess'), description: t('uploadSuccessDesc') });
      setUploadDialogOpen(false);
      setConfigJson('');
      setValidationErrors([]);
      setUploadError(null);
    },
    onError: async (error: unknown) => {
      const err = error as { status?: number; response?: { status?: number; data?: { detail?: string } }; detail?: string };
      const status = err?.status || err?.response?.status;
      const detail = err?.detail || err?.response?.data?.detail || t('errorUpload');

      if (status === 409) {
        const hash = await calculateConfigHash(configJson);
        const msg = t('duplicateDesc', { hash });
        setUploadError(msg);
        toast({ title: t('duplicateTitle'), description: msg, variant: 'destructive' });
      } else {
        setUploadError(detail);
        toast({ title: t('errorTitle'), description: detail, variant: 'destructive' });
      }
    },
  });

  // Mutation para actualizar configuración
  const updateMutation = useMutation({
    mutationFn: ({ configId, is_active }: { configId: number; is_active: boolean }) =>
      updateActionConfig(organizationId, configId, { is_active }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['action-configs', organizationId, scope, vlanId] });
      toast({ title: t('updateSuccess'), description: t('updateSuccessDesc') });
    },
    onError: (error: unknown) => {
      const err = error as { detail?: string };
      toast({ title: t('errorTitle'), description: err?.detail || t('errorUpdate'), variant: 'destructive' });
    },
  });

  // Mutation para eliminar configuración
  const deleteMutation = useMutation({
    mutationFn: (configId: number) => deleteActionConfig(organizationId, configId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['action-configs', organizationId, scope, vlanId] });
      toast({ title: t('deleteSuccess'), description: t('deleteSuccessDesc') });
    },
    onError: (error: unknown) => {
      const err = error as { detail?: string };
      toast({ title: t('errorTitle'), description: err?.detail || t('errorDelete'), variant: 'destructive' });
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
      setUploadError(null);
      const validation = validateAlwaysConfig(content);
      setValidationErrors(validation.errors);
    };
    reader.readAsText(file);
  };

  const handleUpload = async () => {
    setUploadError(null);
    const validation = validateAlwaysConfig(configJson);
    if (!validation.valid) {
      setValidationErrors(validation.errors);
      return;
    }
    uploadMutation.mutate({ config_json: configJson, is_active: isActive });
  };

  const handleToggleActive = (config: ActionConfig) => {
    updateMutation.mutate({ configId: config.id, is_active: !config.is_active });
  };

  const handleDelete = (configId: number) => {
    if (confirm(t('deleteConfirm'))) {
      deleteMutation.mutate(configId);
    }
  };

  const handleViewDetail = async (config: ActionConfig) => {
    try {
      const detail = await getActionConfigDetail(organizationId, config.id);
      setSelectedConfig(detail);
      setDetailDialogOpen(true);
    } catch {
      toast({ title: t('errorTitle'), description: t('errorLoadDetail'), variant: 'destructive' });
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

  const handleMandatoryToggle = async (enabled: boolean) => {
    setTogglingMandatory(true);
    try {
      if (scope === 'org') {
        await apiClient.put(`/organizations/${organizationId}`, { action_config_mandatory: enabled });
      } else if (vlanId) {
        await apiClient.put(`/vlans/${vlanId}`, { action_config_mandatory: enabled });
      }
      setMandatory(enabled);
    } catch { /* silently revert */ }
    finally { setTogglingMandatory(false); }
  };

  const activeConfig = configs?.find((c) => c.is_active);

  return (
    <div className="bg-white rounded-lg shadow">
      <div className="p-6">
        {/* Header del tópico (solo a nivel org) */}
        {scope === 'org' && (
          <div className="flex items-center justify-between mb-5">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-indigo-100 flex items-center justify-center">
                <Cog className="h-5 w-5 text-indigo-600" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-gray-900">{t('title')}</h2>
                <p className="text-sm text-gray-500">{t('subtitle')}</p>
              </div>
            </div>
            <Button
              size="sm"
              onClick={() => { setUploadDialogOpen(true); setUploadError(null); }}
            >
              <Upload className="mr-2 h-4 w-4" />
              {t('uploadBtn')}
            </Button>
          </div>
        )}
        {scope === 'vlan' && (
          <div className="flex justify-end mb-4">
            <Button
              size="sm"
              onClick={() => { setUploadDialogOpen(true); setUploadError(null); }}
            >
              <Upload className="mr-2 h-4 w-4" />
              {t('uploadBtn')}
            </Button>
          </div>
        )}

        {/* Toggle de mandatory */}
        <div className="mb-4 flex items-center justify-between p-3 border rounded-lg bg-gray-50">
          <div>
            <Label className="text-sm font-medium">{t('mandatoryLabel')}</Label>
            <p className="text-xs text-gray-500 mt-0.5">
              {mandatory
                ? (scope === 'org' ? t('mandatoryEnabledDescOrg') : t('mandatoryEnabledDescVlan'))
                : (scope === 'org' ? t('mandatoryDisabledDescOrg') : t('mandatoryDisabledDescVlan'))
              }
            </p>
          </div>
          <Switch
            checked={mandatory}
            onCheckedChange={handleMandatoryToggle}
            disabled={togglingMandatory}
          />
        </div>

        {/* Configuración activa */}
        {activeConfig && (
          <div className="mb-4 p-4 border border-green-200 bg-green-50 rounded-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-green-600" />
                <span className="font-medium text-sm text-green-900">{t('activeConfig')}</span>
                <Badge variant="default" className="bg-green-600 text-xs">{t('active')}</Badge>
              </div>
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => handleViewDetail(activeConfig)} title={t('viewDetails')}>
                  <Eye className="h-3.5 w-3.5" />
                </Button>
                <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => handleToggleActive(activeConfig)} title={t('deactivate')}>
                  <PowerOff className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
            <div className="mt-2 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
              <div>
                <span className="text-gray-500">{t('name')}</span>
                <p className="font-medium text-gray-900">{activeConfig.name}</p>
              </div>
              <div>
                <span className="text-gray-500">{t('version')}</span>
                <p className="font-medium text-gray-900">{activeConfig.version}</p>
              </div>
              <div>
                <span className="text-gray-500">{t('hash')}</span>
                <p className="font-mono text-gray-900">{activeConfig.config_hash}</p>
              </div>
              <div>
                <span className="text-gray-500">{t('created')}</span>
                <p className="text-gray-900">{new Date(activeConfig.created_at).toLocaleDateString()}</p>
              </div>
            </div>
          </div>
        )}

        {/* Lista de configuraciones */}
        {isLoading ? (
          <p className="text-center text-gray-500 py-6">{tCommon('loading')}</p>
        ) : !configs || configs.length === 0 ? (
          <div className="text-center py-8 border border-dashed border-gray-300 rounded-lg">
            <FileText className="mx-auto h-10 w-10 text-gray-400 mb-3" />
            <p className="text-sm text-gray-500">{t('noConfigs')}</p>
            <Button
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={() => setUploadDialogOpen(true)}
            >
              {t('uploadFirst')}
            </Button>
          </div>
        ) : (
          <div className="space-y-2">
            <h3 className="text-sm font-medium text-gray-700 mb-2">{t('allConfigs')}</h3>
            {configs.map((config) => (
              <div
                key={config.id}
                className="flex items-center justify-between p-3 border rounded-lg hover:bg-gray-50 transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm truncate">{config.name}</span>
                    <Badge variant={config.is_active ? 'default' : 'secondary'} className="text-xs">
                      {config.is_active ? t('active') : t('inactive')}
                    </Badge>
                    <span className="text-xs text-gray-500">v{config.version}</span>
                  </div>
                  <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                    <span className="font-mono">{config.config_hash}</span>
                    <span>{new Date(config.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
                <div className="flex items-center gap-1 ml-2">
                  <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => handleViewDetail(config)} title={t('viewDetails')}>
                    <Eye className="h-3.5 w-3.5" />
                  </Button>
                  <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => handleToggleActive(config)} disabled={updateMutation.isPending} title={config.is_active ? t('deactivate') : t('active')}>
                    {config.is_active ? <PowerOff className="h-3.5 w-3.5" /> : <Power className="h-3.5 w-3.5" />}
                  </Button>
                  <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-red-600 hover:text-red-700 hover:bg-red-50" onClick={() => handleDelete(config.id)} disabled={deleteMutation.isPending} title={tCommon('delete')}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Dialog para subir configuración */}
      <Dialog open={uploadDialogOpen} onOpenChange={(open) => { setUploadDialogOpen(open); if (!open) setUploadError(null); }}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t('uploadTitle')}</DialogTitle>
            <DialogDescription>{t('uploadDescription')}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {/* Error de subida */}
            {uploadError && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  <p className="font-semibold mb-1">{t('duplicateTitle')}</p>
                  <p>{uploadError}</p>
                </AlertDescription>
              </Alert>
            )}

            {/* Upload de archivo */}
            <div>
              <Label htmlFor="file-upload-section">{t('fileLabel')}</Label>
              <input
                id="file-upload-section"
                type="file"
                accept=".alwaysconfig,.json"
                onChange={handleFileUpload}
                className="mt-2 block w-full text-sm text-gray-500
                  file:mr-4 file:py-2 file:px-4
                  file:rounded-md file:border-0
                  file:text-sm file:font-semibold
                  file:bg-blue-600 file:text-white
                  hover:file:bg-blue-700"
              />
            </div>

            {/* Editor de JSON */}
            <div>
              <Label htmlFor="config-json-section">{t('jsonLabel')}</Label>
              <Textarea
                id="config-json-section"
                value={configJson}
                onChange={(e) => {
                  setConfigJson(e.target.value);
                  setUploadError(null);
                  const validation = validateAlwaysConfig(e.target.value);
                  setValidationErrors(validation.errors);
                }}
                placeholder={t('jsonPlaceholder')}
                className="mt-2 font-mono text-sm min-h-[250px]"
              />
            </div>

            {/* Errores de validación */}
            {validationErrors.length > 0 && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  <p className="font-semibold mb-2">{t('validationErrors')}</p>
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
              <Switch id="is-active-section" checked={isActive} onCheckedChange={setIsActive} />
              <Label htmlFor="is-active-section">{t('activateImmediately')}</Label>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setUploadDialogOpen(false)}>
              {tCommon('cancel')}
            </Button>
            <Button
              onClick={handleUpload}
              disabled={!configJson || validationErrors.length > 0 || uploadMutation.isPending}
            >
              {uploadMutation.isPending ? t('uploading') : t('upload')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog para ver detalles */}
      <Dialog open={detailDialogOpen} onOpenChange={setDetailDialogOpen}>
        <DialogContent className="max-w-4xl h-[80vh] flex flex-col">
          <DialogHeader className="flex-shrink-0">
            <DialogTitle>{selectedConfig?.name}</DialogTitle>
            <DialogDescription>
              {t('version')} {selectedConfig?.version} • {t('hash')}: {selectedConfig?.config_hash}
            </DialogDescription>
          </DialogHeader>

          {selectedConfig && (
            <div className="flex flex-col flex-1 min-h-0 space-y-4">
              {selectedConfig.description && (
                <p className="text-sm text-gray-500 flex-shrink-0">{selectedConfig.description}</p>
              )}
              <div className="flex-1 min-h-0 flex flex-col">
                <Label className="flex-shrink-0">{t('jsonLabel')}</Label>
                <pre className="mt-2 p-4 bg-gray-100 rounded-lg overflow-auto text-xs flex-1 min-h-0">
                  {JSON.stringify(JSON.parse(selectedConfig.config_json), null, 2)}
                </pre>
              </div>
              <div className="flex gap-2 flex-shrink-0">
                <Button variant="outline" onClick={() => handleDownloadConfig(selectedConfig)}>
                  <Download className="mr-2 h-4 w-4" />
                  {t('download')}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
