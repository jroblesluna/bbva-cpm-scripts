/**
 * Componente para mostrar el estado de sincronización de configuración de acciones
 * de una workstation.
 */

import { CheckCircle2, XCircle, AlertCircle, Loader2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

interface ActionConfigSyncStatusProps {
  workstationId: string;
  localHash?: string | null;
  cloudHash?: string | null;
  hasConfig?: boolean;
  isLoading?: boolean;
}

export function ActionConfigSyncStatus({
  workstationId,
  localHash,
  cloudHash,
  hasConfig = false,
  isLoading = false,
}: ActionConfigSyncStatusProps) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span>Verificando...</span>
      </div>
    );
  }
  
  // Sin configuración en Cloud
  if (!cloudHash) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center gap-2">
              <AlertCircle className="h-4 w-4 text-muted-foreground" />
              <Badge variant="secondary">Sin Config</Badge>
            </div>
          </TooltipTrigger>
          <TooltipContent>
            <p>No hay configuración activa en la organización</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }
  
  // Workstation sin configuración local
  if (!hasConfig || !localHash) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center gap-2">
              <AlertCircle className="h-4 w-4 text-yellow-600" />
              <Badge variant="outline" className="border-yellow-600 text-yellow-600">
                Pendiente
              </Badge>
            </div>
          </TooltipTrigger>
          <TooltipContent>
            <p>La workstation aún no ha descargado la configuración</p>
            <p className="text-xs text-muted-foreground mt-1">
              Hash esperado: {cloudHash}
            </p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }
  
  // Comparar hashes
  const isSynced = localHash === cloudHash;
  
  if (isSynced) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-green-600" />
              <Badge variant="outline" className="border-green-600 text-green-600">
                Sincronizada
              </Badge>
            </div>
          </TooltipTrigger>
          <TooltipContent>
            <p>Configuración sincronizada correctamente</p>
            <p className="text-xs text-muted-foreground mt-1">
              Hash: {localHash}
            </p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }
  
  // Desincronizada
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="flex items-center gap-2">
            <XCircle className="h-4 w-4 text-red-600" />
            <Badge variant="outline" className="border-red-600 text-red-600">
              Desincronizada
            </Badge>
          </div>
        </TooltipTrigger>
        <TooltipContent>
          <p>La configuración local no coincide con la de Cloud</p>
          <div className="text-xs text-muted-foreground mt-1 space-y-1">
            <p>Hash local: {localHash}</p>
            <p>Hash Cloud: {cloudHash}</p>
          </div>
          <p className="text-xs mt-2">
            La workstation descargará la nueva configuración en la próxima conexión
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/**
 * Componente compacto para mostrar solo el ícono de estado.
 */
export function ActionConfigSyncIcon({
  localHash,
  cloudHash,
  hasConfig = false,
  className = '',
}: {
  localHash?: string | null;
  cloudHash?: string | null;
  hasConfig?: boolean;
  className?: string;
}) {
  if (!cloudHash) {
    return <AlertCircle className={`h-4 w-4 text-muted-foreground ${className}`} />;
  }
  
  if (!hasConfig || !localHash) {
    return <AlertCircle className={`h-4 w-4 text-yellow-600 ${className}`} />;
  }
  
  const isSynced = localHash === cloudHash;
  
  if (isSynced) {
    return <CheckCircle2 className={`h-4 w-4 text-green-600 ${className}`} />;
  }
  
  return <XCircle className={`h-4 w-4 text-red-600 ${className}`} />;
}
