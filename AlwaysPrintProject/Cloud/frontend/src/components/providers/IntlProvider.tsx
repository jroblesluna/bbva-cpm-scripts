'use client'

import { NextIntlClientProvider } from 'next-intl'
import { useAuth } from '@/hooks/useAuth'
import enMessages from '../../../messages/en.json'
import esMessages from '../../../messages/es.json'
import { useEffect, useState } from 'react'

const messages = { en: enMessages, es: esMessages } as const
type Locale = 'en' | 'es'

function getBrowserLocale(): Locale {
  if (typeof window === 'undefined') return 'en'
  const lang = navigator.language.split('-')[0].toLowerCase()
  return lang === 'es' ? 'es' : 'en'
}

export function IntlProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  const [browserLocale, setBrowserLocale] = useState<Locale>('en')

  useEffect(() => {
    setBrowserLocale(getBrowserLocale())
  }, [])

  const locale: Locale = (user?.language as Locale) ?? browserLocale

  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  return (
    <NextIntlClientProvider locale={locale} messages={messages[locale]}>
      {children}
    </NextIntlClientProvider>
  )
}
