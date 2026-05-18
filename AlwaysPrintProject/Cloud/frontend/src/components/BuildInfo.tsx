'use client'

import { useEffect, useState } from 'react'
import { apiClient } from '@/lib/api'

export function BuildInfo() {
  const [backendTag, setBackendTag] = useState<string>('...')
  const frontendTag = process.env.NEXT_PUBLIC_BUILD_TAG || 'dev'

  useEffect(() => {
    apiClient.get('/version').then((r) => {
      setBackendTag(r.data?.build_tag || 'dev')
    }).catch(() => {
      setBackendTag('—')
    })
  }, [])

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
