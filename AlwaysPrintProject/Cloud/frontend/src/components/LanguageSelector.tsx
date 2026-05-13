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
      className="w-full text-sm font-bold bg-white border border-gray-300 rounded-md px-3 py-1.5 text-gray-700 hover:border-gray-400 cursor-pointer focus:outline-none focus:ring-2 focus:ring-blue-500"
      title={t('label')}
    >
      <option value="en">{t('en')}</option>
      <option value="es">{t('es')}</option>
    </select>
  )
}
