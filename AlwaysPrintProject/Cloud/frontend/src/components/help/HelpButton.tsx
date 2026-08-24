'use client';

import { useTranslations } from 'next-intl';
import {
  HelpCircle,
  Building2,
  Users,
  Network,
  Monitor,
  Package,
  Printer,
  Globe,
  Zap,
  Server,
  Activity,
  MapPin,
  Wifi,
  Eye,
  FileText,
  MessageSquare,
  Download,
  Library,
  BookOpen,
  Settings,
  Database,
  Shield,
  FileSpreadsheet,
  Clock,
  Sparkles,
  Edit,
  Power,
  Terminal,
  Trash2,
  ShieldAlert,
  Cloud,
  Route,
} from 'lucide-react';
import { useAuth } from '@/hooks/useAuth';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';

const FAQ_COUNT = 13;

// Mismos íconos que usa la navegación/páginas del dashboard para cada concepto, de general a específico
const GLOSSARY_ICONS = [
  Building2, // Organización
  Users, // Usuario
  Network, // VLAN
  Monitor, // Workstation
  Package, // AlwaysPrint Tray
  ShieldAlert, // Contingencia
  Cloud, // CPM (Lexmark)
  Printer, // Dispositivo
  Globe, // IP Pendiente
  Route, // CIDR
  Zap, // Acciones Masivas
  Server, // Estado del Sistema
  Activity, // Telemetría
  MapPin, // Mapa de Red
  Wifi, // Conectividad
  Eye, // Vista Remota
  FileText, // Auditoría
  MessageSquare, // Mensajes
  Download, // Actualizaciones Automáticas
  Library, // Base de Conocimiento
  BookOpen, // Documentación
  Settings, // Configuración
  Database, // Backup
  Shield, // Certificado SSL
  FileSpreadsheet, // Sincronización de Inventario
  Clock, // Línea de Tiempo
  FileText, // Log
  Sparkles, // Análisis de Logs
];

// Mismos íconos que las acciones por fila en la tabla de Estaciones (dashboard/workstations/page.tsx)
const ACTION_ICONS = [Eye, Edit, FileText, Power, Terminal, Download, Trash2, ShieldAlert];

export function HelpButton() {
  const { isAuthenticated } = useAuth();
  const t = useTranslations('help');

  if (!isAuthenticated) return null;

  const faqs = Array.from({ length: FAQ_COUNT }, (_, i) => ({
    q: t(`faqQ${i + 1}`),
    a: t(`faqA${i + 1}`),
  }));
  const glossary = GLOSSARY_ICONS.map((Icon, i) => ({
    Icon,
    term: t(`glossaryTerm${i + 1}`),
    def: t(`glossaryDef${i + 1}`),
  }));
  const actionKeys = [
    'actionViewDetails',
    'actionEdit',
    'actionDownloadLog',
    'actionRestartService',
    'actionRestartTray',
    'actionCheckUpdate',
    'actionDelete',
    'actionForcedContingency',
  ] as const;
  const actions = ACTION_ICONS.map((Icon, i) => ({ Icon, label: t(actionKeys[i]) }));

  return (
    <Dialog>
      <DialogTrigger asChild>
        <button
          type="button"
          title={t('buttonLabel')}
          className="fixed bottom-6 right-6 z-40 flex h-11 w-11 items-center justify-center rounded-full bg-gray-900 text-white shadow-lg transition-colors hover:bg-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
        >
          <HelpCircle className="h-5 w-5" />
          <span className="sr-only">{t('buttonLabel')}</span>
        </button>
      </DialogTrigger>
      <DialogContent className="flex h-[780px] max-w-4xl flex-col overflow-hidden">
        <DialogHeader className="shrink-0">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-50">
              <HelpCircle className="h-5 w-5 text-blue-600" />
            </div>
            <div>
              <DialogTitle>{t('title')}</DialogTitle>
              <DialogDescription>{t('description')}</DialogDescription>
            </div>
          </div>
        </DialogHeader>
        <Tabs defaultValue="faq" className="flex min-h-0 flex-1 flex-col">
          <TabsList className="shrink-0">
            <TabsTrigger value="faq">{t('tabFaq')}</TabsTrigger>
            <TabsTrigger value="glossary">{t('tabGlossary')}</TabsTrigger>
          </TabsList>
          <TabsContent value="faq" className="min-h-0 flex-1 overflow-y-auto">
            <Accordion type="single" collapsible className="rounded-lg border border-gray-200 px-4">
              {faqs.map((item, i) => (
                <AccordionItem key={i} value={`faq-${i}`}>
                  <AccordionTrigger>{item.q}</AccordionTrigger>
                  <AccordionContent>{item.a}</AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </TabsContent>
          <TabsContent value="glossary" className="min-h-0 flex-1 space-y-6 overflow-y-auto">
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
                {t('actionsTitle')}
              </p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {actions.map(({ Icon, label }, i) => (
                  <div key={i} className="flex items-center gap-2 rounded-lg border border-gray-200 p-2">
                    <Icon className="h-4 w-4 shrink-0 text-gray-600" />
                    <span className="text-xs text-gray-700">{label}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              {glossary.map(({ Icon, term, def }, i) => (
                <div key={i} className="flex items-start gap-3 rounded-lg border border-gray-200 p-3">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-gray-50">
                    <Icon className="h-4 w-4 text-gray-600" />
                  </div>
                  <div>
                    <p className="font-medium text-gray-900">{term}</p>
                    <p className="text-sm text-gray-600">{def}</p>
                  </div>
                </div>
              ))}
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
