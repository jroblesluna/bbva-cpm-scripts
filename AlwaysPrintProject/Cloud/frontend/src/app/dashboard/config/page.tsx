/**
 * Página de configuración global del sistema.
 * Solo visible para administradores.
 * La configuración por organización se gestiona desde la página de edición de cada organización.
 */

'use client';

import { useAuth } from '@/hooks/useAuth';
import { useTranslations } from 'next-intl';
import { Settings } from 'lucide-react';

export default function ConfigPage() {
  const { isAdmin } = useAuth();
  const t = useTranslations('config');

  if (!isAdmin()) {
    return null;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900">{t('systemConfigTitle')}</h1>
        <p className="mt-2 text-gray-600">{t('systemConfigMsg')}</p>
      </div>

      {/* Placeholder */}
      <div className="bg-white rounded-lg shadow p-12 text-center">
        <Settings className="mx-auto h-16 w-16 text-gray-300" />
        <h3 className="mt-4 text-lg font-medium text-gray-900">{t('comingSoon')}</h3>
      </div>
    </div>
  );
}
