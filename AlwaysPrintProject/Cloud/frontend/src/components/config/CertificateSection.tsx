/**
 * Sección de Certificado Digital ECDSA.
 * Muestra el estado del certificado de la organización y permite
 * generar o renovar el par de claves ECDSA para firma de configuraciones.
 */

'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { ShieldCheck, ShieldOff, RefreshCw, ExternalLink, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useToast } from '@/hooks/use-toast'
import { useUserTimezone } from '@/hooks/useUserTimezone'
import { formatDateWithTimezone } from '@/lib/dateUtils'
import { apiClient } from '@/lib/api'

/** Respuesta del endpoint GET /organizations/{org_id}/certificate/info */
interface CertificateInfo {
  has_certificate: boolean
  cert_version: number | null
  cert_url: string | null
  expires_at: string | null
}

/** Respuesta del endpoint POST generate/rotate */
interface CertificateActionResponse {
  cert_version: number
  cert_url: string
  expires_at: string
  message: string
  configs_re_signed?: number
}

interface CertificateSectionProps {
  organizationId: string
}

export function CertificateSection({ organizationId }: CertificateSectionProps) {
  const t = useTranslations('orgEdit')
  const tCommon = useTranslations('common')
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const userTimezone = useUserTimezone()

  // Estado para el diálogo de confirmación de rotación
  const [showRotateConfirm, setShowRotateConfirm] = useState(false)

  // Obtener info del certificado
  const { data: certInfo, isLoading } = useQuery<CertificateInfo>({
    queryKey: ['certificate-info', organizationId],
    queryFn: async () => {
      const res = await apiClient.get(`/organizations/${organizationId}/certificate/info`)
      return res.data
    },
    enabled: !!organizationId,
  })

  // Mutación para generar certificado
  const generateMutation = useMutation<CertificateActionResponse>({
    mutationFn: async () => {
      const res = await apiClient.post(`/organizations/${organizationId}/certificate/generate`)
      return res.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['certificate-info', organizationId] })
      toast({
        title: t('certificateGenerateSuccess'),
        description: `v${data.cert_version}`,
      })
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      toast({
        title: tCommon('error'),
        description: err.response?.data?.detail || err.message || 'Error',
        variant: 'destructive',
      })
    },
  })

  // Mutación para renovar certificado
  const rotateMutation = useMutation<CertificateActionResponse>({
    mutationFn: async () => {
      const res = await apiClient.post(`/organizations/${organizationId}/certificate/rotate`)
      return res.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['certificate-info', organizationId] })
      setShowRotateConfirm(false)
      toast({
        title: t('certificateRotateSuccess'),
        description: data.configs_re_signed
          ? t('certificateRotateSuccessDesc', { count: data.configs_re_signed })
          : `v${data.cert_version}`,
      })
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      setShowRotateConfirm(false)
      toast({
        title: tCommon('error'),
        description: err.response?.data?.detail || err.message || 'Error',
        variant: 'destructive',
      })
    },
  })

  // Estado de carga
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-4">
        <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
        <span className="text-sm text-gray-500">{tCommon('loading')}</span>
      </div>
    )
  }

  const hasCertificate = certInfo?.has_certificate ?? false

  return (
    <div className="space-y-4">
      {/* Título de la sección */}
      <div className="flex items-center gap-2">
        {hasCertificate ? (
          <ShieldCheck className="h-5 w-5 text-green-600" />
        ) : (
          <ShieldOff className="h-5 w-5 text-gray-400" />
        )}
        <h3 className="text-sm font-medium text-gray-900">{t('certificateTitle')}</h3>
      </div>

      {/* Estado del certificado */}
      <div className="border rounded-lg p-4 space-y-3">
        {/* Badge de estado */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Label className="text-sm text-gray-600">{t('certificateStatus')}</Label>
            <Badge variant={hasCertificate ? 'default' : 'secondary'} className={hasCertificate ? 'bg-green-100 text-green-800 hover:bg-green-100' : ''}>
              {hasCertificate ? t('certificateGenerated') : t('certificateNotGenerated')}
            </Badge>
          </div>
        </div>

        {/* Detalles del certificado (si existe) */}
        {hasCertificate && certInfo && (
          <div className="space-y-2 text-sm">
            <div className="flex items-center gap-2">
              <span className="text-gray-500">{t('certificateVersion')}:</span>
              <span className="font-mono font-medium">v{certInfo.cert_version}</span>
            </div>
            {certInfo.expires_at && (
              <div className="flex items-center gap-2">
                <span className="text-gray-500">{t('certificateExpiresAt')}:</span>
                <span className="font-medium">{formatDateWithTimezone(certInfo.expires_at, userTimezone)}</span>
              </div>
            )}
            {certInfo.cert_url && (
              <div className="flex items-center gap-2">
                <span className="text-gray-500">{t('certificateUrl')}:</span>
                <a
                  href={certInfo.cert_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:underline flex items-center gap-1 truncate max-w-md"
                >
                  <span className="truncate">{certInfo.cert_url}</span>
                  <ExternalLink className="h-3 w-3 flex-shrink-0" />
                </a>
              </div>
            )}
          </div>
        )}

        {/* Botones de acción */}
        <div className="flex items-center gap-2 pt-2 border-t border-gray-100">
          {!hasCertificate ? (
            <Button
              size="sm"
              onClick={() => generateMutation.mutate()}
              disabled={generateMutation.isPending}
            >
              {generateMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              <ShieldCheck className="mr-2 h-4 w-4" />
              {t('certificateGenerate')}
            </Button>
          ) : (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowRotateConfirm(true)}
              disabled={rotateMutation.isPending}
            >
              {rotateMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              <RefreshCw className="mr-2 h-4 w-4" />
              {t('certificateRotate')}
            </Button>
          )}
        </div>
      </div>

      {/* Diálogo de confirmación para rotación */}
      <Dialog open={showRotateConfirm} onOpenChange={setShowRotateConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('certificateRotateConfirm')}</DialogTitle>
            <DialogDescription>
              {t('certificateRotateDescription')}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowRotateConfirm(false)} disabled={rotateMutation.isPending}>
              {tCommon('cancel')}
            </Button>
            <Button
              onClick={() => rotateMutation.mutate()}
              disabled={rotateMutation.isPending}
            >
              {rotateMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('certificateRotate')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
