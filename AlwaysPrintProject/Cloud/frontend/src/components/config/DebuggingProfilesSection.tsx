/**
 * Sección de Perfiles de Debugging.
 * Permite crear, listar, editar y desactivar perfiles de debugging.
 * Gate: solo visible si la organización tiene LLM habilitado.
 */

'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import {
  Plus,
  Bug,
  Power,
  PowerOff,
  Trash2,
  Edit,
  Loader2,
  AlertCircle,
  X,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useToast } from '@/hooks/use-toast';
import { apiClient } from '@/lib/api';

interface DebuggingProfile {
  id: string;
  name: string;
  description: string;
  confirmation_message: string;
  external_logs: string[];
  eventlog_groups: string[];
  registry_keys: string[];
  monitored_services: string[];
  is_active: boolean;
  created_at: string;
}

interface LLMSuggestion {
  suggested_name: string;
  suggested_message: string;
}

interface DebuggingProfilesSectionProps {
  organizationId: string;
  llmEnabled: boolean;
}

export function DebuggingProfilesSection({ organizationId, llmEnabled }: DebuggingProfilesSectionProps) {
  const t = useTranslations('debugging');
  const tCommon = useTranslations('common');
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [includeInactive, setIncludeInactive] = useState(false);

  // Form state
  const [externalLogs, setExternalLogs] = useState<string[]>([]);
  const [eventlogGroups, setEventlogGroups] = useState<string[]>([]);
  const [registryKeys, setRegistryKeys] = useState<string[]>([]);
  const [monitoredServices, setMonitoredServices] = useState<string[]>([]);
  const [description, setDescription] = useState('');

  // LLM suggestion state
  const [suggestion, setSuggestion] = useState<LLMSuggestion | null>(null);
  const [profileName, setProfileName] = useState('');
  const [confirmationMessage, setConfirmationMessage] = useState('');
  const [gettingSuggestion, setGettingSuggestion] = useState(false);
  const [suggestionError, setSuggestionError] = useState('');
  const [showConfirmStep, setShowConfirmStep] = useState(false);

  // Gate: LLM requerido
  if (!llmEnabled) {
    return (
      <Alert>
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{t('llmRequired')}</AlertDescription>
      </Alert>
    );
  }

  // Query: listar perfiles
  const { data: profiles, isLoading } = useQuery<DebuggingProfile[]>({
    queryKey: ['debugging-profiles', organizationId, includeInactive],
    queryFn: async () => {
      const res = await apiClient.get('/debugging/profiles', {
        params: { include_inactive: includeInactive, organization_id: organizationId },
      });
      return res.data;
    },
    enabled: !!organizationId,
  });

  // Mutation: obtener sugerencia LLM
  const getSuggestionMutation = useMutation<LLMSuggestion>({
    mutationFn: async () => {
      const res = await apiClient.post('/debugging/profiles', {
        external_logs: externalLogs.filter(Boolean),
        eventlog_groups: eventlogGroups,
        registry_keys: registryKeys.filter(Boolean),
        monitored_services: monitoredServices.filter(Boolean),
        description,
      }, { params: { organization_id: organizationId } });
      return res.data;
    },
    onSuccess: (data) => {
      setSuggestion(data);
      setProfileName(data.suggested_name);
      setConfirmationMessage(data.suggested_message);
      setShowConfirmStep(true);
      setSuggestionError('');
    },
    onError: () => {
      setSuggestionError(t('suggestionFailed'));
      setShowConfirmStep(true);
    },
  });

  // Mutation: confirmar y guardar perfil
  const saveMutation = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post('/debugging/profiles/confirm', null, {
        params: {
          organization_id: organizationId,
        },
        data: {
          external_logs: externalLogs.filter(Boolean),
          eventlog_groups: eventlogGroups,
          registry_keys: registryKeys.filter(Boolean),
          monitored_services: monitoredServices.filter(Boolean),
          description,
          name: profileName,
          confirmation_message: confirmationMessage,
        },
      });
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['debugging-profiles'] });
      toast({ title: t('saveSuccess') });
      resetForm();
      setCreateDialogOpen(false);
    },
    onError: () => {
      toast({ title: t('errorCreate'), variant: 'destructive' });
    },
  });

  // Mutation: toggle activación
  const toggleMutation = useMutation({
    mutationFn: async ({ id, is_active }: { id: string; is_active: boolean }) => {
      await apiClient.put(`/debugging/profiles/${id}`, { is_active }, {
        params: { organization_id: organizationId },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['debugging-profiles'] });
      toast({ title: t('updateSuccess') });
    },
    onError: () => {
      toast({ title: t('errorUpdate'), variant: 'destructive' });
    },
  });

  // Mutation: eliminar (soft delete)
  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/debugging/profiles/${id}`, {
        params: { organization_id: organizationId },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['debugging-profiles'] });
      toast({ title: t('deleteSuccess') });
    },
    onError: () => {
      toast({ title: t('errorDelete'), variant: 'destructive' });
    },
  });

  const resetForm = () => {
    setExternalLogs([]);
    setEventlogGroups([]);
    setRegistryKeys([]);
    setMonitoredServices([]);
    setDescription('');
    setSuggestion(null);
    setProfileName('');
    setConfirmationMessage('');
    setShowConfirmStep(false);
    setSuggestionError('');
  };

  const hasTargets =
    externalLogs.filter(Boolean).length > 0 ||
    eventlogGroups.length > 0 ||
    registryKeys.filter(Boolean).length > 0 ||
    monitoredServices.filter(Boolean).length > 0;

  const handleGetSuggestion = () => {
    if (!hasTargets) {
      toast({ title: t('atLeastOneTarget'), variant: 'destructive' });
      return;
    }
    if (description.length < 10) {
      return;
    }
    setGettingSuggestion(true);
    getSuggestionMutation.mutate(undefined, {
      onSettled: () => setGettingSuggestion(false),
    });
  };

  // Dynamic list helpers
  const addToList = (setter: React.Dispatch<React.SetStateAction<string[]>>) => {
    setter((prev) => [...prev, '']);
  };
  const removeFromList = (setter: React.Dispatch<React.SetStateAction<string[]>>, idx: number) => {
    setter((prev) => prev.filter((_, i) => i !== idx));
  };
  const updateInList = (setter: React.Dispatch<React.SetStateAction<string[]>>, idx: number, value: string) => {
    setter((prev) => prev.map((v, i) => (i === idx ? value : v)));
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h3 className="text-lg font-medium">{t('title')}</h3>
          <p className="text-sm text-gray-500">{t('subtitle')}</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Switch
              checked={includeInactive}
              onCheckedChange={setIncludeInactive}
              id="include-inactive"
            />
            <Label htmlFor="include-inactive" className="text-sm">{t('includeInactive')}</Label>
          </div>
          <Button onClick={() => { resetForm(); setCreateDialogOpen(true); }}>
            <Plus className="w-4 h-4 mr-2" />
            {t('createProfile')}
          </Button>
        </div>
      </div>

      {/* Listado de perfiles */}
      {isLoading ? (
        <div className="flex items-center gap-2 py-8 justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
          <span className="text-sm text-gray-500">{tCommon('loading')}</span>
        </div>
      ) : !profiles || profiles.length === 0 ? (
        <div className="text-center py-12 bg-gray-50 rounded-lg border-2 border-dashed">
          <Bug className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <p className="text-sm font-medium text-gray-600">{t('noProfiles')}</p>
          <p className="text-xs text-gray-500 mt-1">{t('noProfilesDesc')}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {profiles.map((profile) => (
            <div
              key={profile.id}
              className="p-4 border rounded-lg hover:shadow-sm transition flex flex-col md:flex-row md:items-center md:justify-between gap-3"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-sm truncate">{profile.name}</span>
                  <Badge variant={profile.is_active ? 'default' : 'secondary'}>
                    {profile.is_active ? t('active') : t('inactive')}
                  </Badge>
                </div>
                <p className="text-xs text-gray-500 line-clamp-2">{profile.description}</p>
                <div className="flex flex-wrap gap-1 mt-2">
                  {profile.monitored_services.length > 0 && (
                    <Badge variant="outline" className="text-xs">
                      {profile.monitored_services.length} {t('monitoredServices').toLowerCase()}
                    </Badge>
                  )}
                  {profile.eventlog_groups.length > 0 && (
                    <Badge variant="outline" className="text-xs">
                      {profile.eventlog_groups.join(', ')}
                    </Badge>
                  )}
                  {profile.external_logs.length > 0 && (
                    <Badge variant="outline" className="text-xs">
                      {profile.external_logs.length} logs
                    </Badge>
                  )}
                  {profile.registry_keys.length > 0 && (
                    <Badge variant="outline" className="text-xs">
                      {profile.registry_keys.length} {t('registryKeys').toLowerCase()}
                    </Badge>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 w-8 p-0"
                  title={profile.is_active ? t('deactivateProfile') : t('activateProfile')}
                  onClick={() => toggleMutation.mutate({ id: profile.id, is_active: !profile.is_active })}
                >
                  {profile.is_active ? <PowerOff className="w-4 h-4" /> : <Power className="w-4 h-4" />}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 w-8 p-0"
                  title={t('deleteProfile')}
                  onClick={() => deleteMutation.mutate(profile.id)}
                >
                  <Trash2 className="w-4 h-4 text-red-500" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Dialog de creación */}
      <Dialog open={createDialogOpen} onOpenChange={(open) => { if (!open) { resetForm(); setCreateDialogOpen(false); } }}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t('createProfile')}</DialogTitle>
            <DialogDescription>{t('subtitle')}</DialogDescription>
          </DialogHeader>

          {!showConfirmStep ? (
            <div className="space-y-6 py-4">
              {/* External Logs */}
              <div className="space-y-2">
                <Label className="font-medium">{t('externalLogs')}</Label>
                <p className="text-xs text-gray-500">{t('externalLogsDesc')}</p>
                {externalLogs.map((log, idx) => (
                  <div key={idx} className="flex gap-2">
                    <Input
                      value={log}
                      onChange={(e) => updateInList(setExternalLogs, idx, e.target.value)}
                      placeholder={t('logPathPlaceholder')}
                      className="font-mono text-sm"
                    />
                    <Button variant="ghost" size="sm" className="h-9 w-9 p-0" onClick={() => removeFromList(setExternalLogs, idx)}>
                      <X className="w-4 h-4" />
                    </Button>
                  </div>
                ))}
                <Button variant="outline" size="sm" onClick={() => addToList(setExternalLogs)}>
                  <Plus className="w-3 h-3 mr-1" />{t('addLog')}
                </Button>
              </div>

              {/* Event Log Groups */}
              <div className="space-y-2">
                <Label className="font-medium">{t('eventlogGroups')}</Label>
                <p className="text-xs text-gray-500">{t('eventlogGroupsDesc')}</p>
                <div className="flex flex-wrap gap-2">
                  {['System', 'Application', 'Security'].map((group) => (
                    <label key={group} className="flex items-center gap-2 px-3 py-2 border rounded-md cursor-pointer hover:bg-gray-50">
                      <input
                        type="checkbox"
                        checked={eventlogGroups.includes(group)}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setEventlogGroups((prev) => [...prev, group]);
                          } else {
                            setEventlogGroups((prev) => prev.filter((g) => g !== group));
                          }
                        }}
                        className="rounded"
                      />
                      <span className="text-sm">{group}</span>
                    </label>
                  ))}
                </div>
              </div>

              {/* Registry Keys */}
              <div className="space-y-2">
                <Label className="font-medium">{t('registryKeys')}</Label>
                <p className="text-xs text-gray-500">{t('registryKeysDesc')}</p>
                {registryKeys.map((key, idx) => (
                  <div key={idx} className="flex gap-2">
                    <Input
                      value={key}
                      onChange={(e) => updateInList(setRegistryKeys, idx, e.target.value)}
                      placeholder={t('registryKeyPlaceholder')}
                      className="font-mono text-sm"
                    />
                    <Button variant="ghost" size="sm" className="h-9 w-9 p-0" onClick={() => removeFromList(setRegistryKeys, idx)}>
                      <X className="w-4 h-4" />
                    </Button>
                  </div>
                ))}
                <Button variant="outline" size="sm" onClick={() => addToList(setRegistryKeys)}>
                  <Plus className="w-3 h-3 mr-1" />{t('addRegistryKey')}
                </Button>
              </div>

              {/* Monitored Services */}
              <div className="space-y-2">
                <Label className="font-medium">{t('monitoredServices')}</Label>
                <p className="text-xs text-gray-500">{t('monitoredServicesDesc')}</p>
                {monitoredServices.map((svc, idx) => (
                  <div key={idx} className="flex gap-2">
                    <Input
                      value={svc}
                      onChange={(e) => updateInList(setMonitoredServices, idx, e.target.value)}
                      placeholder={t('servicePlaceholder')}
                      className="font-mono text-sm"
                    />
                    <Button variant="ghost" size="sm" className="h-9 w-9 p-0" onClick={() => removeFromList(setMonitoredServices, idx)}>
                      <X className="w-4 h-4" />
                    </Button>
                  </div>
                ))}
                <Button variant="outline" size="sm" onClick={() => addToList(setMonitoredServices)}>
                  <Plus className="w-3 h-3 mr-1" />{t('addService')}
                </Button>
              </div>

              {/* Description */}
              <div className="space-y-2">
                <Label className="font-medium">{t('description')}</Label>
                <Textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder={t('descriptionPlaceholder')}
                  rows={3}
                />
              </div>

              {!hasTargets && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>{t('atLeastOneTarget')}</AlertDescription>
                </Alert>
              )}
            </div>
          ) : (
            /* Confirm step: name + message from LLM */
            <div className="space-y-4 py-4">
              {suggestionError && (
                <Alert>
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>{suggestionError}</AlertDescription>
                </Alert>
              )}
              <div className="space-y-2">
                <Label className="font-medium">{t('suggestedName')}</Label>
                <Input
                  value={profileName}
                  onChange={(e) => setProfileName(e.target.value)}
                  maxLength={60}
                />
              </div>
              <div className="space-y-2">
                <Label className="font-medium">{t('suggestedMessage')}</Label>
                <Textarea
                  value={confirmationMessage}
                  onChange={(e) => setConfirmationMessage(e.target.value)}
                  maxLength={200}
                  rows={2}
                />
              </div>
            </div>
          )}

          <DialogFooter>
            {!showConfirmStep ? (
              <Button
                onClick={handleGetSuggestion}
                disabled={!hasTargets || description.length < 10 || gettingSuggestion}
              >
                {gettingSuggestion ? (
                  <><Loader2 className="w-4 h-4 mr-2 animate-spin" />{t('gettingSuggestion')}</>
                ) : (
                  t('getSuggestion')
                )}
              </Button>
            ) : (
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setShowConfirmStep(false)}>
                  {tCommon('back')}
                </Button>
                <Button
                  onClick={() => saveMutation.mutate()}
                  disabled={!profileName || !confirmationMessage || saveMutation.isPending}
                >
                  {saveMutation.isPending ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : null}
                  {t('confirmSave')}
                </Button>
              </div>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
