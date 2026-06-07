import type { Metadata } from 'next'
import localFont from 'next/font/local'
import './globals.css'
import { QueryProvider } from '@/components/providers/query-provider'
import { AuthProvider } from '@/components/providers/AuthProvider'
import { IntlProvider } from '@/components/providers/IntlProvider'
import { Toaster } from '@/components/ui/toaster'

// Inter variable font cargada localmente — evita dependencia de Google Fonts en build time
const inter = localFont({
  src: './fonts/inter-var.woff2',
  variable: '--font-inter',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'AlwaysPrint Cloud Manager',
  description: 'Sistema de gestión centralizada de estaciones AlwaysPrint para impresión corporativa',
  icons: {
    icon: '/favicon.ico',
    apple: '/alwaysprint-logo.png',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={inter.className} suppressHydrationWarning>
        <QueryProvider>
          <AuthProvider>
            <IntlProvider>
              {children}
              <Toaster />
            </IntlProvider>
          </AuthProvider>
        </QueryProvider>
      </body>
    </html>
  )
}
