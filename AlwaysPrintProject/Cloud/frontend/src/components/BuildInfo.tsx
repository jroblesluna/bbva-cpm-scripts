'use client'

import { useEffect, useState } from 'react'
import { Globe, Server } from 'lucide-react'
import { apiClient } from '@/lib/api'

interface BuildInfoProps {
  compact?: boolean
}

/**
 * Componente que muestra la versión del frontend y backend.
 * En modo compact se renderiza inline (para el header).
 */
export function BuildInfo({ compact = false }: BuildInfoProps) {
  const [backendTag, setBackendTag] = useState<string>('...')
  const frontendTag = process.env.NEXT_PUBLIC_BUILD_TAG || 'dev'

  useEffect(() => {
    apiClient.get('/version').then((r) => {
      setBackendTag(r.data?.build_tag || 'dev')
    }).catch(() => {
      setBackendTag('—')
    })
  }, [])

  // Versión compacta para el header (alineada debajo del logo)
  if (compact) {
    return (
      <div className="flex items-center gap-2 mt-1.5">
        <div className="inline-flex items-center gap-1 rounded-md bg-blue-50 px-2 py-0.5 text-[11px] font-mono text-blue-700 ring-1 ring-inset ring-blue-200">
          <Globe className="w-3 h-3 flex-shrink-0" />
          <span>{frontendTag.slice(0, 8)}</span>
        </div>
        <div className="inline-flex items-center gap-1 rounded-md bg-purple-50 px-2 py-0.5 text-[11px] font-mono text-purple-700 ring-1 ring-inset ring-purple-200">
          <Server className="w-3 h-3 flex-shrink-0" />
          <span>{backendTag.slice(0, 8)}</span>
        </div>
      </div>
    )
  }

  // Versión completa para sidebar footer
  return (
    <div className="px-3 py-2 mt-1">
      <div className="rounded-md bg-gray-950 px-3 py-2 font-mono text-[10px] leading-relaxed">
        <div className="flex items-center gap-1.5 text-gray-400">
          <span className="text-blue-400">◈</span>
          <span className="text-gray-500">fe:</span>
          <span className="text-blue-300 tracking-wide">{frontendTag}</span>
        </div>
        <div className="flex items-center gap-1.5 text-gray-400">
          <span className="text-emerald-400">◈</span>
          <span className="text-gray-500">be:</span>
          <span className="text-emerald-300 tracking-wide">{backendTag}</span>
        </div>
      </div>
    </div>
  )
}
