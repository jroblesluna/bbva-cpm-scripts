'use client'

/**
 * Componente selector multi-select de artículos de conocimiento.
 *
 * Permite seleccionar hasta 10 artículos de la base de conocimiento
 * para asociar a un perfil de debugging. Incluye búsqueda por título
 * y muestra los artículos actualmente asociados como pre-seleccionados.
 */

import { useState, useEffect, useMemo } from 'react'
import { useTranslations } from 'next-intl'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Search, BookOpen, AlertTriangle, Loader2 } from 'lucide-react'
import { getKnowledgeArticles } from '@/lib/api/knowledge-articles'
import type { KnowledgeArticleListItem } from '@/types/knowledge-article'

/** Límite máximo de artículos seleccionables por perfil */
const MAX_ARTICLES = 10

interface KnowledgeArticleSelectorProps {
  /** IDs de artículos actualmente seleccionados/asociados */
  selectedArticleIds: string[]
  /** Callback cuando la selección cambia */
  onChange: (articleIds: string[]) => void
  /** Texto de label opcional (se sobreescribe con i18n si no se pasa) */
  label?: string
}

export function KnowledgeArticleSelector({
  selectedArticleIds,
  onChange,
  label,
}: KnowledgeArticleSelectorProps) {
  const t = useTranslations('knowledgeBase')

  const [articles, setArticles] = useState<KnowledgeArticleListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')

  // Cargar todos los artículos disponibles al montar el componente
  useEffect(() => {
    let cancelled = false

    async function fetchArticles() {
      setLoading(true)
      try {
        const data = await getKnowledgeArticles()
        if (!cancelled) {
          setArticles(data)
        }
      } catch (error) {
        // Error de carga — se muestra lista vacía
        console.error('Error cargando artículos:', error)
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    fetchArticles()
    return () => { cancelled = true }
  }, [])

  // Filtrar artículos por término de búsqueda (por título)
  const filteredArticles = useMemo(() => {
    if (!searchTerm.trim()) return articles
    const term = searchTerm.toLowerCase()
    return articles.filter((article) =>
      article.title.toLowerCase().includes(term)
    )
  }, [articles, searchTerm])

  // Verificar si se alcanzó el límite máximo
  const isMaxReached = selectedArticleIds.length >= MAX_ARTICLES

  // Manejar toggle de un artículo
  const handleToggle = (articleId: string) => {
    const isSelected = selectedArticleIds.includes(articleId)
    if (isSelected) {
      // Remover de la selección
      onChange(selectedArticleIds.filter((id) => id !== articleId))
    } else {
      // Agregar a la selección (si no se excede el límite)
      if (!isMaxReached) {
        onChange([...selectedArticleIds, articleId])
      }
    }
  }

  return (
    <div className="space-y-3">
      {/* Label */}
      <div className="flex items-center justify-between">
        <Label className="flex items-center gap-2">
          <BookOpen className="h-4 w-4" />
          {label ?? t('selectorLabel')}
        </Label>
        <Badge variant="secondary">
          {t('selectedCount', { count: selectedArticleIds.length })}
        </Badge>
      </div>

      {/* Búsqueda */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
        <Input
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder={t('searchPlaceholder')}
          className="pl-9"
        />
      </div>

      {/* Aviso de límite alcanzado */}
      {isMaxReached && (
        <div className="flex items-center gap-2 text-sm text-amber-600 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>{t('maxArticlesWarning', { max: MAX_ARTICLES })}</span>
        </div>
      )}

      {/* Lista de artículos */}
      <div className="border border-gray-200 rounded-md max-h-64 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-6 text-gray-500 text-sm">
            <Loader2 className="h-4 w-4 animate-spin mr-2" />
            {t('loadingArticles')}
          </div>
        ) : filteredArticles.length === 0 ? (
          <div className="py-6 text-center text-sm text-gray-500">
            {t('noResults')}
          </div>
        ) : (
          <ul className="divide-y divide-gray-100" role="listbox" aria-multiselectable="true">
            {filteredArticles.map((article) => {
              const isSelected = selectedArticleIds.includes(article.id)
              const isDisabled = !isSelected && isMaxReached

              return (
                <li
                  key={article.id}
                  role="option"
                  aria-selected={isSelected}
                  className={`flex items-start gap-3 px-3 py-2.5 cursor-pointer transition-colors ${
                    isSelected
                      ? 'bg-blue-50'
                      : isDisabled
                        ? 'opacity-50 cursor-not-allowed bg-gray-50'
                        : 'hover:bg-gray-50'
                  }`}
                  onClick={() => !isDisabled && handleToggle(article.id)}
                >
                  <Checkbox
                    checked={isSelected}
                    disabled={isDisabled}
                    onChange={() => handleToggle(article.id)}
                    className="mt-0.5"
                    aria-label={article.title}
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {article.title}
                    </p>
                    <p className="text-xs text-gray-500 line-clamp-2">
                      {article.description}
                    </p>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
