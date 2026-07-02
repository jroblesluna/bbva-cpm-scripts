/**
 * Sección de Certificado Digital ECDSA.
 * Muestra el estado del certificado de la organización y permite
 * generar o renovar el par de claves ECDSA para firma de configuraciones.
 */

'use client'

import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { ShieldCheck, ShieldOff, RefreshCw, ExternalLink, Loader2, Timer, PauseCircle, PlayCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
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
  signature_paused: boolean
  signature_paused_until: string | null
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
  // Estado para el diálogo de pausa de firma
  const [showPauseConfirm, setShowPauseConfirm] = useState(false)
  const [pauseDurationMinutes, setPauseDurationMinutes] = useState(30)
  // Countdown de pausa activa
  const [remainingSeconds, setRemainingSeconds] = useState(0)

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

  // Mutación para pausar firma
  const pauseMutation = useMutation({
    mutationFn: async (params: { pause: boolean; duration_minutes?: number }) => {
      const res = await apiClient.put(
        `/organizations/${organizationId}/certificate/signature-pause`,
        null,
        { params: { pause: params.pause, duration_minutes: params.duration_minutes || 30 } }
      )
      return res.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['certificate-info', organizationId] })
      setShowPauseConfirm(false)
      toast({
        title: data.paused ? t('signaturePauseActivated') : t('signaturePauseDeactivated'),
        description: data.message,
      })
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      setShowPauseConfirm(false)
      toast({
        title: tCommon('error'),
        description: err.response?.data?.detail || err.message || 'Error',
        variant: 'destructive',
      })
    },
  })

  // Countdown para pausa activa
  useEffect(() => {
    if (!certInfo?.signature_paused || !certInfo?.signature_paused_until) {
      setRemainingSeconds(0)
      return
    }

    const calculateRemaining = () => {
      const until = new Date(certInfo.signature_paused_until + 'Z').getTime()
      const now = Date.now()
      const remaining = Math.max(0, Math.floor((until - now) / 1000))
      setRemainingSeconds(remaining)
    }

    calculateRemaining()
    const interval = setInterval(calculateRemaining, 1000)
    return () => clearInterval(interval)
  }, [certInfo?.signature_paused, certInfo?.signature_paused_until])

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

      {/* === Sección de Pausa de Firma (Modo Compatibilidad) === */}
      {hasCertificate && (
        <div className="border rounded-lg p-4 space-y-3">
          <div className="flex items-center gap-2">
            <PauseCircle className="h-4 w-4 text-orange-500" />
            <h4 className="text-sm font-medium text-gray-900">{t('signaturePauseTitle')}</h4>
          </div>
          <p className="text-xs text-gray-500">{t('signaturePauseDescription')}</p>

          {/* Estado actual de la pausa */}
          {certInfo?.signature_paused && remainingSeconds > 0 ? (
            <Alert className="border-orange-200 bg-orange-50">
              <Timer className="h-4 w-4 text-orange-600" />
              <AlertDescription className="flex items-center justify-between w-full">
                <span className="text-sm text-orange-900">
                  {t('signaturePauseActive', {
                    minutes: String(Math.ceil(remainingSeconds / 60))
                  })}
                </span>
                <Badge variant="outline" className="font-mono text-xs text-orange-700 border-orange-300">
                  {Math.floor(remainingSeconds / 60)}:{String(remainingSeconds % 60).padStart(2, '0')}
                </Badge>
              </AlertDescription>
            </Alert>
          ) : null}

          {/* Botón de acción */}
          <div className="flex items-center gap-2">
            {certInfo?.signature_paused && remainingSeconds > 0 ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() => pauseMutation.mutate({ pause: false })}
                disabled={pauseMutation.isPending}
              >
                {pauseMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                <PlayCircle className="mr-2 h-4 w-4" />
                {t('signaturePauseRestore')}
              </Button>
            ) : (
              <Button
                size="sm"
                variant="outline"
                className="border-orange-300 text-orange-700 hover:bg-orange-50"
                onClick={() => setShowPauseConfirm(true)}
                disabled={pauseMutation.isPending}
              >
                <PauseCircle className="mr-2 h-4 w-4" />
                {t('signaturePauseActivate')}
              </Button>
            )}
          </div>
        </div>
      )}

      {/* Diálogo de confirmación para pausa de firma */}
      <Dialog open={showPauseConfirm} onOpenChange={setShowPauseConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('signaturePauseConfirmTitle')}</DialogTitle>
            <DialogDescription>
              {t('signaturePauseConfirmDesc')}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <Alert className="border-orange-200 bg-orange-50">
              <AlertDescription className="text-xs text-orange-800">
                {t('signaturePauseWarning')}
              </AlertDescription>
            </Alert>
            <div className="space-y-2">
              <Label>{t('signaturePauseDuration')}</Label>
              <Input
                type="number"
                min={5}
                max={120}
                value={pauseDurationMinutes}
                onChange={(e) => setPauseDurationMinutes(Math.min(120, Math.max(5, parseInt(e.target.value) || 30)))}
              />
              <p className="text-xs text-gray-500">{t('signaturePauseDurationHelp')}</p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowPauseConfirm(false)} disabled={pauseMutation.isPending}>
              {tCommon('cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => pauseMutation.mutate({ pause: true, duration_minutes: pauseDurationMinutes })}
              disabled={pauseMutation.isPending}
            >
              {pauseMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('signaturePauseConfirmBtn')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
