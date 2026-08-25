/**
 * Página de configuración global del sistema.
 * Solo visible para administradores.
 * La configuración por organización se gestiona desde la página de edición de cada organización.
 */

'use client';

import { useState } from 'react';
import { useAuth } from '@/hooks/useAuth';
import { useTranslations } from 'next-intl';
import { Shield, FileSpreadsheet, Database } from 'lucide-react';
import { SyncInventorySection } from '@/components/config/SyncInventorySection';
import { SslCertificateSection } from '@/components/config/SslCertificateSection';
import { BackupSection } from '@/components/admin/BackupSection';

type TabKey = 'certificate' | 'sync' | 'backup';

interface TabDef {
  key: TabKey;
  labelKey: string;
  icon: React.ComponentType<{ className?: string }>;
}

const TABS: TabDef[] = [
  { key: 'certificate', labelKey: 'tabCertificate', icon: Shield },
  { key: 'sync', labelKey: 'tabSync', icon: FileSpreadsheet },
  { key: 'backup', labelKey: 'tabBackup', icon: Database },
];

export default function ConfigPage() {
  const { isAdmin } = useAuth();
  const t = useTranslations('config');
  const [activeTab, setActiveTab] = useState<TabKey>('certificate');

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

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex gap-1 overflow-x-auto -mb-px" aria-label="Tabs">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-2 px-4 py-3 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'border-blue-600 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              <tab.icon className="h-4 w-4" />
              {t(tab.labelKey as any)}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      {activeTab === 'certificate' && <SslCertificateSection />}
      {activeTab === 'sync' && <SyncInventorySection />}
      {activeTab === 'backup' && <BackupSection />}
    </div>
  );
}
