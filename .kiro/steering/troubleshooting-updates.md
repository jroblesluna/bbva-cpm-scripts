---
inclusion: auto
description: Guía de diagnóstico para errores de actualización del cliente AlwaysPrint
---

# Troubleshooting: Errores de Actualización del Cliente

## Error 401 en UpdateChecker o UpdateDownloader

Cuando el log del cliente muestra:

```
UpdateChecker: backend retornó código 401 en verificación de actualización. Reintentando en próximo ciclo.
```

o

```
UpdateDownloader: descarga de actualización interrumpida por error de red: ... 401 (Unauthorized)
```

**Causa más probable**: La IP pública de la workstation no está aprobada en el Cloud Manager (sección "IPs Pendientes" / Pending IPs).

### Contexto

Los endpoints `/api/v1/updates/check` y `/api/v1/updates/download` identifican la workstation en este orden:

1. Header `X-Workstation-ID` (solo disponible en builds >= 1.26.819.x)
2. IP pública registrada como autorizada en tabla `public_ips`

Si la workstation corre un build antiguo (sin `X-Workstation-ID`) y su IP pública no está autorizada, ambos endpoints retornan 401.

### Solución

1. Ir a Cloud Manager → Pending IPs
2. Aprobar la IP pública de la workstation
3. Reintentar la actualización (o esperar al próximo ciclo)

### Nota

Builds >= 1.26.819.x incluyen el header `X-Workstation-ID` en ambos requests (check y download), eliminando la dependencia de la IP pública para autenticación. El problema se auto-resuelve una vez que la workstation actualiza a una versión con este fix.
