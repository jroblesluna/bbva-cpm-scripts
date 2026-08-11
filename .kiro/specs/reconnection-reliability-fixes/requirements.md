# Requirements Document

## Introduction

Este documento define los requisitos para corregir 4 bugs identificados en los logs de producción del 10 de agosto de 2026. Los bugs afectan la fiabilidad de reconexión, auto-actualización y ejecución de acciones del cliente AlwaysPrint, impactando aproximadamente al 30% de la flota de workstations.

Los problemas identificados son:
1. Actualización MSI no se dispara en reconexiones WebSocket
2. El HttpClient de ConfigurationSync no usa proxy corporativo
3. Condición de carrera "First message must be register" en WebSocket
4. StopService/StartService falla fatalmente cuando un servicio no existe

## Glossary

- **Tray**: Aplicación AlwaysPrintTray (proceso de usuario) que gestiona la conexión WebSocket y la UI de bandeja del sistema
- **Service**: Servicio Windows AlwaysPrintService (LocalSystem) que ejecuta acciones administrativas
- **PushMessageHandler**: Componente del Tray que procesa mensajes push del servidor y ejecuta sincronización de estado (certificados, configuración, MSI)
- **SyncFromState**: Método de PushMessageHandler que compara el estado de distribución del servidor contra el estado local y descarga recursos que difieran
- **DistributionState**: Objeto que contiene el estado de distribución enriquecido enviado por el servidor (MsiVersion, MsiUrl, ConfigHash, CertVersion, etc.)
- **ConfigurationSync**: Componente del Tray responsable de descargar la configuración efectiva de la workstation desde el endpoint REST
- **ProxyHelper**: Utilidad compartida que detecta y configura el proxy corporativo para conexiones HTTP/WebSocket
- **DomainHealthChecker**: Componente estático que verifica conectividad con el dominio APCM y expone un HttpClient compartido
- **CloudWebSocketClient**: Cliente WebSocket del Tray que gestiona conexión, reconexión automática y envío/recepción de mensajes
- **ActionEngine**: Motor de ejecución de acciones administrativas definidas en archivos .alwaysconfig
- **AdminActions**: Clase estática con las 9 funciones administrativas ejecutables (StopService, StartService, etc.)
- **Backend_WS**: Endpoint WebSocket del backend FastAPI (`/ws/workstation`) que acepta conexiones de workstations

## Requirements

### Requirement 1: Evaluación de MsiVersion en SyncFromState durante reconexión

**User Story:** Como administrador de flota, quiero que las workstations auto-actualicen su versión MSI al reconectarse al WebSocket, para que no sea necesario un push explícito adicional después de cada reconexión.

#### Acceptance Criteria

1. WHEN the Tray reconnects to the WebSocket and receives a DistributionState with a MsiVersion higher than the local Assembly version, THE PushMessageHandler SHALL compare the MsiVersion field from the server state against the local Tray version
2. WHEN the server MsiVersion is newer than the local version AND a MsiUrl is available in the DistributionState, THE PushMessageHandler SHALL initiate an asynchronous MSI download via UpdateDownloader
3. WHEN the MSI download completes successfully, THE PushMessageHandler SHALL send an InstallUpdate message to the Service via Named Pipe
4. WHEN the server MsiVersion is newer but no MsiUrl is present in the DistributionState, THE PushMessageHandler SHALL log a warning indicating the version difference without a download URL
5. WHEN the server MsiVersion equals the local version, THE PushMessageHandler SHALL log that msi_version is up to date and skip the download

### Requirement 2: ConfigurationSync HTTP client con soporte de proxy corporativo

**User Story:** Como workstation detrás de un proxy corporativo, quiero que la descarga de configuración efectiva use el proxy detectado, para que la sincronización no falle con timeout o error TLS en redes que requieren proxy.

#### Acceptance Criteria

1. THE DomainHealthChecker SHALL initialize its static HttpClient using an HttpClientHandler obtained from ProxyHelper.GetHttpClientHandler()
2. WHEN ProxyHelper detects a corporate proxy, THE DomainHealthChecker HttpClient SHALL route all HTTP requests through the detected proxy
3. WHEN ProxyHelper does not detect a proxy, THE DomainHealthChecker HttpClient SHALL use a direct connection without proxy configuration
4. WHEN ConfigurationSync calls DownloadConfig using DomainHealthChecker.Http, THE HTTP request SHALL inherit the proxy configuration from the shared HttpClient
5. IF the proxy configuration fails or the proxy is unreachable, THEN THE ConfigurationSync SHALL log the error with the specific failure reason (timeout vs TLS vs connection refused) and return null

### Requirement 3: Eliminación de condición de carrera en registro WebSocket

**User Story:** Como workstation que se reconecta frecuentemente, quiero que el servidor espere un tiempo razonable para recibir el mensaje de registro, para que no se cierre la conexión prematuramente con código 1008.

#### Acceptance Criteria

1. WHEN the Backend_WS accepts a new WebSocket connection, THE Backend_WS SHALL wait up to 10 seconds for the first message before closing the connection
2. IF no message is received within the 10-second timeout, THEN THE Backend_WS SHALL close the connection with code 1008 and reason "Timeout esperando mensaje de registro"
3. WHEN the CloudWebSocketClient establishes a connection successfully (ConnectAsync completes), THE CloudWebSocketClient SHALL send the register message immediately before processing any other event or message
4. WHEN the Connected event fires, THE CloudManager SHALL invoke SendRegistration synchronously within the event handler before yielding control
5. IF the Backend_WS receives a non-register message as the first message, THEN THE Backend_WS SHALL close the connection with code 1008 and reason "First message must be register"

### Requirement 4: Manejo tolerante de servicios inexistentes en StopService/StartService

**User Story:** Como administrador que define configuraciones .alwaysconfig, quiero que StopService y StartService manejen gracefully servicios no instalados, para que la ausencia de un servicio opcional no marque como fallida toda la cadena de acciones.

#### Acceptance Criteria

1. WHEN StopService is invoked for a service that does not exist on the workstation, THE AdminActions SHALL log a warning indicating the service was not found and return true (success)
2. WHEN StartService is invoked for a service that does not exist on the workstation, THE AdminActions SHALL log a warning indicating the service was not found and return true (success)
3. WHEN a service-not-found condition occurs, THE AdminActions SHALL NOT propagate an exception to the ActionEngine
4. WHEN StopService or StartService encounters a genuine operational error (access denied, timeout, etc.), THE AdminActions SHALL still return false and log the error as before
5. WHEN a Conditional action contains StopService for a non-existent service, THE ActionEngine SHALL continue executing subsequent actions in the sequence without marking the Conditional as failed
