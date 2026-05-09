# AlwaysPrint.Shared

Biblioteca compartida entre AlwaysPrintService y AlwaysPrintTray.

## Descripción

Contiene clases y estructuras de datos compartidas por ambos ejecutables para garantizar consistencia en la comunicación vía Named Pipe y en la gestión de configuración.

## Estructura

```
AlwaysPrint.Shared/
├── Configuration/              # Gestión de configuración
│   ├── AppConfiguration.cs    # Modelo de configuración
│   └── RegistryConfigManager.cs # Lectura/escritura en Registry
├── Logging/                    # Sistema de logging
│   └── EventLogWriter.cs      # Escritura en Event Log de Windows
├── Messages/                   # Protocolo Named Pipe
│   ├── PipeMessage.cs         # Estructura de mensaje
│   ├── MessageType.cs         # Tipos de mensaje (enum)
│   ├── Payloads.cs            # Payloads de mensajes
│   └── PipeConstants.cs       # Constantes (nombre del pipe, timeouts)
└── Models/                     # Modelos de datos
    └── ServiceState.cs        # Estados del servicio (enum)
```

## Componentes Principales

### Configuration

**AppConfiguration**: Modelo de configuración que mapea los valores del Registry.

**RegistryConfigManager**: Gestiona lectura y escritura en `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`.

### Logging

**EventLogWriter**: Escribe eventos en el Event Log de Windows con IDs fijos (1000-1099).

### Messages

**PipeMessage**: Estructura JSON para comunicación vía Named Pipe.

**MessageType**: Enum con tipos de mensaje:
- `Ping` / `Pong`
- `TrayInitialized`
- `UpdateConfiguration`
- `GetCurrentConfiguration`
- `CheckCorporateQueue`
- `CheckServiceStatus`
- `ReportTelemetry` (para Cloud Manager)
- `CloudConfigurationReceived` (desde Cloud Manager)
- `Ack` / `Error`

**Payloads**: Clases de datos para cada tipo de mensaje.

**PipeConstants**: Constantes compartidas:
- `PipeName`: `"AlwaysPrintService"`
- `Timeout`: 30 segundos

### Models

**ServiceState**: Estados del ciclo de vida del servicio:
- `Starting`
- `WaitingUser`
- `TrayStarting`
- `TrayStarted`
- `Running`
- `TrayError`
- `Stopping`
- `Stopped`

## Uso

Esta biblioteca es referenciada por:
- `AlwaysPrintService.csproj`
- `AlwaysPrintTray.csproj`

Cualquier cambio en esta biblioteca requiere recompilar ambos ejecutables.

## Target Framework

- .NET Framework 4.8

## Dependencias

- Newtonsoft.Json (para serialización de mensajes)

---

**Robles.AI**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI  
Prohibida la utilización sin autorización de Inversiones On Line SAC
