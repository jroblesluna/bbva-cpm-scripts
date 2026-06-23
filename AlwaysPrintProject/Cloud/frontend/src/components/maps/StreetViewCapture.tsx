'use client'

/**
 * Componente de captura interactiva de Street View.
 * El usuario navega el panorama outdoor y puede capturar la vista actual.
 * Filtra photospheres de interior usando source=OUTDOOR.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { Camera, X } from 'lucide-react'

interface StreetViewCaptureProps {
  latitude: number
  longitude: number
  onCapture: (heading: number, pitch: number, fov: number, panoId: string) => void
  onClose: () => void
}

export function StreetViewCapture({ latitude, longitude, onCapture, onClose }: StreetViewCaptureProps) {
  const t = useTranslations('map')
  const containerRef = useRef<HTMLDivElement>(null)
  const panoramaRef = useRef<google.maps.StreetViewPanorama | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'no-coverage'>('loading')

  useEffect(() => {
    if (!containerRef.current || !window.google?.maps) return

    // Buscar panorama OUTDOOR más cercano a las coordenadas
    const sv = new google.maps.StreetViewService()
    sv.getPanorama(
      {
        location: { lat: latitude, lng: longitude },
        radius: 100,
        source: google.maps.StreetViewSource.OUTDOOR,
        preference: google.maps.StreetViewPreference.NEAREST,
      },
      (data, svStatus) => {
        if (svStatus !== google.maps.StreetViewStatus.OK || !data?.location?.latLng) {
          setStatus('no-coverage')
          return
        }

        // Calcular heading inicial mirando hacia las coordenadas del edificio
        const svLat = data.location.latLng.lat()
        const svLng = data.location.latLng.lng()
        const heading = google.maps.geometry?.spherical?.computeHeading(
          new google.maps.LatLng(svLat, svLng),
          new google.maps.LatLng(latitude, longitude)
        ) ?? 0

        // Crear panorama con el pano_id outdoor encontrado
        const panorama = new google.maps.StreetViewPanorama(containerRef.current!, {
          pano: data.location.pano,
          pov: { heading, pitch: 5 },
          zoom: 1,
          addressControl: false,
          fullscreenControl: false,
          motionTracking: false,
          motionTrackingControl: false,
          linksControl: true, // Permitir navegación por la calle
          panControl: true,
          zoomControl: true,
        })

        panoramaRef.current = panorama
        setStatus('ready')
      }
    )
  }, [latitude, longitude])

  const handleCapture = useCallback(() => {
    if (!panoramaRef.current) return
    const pov = panoramaRef.current.getPov()
    const zoom = panoramaRef.current.getZoom()
    const pano = panoramaRef.current.getPano()
    // FOV para Street View Static API:
    // El JS viewer con zoom=1 muestra ~90° horizontal en un contenedor 3:2
    // zoom=0 → 180°, zoom=1 → 90°, zoom=2 → 45°, zoom=3 → 22.5°
    // Fórmula estándar de Google: fov = 180 / 2^zoom
    const fov = Math.min(120, Math.max(10, 180 / Math.pow(2, zoom)))
    onCapture(pov.heading, pov.pitch, fov, pano)
  }, [onCapture])

  if (status === 'no-coverage') {
    return (
      <div className="border rounded-lg p-6 text-center bg-gray-50">
        <p className="text-sm text-gray-500">{t('streetViewNoAvailable')}</p>
        <Button variant="ghost" size="sm" onClick={onClose} className="mt-2">
          <X className="h-4 w-4 mr-1" />
          {t('close')}
        </Button>
      </div>
    )
  }

  return (
    <div className="border rounded-lg overflow-hidden">
      {/* Visor interactivo de Street View — aspect ratio 3:2 (igual que imagen guardada 600x400) */}
      <div ref={containerRef} className="w-full bg-gray-100" style={{ aspectRatio: '3/2' }}>
        {status === 'loading' && (
          <div className="w-full h-full flex items-center justify-center">
            <p className="text-sm text-gray-400">{t('streetViewLoading')}</p>
          </div>
        )}
      </div>

      {/* Controles */}
      <div className="flex items-center justify-between p-2 bg-gray-50 border-t">
        <p className="text-xs text-gray-500">{t('streetViewDrag')}</p>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} className="h-8">
            <X className="h-4 w-4 mr-1" />
            {t('close')}
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={handleCapture}
            className="h-8"
            disabled={status !== 'ready'}
          >
            <Camera className="h-4 w-4 mr-1" />
            {t('streetViewCapture')}
          </Button>
        </div>
      </div>
    </div>
  )
}
