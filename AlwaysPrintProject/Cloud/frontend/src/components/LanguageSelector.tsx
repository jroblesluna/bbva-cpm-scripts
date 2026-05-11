'use client'

import { useTranslations } from 'next-intl'
import { useAuth } from '@/hooks/useAuth'

export function LanguageSelector() {
  const t = useTranslations('language')
  const { user, updateLanguage } = useAuth()

  if (!user) return null

  return (
    <select
      value={user.language ?? 'en'}
      onChange={(e) => updateLanguage(e.target.value as 'en' | 'es')}
      className="text-sm bg-transparent border border-gray-600 rounded px-2 py-1 text-gray-300 hover:border-gray-400 cursor-pointer focus:outline-none focus:border-blue-400"
      title={t('label')}
    >
      <option value="en">{t('en')}</option>
      <option value="es">{t('es')}</option>
    </select>
  )
}
