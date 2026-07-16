/**
 * Componente de selección con búsqueda paginada.
 *
 * Renderiza un <select> nativo normal, pero al activar el modo búsqueda
 * muestra un dropdown custom con input de búsqueda, listado paginado
 * y controles Prev/Next (similar a un combobox).
 */

'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { Search, ChevronLeft, ChevronRight, X, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'

export interface SearchableSelectOption {
  value: string
  label: string
}

interface SearchableSelectProps {
  /** Valor seleccionado actualmente */
  value: string | undefined
  /** Callback al seleccionar una opción */
  onChange: (value: string | undefined) => void
  /** Texto cuando no hay selección (primera opción) */
  placeholder: string
  /** Función para cargar opciones desde backend (paginada) */
  loadOptions: (params: { search: string; skip: number; limit: number }) => Promise<{ options: SearchableSelectOption[]; total: number }>
  /** Texto del placeholder del input de búsqueda */
  searchPlaceholder?: string
  /** Texto para Prev */
  prevLabel?: string
  /** Texto para Next */
  nextLabel?: string
  /** Items por página en modo búsqueda */
  pageSize?: number
  /** Label del botón de búsqueda (tooltip) */
  searchButtonTitle?: string
  /** Clase CSS adicional para el contenedor */
  className?: string
  /** Deshabilitado */
  disabled?: boolean
  /** Label seleccionado actualmente (para mostrar cuando se seleccionó en modo search) */
  selectedLabel?: string
}

export function SearchableSelect({
  value,
  onChange,
  placeholder,
  loadOptions,
  searchPlaceholder = 'Search...',
  prevLabel = '← Prev',
  nextLabel = 'Next →',
  pageSize = 5,
  searchButtonTitle = 'Search',
  className = '',
  disabled = false,
  selectedLabel,
}: SearchableSelectProps) {
  const [searchMode, setSearchMode] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [options, setOptions] = useState<SearchableSelectOption[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [simpleOptions, setSimpleOptions] = useState<SearchableSelectOption[]>([])
  const [simpleLoading, setSimpleLoading] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const totalPages = Math.ceil(total / pageSize)

  // Cargar opciones para el select simple (primera página sin búsqueda)
  useEffect(() => {
    if (searchMode) return
    const loadSimple = async () => {
      setSimpleLoading(true)
      try {
        const result = await loadOptions({ search: '', skip: 0, limit: 0 })
        setSimpleOptions(result.options)
      } catch (error) {
        console.error('Error cargando opciones:', error)
      } finally {
        setSimpleLoading(false)
      }
    }
    loadSimple()
  }, [searchMode]) // eslint-disable-line react-hooks/exhaustive-deps

  // Cargar opciones paginadas en modo búsqueda
  const fetchOptions = useCallback(async (search: string, pageNum: number) => {
    setLoading(true)
    try {
      const skip = (pageNum - 1) * pageSize
      const result = await loadOptions({ search, skip, limit: pageSize })
      setOptions(result.options)
      setTotal(result.total)
    } catch (error) {
      console.error('Error cargando opciones:', error)
    } finally {
      setLoading(false)
    }
  }, [loadOptions, pageSize])

  // Cuando se activa modo búsqueda, cargar primera página
  useEffect(() => {
    if (searchMode) {
      fetchOptions(searchTerm, 1)
      setTimeout(() => searchInputRef.current?.focus(), 100)
    }
  }, [searchMode]) // eslint-disable-line react-hooks/exhaustive-deps

  // Debounce en búsqueda
  useEffect(() => {
    if (!searchMode) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setPage(1)
      fetchOptions(searchTerm, 1)
    }, 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [searchTerm]) // eslint-disable-line react-hooks/exhaustive-deps

  // Cuando cambia la página
  useEffect(() => {
    if (!searchMode) return
    fetchOptions(searchTerm, page)
  }, [page]) // eslint-disable-line react-hooks/exhaustive-deps

  // Cerrar al hacer click fuera
  useEffect(() => {
    if (!searchMode) return
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setSearchMode(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [searchMode])

  const handleSelectOption = (optionValue: string) => {
    onChange(optionValue || undefined)
    setSearchMode(false)
    setSearchTerm('')
    setPage(1)
  }

  if (searchMode) {
    return (
      <div ref={containerRef} className={`relative ${className}`}>
        {/* Input de búsqueda */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            ref={searchInputRef}
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder={searchPlaceholder}
            className="w-full pl-9 pr-8 py-2 border border-blue-500 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
          />
          <button
            type="button"
            onClick={() => { setSearchMode(false); setSearchTerm(''); setPage(1) }}
            className="absolute right-2 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Dropdown con resultados */}
        <div className="absolute z-50 mt-1 w-full bg-white border border-gray-200 rounded-md shadow-lg max-h-64 overflow-hidden">
          {loading ? (
            <div className="flex items-center justify-center py-4">
              <RefreshCw className="h-4 w-4 animate-spin text-gray-400" />
            </div>
          ) : options.length === 0 ? (
            <div className="py-3 px-4 text-sm text-gray-500 text-center">
              {searchTerm ? 'Sin resultados' : 'No hay opciones'}
            </div>
          ) : (
            <>
              {/* Opción "Todas" siempre visible */}
              <button
                type="button"
                onClick={() => handleSelectOption('')}
                className={`w-full text-left px-4 py-2 text-sm hover:bg-gray-100 border-b border-gray-100 ${!value ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-700'}`}
              >
                {placeholder}
              </button>
              {/* Opciones paginadas */}
              <div className="overflow-y-auto max-h-40">
                {options.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => handleSelectOption(option.value)}
                    className={`w-full text-left px-4 py-2 text-sm hover:bg-gray-100 ${value === option.value ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-700'}`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              {/* Paginación */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between px-3 py-2 border-t border-gray-100 bg-gray-50 text-xs">
                  <button
                    type="button"
                    onClick={() => setPage(Math.max(1, page - 1))}
                    disabled={page <= 1}
                    className="text-gray-600 hover:text-gray-900 disabled:text-gray-300 disabled:cursor-not-allowed"
                  >
                    {prevLabel}
                  </button>
                  <span className="text-gray-500">{page} / {totalPages}</span>
                  <button
                    type="button"
                    onClick={() => setPage(Math.min(totalPages, page + 1))}
                    disabled={page >= totalPages}
                    className="text-gray-600 hover:text-gray-900 disabled:text-gray-300 disabled:cursor-not-allowed"
                  >
                    {nextLabel}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    )
  }

  // Modo normal: select nativo + botón de búsqueda, agrupados visualmente como un solo control
  return (
    <div className={`flex ${className}`}>
      <select
        value={value || 'all'}
        onChange={(e) => onChange(e.target.value === 'all' ? undefined : e.target.value)}
        disabled={disabled || simpleLoading}
        className="flex-1 min-w-0 h-[38px] px-3 border border-gray-300 rounded-l-md rounded-r-none border-r-0 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:z-10 text-sm"
      >
        <option value="all">{placeholder}</option>
        {simpleOptions.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setSearchMode(true)}
        disabled={disabled}
        className="h-[38px] w-9 p-0 shrink-0 rounded-l-none focus:z-10"
        title={searchButtonTitle}
      >
        <Search className="h-4 w-4" />
      </Button>
    </div>
  )
}
