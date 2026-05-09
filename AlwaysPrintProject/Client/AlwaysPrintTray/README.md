# AlwaysPrintTray

Aplicación de bandeja del sistema (system tray) que proporciona interfaz de usuario y comunicación con la nube.

## Descripción

**AlwaysPrintTray** es la interfaz de usuario de AlwaysPrint. Corre en la sesión del usuario (no como servicio), con permisos de usuario estándar, y proporciona:

- Icono en la bandeja del sistema (system tray)
- Menú contextual para configuración
- Cliente Named Pipe para comunicación con AlwaysPrintService
- Cliente HTTP para comunicación con AlwaysPrint Cloud Manager (opcional)
- Health check de licencia

## Estructura

```
AlwaysPrintTray/
├── Bootstrap/                  # Inicialización
│   └── DomainHealthChecker.cs # Health check HTTP de licencia
├── Forms/                      # Formularios WinForms
│   ├── AboutForm.cs           # Ventana "Acerca de"
│   └── ConfigurationForm.cs   # Ventana de configuración
├── Pipe/                       # Comunicación Named Pipe
│   └── PipeClient.cs          # Cliente Named Pipe
├── Cloud/                      # Integración Cloud (opcional)
│   ├── CloudApiClient.cs      # Cliente HTTP para API
│   ├── HeartbeatManager.cs    # Gestión de heartbeat
│   ├── TelemetryReporter.cs   # Reporte de telemetría
│   ├── ConfigurationSync.cs   # Sincronización de config
│   └── ProxyHelper.cs         # Detección de proxy
├── TrayApplicationContext.cs   # Contexto de aplicación
└── Program.cs                  # Punto de entrada
```

## Componentes Principales

### Bootstrap

**DomainHealthChecker**: Realiza HTTP GET a `https://alwaysprint.{dominio}/health` para validar licencia.
- Timeout: 5 segundos por dominio
- Dominios configurables en Registry (`BootstrapDomains`)
- Ejecuta en thread de fondo

### Forms

**AboutForm**: Ventana "Acerca de" con información de versión y licencia.

**ConfigurationForm**: Ventana de configuración con campos para:
- `CorporateQueueName`
- `SearchTargets`
- `PendingTaskPollingMinutes`
- `BootstrapDomains`
- `RoblesAiLicenseSerial`
- Configuración Cloud (si está habilitada)

### Pipe

**PipeClient**: Cliente Named Pipe para comunicación con AlwaysPrintService.
- Conexión: `\\.\pipe\AlwaysPrintService`
- Timeout: 30 segundos
- Reintentos: 5 intentos con 1 segundo entre intentos
- Formato: JSON por líneas

### Cloud (Opcional)

**CloudApiClient**: Cliente HTTP para AlwaysPrint Cloud Manager.
- Soporta proxy corporativo (detección automática)
- Autenticación: API Key en header `X-API-Key`
- Endpoints:
  - `POST /api/v1/workstations/register`
  - `POST /api/v1/workstations/{id}/heartbeat`
  - `POST /api/v1/workstations/{id}/telemetry`
  - `GET /api/v1/workstations/{id}/config`

**HeartbeatManager**: Envía heartbeat cada 60 segundos.

**TelemetryReporter**: Reporta métricas y eventos al Cloud Manager.

**ConfigurationSync**: Sincroniza configuración desde la nube cada 5 minutos.

**ProxyHelper**: Detecta y configura proxy corporativo automáticamente.

## Flujo de Inicio

```
1. Program.Main() inicia
2. Verifica instancia única (Mutex)
3. Crea PipeClient y conecta a AlwaysPrintService
4. Ejecuta DomainHealthChecker (health check de licencia)
5. Envía TrayInitialized al servicio
6. Si CloudEnabled = 1:
   a. Crea CloudApiClient
   b. Registra workstation (si no está registrada)
   c. Inicia HeartbeatManager
   d. Inicia ConfigurationSync
7. Muestra icono en system tray
8. Entra en loop de mensajes de Windows
```

## Menú Contextual

- **Configuración de Valores**: Abre ConfigurationForm
- **Verificar Cola Corporativa**: Envía CheckCorporateQueue al servicio
- **Estado del Servicio**: Envía CheckServiceStatus al servicio
- **Acerca de**: Abre AboutForm
- **Salir**: Cierra la aplicación

## Configuración Cloud

Lee configuración de `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`:
- `CloudEnabled` (DWORD): 1 = habilitar integración cloud
- `CloudApiUrl` (String): URL del backend (ej: https://api.alwaysprint.com)
- `CloudApiKey` (String): Organization API Key

Guarda credenciales de workstation en `HKCU\SOFTWARE\Robles.AI\AlwaysPrint\Cloud`:
- `WorkstationId` (String): ID de workstation
- `ApiKey` (String): Workstation API Key

## Logs

Escribe logs en:
- Event Log de Windows (Application log, source: AlwaysPrint)
- Archivo: `C:\ProgramData\AlwaysPrint\logs\AlwaysPrint_yyyyMMdd.log`

Event IDs: 1000-1099 (origen: APP)

## Target Framework

- .NET Framework 4.8

## Dependencias

- AlwaysPrint.Shared
- Newtonsoft.Json
- System.Windows.Forms
- System.Drawing

---

© 2026 Robles.AI
