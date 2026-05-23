/**
 * Componente para visualizar el resultado de un análisis de log.
 *
 * Renderiza el Markdown del análisis LLM con formato adecuado y muestra
 * metadata del análisis: fecha, ruta de procesamiento, tamaño del log,
 * duración del procesamiento y nombre del archivo original.
 */

'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Calendar, Clock, FileText, HardDrive, Route } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { useTranslations } from 'next-intl';
import type { LogAnalysisResponse } from '@/types';

interface LogAnalysisResultProps {
  analysis: LogAnalysisResponse;
  className?: string;
}

/**
 * Formatea bytes a una representación legible (KB, MB).
 */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

/**
 * Formatea milisegundos a una representación legible (ms, s, min).
 */
function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = ((ms % 60000) / 1000).toFixed(0);
  return `${minutes} min ${seconds} s`;
}

export function LogAnalysisResult({ analysis, className = '' }: LogAnalysisResultProps) {
  const t = useTranslations('logAnalysis');

  return (
    <div className={`space-y-4 ${className}`}>
      {/* Metadata del análisis */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-medium">
            {t('metadataTitle')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <MetadataItem
              icon={<Calendar className="h-4 w-4 text-gray-500" />}
              label={t('analysisDate')}
              value={analysis.analysis_date}
            />
            <MetadataItem
              icon={<Route className="h-4 w-4 text-gray-500" />}
              label={t('processingPath')}
              value={
                <Badge
                  variant={analysis.processing_path === 'direct' ? 'secondary' : 'default'}
                >
                  {analysis.processing_path === 'direct'
                    ? t('processingPathDirect')
                    : t('processingPathStructural')}
                </Badge>
              }
            />
            <MetadataItem
              icon={<HardDrive className="h-4 w-4 text-gray-500" />}
              label={t('logSize')}
              value={formatBytes(analysis.log_size_bytes)}
            />
            <MetadataItem
              icon={<Clock className="h-4 w-4 text-gray-500" />}
              label={t('processingDuration')}
              value={formatDuration(analysis.processing_duration_ms)}
            />
            <MetadataItem
              icon={<FileText className="h-4 w-4 text-gray-500" />}
              label={t('originalFilename')}
              value={analysis.original_filename}
            />
          </div>
        </CardContent>
      </Card>

      {/* Contenido del análisis en Markdown */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-medium">
            {t('resultTitle')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {analysis.analysis_text ? (
            <div className="prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-li:text-gray-700 prose-strong:text-gray-900 prose-table:text-sm prose-th:bg-gray-50 prose-th:p-2 prose-td:p-2 prose-th:border prose-td:border prose-th:border-gray-200 prose-td:border-gray-200">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {analysis.analysis_text}
              </ReactMarkdown>
            </div>
          ) : (
            <p className="text-sm text-gray-500 italic">
              {t('noAnalysisText')}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * Componente interno para mostrar un item de metadata con ícono y label.
 */
function MetadataItem({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-2">
      <div className="mt-0.5">{icon}</div>
      <div className="min-w-0">
        <p className="text-xs text-gray-500">{label}</p>
        <div className="text-sm font-medium text-gray-900 truncate">
          {value}
        </div>
      </div>
    </div>
  );
}
