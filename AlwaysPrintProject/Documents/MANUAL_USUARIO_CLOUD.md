---
título: Manual de Usuario — AlwaysPrint Cloud Manager
versión: 1.0.0
fecha: Mayo 2026
producto: AlwaysPrint Cloud Manager (Web)
empresa: Inversiones On Line SAC — Robles.AI
clasificación: Confidencial — Uso interno
---

# Manual de Usuario — AlwaysPrint Cloud Manager

**Versión**: 1.0.0  
**Fecha**: Mayo 2026  
**Producto**: AlwaysPrint Cloud Manager (Dashboard Web)  
**Empresa**: Inversiones On Line SAC — Robles.AI  
**Clasificación**: Confidencial — Uso interno

---

## Historial de Versiones

| Versión | Fecha | Autor | Descripción del cambio |
|---------|-------|-------|------------------------|
| 1.0.0 | Mayo 2026 | Robles.AI | Versión inicial del manual |
| — | — | — | — |

---

## Tabla de Contenidos

1. [Introducción](#1-introducción)
2. [Descripción General del Sistema](#2-descripción-general-del-sistema)
3. [Requisitos del Sistema](#3-requisitos-del-sistema)
4. [Instalación y Despliegue](#4-instalación-y-despliegue)
5. [Primeros Pasos / Inicio Rápido](#5-primeros-pasos--inicio-rápido)
6. [Interfaz de Usuario](#6-interfaz-de-usuario)
7. [Configuración](#7-configuración)
8. [Uso Diario / Operación Normal](#8-uso-diario--operación-normal)
9. [Funciones Avanzadas](#9-funciones-avanzadas)
10. [Estados del Sistema](#10-estados-del-sistema)
11. [Seguridad y Permisos](#11-seguridad-y-permisos)
12. [Solución de Problemas](#12-solución-de-problemas)
13. [Preguntas Frecuentes](#13-preguntas-frecuentes)
14. [Glosario](#14-glosario)
15. [Soporte y Contacto](#15-soporte-y-contacto)

---

## Convenciones del Documento

| Icono | Significado |
|-------|-------------|
| ℹ️ | Información adicional o nota aclaratoria |
| ⚠️ | Advertencia — acción que requiere precaución |
| 🚫 | Prohibición — acción que NO debe realizarse |
| ✅ | Confirmación o paso completado exitosamente |
| 💡 | Consejo o buena práctica |

---

## 1. Introducción

### 1.1 Propósito del Documento

Este manual describe el uso del **AlwaysPrint Cloud Manager**, la plataforma web de gestión centralizada para el sistema de contingencia de impresión AlwaysPrint. Está dirigido a:

- **Administradores TI** que gestionan las workstations, monitorean el estado del sistema y configuración
- **Administradores globales** que gestionan organizaciones y usuarios

### 1.2 Alcance

Cubre la plataforma web (dashboard) accesible en `https://alwaysprint.apps.iol.pe`. Para el software instalado en workstations, consultar el *Manual de Usuario — AlwaysPrint Client*.

### 1.3 Audiencia

| Perfil | Rol en el sistema | Secciones relevantes |
|--------|-------------------|---------------------|
| Administrador TI | OPERATOR | 5, 6, 8, 10, 12, 13 |
| Administrador global | ADMIN (multi-org) | Todas + sección 9 |
| Solo lectura | READONLY | 5, 6, 8, 10, 13 |

---

## 2. Descripción General del Sistema

### 2.1 ¿Qué es AlwaysPrint Cloud Manager?

AlwaysPrint Cloud Manager (APCM) es una plataforma SaaS multi-tenant que permite:

- **Monitorear** el estado de todas las workstations en tiempo real
- **Configurar** parámetros de forma centralizada (por organización, por VLAN, por workstation)
- **Gestionar** contingencias de impresión
- **Ejecutar** acciones administrativas remotas
- **Analizar** telemetría y logs de impresión
- **Administrar** organizaciones, usuarios, VLANs y dispositivos

### 2.2 Arquitectura de Alto Nivel

```
┌──────────────────────────────────────────────────────────────┐
│  NAVEGADOR WEB (Administrador)                                │
│  https://alwaysprint.apps.iol.pe                             │
└──────────────────────┬───────────────────────────────────────┘
                       │ HTTPS + WebSocket (WSS)
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  AWS Cloud (us-west-2)                                        │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐     │
│  │  Nginx (SSL/TLS 1.3, Let's Encrypt)                 │     │
│  │  ├── /* → Frontend (Next.js 15, puerto 3000)        │     │
│  │  ├── /api/* → Backend (FastAPI, puerto 8000)        │     │
│  │  └── /ws/* → Backend (WebSocket)                    │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ Backend  │  │ Frontend │  │  Redis   │  │   RDS    │    │
│  │ FastAPI  │  │ Next.js  │  │  Cache   │  │ Postgres │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
└──────────────────────────────────────────────────────────────┘
                       ▲
                       │ HTTPS + WebSocket (WSS)
                       │
┌──────────────────────┴───────────────────────────────────────┐
│  WORKSTATIONS (AlwaysPrintTray)                               │
│  N estaciones conectadas vía proxy corporativo               │
└──────────────────────────────────────────────────────────────┘
```

### 2.3 Modelo Multi-Tenant

El sistema soporta múltiples organizaciones (tenants) con aislamiento completo:

- Cada organización tiene sus propias workstations, VLANs, configuración y usuarios
- Los datos de una organización nunca son visibles para otra
- Un administrador global puede gestionar múltiples organizaciones

---

## 3. Requisitos del Sistema

### 3.1 Requisitos del Navegador

| Navegador | Versión mínima | Soporte |
|-----------|---------------|---------|
| Google Chrome | 90+ | ✅ Recomendado |
| Microsoft Edge | 90+ | ✅ Soportado |
| Mozilla Firefox | 90+ | ✅ Soportado |
| Safari | 15+ | ✅ Soportado |

### 3.2 Requisitos de Red

| Recurso | Protocolo | Puerto |
|---------|-----------|--------|
| Dashboard web | HTTPS | 443 |
| WebSocket (tiempo real) | WSS | 443 |

### 3.3 URL de Acceso

| Entorno | URL |
|---------|-----|
| Producción | https://alwaysprint.apps.iol.pe |
| Desarrollo | https://alwaysprint.dev.iol.pe |

---

## 4. Instalación y Despliegue

### 4.1 Para Usuarios del Dashboard

No se requiere instalación. El dashboard es una aplicación web accesible desde cualquier navegador moderno.



## 5. Primeros Pasos / Inicio Rápido

### 5.1 Setup Inicial (Primera vez)

Si es la primera vez que se accede al sistema:

1. Navegar a `https://alwaysprint.apps.iol.pe/setup`
2. Crear el primer usuario administrador global:
   - Email
   - Contraseña (mínimo 8 caracteres)
   - Nombre de la organización
3. El sistema crea la organización y el usuario
4. Redirige al login

### 5.2 Login

1. Navegar a `https://alwaysprint.apps.iol.pe/login`
2. Ingresar email y contraseña
3. Click en "Iniciar sesión"
4. Se redirige al Dashboard principal

### 5.3 Autorizar Primera Workstation

Para que una workstation se conecte:

1. Instalar AlwaysPrint Client en la workstation
2. La workstation intenta conectarse → su IP pública queda como "pendiente"
3. En el dashboard: ir a **Operario → IPs Pendientes**
4. Localizar la IP nueva
5. Asignarla a la organización correspondiente
6. La workstation se conecta automáticamente en los próximos segundos

### 5.4 Flujo Rápido Post-Setup

```
Setup → Login → Autorizar IPs → Ver workstations en Dashboard → Configurar
```

---

## 6. Interfaz de Usuario

### 6.1 Estructura General del Dashboard

```
┌─────────────────────────────────────────────────────────────┐
│  BARRA SUPERIOR                                              │
│  Logo | Nombre de organización | Idioma (ES/EN) | Usuario ▼ │
├──────────────┬──────────────────────────────────────────────┤
│              │                                               │
│  SIDEBAR     │  CONTENIDO PRINCIPAL                         │
│              │                                               │
│  Dashboard   │  (varía según la página seleccionada)        │
│  Workstations│                                               │
│  VLANs       │                                               │
│  Dispositivos│                                               │
│  Configuración│                                              │
│  Mensajes    │                                               │
│  Telemetría  │                                               │
│  Conectividad│                                               │
│  Auditoría   │                                               │
│              │                                               │
│  ── Admin ── │                                               │
│  Organizaciones│                                             │
│  Usuarios    │                                               │
│  IPs Pendientes│                                             │
│  Action Configs│                                             │
│  Actualizaciones│                                            │
│              │                                               │
└──────────────┴──────────────────────────────────────────────┘
```

### 6.2 Navegación Principal

| Sección | Icono | Función |
|---------|-------|---------|
| Dashboard | 📊 | Resumen general, estadísticas, alertas |
| Workstations | 🖥️ | Lista y gestión de estaciones |
| VLANs | 🌐 | Agrupaciones de red |
| Dispositivos | 🖨️ | Impresoras y dispositivos |
| Configuración | ⚙️ | Config de organización y por workstation |
| Mensajes | 💬 | Envío de mensajes a workstations |
| Telemetría | 📈 | Métricas de impresión |
| Conectividad | 🔗 | Resultados de checks de red |
| Auditoría | 📋 | Logs de acciones administrativas |

### 6.3 Sección Admin (solo ADMIN)

| Sección | Función |
|---------|---------|
| Organizaciones | CRUD de organizaciones/tenants |
| Usuarios | Gestión de usuarios administradores |
| IPs Pendientes | Autorización de IPs públicas nuevas |
| Action Configs | Gestión de configuraciones de acciones remotas |
| Actualizaciones | Gestión de versiones del cliente |

### 6.4 Patrones de UI Comunes

- **Vista dual**: Todas las listas ofrecen vista de tarjetas (mobile) y tabla (desktop)
- **Toggle de vista**: Botones LayoutGrid / List en la barra de filtros
- **Filtros**: Búsqueda por texto, filtros por estado, organización, VLAN
- **Paginación**: Controles "Anterior / Siguiente" con indicador "Mostrando X-Y de Z"
- **Acciones**: Botones icon-only con tooltip en cada item
- **Polling**: Los datos se actualizan automáticamente cada 10 segundos

---

## 7. Configuración

### 7.1 Jerarquía de Configuración

La configuración sigue una jerarquía con herencia:

```
Organización (Config de Organización)
    │
    ├── VLAN Config (sobrescribe Organización para workstations de esa VLAN)
    │
    └── Workstation Config (sobrescribe VLAN y Organización para esa workstation)
```

**Regla de resolución**: Workstation > VLAN > Organización

### 7.2 Configuración de Organización

Accesible desde **Configuración** en el sidebar. Aplica a todas las workstations de la organización.

| Parámetro | Descripción | Ejemplo |
|-----------|-------------|---------|
| Cola corporativa | Nombre de la cola de impresión | LexmarkBBVA |
| Dominios bootstrap | Dominios para descubrimiento | apps.iol.pe |
| Telemetría habilitada | Enviar datos de uso | Sí/No |
| Intervalo de telemetría | Frecuencia de envío (segundos) | 300 |
| Checks de conectividad | Lista de verificaciones de red | HTTP, TCP, Ping, DNS |
| IPs de búsqueda | IPs de impresoras a buscar | 118.64.40.x |
| Rangos de búsqueda | Rangos de red para escaneo | 118.64.40.0/24 |

### 7.3 Configuración por Workstation

Accesible desde **Workstations → [seleccionar] → Configuración**. Sobrescribe la configuración de organización para esa workstation específica.

### 7.4 Configuración de Acciones (.alwaysconfig)

Accesible desde **Admin → Action Configs**. Define acciones administrativas que se ejecutan automáticamente en las workstations.

#### Flujo de gestión:
1. Crear/subir archivo JSON de configuración
2. Validar estructura (el sistema valida automáticamente)
3. Activar la configuración
4. Las workstations descargan automáticamente la nueva configuración
5. El Service ejecuta las acciones según los triggers definidos

#### Niveles de scope:
| Scope | Aplica a | Ejemplo |
|-------|----------|---------|
| org | Toda la organización | Limpieza general de cachés |
| vlan | Una VLAN específica | Configuración de impresoras de esa red |
| workstation | Una workstation específica | Configuración particular |

### 7.5 Configuración de Organización

Accesible desde **Admin → Organizaciones → [editar]**.

| Parámetro | Descripción |
|-----------|-------------|
| Nombre | Nombre de la organización |
| Zona horaria | Para mostrar fechas correctamente |
| Idioma | Idioma por defecto (es/en) |
| Contingencia forzada | Forzar contingencia en TODAS las workstations |
| Auto-actualización | Permitir actualizaciones automáticas del client |
| Versión objetivo | Versión específica para actualizar |
| Action config mandatory | Si la config de org es obligatoria para todos |
| Modelo LLM | Modelo de IA para análisis de logs |

---

## 8. Uso Diario / Operación Normal

### 8.1 Monitoreo del Dashboard Principal

Al ingresar al dashboard se muestra:

| Sección | Información |
|---------|-------------|
| Tarjetas de estadísticas | Total workstations, online, offline, en contingencia, VLANs |
| IPs pendientes (si hay) | Alerta de IPs nuevas que requieren autorización |
| Distribución por cuenta | Desglose por organización (administrador global) |
| Última actualización | Timestamp del último refresh (cada 10s) |

💡 **Acción diaria**: Verificar que no hay workstations offline inesperadas ni contingencias activas.

### 8.2 Gestión de Workstations

#### Ver lista de workstations:
1. Ir a **Workstations** en el sidebar
2. Usar filtros: búsqueda por IP/hostname, estado (online/offline), contingencia
3. Alternar entre vista de tarjetas y tabla

#### Información por workstation:
| Campo | Descripción |
|-------|-------------|
| IP privada | Identificador único de la estación |
| Hostname | Nombre del equipo Windows |
| Estado | Online / Offline |
| Contingencia | Activa / Inactiva |
| Versión Tray | Versión del software instalado |
| VLAN | Red asignada |
| Última conexión | Timestamp del último heartbeat |
| Usuario actual | Usuario con sesión activa |

#### Comandos remotos:
| Comando | Efecto |
|---------|--------|
| Restart Service | Reinicia AlwaysPrintService en la workstation |
| Restart Tray | Reinicia AlwaysPrintTray |
| Check Update | Fuerza verificación de actualización |
| Forzar contingencia | Activa contingencia manualmente |
| Descargar logs | Descarga logs remotos de la workstation |
| Analizar logs (IA) | Envía logs a LLM para análisis inteligente |

### 8.3 Gestión de VLANs

1. Ir a **VLANs** en el sidebar
2. Crear VLAN: nombre + CIDR (ej: "Piso 3", "192.168.3.0/24")
3. Las workstations se asignan automáticamente por su CIDR reportado
4. Cada VLAN puede tener configuración específica

### 8.4 Gestión de Dispositivos (Impresoras)

1. Ir a **Dispositivos** en el sidebar
2. Crear dispositivo: nombre, IP, puerto, VLAN
3. Asignar como impresora predeterminada a workstations

### 8.5 Envío de Mensajes

1. Ir a **Mensajes** en el sidebar
2. Crear mensaje: contenido, tipo de destino (broadcast, VLAN, workstation)
3. El mensaje se envía vía WebSocket a las workstations conectadas
4. El Tray muestra el mensaje como notificación al usuario

### 8.6 Revisión de Auditoría

1. Ir a **Auditoría** en el sidebar
2. Filtrar por fecha, usuario, tipo de acción
3. Ver detalle de cada acción (quién, qué, cuándo, desde dónde)

---

## 9. Funciones Avanzadas

### 9.1 Contingencia Forzada

#### A nivel de organización:
1. Ir a **Admin → Organizaciones → [editar]**
2. Activar "Contingencia forzada"
3. TODAS las workstations de esa organización entran en contingencia
4. Útil para mantenimiento programado de CPM

#### A nivel de workstation individual:
1. Ir a **Workstations → [seleccionar]**
2. Click en "Forzar contingencia"
3. Solo esa workstation entra en contingencia
4. Útil para pruebas o problemas localizados

⚠️ **Precaución**: La contingencia forzada hace bypass del sistema de producción CPM. Usar solo cuando sea necesario.

### 9.2 Configuración de Acciones Administrativas

#### Crear nueva configuración:
1. Ir a **Admin → Action Configs**
2. Click en "Crear configuración"
3. Subir archivo JSON `.alwaysconfig` o escribir directamente
4. El sistema valida la estructura JSON en tiempo real
5. Seleccionar scope (org, vlan, workstation)
6. Guardar

#### Estructura del archivo .alwaysconfig:
```json
{
  "version": "1.0",
  "name": "Nombre_Descriptivo",
  "triggers": [
    {
      "event": "OnTrayLaunched",
      "actions": [
        {
          "type": "NombreAccion",
          "parameters": { ... }
        }
      ]
    }
  ]
}
```

#### Activar/Desactivar:
- Solo una configuración puede estar activa por scope
- Al activar una nueva, la anterior se desactiva automáticamente
- Las workstations descargan la nueva configuración en el próximo check

#### Verificar propagación:
- El hash SHA256 (8 chars) permite verificar que la workstation tiene la versión correcta
- En el dashboard se puede ver qué hash tiene cada workstation

### 9.3 Análisis de Logs con IA

1. Ir a **Workstations → [seleccionar] → Logs**
2. Click en "Analizar con IA"
3. El sistema envía los logs al modelo LLM configurado
4. Recibe un análisis con:
   - Problemas detectados
   - Posibles causas
   - Recomendaciones de acción

ℹ️ Soporta AWS Bedrock y OpenAI. El modelo se configura por organización.

### 9.4 Auto-Actualización del Cliente

#### Configurar:
1. Ir a **Admin → Organizaciones → [editar]**
2. Activar "Auto-actualización"
3. Opcionalmente, establecer "Versión objetivo" (si no, usa la última)

#### Gestionar versiones:
1. Ir a **Admin → Actualizaciones**
2. Ver versiones disponibles en S3
3. Las workstations verifican periódicamente y se actualizan

### 9.5 Gestión Multi-Organización (Administrador Global)

#### Crear organización:
1. Ir a **Admin → Organizaciones**
2. Click en "Crear organización"
3. Completar: nombre, zona horaria, idioma
4. La organización queda lista para recibir workstations

#### Asignar IPs públicas:
1. Ir a **Admin → IPs Pendientes**
2. Ver IPs que intentaron conectarse sin autorización
3. Asignar cada IP a la organización correspondiente
4. Las workstations de esa IP se conectan automáticamente

### 9.6 Gestión de Usuarios

#### Roles disponibles:

| Rol | Nombre en UI | Permisos |
|-----|-------------|----------|
| ADMIN | Administrador Global | Acceso completo a su organización + sección Admin |
| OPERATOR | Administrador TI | Monitoreo y comandos, sin configuración avanzada |
| READONLY | Solo lectura | Solo visualización, sin acciones |

#### Crear usuario:
1. Ir a **Admin → Usuarios**
2. Click en "Crear usuario"
3. Completar: email, rol, contraseña temporal
4. El usuario recibe acceso al dashboard

### 9.7 Recuperación de Contraseña

1. En la página de login, click en "¿Olvidaste tu contraseña?"
2. Ingresar email registrado
3. Se envía un enlace de reset vía email (AWS SES)
4. El enlace es válido por 1 hora
5. Establecer nueva contraseña

---

## 10. Estados del Sistema

### 10.1 Estados de Workstation

| Estado | Indicador visual | Significado |
|--------|-----------------|-------------|
| Online | 🟢 Verde | Conectada y reportando |
| Offline | 🔴 Rojo | Sin comunicación (>timeout) |
| Contingencia activa | 🟡 Amarillo | Modo contingencia (automática o forzada) |
| Pendiente | ⚪ Gris | IP no autorizada aún |

### 10.2 Estados de Conexión WebSocket

| Estado | Efecto en dashboard |
|--------|-------------------|
| Conectado | Actualizaciones en tiempo real |
| Desconectado | Fallback a polling cada 10 segundos |
| Reconectando | Intento automático de reconexión |

### 10.3 Estados de Configuración

| Estado | Significado |
|--------|-------------|
| Sincronizada | Workstation tiene la última configuración |
| Pendiente | Configuración nueva aún no descargada |
| Error | Error al aplicar configuración |

### 10.4 Estados de IP Pública

| Estado | Significado | Acción requerida |
|--------|-------------|-----------------|
| Autorizada | IP asignada a una organización | Ninguna |
| Pendiente | IP nueva, sin autorizar | Admin debe asignar a organización |
| Rechazada | IP bloqueada intencionalmente | Ninguna (contactar admin si es error) |

---

## 11. Seguridad y Permisos

### 11.1 Autenticación

| Mecanismo | Aplica a | Detalle |
|-----------|----------|---------|
| JWT Bearer Token | Administradores (dashboard) | Login con email/password |
| IP pública autorizada | Workstations | Sin credenciales, auth por IP |
| Password reset | Admins | Token de 1 hora vía email |

### 11.2 Roles y Permisos

| Permiso | Admin Global | Admin TI | Solo lectura |
|---------|-------------|----------|--------------|
| Ver dashboard | ✅ | ✅ | ✅ |
| Ver workstations | ✅ | ✅ | ✅ |
| Enviar comandos remotos | ✅ | ✅ | 🚫 |
| Forzar contingencia | ✅ | ✅ | 🚫 |
| Modificar configuración | ✅ | 🚫 | 🚫 |
| Gestionar VLANs | ✅ | 🚫 | 🚫 |
| Gestionar dispositivos | ✅ | 🚫 | 🚫 |
| Gestionar usuarios | ✅ | 🚫 | 🚫 |
| Gestionar organizaciones | ✅ | 🚫 | 🚫 |
| Autorizar IPs | ✅ | 🚫 | 🚫 |
| Gestionar action configs | ✅ | 🚫 | 🚫 |
| Ver auditoría | ✅ | ✅ | ✅ |

### 11.3 Aislamiento Multi-Tenant

- Cada usuario pertenece a una organización
- Solo puede ver datos de su organización
- Las queries de BD siempre filtran por `organization_id`
- Un administrador global puede ver múltiples organizaciones

### 11.4 Seguridad de la Plataforma

| Capa | Mecanismo |
|------|-----------|
| Transporte | TLS 1.3 (Let's Encrypt) |
| Aplicación | Rate limiting, security headers |
| Datos | Passwords con bcrypt, secretos en AWS Secrets Manager |
| Infraestructura | RDS en subnet privada, sin SSH, SSM only |
| Auditoría | Log de todas las acciones administrativas |

### 11.5 Buenas Prácticas de Seguridad

- 💡 Usar contraseñas fuertes (mínimo 12 caracteres)
- 💡 No compartir credenciales entre usuarios
- 💡 Revisar periódicamente IPs pendientes
- 💡 Revisar logs de auditoría semanalmente
- 💡 Desactivar usuarios que ya no necesitan acceso
- ⚠️ No autorizar IPs desconocidas sin verificar su origen

---

## 12. Solución de Problemas

### 12.1 Problemas de Acceso

| Problema | Causa probable | Solución |
|----------|---------------|----------|
| No puedo iniciar sesión | Credenciales incorrectas | Usar "Olvidé mi contraseña" |
| Token expirado | Sesión inactiva por mucho tiempo | Volver a iniciar sesión |
| Página en blanco | Error de carga del frontend | Limpiar caché del navegador, recargar |
| Error 502 Bad Gateway | Backend no responde | Contactar DevOps (ver troubleshooting backend) |

### 12.2 Problemas de Workstations

| Problema | Causa probable | Solución |
|----------|---------------|----------|
| Workstation no aparece | IP no autorizada | Verificar en Admin → IPs Pendientes |
| Workstation offline | Sin conexión de red o Tray detenido | Verificar red, reiniciar Tray remotamente |
| Configuración no se aplica | Error en JSON o workstation offline | Verificar validez del JSON, esperar reconexión |
| Contingencia no se activa | Service no detecta falla | Verificar logs del Service en la workstation |

### 12.3 Problemas de Infraestructura

| Problema | Diagnóstico | Solución |
|----------|-------------|----------|
| Backend no responde (502) | `docker logs alwaysprint-backend-1 --tail 100` | Reiniciar container, verificar BD |
| Frontend no carga | `docker logs alwaysprint-frontend-1 --tail 100` | Reiniciar container |
| BD no accesible | Verificar RDS status en AWS Console | Verificar security groups, reiniciar RDS |
| SSL expirado | Verificar certificado Let's Encrypt | `certbot renew` en el EC2 |

### 12.4 Comandos de Diagnóstico (DevOps)

```bash
# Acceso al servidor (sin SSH)
aws ssm start-session --target <INSTANCE_ID> --profile <PROFILE>

# Ver logs del backend
docker logs alwaysprint-backend-1 --tail 100

# Ver logs del frontend
docker logs alwaysprint-frontend-1 --tail 100

# Verificar estado de containers
docker compose ps

# Verificar migraciones de BD
docker exec alwaysprint-backend-1 alembic current

# Health check
curl https://alwaysprint.apps.iol.pe/api/v1/health
```

---

## 13. Preguntas Frecuentes

**P: ¿Cuántas workstations puedo gestionar?**  
R: No hay límite técnico definido. El sistema está diseñado para soportar 500+ workstations por organización.

**P: ¿Los datos se actualizan en tiempo real?**  
R: Sí, vía WebSocket. Si la conexión WebSocket se pierde, el dashboard hace polling cada 10 segundos como fallback.

**P: ¿Puedo gestionar múltiples organizaciones?**  
R: Sí, si tu usuario tiene rol ADMIN y acceso a múltiples organizaciones (administrador global).

**P: ¿Qué pasa si autorizo una IP incorrecta?**  
R: Puedes revocar la autorización en cualquier momento desde Admin → Organizaciones → IPs.

**P: ¿Los mensajes llegan a workstations offline?**  
R: Los mensajes se almacenan y se entregan cuando la workstation se reconecta.

**P: ¿Puedo exportar datos del dashboard?**  
R: Actualmente no hay exportación nativa. Se planea para una versión futura.

**P: ¿El sistema funciona si Cloud Manager está caído?**  
R: Sí. Las workstations funcionan de forma autónoma. Cloud Manager es para gestión y monitoreo, no para la operación de contingencia.

**P: ¿Cómo sé si una workstation tiene la última configuración?**  
R: Comparar el hash de configuración en el dashboard con el hash activo de la workstation.

**P: ¿Puedo revertir una configuración de acciones?**  
R: Sí. Desactivar la configuración actual y activar la anterior. Las workstations descargarán la versión activa.

---

## 14. Glosario

| Término | Definición |
|---------|-----------|
| APCM | AlwaysPrint Cloud Manager — esta plataforma web |
| Tenant | Organización cliente en el modelo multi-tenant |
| Organización | Entidad principal que agrupa workstations, usuarios y configuración |
| Workstation | Equipo Windows con AlwaysPrint Client instalado |
| VLAN | Red de área local virtual — agrupación lógica de workstations por red |
| Contingencia | Modo activado cuando CPM falla; redirige impresión directamente |
| CPM | Cloud Print Manager (Lexmark) — sistema de impresión de producción |
| ActionConfig | Archivo .alwaysconfig con acciones administrativas remotas |
| Scope | Nivel de aplicación de una configuración (org, vlan, workstation) |
| Heartbeat | Señal periódica que indica que una workstation está activa |
| Telemetría | Datos de uso y rendimiento enviados por las workstations |
| JWT | JSON Web Token — mecanismo de autenticación para administradores |
| IP pública | Dirección IP desde la cual las workstations se conectan a Internet |
| WebSocket | Protocolo de comunicación bidireccional en tiempo real |
| Polling | Consulta periódica de datos (fallback cuando WebSocket no está disponible) |
| Hash | Valor SHA256 (8 chars) que identifica una versión de configuración |
| LLM | Large Language Model — modelo de IA para análisis de logs |
| SSM | AWS Systems Manager — acceso al servidor sin SSH |
| ECR | Elastic Container Registry — almacén de imágenes Docker |
| SES | Simple Email Service — servicio de email de AWS |
| CIDR | Classless Inter-Domain Routing — notación de redes (ej: 192.168.1.0/24) |
| LPD | Line Printer Daemon — protocolo de impresión (puerto 515) |
| RAW | Protocolo de impresión directa (puerto 9100) |
| Balloon Tip | Notificación emergente de Windows |
| Named Pipe | Canal de comunicación local entre procesos en Windows |

---

## 15. Soporte y Contacto

### Soporte de Primer Nivel (Administrador de la organización)
- Verificar estado de workstations en el dashboard
- Autorizar IPs pendientes
- Reiniciar servicios remotamente
- Revisar logs y auditoría

### Soporte de Segundo Nivel (Robles.AI)
- **Email**: antonio@robles.ai
- **Teléfono**: +1 408 590 0153
- **Web**: https://robles.ai

### Información para Reportar Incidencias

Al reportar un problema con la plataforma, incluir:
1. URL exacta donde ocurre el error
2. Captura de pantalla del error
3. Navegador y versión utilizada
4. Hora exacta del incidente
5. Acciones realizadas antes del error
6. Respuesta del endpoint `/api/v1/health` (si es accesible)

---

## Apéndices

### Apéndice A: Endpoints de la API

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/api/v1/auth/login` | Iniciar sesión |
| POST | `/api/v1/auth/forgot-password` | Solicitar reset de contraseña |
| POST | `/api/v1/auth/reset-password` | Cambiar contraseña |
| GET | `/api/v1/workstations` | Listar workstations |
| GET | `/api/v1/workstations/stats` | Estadísticas de workstations |
| POST | `/api/v1/workstations/{id}/command` | Enviar comando remoto |
| GET | `/api/v1/vlans` | Listar VLANs |
| POST | `/api/v1/vlans` | Crear VLAN |
| GET | `/api/v1/config/global` | Obtener configuración de organización |
| PUT | `/api/v1/config/global` | Actualizar configuración de organización |
| GET | `/api/v1/messages` | Listar mensajes |
| POST | `/api/v1/messages` | Enviar mensaje |
| GET | `/api/v1/audit` | Listar logs de auditoría |
| GET | `/api/v1/organizations` | Listar organizaciones |
| POST | `/api/v1/organizations` | Crear organización |
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/version` | Versión del build |

ℹ️ Documentación completa de la API disponible en `/docs` (Swagger UI).

### Apéndice B: Estructura de Archivo .alwaysconfig

```json
{
  "version": "1.0",
  "name": "Nombre_Configuracion",
  "triggers": [
    {
      "event": "OnTrayLaunched | OnServiceStart | OnConfigChange | OnContingencyActivated | OnContingencyDeactivated",
      "actions": [
        {
          "type": "NombreAccion",
          "parameters": {
            "param1": "valor1",
            "param2": "valor2"
          },
          "store_result_in": "nombre_variable"
        }
      ]
    }
  ]
}
```

#### Acciones disponibles:
| Acción | Parámetros principales |
|--------|----------------------|
| PropagatePermissions | path, recursive |
| GetLoggedInUsers | exclude_active_console_user |
| DeleteFolderContents | path_template, iterate_users |
| StopService / StartService | service_name |
| KillProcessesByName | process_name, username_filter |
| Conditional | condition (variable, operator, value), actions |
| StopTray / StartTray | — |
| CreateTcpPort / SetTcpPort | port_name, ip_address, port_number |
| AssignPortToQueue | queue_name, port_name |
| SetDefaultPrinter | printer_name |
| RunProcess | path, arguments, wait_for_exit |

### Apéndice C: Códigos de Estado HTTP

| Código | Significado en APCM |
|--------|---------------------|
| 200 | Operación exitosa |
| 201 | Recurso creado |
| 400 | Error de validación (JSON inválido, parámetros faltantes) |
| 401 | No autenticado (token expirado o ausente) |
| 403 | Sin permisos (rol insuficiente) |
| 404 | Recurso no encontrado |
| 409 | Conflicto (ej: IP ya autorizada) |
| 429 | Rate limit excedido |
| 500 | Error interno del servidor |
| 502 | Backend no disponible (Nginx no puede conectar) |

---

**Robles.AI**  
Email: antonio@robles.ai  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados
