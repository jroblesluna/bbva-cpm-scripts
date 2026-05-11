/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  images: {
    domains: [],
  },
  output: 'standalone',
  outputFileTracingRoot: require('path').join(__dirname, '../../..'),
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
