'use client'

import { InfoWindow } from '@react-google-maps/api'
import { useTranslations } from 'next-intl'

interface VlanGeoData {
  id: string
  name: string
  organization_id: string
  organization_name: string
  address: string
  latitude: number
  longitude: number
  location_image_url?: string | null
  ws_total: number
  ws_online: number
  ws_offline: number
  ws_contingency: number
}

interface MarkerInfoWindowProps {
  vlan: VlanGeoData
  onClose: () => void
}

/**
 * Popup de información que se muestra al hacer click en un marker del mapa.
 * Muestra nombre, dirección, imagen (opcional) y estadísticas de workstations.
 */
export function MarkerInfoWindow({ vlan, onClose }: MarkerInfoWindowProps) {
  const t = useTranslations('map')

  return (
    <InfoWindow
      position={{ lat: vlan.latitude, lng: vlan.longitude }}
      onCloseClick={onClose}
    >
      <div className="max-w-[280px] p-1">
        {/* Nombre de la VLAN */}
        <h3 className="text-sm font-bold text-gray-900">{vlan.name}</h3>

        {/* Dirección */}
        <p className="text-xs text-gray-500 mt-0.5">{vlan.address}</p>

        {/* Imagen de la ubicación (si existe) */}
        {vlan.location_image_url && (
          <img
            src={vlan.location_image_url}
            alt={vlan.name}
            className="mt-2 max-h-24 w-full rounded object-cover"
          />
        )}

        {/* Stats con badges de color */}
        <div className="mt-2 flex flex-wrap gap-1.5">
          <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
            {vlan.ws_total} {t('wsTotal')}
          </span>
          <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
            {vlan.ws_online} {t('wsOnline')}
          </span>
          <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
            {vlan.ws_offline} {t('wsOffline')}
          </span>
          <span className="inline-flex items-center rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-700">
            {vlan.ws_contingency} {t('wsContingency')}
          </span>
        </div>
      </div>
    </InfoWindow>
  )
}
