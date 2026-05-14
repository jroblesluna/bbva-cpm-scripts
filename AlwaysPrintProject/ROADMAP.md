# AlwaysPrint — Roadmap de Integración Cloud (Client ↔ APCM)

**Última actualización**: 2026-05-14

---

## Fase 1 — Fundamentos de Integración Cloud ✅

> Preparar la infraestructura interna del Client para la integración futura con APCM.

| # | Componente | Estado |
|---|---|---|
| 1.1 | `AppConfiguration` — campos Cloud + `ConnectivityCheck` + `Validate()` | ✅ |
| 1.2 | `RegistryConfigManager` — Load/Save/EnsureDefaults campos Cloud (HKLM) | ✅ |
| 1.3 | `CloudCredentialsManager` — gestión de credenciales en HKCU | ✅ |
| 1.4 | `MessageType` — 4 nuevos tipos Cloud en el enum | ✅ |
| 1.5 | `Payloads.cs` — 4 nuevas clases de payload Cloud | ✅ |
| 1.6 | `LocalizationManager` + archivos `.resx` (i18n) | ✅ |
| 1.7 | `TrayApplicationContext` — integración i18n en menú y balloons | ✅ |
| 1.8 | `Program.cs` — `LocalizationManager.Initialize()` antes del contexto | ✅ |
| 1.9 | `MessageDispatcher` — handler `CloudConfigurationReceived` | ✅ |
| 1.10 | `ConfigurationForm` — campos Cloud (CheckBox, TextBox, ComboBox) | ✅ |
| 1.11 | `Product.wxs` — 6 RegistryValue Cloud en el instalador MSI | ✅ |
| 1.12 | Compilación sin errores ni advertencias | ✅ |

---

## Fase 2 — Conexión Cloud: WebSocket, Registro, Heartbeat ✅

> El Tray se conecta a APCM vía WebSocket, se registra y mantiene la conexión activa.

| # | Componente | Estado |
|---|---|---|
| 2.1 | `ProxyHelper.cs` — detección de proxy corporativo | ✅ |
| 2.2 | `CloudWebSocketClient.cs` — conexión WSS + reconexión exponencial | ✅ |
| 2.3 | `CloudManager.cs` — orquestador (registro, heartbeat, notificación) | ✅ |
| 2.4 | `TrayApplicationContext` — integración CloudManager en bootstrap | ✅ |
| 2.5 | `AlwaysPrintTray.csproj` — WebSocket4Net 0.15.2 + System.Management | ✅ |
| 2.6 | Compilación sin errores ni advertencias | ✅ |

---

## Fase 3 — Sincronización de Configuración ✅

> El Tray descarga configuración de APCM y la aplica al Service vía Named Pipe.

| # | Componente | Estado |
|---|---|---|
| 3.1 | `ConfigurationSync.cs` — handler de `config_update` del servidor | ✅ |
| 3.2 | `OfflineStateManager.cs` — gestión de estado offline y caché | ✅ |

---

## Fase 4 — Telemetría ✅

> El Service reporta telemetría al Tray, que la reenvía a APCM.

| # | Componente | Estado |
|---|---|---|
| 4.1 | `TelemetryReporter.cs` — reenvío de telemetría a APCM | ✅ |

---

## Fase 5 — Resiliencia ✅

> Checks de conectividad y monitoreo de estado de red.

| # | Componente | Estado |
|---|---|---|
| 5.1 | `ConnectivityMonitor.cs` — checks de conectividad configurables | ✅ |

---

## Fase 6 — Portal Cloud (APCM) ✅

> Plataforma SaaS para gestión centralizada de workstations.

| # | Componente | Estado |
|---|---|---|
| 6.1 | Backend FastAPI — auth, workstations, config, telemetry, audit, VLANs, messages | ✅ |
| 6.2 | WebSocket server — registro y comunicación en tiempo real | ✅ |
| 6.3 | Frontend Next.js — dashboard, workstations, config, telemetry, audit, connectivity | ✅ |
| 6.4 | Infraestructura Terraform — EC2, ECR, RDS, VPC | ✅ |
| 6.5 | CI/CD — GitHub Actions deploy backend + frontend | ✅ |
| 6.6 | i18n — soporte español/inglés en frontend | ✅ |

---

## Pendientes / Mejoras futuras ⏳

| # | Tema | Estado |
|---|---|---|
| P.1 | Fix `deploy.sh` en EC2 para IMDSv2 (token requerido para metadata) | ⏳ |
| P.2 | Compilación y generación MSI en Windows (verificación final) | ⏳ |
| P.3 | Tests unitarios / integración para componentes Cloud del Client | ⏳ |
| P.4 | Documentación de API (OpenAPI/Swagger) | ⏳ |
| P.5 | Alertas y monitoreo (CloudWatch, health checks) | ⏳ |

---

## Notas

- **Client**: C# .NET Framework 4.8 (Windows)
- **Backend**: Python 3.12, FastAPI, PostgreSQL
- **Frontend**: TypeScript, Next.js 15, React 18
- **Infraestructura**: AWS (EC2, ECR, RDS), Terraform
- **CI/CD**: GitHub Actions con deploy vía SSM
