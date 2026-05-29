'use client'

import { useEffect } from 'react'
import { useToast } from '@/hooks/use-toast'
import { X, AlertTriangle, AlertCircle, CheckCircle } from 'lucide-react'

export function Toaster() {
  const { toasts, dismiss } = useToast()

  useEffect(() => {
    if (toasts.length === 0) return
    const timer = setTimeout(() => {
      dismiss(toasts[0].id)
    }, 5000)
    return () => clearTimeout(timer)
  }, [toasts, dismiss])

  if (toasts.length === 0) return null

  return (
    <div className="fixed bottom-6 right-6 z-[9999] flex flex-col gap-3 w-full max-w-sm">
      {toasts.map((toast) => {
        const isWarning = toast.variant === 'warning'
        const isDestructive = toast.variant === 'destructive'

        return (
          <div
            key={toast.id}
            className={`
              relative flex items-start gap-3 rounded-lg border px-4 py-3.5 shadow-lg backdrop-blur-sm
              ${isWarning
                ? 'bg-white/80 border-orange-200 text-orange-900'
                : isDestructive
                  ? 'bg-white/80 border-red-200 text-red-900'
                  : 'bg-white/80 border-gray-200 text-gray-900'
              }
            `}
          >
            {/* Barra lateral */}
            <div className={`absolute left-0 top-0 bottom-0 w-[3px] rounded-l-lg ${
              isWarning ? 'bg-orange-400' : isDestructive ? 'bg-red-500' : 'bg-blue-500'
            }`} />

            {/* Icono */}
            <div className="shrink-0 mt-0.5">
              {isWarning
                ? <AlertTriangle className="w-4 h-4 text-orange-500" />
                : isDestructive
                  ? <AlertCircle className="w-4 h-4 text-red-500" />
                  : <CheckCircle className="w-4 h-4 text-blue-500" />
              }
            </div>

            {/* Contenido */}
            <div className="flex-1 min-w-0">
              {toast.title && (
                <p className="font-semibold text-sm">{toast.title}</p>
              )}
              {toast.description && (
                <p className={`text-sm ${toast.title ? 'mt-0.5 opacity-80' : ''}`}>
                  {toast.description}
                </p>
              )}
            </div>

            {/* Cerrar */}
            <button
              onClick={() => dismiss(toast.id)}
              className="shrink-0 opacity-40 hover:opacity-70 transition-opacity"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )
      })}
    </div>
  )
}
