/**
 * Indicador visual de sesión de vista remota activa.
 * Se muestra como un icono pequeño de "ojo" cuando una workstation
 * tiene una sesión de remote view activa.
 */

'use client';

import { Eye } from 'lucide-react';
import { useTranslations } from 'next-intl';

interface RemoteViewIndicatorProps {
  /** Tamaño del icono en píxeles (default: 14) */
  size?: number;
  /** Clase CSS adicional */
  className?: string;
}

export function RemoteViewIndicator({ size = 14, className = '' }: RemoteViewIndicatorProps) {
  const t = useTranslations('remoteView');

  return (
    <span
      title={t('activeSession')}
      className={`inline-flex items-center justify-center text-indigo-600 ${className}`}
    >
      <Eye style={{ width: size, height: size }} />
    </span>
  );
}
