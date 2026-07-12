/**
 * Sección de Comandos de Sistema Operativo.
 *
 * Permite ejecutar comandos predefinidos en el alwaysconfig y descargar archivos
 * declarados en la configuración. Los comandos son solo los que el administrador
 * definió en remote_commands del alwaysconfig; no se permite entrada libre.
 *
 * A) Ejecutar comandos: muestra lista de comandos definidos, al ejecutar envía
 *    al backend que lo redirige vía WebSocket al cliente, el resultado (stdout)
 *    se muestra en un dialog.
 *
 * B) Descargar archivos: muestra lista de archivos declarados en downloadable_files,
 *    al hacer click inicia descarga comprimida en ZIP (mismo mecanismo que log).
 */

'use client';

import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import {
  Terminal,
  Play,
  Loader2,
  WifiOff,
  FileDown,
  Download,
  Copy,
  X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useToast } from '@/hooks/use-toast';
import { workstationsApi } from '@/lib/api';

// === TIPOS ===

interface RemoteCommand {
  label: string;
  command: string;
  description: string;
}

interface DownloadableFile {
  label: string;
  path: string;
  description: string;
}

interface OsCommandsSectionProps {
  workstationId: string;
  isOnline: boolean;
}

// === COMPONENTE ===

export function OsCommandsSection({ workstationId, isOnline }: OsCommandsSectionProps) {
  const t = useTranslations('workstations');
  const tCommon = useTranslations('common');
  const { toast } = useToast();

  const [commandOutput, setCommandOutput] = useState<{ label: string; stdout: string } | null>(null);
  const [downloadingFile, setDownloadingFile] = useState<string | null>(null);

  // Obtener comandos y archivos disponibles desde el config efectivo
  const { data, isLoading } = useQuery<{
    commands: RemoteCommand[];
    files: DownloadableFile[];
  }>({
    queryKey: ['os-commands', workstationId],
    queryFn: async () => {
      const response = await workstationsApi.getOsCommands(workstationId);
      return response;
    },
  });

  // Mutación para ejecutar un comando
  const executeMutation = useMutation({
    mutationFn: async (command: RemoteCommand) => {
      const result = await workstationsApi.sendCommand(
        workstationId,
        'execute_remote_command' as 'execute_on_demand',
        { label: command.label, command: command.command }
      );
      return result;
    },
    onSuccess: (data, command) => {
      const stdout = (data as unknown as { stdout?: string })?.stdout || t('osCommandsNoOutput');
      setCommandOutput({ label: command.label, stdout });
    },
    onError: (error: { detail?: string; status?: number }, command) => {
      if (error.status === 409) {
        toast({ variant: 'destructive', title: t('osCommandsFailed'), description: t('wsOfflineTooltip') });
      } else if (error.status === 408 || error.status === 504) {
        toast({ variant: 'destructive', title: t('osCommandsFailed'), description: t('osCommandsTimeout') });
      } else {
        toast({ variant: 'destructive', title: t('osCommandsFailed'), description: error.detail ?? t('osCommandsError') });
      }
    },
  });

  // Handler para descargar archivo
  const handleDownloadFile = async (file: DownloadableFile) => {
    setDownloadingFile(file.label);
    try {
      const result = await workstationsApi.sendCommand(
        workstationId,
        'download_file' as 'execute_on_demand',
        { label: file.label, path: file.path }
      );
      // El backend retorna el archivo como descarga — necesitamos el blob
      const downloadUrl = (result as unknown as { download_url?: string })?.download_url;
      if (downloadUrl) {
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = `${file.label.replace(/[^a-zA-Z0-9]/g, '_')}.zip`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      }
      toast({ title: t('osFilesDownloading'), description: file.label });
    } catch (error: unknown) {
      const err = error as { detail?: string };
      toast({ variant: 'destructive', title: t('osFilesFailed'), description: err?.detail ?? t('osFilesError') });
    } finally {
      setDownloadingFile(null);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    toast({ title: t('osCommandsCopied') });
  };

  // Loading state
  if (isLoading) {
    return (
      <div className="space-y-2">
        <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
          <div className="flex items-center gap-1.5">
            <Terminal className="w-3.5 h-3.5" />
            {t('osCommandsSection')}
          </div>
        </h3>
        <div className="animate-pulse space-y-2">
          <div className="h-10 bg-gray-100 rounded-lg" />
          <div className="h-10 bg-gray-100 rounded-lg" />
        </div>
      </div>
    );
  }

  const commands = data?.commands ?? [];
  const files = data?.files ?? [];

  // Sin comandos ni archivos
  if (commands.length === 0 && files.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wide">
        <div className="flex items-center gap-1.5">
          <Terminal className="w-3.5 h-3.5" />
          {t('osCommandsSection')}
        </div>
      </h3>

      {/* Comandos remotos */}
      {commands.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-gray-500 font-medium">{t('osCommandsSubtitle')}</p>
          {commands.map((cmd) => (
            <div
              key={cmd.label}
              className="flex items-center justify-between p-3 bg-gray-50 border border-gray-100 rounded-lg"
            >
              <div className="flex-1 min-w-0 mr-3">
                <p className="text-sm font-medium text-gray-900 truncate">{cmd.label}</p>
                <p className="text-xs text-gray-500 font-mono truncate">{cmd.command}</p>
              </div>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!isOnline || executeMutation.isPending}
                        onClick={() => executeMutation.mutate(cmd)}
                        className="shrink-0"
                      >
                        {executeMutation.isPending ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Play className="w-3.5 h-3.5 mr-1.5" />
                        )}
                        {t('osCommandsRun')}
                      </Button>
                    </span>
                  </TooltipTrigger>
                  {!isOnline && (
                    <TooltipContent>
                      <div className="flex items-center gap-1.5">
                        <WifiOff className="w-3.5 h-3.5" />
                        {t('wsOfflineTooltip')}
                      </div>
                    </TooltipContent>
                  )}
                </Tooltip>
              </TooltipProvider>
            </div>
          ))}
        </div>
      )}

      {/* Archivos descargables */}
      {files.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-gray-500 font-medium">{t('osFilesSubtitle')}</p>
          {files.map((file) => (
            <div
              key={file.label}
              className="flex items-center justify-between p-3 bg-gray-50 border border-gray-100 rounded-lg"
            >
              <div className="flex-1 min-w-0 mr-3">
                <p className="text-sm font-medium text-gray-900 truncate">{file.label}</p>
                <p className="text-xs text-gray-500 font-mono truncate">{file.path}</p>
              </div>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!isOnline || downloadingFile === file.label}
                        onClick={() => handleDownloadFile(file)}
                        className="shrink-0"
                      >
                        {downloadingFile === file.label ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Download className="w-3.5 h-3.5 mr-1.5" />
                        )}
                        {t('osFilesDownload')}
                      </Button>
                    </span>
                  </TooltipTrigger>
                  {!isOnline && (
                    <TooltipContent>
                      <div className="flex items-center gap-1.5">
                        <WifiOff className="w-3.5 h-3.5" />
                        {t('wsOfflineTooltip')}
                      </div>
                    </TooltipContent>
                  )}
                </Tooltip>
              </TooltipProvider>
            </div>
          ))}
        </div>
      )}

      {/* Dialog de resultado de comando */}
      <Dialog open={!!commandOutput} onOpenChange={(open) => !open && setCommandOutput(null)}>
        <DialogContent className="max-w-2xl max-h-[80vh]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Terminal className="w-4 h-4" />
              {commandOutput?.label}
            </DialogTitle>
            <DialogDescription>{t('osCommandsOutputDesc')}</DialogDescription>
          </DialogHeader>
          <div className="relative">
            <pre className="bg-gray-900 text-green-400 p-4 rounded-lg text-xs font-mono overflow-auto max-h-[50vh] whitespace-pre-wrap">
              {commandOutput?.stdout || t('osCommandsNoOutput')}
            </pre>
            <Button
              variant="ghost"
              size="sm"
              className="absolute top-2 right-2 h-7 w-7 p-0 text-gray-400 hover:text-white"
              onClick={() => commandOutput && copyToClipboard(commandOutput.stdout)}
              title={tCommon('copy')}
            >
              <Copy className="w-3.5 h-3.5" />
            </Button>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCommandOutput(null)}>
              {tCommon('close')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
