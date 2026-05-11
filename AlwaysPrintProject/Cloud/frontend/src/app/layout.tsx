import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import { QueryProvider } from '@/components/providers/query-provider'
import { AuthProvider } from '@/components/providers/AuthProvider'
import { IntlProvider } from '@/components/providers/IntlProvider'

const inter = Inter({ subsets: ['latin'] })

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
      <body className={inter.className}>
        <QueryProvider>
          <AuthProvider>
            <IntlProvider>
              {children}
            </IntlProvider>
          </AuthProvider>
        </QueryProvider>
      </body>
    </html>
  )
}
