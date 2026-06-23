'use client'

/**
 * Componente de captura interactiva de Street View.
 * El usuario navega el panorama y puede capturar la vista actual como imagen.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { Camera, X } from 'lucide-react'

interface StreetViewCaptureProps {
  latitude: number
  longitude: number
  onCapture: (heading: number, pitch: number, fov: number) => void
  onClose: () => void
}

export function StreetViewCapture({ latitude, longitude, onCapture, onClose }: StreetViewCaptureProps) {
  const t = useTranslations('map')
  const containerRef = useRef<HTMLDivElement>(null)
  const panoramaRef = useRef<google.maps.StreetViewPanorama | null>(null)
  const [hasStreetView, setHasStreetView] = useState(true)

  useEffect(() => {
    if (!containerRef.current || !window.google?.maps) return

    const panorama = new google.maps.StreetViewPanorama(containerRef.current, {
      position: { lat: latitude, lng: longitude },
      pov: { heading: 0, pitch: 0 },
      zoom: 1,
      addressControl: false,
      fullscreenControl: false,
      motionTracking: false,
      motionTrackingControl: false,
    })

    // Verificar si hay cobertura
    const sv = new google.maps.StreetViewService()
    sv.getPanorama(
      { location: { lat: latitude, lng: longitude }, radius: 50, source: google.maps.StreetViewSource.OUTDOOR },
      (data, status) => {
        if (status !== google.maps.StreetViewStatus.OK) {
          setHasStreetView(false)
        }
      }
    )

    panoramaRef.current = panorama
  }, [latitude, longitude])

  const handleCapture = useCallback(() => {
    if (!panoramaRef.current) return
    const pov = panoramaRef.current.getPov()
    const zoom = panoramaRef.current.getZoom()
    // Convertir zoom de Street View a FOV (field of view)
    // zoom 0 = 180°, zoom 1 = 90°, zoom 2 = 45°, etc.
    const fov = 180 / Math.pow(2, zoom)
    onCapture(pov.heading, pov.pitch, fov)
  }, [onCapture])

  if (!hasStreetView) {
    return (
      <div className="border rounded-lg p-6 text-center bg-gray-50">
        <p className="text-sm text-gray-500">{t('streetViewNoAvailable')}</p>
        <Button variant="ghost" size="sm" onClick={onClose} className="mt-2">
          {t('close')}
        </Button>
      </div>
    )
  }

  return (
    <div className="border rounded-lg overflow-hidden">
      {/* Visor interactivo de Street View */}
      <div ref={containerRef} className="w-full h-64" />

      {/* Controles */}
      <div className="flex items-center justify-between p-2 bg-gray-50 border-t">
        <p className="text-xs text-gray-500">{t('streetViewDrag')}</p>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} className="h-8">
            <X className="h-4 w-4 mr-1" />
            {t('close')}
          </Button>
          <Button variant="default" size="sm" onClick={handleCapture} className="h-8">
            <Camera className="h-4 w-4 mr-1" />
            {t('streetViewCapture')}
          </Button>
        </div>
      </div>
    </div>
  )
}
