/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  images: {
    domains: [],
  },
  // Configuración para producción
  output: 'standalone',
}

module.exports = nextConfig
