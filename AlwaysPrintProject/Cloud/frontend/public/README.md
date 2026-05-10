# Carpeta Public - Archivos Estáticos

Esta carpeta contiene archivos estáticos que se sirven directamente desde la raíz del sitio.

## Favicon

El archivo `favicon.svg` es el ícono que aparece en la pestaña del navegador.

### Cómo reemplazar el favicon:

1. **Opción 1: Usar tu propio favicon.svg**
   - Reemplaza el archivo `public/favicon.svg` con tu propio archivo SVG
   - El archivo debe ser un SVG válido
   - Tamaño recomendado: 32x32 o 64x64 píxeles

2. **Opción 2: Usar favicon.ico**
   - Coloca tu archivo `favicon.ico` en esta carpeta
   - Actualiza `src/app/layout.tsx`:
     ```typescript
     icons: {
       icon: '/favicon.ico',
     }
     ```

3. **Opción 3: Múltiples tamaños**
   ```typescript
   icons: {
     icon: [
       { url: '/favicon-16x16.png', sizes: '16x16', type: 'image/png' },
       { url: '/favicon-32x32.png', sizes: '32x32', type: 'image/png' },
     ],
     apple: '/apple-touch-icon.png',
   }
   ```

### Formatos soportados:
- `.ico` - Formato clásico (recomendado para compatibilidad)
- `.svg` - Formato vectorial (moderno, escalable)
- `.png` - Formato raster (común)

### Después de cambiar el favicon:
1. Reinicia el servidor de desarrollo si está corriendo
2. Limpia la caché del navegador (Ctrl+Shift+R o Cmd+Shift+R)
3. El nuevo favicon debería aparecer en la pestaña del navegador
