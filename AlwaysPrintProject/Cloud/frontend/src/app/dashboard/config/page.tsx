/**
 * Página de configuración global del sistema.
 * Solo visible para administradores.
 * La configuración por organización se gestiona desde la página de edición de cada organización.
 */

'use client';

import { useAuth } from '@/hooks/useAuth';
import { useTranslations } from 'next-intl';
import { SyncInventorySection } from '@/components/config/SyncInventorySection';
import { SslCertificateSection } from '@/components/config/SslCertificateSection';

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

      {/* Certificado SSL */}
      <SslCertificateSection />

      {/* Sincronización de Inventario */}
      <SyncInventorySection />
    </div>
  );
}
