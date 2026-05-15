const path = require('path')

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  images: {
    domains: [],
  },
  output: 'standalone',
  // Fijar el root del workspace para evitar que Next.js infiera incorrectamente
  // cuando hay múltiples package-lock.json en el sistema
  outputFileTracingRoot: path.join(__dirname, './'),
  // Next.js 15 es incompatible con ESLint 9 flat config — desactivar linting integrado.
  // Ejecutar ESLint por separado: npx eslint src/
  eslint: {
    ignoreDuringBuilds: true,
  },
  async rewrites() {
    // En desarrollo, proxy /api/* al backend en localhost:8000
    // En producción nginx hace este proxy directamente
    if (process.env.NODE_ENV === 'development') {
      const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      return [
        {
          source: '/api/:path*',
          destination: `${backendUrl}/api/:path*`,
        },
      ]
    }
    return []
  },
}

module.exports = nextConfig
