/**
 * Componente de historial de análisis de logs de una workstation.
 *
 * Muestra una lista paginada de análisis previos con opción de ver
 * el detalle de cada uno al hacer clic.
 */

'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { logAnalysisApi } from '@/lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  FileText,
  ChevronLeft,
  ChevronRight,
  Clock,
  HardDrive,
  Route,
  AlertCircle,
  X,
} from 'lucide-react';
import { formatDateWithTimezone } from '@/lib/dateUtils';
import { useUserTimezone } from '@/hooks/useUserTimezone';
import type { LogAnalysisResponse } from '@/types';

const PAGE_SIZE = 20;

interface LogAnalysisHistoryProps {
  workstationId: string;
}

/**
 * Formatea bytes a una representación legible (KB, MB).
 */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Formatea duración en milisegundos a una representación legible.
 */
function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  return `${(ms / 60000).toFixed(1)} min`;
}

export function LogAnalysisHistory({ workstationId }: LogAnalysisHistoryProps) {
  const t = useTranslations('logAnalysis');
  const tCommon = useTranslations('common');
  const userTimezone = useUserTimezone();
  const [page, setPage] = useState(1);
  const [selectedAnalysis, setSelectedAnalysis] = useState<LogAnalysisResponse | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ['log-analyses', workstationId, page],
    queryFn: () => logAnalysisApi.list(workstationId, { page, page_size: PAGE_SIZE }),
  });

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;
  const paginationStart = (page - 1) * PAGE_SIZE + 1;
  const paginationEnd = data ? Math.min(page * PAGE_SIZE, data.total) : 0;

  // Vista de detalle de un análisis individual
  if (selectedAnalysis) {
    return (
      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <FileText className="w-4 h-4" />
            {t('analysisDetail')}
          </CardTitle>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelectedAnalysis(null)}
            className="h-8 w-8 p-0"
            title={tCommon('back')}
          >
            <X className="w-4 h-4" />
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Metadata del análisis */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div className="flex items-center gap-1.5 text-gray-600">
              <Clock className="w-3.5 h-3.5" />
              <span>{formatDateWithTimezone(selectedAnalysis.created_at, userTimezone)}</span>
            </div>
            <div className="flex items-center gap-1.5 text-gray-600">
              <Route className="w-3.5 h-3.5" />
              <Badge variant="outline" className="text-xs">
                {selectedAnalysis.processing_path === 'direct' ? t('pathDirect') : t('pathStructural')}
              </Badge>
            </div>
            <div className="flex items-center gap-1.5 text-gray-600">
              <HardDrive className="w-3.5 h-3.5" />
              <span>{formatBytes(selectedAnalysis.log_size_bytes)}</span>
            </div>
            <div className="flex items-center gap-1.5 text-gray-600">
              <Clock className="w-3.5 h-3.5" />
              <span>{formatDuration(selectedAnalysis.processing_duration_ms)}</span>
            </div>
          </div>

          {/* Texto del análisis (renderizado como Markdown) */}
          <div className="border rounded-lg p-4 bg-gray-50 max-h-[400px] overflow-y-auto">
            <div className="prose prose-sm max-w-none text-gray-800 prose-headings:text-gray-900 prose-p:text-gray-700 prose-li:text-gray-700 prose-strong:text-gray-900">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {selectedAnalysis.analysis_text}
              </ReactMarkdown>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  // Estado de carga
  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <FileText className="w-4 h-4" />
            {t('title')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-10 bg-gray-100 rounded" />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  // Estado de error
  if (error) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <FileText className="w-4 h-4" />
            {t('title')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 text-sm text-red-600">
            <AlertCircle className="w-4 h-4" />
            <span>{t('loadError')}</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  // Sin datos
  if (!data || data.items.length === 0) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <FileText className="w-4 h-4" />
            {t('title')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-gray-500">{t('empty')}</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <FileText className="w-4 h-4" />
          {t('title')}
          <Badge variant="secondary" className="ml-1 text-xs">
            {data.total}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">{t('colDate')}</TableHead>
                <TableHead className="text-xs">{t('colPath')}</TableHead>
                <TableHead className="text-xs">{t('colSize')}</TableHead>
                <TableHead className="text-xs">{t('colDuration')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((analysis) => (
                <TableRow
                  key={analysis.id}
                  className="cursor-pointer"
                  onClick={() => setSelectedAnalysis(analysis)}
                >
                  <TableCell className="text-sm">
                    {formatDateWithTimezone(analysis.created_at, userTimezone)}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-xs">
                      {analysis.processing_path === 'direct' ? t('pathDirect') : t('pathStructural')}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm text-gray-600">
                    {formatBytes(analysis.log_size_bytes)}
                  </TableCell>
                  <TableCell className="text-sm text-gray-600">
                    {formatDuration(analysis.processing_duration_ms)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        {/* Paginación */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between pt-2 border-t">
            <p className="text-xs text-gray-500">
              {t('pagination', { start: paginationStart, end: paginationEnd, total: data.total })}
            </p>
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage(page - 1)}
                disabled={page <= 1}
                className="h-7 w-7 p-0"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </Button>
              <span className="text-xs text-gray-600 px-2">
                {t('pageNumber', { page })}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage(page + 1)}
                disabled={page >= totalPages}
                className="h-7 w-7 p-0"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
