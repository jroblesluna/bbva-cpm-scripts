using System;
using System.Diagnostics;
using System.IO;
using System.ServiceProcess;
using System.Threading;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrint.Shared.Models;
using AlwaysPrint.Shared.Network;
using AlwaysPrintService.Actions;
using AlwaysPrintService.Pipe;
using AlwaysPrintService.Queue;
using AlwaysPrintService.UserSession;

namespace AlwaysPrintService
{
    public sealed class AlwaysPrintWindowsService : ServiceBase
    {
        // 'new' suprime CS0108 — la constante oculta intencionalmente ServiceBase.ServiceName
        // para que el nombre sea accesible en tiempo de compilación sin instanciar el servicio.
        public new const string ServiceName = "AlwaysPrintService";
        private const int TrayTimeoutSeconds = 1800;   // 30 minutos
        private const int UserPollSeconds    = 60;

        // ── Componentes ──────────────────────────────────────────────────────────
        private readonly ServiceStateMachine   _state     = new ServiceStateMachine();
        private readonly RegistryConfigManager _registry  = new RegistryConfigManager();
        private readonly TaskQueueManager      _taskQueue = new TaskQueueManager();
        private readonly ActionEngine          _actionEngine = new ActionEngine();
        private readonly Watchdog.ServiceWatchdogRunner _watchdog = new Watchdog.ServiceWatchdogRunner();
        private MessageDispatcher?   _dispatcher;
        private PipeServer?          _pipeServer;

        // Gate de handshake con el Tray.
        private readonly ManualResetEventSlim _trayInitGate   = new ManualResetEventSlim(false);

        // Gate para despertar WaitForUser cuando llega un evento de sesión.
        private readonly ManualResetEventSlim _userArrivedGate = new ManualResetEventSlim(false);

        private Thread? _startupThread;
        private CancellationTokenSource _cts = new CancellationTokenSource();
        
        // Timer para ejecución periódica de OnScheduledTask
        private System.Threading.Timer? _scheduledTaskTimer;
        
        // Ruta del archivo de configuración de acciones.
        // Se usa ProgramData para que tanto el Tray (usuario normal, solo lectura) como el
        // Service (LocalSystem, lectura/escritura) puedan acceder al mismo archivo.
        private string ConfigFilePath => PipeConstants.ActionConfigFilePath;

        private new const bool CanHandleSessionChangeEvent = true;

        public AlwaysPrintWindowsService()
        {
            base.ServiceName                 = ServiceName;
            base.CanStop                     = true;
            base.CanShutdown                 = true;
            base.CanHandleSessionChangeEvent = CanHandleSessionChangeEvent;
            base.CanPauseAndContinue         = false;
            base.AutoLog                     = false;
        }

        // ── Telemetría: envío de ReportTelemetry al Tray ────────────────────────

        /// <summary>
        /// Envía un mensaje ReportTelemetry al Tray vía Named Pipe con los datos
        /// de un trabajo de impresión completado. Si el pipe está desconectado,
        /// registra una advertencia y descarta el mensaje.
        /// </summary>
        /// <param name="releaseTimeMs">Tiempo de liberación del trabajo en milisegundos (no negativo).</param>
        public void NotifyPrintJobCompleted(long releaseTimeMs)
        {
            try
            {
                if (_pipeServer == null || !_pipeServer.IsClientConnected)
                {
                    AlwaysPrintLogger.WriteWarning(
                        "ReportTelemetry: pipe desconectado, no se puede enviar datos de telemetría al Tray. Mensaje descartado.",
                        AlwaysPrintLogger.EvtGenericWarning);
                    return;
                }

                var payload = new ReportTelemetryPayload
                {
                    JobCount = 1,
                    ReleaseTimeMs = releaseTimeMs
                };

                var message = PipeMessage.Create(MessageType.ReportTelemetry, payload);
                bool sent = _pipeServer.SendToClient(message);

                if (!sent)
                {
                    AlwaysPrintLogger.WriteWarning(
                        "ReportTelemetry: no se pudo enviar mensaje de telemetría al Tray. Pipe desconectado. Mensaje descartado.",
                        AlwaysPrintLogger.EvtGenericWarning);
                }
                else
                {
                    AlwaysPrintLogger.WriteInfo(
                        $"ReportTelemetry: datos de trabajo enviados al Tray. releaseTimeMs={releaseTimeMs}.");
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"ReportTelemetry: error al enviar telemetría al Tray. {ex.Message}. Mensaje descartado.",
                    AlwaysPrintLogger.EvtGenericWarning);
            }
        }

        // ── Puntos de entrada del servicio ──────────────────────────────────────

        protected override void OnStart(string[] args)
        {
            // Capturar excepciones no manejadas en threads de background para evitar crash silencioso
            AppDomain.CurrentDomain.UnhandledException += (sender, e) =>
            {
                var ex = e.ExceptionObject as Exception;
                AlwaysPrintLogger.WriteError(
                    $"EXCEPCIÓN NO MANEJADA (IsTerminating={e.IsTerminating}): {ex?.GetType().Name}: {ex?.Message}\n{ex?.StackTrace}",
                    AlwaysPrintLogger.EvtGenericError);
            };

            _startupThread = new Thread(RunStartupSequence)
            {
                IsBackground = true,
                Name = "AlwaysPrint-Startup"
            };
            _startupThread.Start();
        }

        protected override void OnStop()
        {
            _state.Transition(ServiceState.Stopping);
            _cts.Cancel();
            StopScheduledTaskTimer();
            _watchdog.Stop();
            _userArrivedGate.Set();
            _pipeServer?.Stop();
            _taskQueue.Stop();
            KillExistingTray();
            _state.Transition(ServiceState.Stopped);
            AlwaysPrintLogger.WriteInfo("AlwaysPrintService detenido.", AlwaysPrintLogger.EvtServiceStopped);
        }

        protected override void OnShutdown() => OnStop();

        protected override void OnSessionChange(SessionChangeDescription changeDescription)
        {
            AlwaysPrintLogger.WriteInfo(
                $"Session change: {SessionMonitor.DescribeReason(changeDescription.Reason)} (session {changeDescription.SessionId})",
                AlwaysPrintLogger.EvtUserDetected);

            var reason = changeDescription.Reason;
            bool userArrived = reason == SessionChangeReason.SessionLogon   ||
                               reason == SessionChangeReason.SessionUnlock;

            bool userLeft = reason == SessionChangeReason.SessionLogoff     ||
                            reason == SessionChangeReason.ConsoleDisconnect;

            if (userArrived && _state.Is(ServiceState.WaitingUser))
                _userArrivedGate.Set();

            // Disparar trigger OnSessionUnlocked al desbloquear pantalla
            if (reason == SessionChangeReason.SessionUnlock && _state.Is(ServiceState.Running))
            {
                AlwaysPrintLogger.WriteInfo(
                    $"Sesión desbloqueada (session {changeDescription.SessionId}). Ejecutando trigger OnSessionUnlocked.",
                    AlwaysPrintLogger.EvtUserDetected);
                ExecuteActionTrigger(TriggerEvents.OnSessionUnlocked);
            }

            if (userLeft && (_state.Is(ServiceState.TrayStarted) || _state.Is(ServiceState.Running)))
            {
                AlwaysPrintLogger.WriteWarning("Sesión de usuario finalizada. Eliminando Tray y esperando nueva sesión.",
                    AlwaysPrintLogger.EvtTrayKilled);

                // Escribir LastRestartTimestamp antes de matar el Tray para que
                // aplique jitter al reconectar (prevención de thundering herd).
                try
                {
                    _registry.SaveLastRestartTimestamp(DateTime.UtcNow);
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteError(
                        $"No se pudo escribir LastRestartTimestamp en registro: {ex.Message}",
                        AlwaysPrintLogger.EvtGenericError);
                }

                KillExistingTray();
                _trayInitGate.Reset();
                _state.Transition(ServiceState.WaitingUser);
                _userArrivedGate.Set();
            }
        }

        // ── Secuencia de inicio ─────────────────────────────────────────────────

        private void RunStartupSequence()
        {
            try
            {
                AlwaysPrintLogger.WriteInfo("AlwaysPrintService iniciando...", AlwaysPrintLogger.EvtServiceStarted);
                AlwaysPrintLogger.WriteInfo($"Versión: {System.Reflection.Assembly.GetExecutingAssembly().GetName().Version}", AlwaysPrintLogger.EvtServiceStarted);
                _state.Transition(ServiceState.Starting);

                // 1. Guardia contra instancias duplicadas.
                if (IsDuplicateServiceRunning())
                {
                    AlwaysPrintLogger.WriteWarning("Instancia duplicada de AlwaysPrintService detectada. Abortando inicio.",
                        AlwaysPrintLogger.EvtDuplicateInstance);
                    Stop();
                    return;
                }

                // 2. Matar instancias huérfanas del Tray.
                // Escribir LastRestartTimestamp antes de matar para que el Tray
                // aplique jitter al reconectar (prevención de thundering herd).
                if (IsTrayRunning())
                {
                    try
                    {
                        _registry.SaveLastRestartTimestamp(DateTime.UtcNow);
                    }
                    catch (Exception ex)
                    {
                        AlwaysPrintLogger.WriteError(
                            $"No se pudo escribir LastRestartTimestamp en registro: {ex.Message}",
                            AlwaysPrintLogger.EvtGenericError);
                    }
                }

                int killedTrays = KillExistingTray();
                if (killedTrays > 0)
                    AlwaysPrintLogger.WriteWarning($"Se eliminaron {killedTrays} instancia(s) huérfana(s) de AlwaysPrintTray.",
                        AlwaysPrintLogger.EvtTrayKilled);
                else
                    AlwaysPrintLogger.WriteInfo("No se encontraron instancias huérfanas del Tray.", AlwaysPrintLogger.EvtTrayKilled);

                // 3. Asegurar valores por defecto en registro.
                _registry.EnsureDefaults();

                // 3.2. Asegurar que el directorio de configuración de acciones existe.
                EnsureActionConfigDirectory();

                // 3.5. Cargar configuración de acciones si existe.
                LoadActionConfiguration();

                // 3.6. Escribir Root Log con información diagnóstica de la workstation.
                WriteRootLogBlock();

                // 4. Inicializar cola de tareas.
                _taskQueue.Start();
                int cleared = _taskQueue.ClearAll();
                if (cleared > 0)
                    AlwaysPrintLogger.WriteWarning($"Se descartaron {cleared} tarea(s) pendiente(s) al iniciar.",
                        AlwaysPrintLogger.EvtQueueCleared);
                else
                    AlwaysPrintLogger.WriteInfo("Cola de tareas inicializada vacía.", AlwaysPrintLogger.EvtQueueCleared);

                // 5. Iniciar servidor Named Pipe.
                _dispatcher = new MessageDispatcher(_registry, _taskQueue, _state, ReloadActionConfiguration, LoadResourceVariables, _actionEngine.ExecuteOnDemandTrigger);
                _dispatcher.TrayInitializedReceived += OnTrayInitialized;
                _dispatcher.ForcedContingencyReceived += OnForcedContingencyReceived;
                _dispatcher.DebuggingCaptureCompleted += OnDebuggingCaptureCompleted;
                _dispatcher.DebuggingCaptureErrorOccurred += OnDebuggingCaptureError;

                // Suscribir a eventos de progreso OnDemand para push al Tray
                _actionEngine.OnActionProgress += OnActionProgress;
                _pipeServer = new PipeServer(_dispatcher);
                _pipeServer.Start();

                // Establecer callback de cierre suave para StopTray (evita iconos fantasma)
                _actionEngine.SetGracefulStopTrayCallback(() =>
                {
                    if (_pipeServer != null && _pipeServer.IsClientConnected)
                    {
                        var shutdownMsg = PipeMessage.Create(MessageType.ServiceStopping);
                        _pipeServer.SendToClient(shutdownMsg);
                        // Esperar para que el Tray procese y oculte el NotifyIcon
                        Thread.Sleep(1500);
                        return true;
                    }
                    return false;
                });

                // Establecer callback para envío de mensajes pipe desde ActionEngine
                _actionEngine.SetSendPipeMessageCallback((msg) =>
                {
                    if (_pipeServer != null && _pipeServer.IsClientConnected)
                    {
                        return _pipeServer.SendToClient(msg);
                    }
                    return false;
                });

                // 6. Bucle principal: esperar usuario → lanzar Tray → monitorear.
                RunSessionLoop();
            }
            catch (OperationCanceledException)
            {
                AlwaysPrintLogger.WriteInfo("Secuencia de inicio cancelada.");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError("Error fatal en la secuencia de inicio.", ex);
                Stop();
            }
        }

        /// <summary>
        /// Bucle que gestiona el ciclo completo de sesión de usuario:
        /// WaitingUser → TrayStarting → TrayStarted → Running → (logoff) → WaitingUser → …
        /// </summary>
        private void RunSessionLoop()
        {
            while (!_cts.IsCancellationRequested)
            {
                // ── Esperar sesión interactiva ──────────────────────────────────
                _state.Transition(ServiceState.WaitingUser);
                WaitForUser();
                if (_cts.IsCancellationRequested) return;

                // ── Lanzar Tray en la sesión del usuario ────────────────────────
                _trayInitGate.Reset();
                _state.Transition(ServiceState.TrayStarting);
                LaunchTray();

                // ── Esperar handshake del Tray ───────────────────────────────────
                bool trayOk = _trayInitGate.Wait(TimeSpan.FromSeconds(TrayTimeoutSeconds), _cts.Token);
                if (_cts.IsCancellationRequested) return;

                if (!trayOk)
                {
                    _state.Transition(ServiceState.TrayError);
                    AlwaysPrintLogger.WriteError(
                        $"El Tray no confirmó la inicialización en el tiempo límite ({TrayTimeoutSeconds}s). Deteniendo el servicio.",
                        AlwaysPrintLogger.EvtTrayError);
                    Stop();
                    return;
                }

                _state.Transition(ServiceState.TrayStarted);
                _state.Transition(ServiceState.Running);

                // ── Bucle de monitoreo ───────────────────────────────────────────
                MonitoringLoop();

                if (!_cts.IsCancellationRequested)
                    AlwaysPrintLogger.WriteInfo("Sesión de usuario finalizada. Esperando nueva sesión.",
                        AlwaysPrintLogger.EvtWaitingUser);
            }
        }

        private void WaitForUser()
        {
            while (!SessionMonitor.IsUserLoggedIn())
            {
                if (_cts.IsCancellationRequested) return;
                AlwaysPrintLogger.WriteInfo("Esperando sesión interactiva de usuario...", AlwaysPrintLogger.EvtWaitingUser);

                int signaled = WaitHandle.WaitAny(
                    new[] { _userArrivedGate.WaitHandle, _cts.Token.WaitHandle },
                    TimeSpan.FromSeconds(UserPollSeconds));

                _userArrivedGate.Reset();
                if (signaled == 1) return;
            }
            AlwaysPrintLogger.WriteInfo("Sesión interactiva de usuario detectada.", AlwaysPrintLogger.EvtUserDetected);
        }

        private void LaunchTray()
        {
            AlwaysPrintLogger.WriteInfo("LaunchTray: esperando 3 segundos para que PipeServer esté listo.");
            Thread.Sleep(3000);

            string trayExe = Path.Combine(
                Path.GetDirectoryName(Process.GetCurrentProcess().MainModule!.FileName)!,
                "AlwaysPrintTray.exe");

            AlwaysPrintLogger.WriteInfo($"LaunchTray: lanzando {trayExe}");
            bool ok = InteractiveProcessLauncher.Launch(trayExe);
            if (!ok)
                AlwaysPrintLogger.WriteError($"No se pudo lanzar el Tray desde '{trayExe}'.", AlwaysPrintLogger.EvtTrayError);
            else
                AlwaysPrintLogger.WriteInfo("LaunchTray: Tray lanzado exitosamente.");
        }

        private void OnTrayInitialized(bool success, string? details)
        {
            AlwaysPrintLogger.WriteInfo($"OnTrayInitialized: success={success}, details={details}");
            if (!success)
                AlwaysPrintLogger.WriteWarning(
                    $"Tray reportó fallo en health check bootstrap: {details}. El servicio continuará en modo local (offline-first).",
                    AlwaysPrintLogger.EvtTrayError);

            // El handshake se acepta siempre que el Tray se haya conectado y respondido,
            // independientemente del resultado del health check de dominios bootstrap.
            // Principio offline-first: el sistema funciona sin conectividad externa.
            _trayInitGate.Set();
            
            // Ejecutar trigger OnTrayLaunched después de que el Tray se haya inicializado
            ExecuteActionTrigger(TriggerEvents.OnTrayLaunched);
        }

        /// <summary>
        /// Callback cuando se recibe ForcedContingencyChanged del Tray.
        /// Ejecuta el trigger OnContingencyActivated o OnContingencyDeactivated según corresponda.
        /// Defensa: si enabled=true y no hay printer_ip válida, no se ejecuta el trigger de activación.
        /// Defensa: si enabled=false y la contingencia ya está desactivada (semáforo=0), no se re-ejecuta
        /// el trigger de desactivación (evita cascada de RunProcess en cada reconexión WebSocket).
        /// </summary>
        private void OnForcedContingencyReceived(bool enabled, string source, string sourceName, string? printerIp)
        {
            AlwaysPrintLogger.WriteInfo(
                $"OnForcedContingencyReceived: enabled={enabled}, source={source}, sourceName={sourceName}, printerIp={printerIp ?? "null"}");

            if (enabled)
            {
                // Validar que se recibió una IP de contingencia válida antes de ejecutar el trigger
                if (string.IsNullOrEmpty(printerIp))
                {
                    AlwaysPrintLogger.WriteWarning(
                        "Contingencia forzada recibida sin printer_ip válida. No se ejecutará OnContingencyActivated.",
                        AlwaysPrintLogger.EvtGenericWarning);
                    return;
                }

                // Establecer la IP de contingencia como variable del ActionEngine
                _actionEngine.SetConfigVariable("contingency_printer_ip", printerIp);
                ExecuteActionTrigger(TriggerEvents.OnContingencyActivated);
            }
            else
            {
                // Verificar si la contingencia ya está desactivada (semáforo en registro = 0).
                // Si ya está en 0, no re-ejecutar el trigger para evitar cascada de RunProcess
                // que cuelga cuando el print server está apagado.
                try
                {
                    using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                        RegistryConfigManager.RegistryPath, writable: false))
                    {
                        int currentValue = key != null
                            ? Convert.ToInt32(key.GetValue("ContingencyEnabled", 0))
                            : 0;

                        if (currentValue == 0)
                        {
                            AlwaysPrintLogger.WriteInfo(
                                "OnForcedContingencyReceived: contingencia ya desactivada (semáforo=0). " +
                                "Omitiendo trigger OnContingencyDeactivated.");
                            return;
                        }
                    }
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteWarning(
                        $"OnForcedContingencyReceived: no se pudo leer semáforo ContingencyEnabled: {ex.Message}. Ejecutando trigger por precaución.");
                }

                ExecuteActionTrigger(TriggerEvents.OnContingencyDeactivated);
            }
        }

        /// <summary>
        /// Evento del DebuggingEngine: captura finalizada exitosamente.
        /// Envía push al Tray con el tamaño total para que reporte debugging_ready al backend.
        /// </summary>
        private void OnDebuggingCaptureCompleted(string debuggingId, long totalSizeBytes)
        {
            AlwaysPrintLogger.WriteInfo(
                $"DebuggingCapture completada: id={debuggingId}, size={totalSizeBytes} bytes");

            if (_pipeServer != null && _pipeServer.IsClientConnected)
            {
                var msg = PipeMessage.Create(MessageType.DebuggingCaptureReady,
                    new DebuggingCaptureReadyPayload
                    {
                        DebuggingId = debuggingId,
                        TotalSizeBytes = totalSizeBytes
                    });
                _pipeServer.SendToClient(msg);
            }
        }

        /// <summary>
        /// Evento del DebuggingEngine: error durante la captura.
        /// Envía push al Tray para que reporte debugging_error al backend.
        /// </summary>
        private void OnDebuggingCaptureError(string debuggingId, string errorMessage)
        {
            AlwaysPrintLogger.WriteError(
                $"DebuggingCapture error: id={debuggingId}, error={errorMessage}");

            if (_pipeServer != null && _pipeServer.IsClientConnected)
            {
                var msg = PipeMessage.Create(MessageType.DebuggingCaptureError,
                    new DebuggingCaptureErrorPayload
                    {
                        DebuggingId = debuggingId,
                        ErrorMessage = errorMessage
                    });
                _pipeServer.SendToClient(msg);
            }
        }

        /// <summary>
        /// Evento del ActionEngine: progreso de un paso OnDemand.
        /// Envía push al Tray para actualizar la ventana de progreso.
        /// </summary>
        private void OnActionProgress(string triggerLabel, string actionType, string description, string status)
        {
            if (_pipeServer != null && _pipeServer.IsClientConnected)
            {
                bool isComplete = status.StartsWith("completed");
                var msg = PipeMessage.Create(MessageType.OnDemandActionProgress,
                    new OnDemandActionProgressPayload
                    {
                        TriggerLabel = triggerLabel,
                        ActionType = actionType,
                        StepName = description,
                        Status = isComplete ? (status == "completed_ok" ? "ok" : "error") : status,
                        IsComplete = isComplete,
                        OverallSuccess = status == "completed_ok",
                    });
                _pipeServer.SendToClient(msg);
            }
        }

        private void MonitoringLoop()
        {
            while (!_cts.IsCancellationRequested && _state.Is(ServiceState.Running))
            {
                // Verificar si el Tray sigue vivo
                if (!IsTrayRunning())
                {
                    AlwaysPrintLogger.WriteWarning(
                        "Tray no está corriendo. Relanzando...",
                        AlwaysPrintLogger.EvtTrayKilled);
                    // Salir del MonitoringLoop para que RunSessionLoop relance el Tray
                    break;
                }

                var cfg = _registry.Load();
                int interval = Math.Max(1, cfg.PendingTaskPollingMinutes);

                AlwaysPrintLogger.WriteInfo(
                    $"AlwaysPrint activo. Estado={_state.Current} TareasPendientes={_taskQueue.PendingCount}",
                    AlwaysPrintLogger.EvtServiceStarted);

                WaitHandle.WaitAny(
                    new[] { _userArrivedGate.WaitHandle, _cts.Token.WaitHandle },
                    TimeSpan.FromMinutes(interval));

                _userArrivedGate.Reset();
            }
        }

        // ── Helpers ─────────────────────────────────────────────────────────────

        /// <summary>
        /// Escribe el bloque Root Log con información diagnóstica de la workstation.
        /// Se invoca al inicio del servicio después de cargar la configuración.
        /// Algunos datos (organización, workstation ID) pueden no estar disponibles
        /// hasta que el Tray se registre en Cloud — se escribe lo disponible.
        /// </summary>
        private void WriteRootLogBlock()
        {
            try
            {
                var cfg = _registry.Load();
                string version = System.Reflection.Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "desconocida";
                string hostname = NetworkHelper.GetHostname();
                string localIp = NetworkHelper.GetOutboundLocalIP();

                // Determinar entorno
#if ENV_DEV
                string environment = "DEV";
#else
                string environment = "PROD";
#endif

                // Servidor Cloud (extraer dominio de la URL)
                string? serverUrl = null;
                if (!string.IsNullOrEmpty(cfg.CloudApiUrl))
                {
                    try
                    {
                        var uri = new Uri(cfg.CloudApiUrl);
                        serverUrl = uri.Host;
                    }
                    catch
                    {
                        serverUrl = cfg.CloudApiUrl;
                    }
                }
                else if (!string.IsNullOrEmpty(cfg.BootstrapDomains))
                {
                    // Usar el primer dominio bootstrap como referencia
                    string firstDomain = cfg.BootstrapDomains.Split(',')[0].Trim();
                    serverUrl = $"alwaysprint.{firstDomain}";
                }

                // Información de configuración de acciones
                string? actionConfigInfo = _actionEngine.GetConfigurationInfo();
                if (actionConfigInfo == "No hay configuración cargada")
                    actionConfigInfo = null;

                // Información del sistema operativo
                string osInfo = $"{Environment.OSVersion.VersionString} ({(Environment.Is64BitOperatingSystem ? "64-bit" : "32-bit")})";

                // Zona horaria
                var tz = TimeZoneInfo.Local;
                string utcOffset = tz.BaseUtcOffset.Hours >= 0
                    ? $"UTC+{tz.BaseUtcOffset.Hours}"
                    : $"UTC{tz.BaseUtcOffset.Hours}";
                string timezone = $"{utcOffset} ({tz.Id})";

                // Datos de Cloud (organización, workstation ID) — pueden no estar disponibles
                // ya que se almacenan en HKCU y el servicio corre como SYSTEM.
                // El Tray los registra después. Se deja null si no están disponibles.
                string? organizationName = null;
                string? organizationId = null;
                string? workstationId = null;

                // Intentar leer WorkstationId desde HKLM (si existe algún valor cacheado)
                try
                {
                    using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(RegistryConfigManager.RegistryPath, writable: false))
                    {
                        if (key != null)
                        {
                            workstationId = key.GetValue("WorkstationId", null) as string;
                            organizationName = key.GetValue("OrganizationName", null) as string;
                            organizationId = key.GetValue("OrganizationId", null) as string;
                        }
                    }
                }
                catch
                {
                    // Si no se puede leer, dejar null — no es crítico
                }

                AlwaysPrintLogger.WriteRootLog(
                    organizationName: organizationName,
                    organizationId: organizationId,
                    environment: environment,
                    serverUrl: serverUrl,
                    version: version,
                    hostname: hostname,
                    workstationId: workstationId,
                    localIp: localIp,
                    actionConfigInfo: actionConfigInfo,
                    osInfo: osInfo,
                    timezone: timezone);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"Error escribiendo Root Log: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
            }
        }

        private static bool IsDuplicateServiceRunning()
        {
            int ownPid = Process.GetCurrentProcess().Id;
            foreach (var p in Process.GetProcessesByName("AlwaysPrintService"))
                if (p.Id != ownPid) return true;
            return false;
        }

        private int KillExistingTray()
        {
            int count = 0;
            var processes = Process.GetProcessesByName("AlwaysPrintTray");
            if (processes.Length == 0) return 0;
            
            // Intentar cierre graceful: enviar señal vía pipe para que el Tray
            // oculte su NotifyIcon antes de morir (evita iconos fantasma en el tray)
            if (_pipeServer != null && _pipeServer.IsClientConnected)
            {
                try
                {
                    var shutdownMsg = PipeMessage.Create(MessageType.ServiceStopping);
                    _pipeServer.SendToClient(shutdownMsg);
                    // Dar 1.5 segundos para que el Tray procese y oculte el icono
                    Thread.Sleep(1500);
                }
                catch { /* Si falla el envío, proceder con kill directo */ }
            }
            
            // Forzar kill de los que no se cerraron voluntariamente
            foreach (var p in Process.GetProcessesByName("AlwaysPrintTray"))
            {
                try { p.Kill(); count++; } catch { /* already gone */ }
            }
            
            return count;
        }

        private static bool IsTrayRunning()
        {
            return Process.GetProcessesByName("AlwaysPrintTray").Length > 0;
        }

        public void TestStartFromConsole()  => OnStart(Array.Empty<string>());
        public void TestStopFromConsole()   => OnStop();
        
        // ── Gestión de Configuración de Acciones ────────────────────────────────
        
        /// <summary>
        /// Asegura que el directorio de configuración de acciones existe.
        /// Se ejecuta al inicio del servicio para que esté disponible antes de
        /// cualquier escritura o lectura.
        /// </summary>
        private void EnsureActionConfigDirectory()
        {
            try
            {
                string configDir = PipeConstants.ActionConfigDirectory;
                if (!Directory.Exists(configDir))
                {
                    Directory.CreateDirectory(configDir);
                    AlwaysPrintLogger.WriteInfo($"Directorio de configuración de acciones creado: {configDir}");
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"Error creando directorio de configuración de acciones: {ex.Message}", ex);
            }
        }

        /// <summary>
        /// Carga la configuración de acciones desde el archivo active.alwaysconfig.
        /// </summary>
        private void LoadActionConfiguration()
        {
            try
            {
                // Establecer variables de configuración desde AppConfiguration
                var cfg = _registry.Load();
                _actionEngine.SetConfigVariable("corporate_queue_name", cfg.CorporateQueueName);
                _actionEngine.SetConfigVariable("registry_path", @"HKLM\" + RegistryConfigManager.RegistryPath);
                // contingency_printer_ip se establece dinámicamente al activar contingencia
                // (se resuelve desde la configuración de la workstation o el parámetro del trigger)

                // Cargar variables desde resources.json (metadata de VLAN)
                LoadResourceVariables();
                
                if (File.Exists(ConfigFilePath))
                {
                    AlwaysPrintLogger.WriteInfo($"Cargando configuración de acciones desde {ConfigFilePath}");
                    
                    bool loaded = _actionEngine.LoadConfiguration(ConfigFilePath);
                    
                    if (loaded)
                    {
                        AlwaysPrintLogger.WriteInfo($"Configuración de acciones cargada: {_actionEngine.GetConfigurationInfo()}");
                        
                        // Ejecutar trigger OnServiceStart si existe
                        ExecuteActionTrigger(TriggerEvents.OnServiceStart);
                        
                        // Iniciar timer periódico si hay trigger OnScheduledTask configurado
                        StartScheduledTaskTimer();

                        // Iniciar watchdog de servicios si está configurado
                        StartServiceWatchdog();
                    }
                    else
                    {
                        AlwaysPrintLogger.WriteWarning("No se pudo cargar la configuración de acciones");
                    }
                }
                else
                {
                    AlwaysPrintLogger.WriteInfo($"No existe archivo de configuración de acciones: {ConfigFilePath}");
                    // Si previamente había una configuración cargada, limpiar el estado del engine.
                    // Esto cubre el caso donde el archivo fue eliminado (ej: cert invalidado por cambio de entorno).
                    _actionEngine.UnloadConfiguration();
                    StopScheduledTaskTimer();
                    _watchdog.Stop();
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"Error cargando configuración de acciones: {ex.Message}", ex);
            }
        }

        /// <summary>
        /// Carga variables desde resources.json (metadata de VLAN) en el ActionEngine.
        /// Cada clave del objeto vlan_metadata se establece como variable de configuración.
        /// </summary>
        private void LoadResourceVariables()
        {
            try
            {
                string resourcesPath = PipeConstants.ResourcesFilePath;
                if (!File.Exists(resourcesPath))
                    return;

                string json = File.ReadAllText(resourcesPath, System.Text.Encoding.UTF8);
                var obj = Newtonsoft.Json.Linq.JObject.Parse(json);

                // Cargar remote_queue_path directamente si existe
                var remoteQueuePath = obj["remote_queue_path"]?.ToString();
                if (!string.IsNullOrEmpty(remoteQueuePath))
                    _actionEngine.SetConfigVariable("remote_queue_path", remoteQueuePath!);

                // Cargar todas las claves de vlan_metadata como variables
                var metadata = obj["vlan_metadata"] as Newtonsoft.Json.Linq.JObject;
                if (metadata != null)
                {
                    foreach (var prop in metadata.Properties())
                    {
                        string value = prop.Value?.ToString() ?? "";
                        if (!string.IsNullOrEmpty(value))
                            _actionEngine.SetConfigVariable(prop.Name, value);
                    }
                }

                AlwaysPrintLogger.WriteInfo(
                    $"LoadResourceVariables: variables cargadas desde resources.json" +
                    (remoteQueuePath != null ? $" (remote_queue_path={remoteQueuePath})" : ""));
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning($"LoadResourceVariables: error leyendo resources.json: {ex.Message}");
            }
        }

        /// <summary>
        /// Recarga la configuración de acciones desde el archivo.
        /// Solo ejecuta OnConfigChange cuando hay un config previo cargado que cambió
        /// a una versión diferente. La primera carga no dispara OnConfigChange porque
        /// el Tray ya se actualizó sin necesidad de restart.
        /// </summary>
        public void ReloadActionConfiguration()
        {
            try
            {
                AlwaysPrintLogger.WriteInfo("Recargando configuración de acciones");
                
                // Guardar hash anterior para detectar si hubo cambio real
                string? previousHash = _actionEngine.LoadedConfigHash;
                
                LoadActionConfiguration();
                
                // Evaluar si corresponde ejecutar OnConfigChange
                string? newHash = _actionEngine.LoadedConfigHash;
                
                if (previousHash == null)
                {
                    // Primera carga — config cargada en memoria por primera vez.
                    // No ejecutar OnConfigChange (el Tray ya se actualizó sin necesidad de restart).
                    AlwaysPrintLogger.WriteInfo(
                        $"ReloadActionConfiguration: primera carga de config (hash={newHash?.Substring(0, 8)}). " +
                        "Omitiendo trigger OnConfigChange (no hay config previo que reemplazar).");
                    // SIEMPRE notificar al Tray para que reconstruya el submenú OnDemand,
                    // incluso en primera carga (el Tray necesita saber que hay config disponible).
                    NotifyTrayActionConfigChanged();
                    return;
                }
                
                if (previousHash == newHash)
                {
                    // Misma config recargada — no hay cambio real.
                    AlwaysPrintLogger.WriteInfo(
                        $"ReloadActionConfiguration: config sin cambios (hash={newHash?.Substring(0, 8)}). " +
                        "Omitiendo trigger OnConfigChange.");
                    return;
                }
                
                // Config cambió (previousHash != newHash, y previousHash no es null) — ejecutar OnConfigChange
                AlwaysPrintLogger.WriteInfo(
                    $"ReloadActionConfiguration: config cambió (previo={previousHash?.Substring(0, 8)}, nuevo={newHash?.Substring(0, 8)}). " +
                    "Ejecutando trigger OnConfigChange.");
                ExecuteActionTrigger(TriggerEvents.OnConfigChange);
                
                // Notificar al Tray para que reconstruya el submenú OnDemand
                NotifyTrayActionConfigChanged();
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"Error recargando configuración de acciones: {ex.Message}", ex);
            }
        }
        
        /// <summary>
        /// Envía un push ActionConfigChanged al Tray vía Named Pipe para que reconstruya
        /// el submenú OnDemand y actualice el StatusForm. Se invoca tanto en primera carga
        /// como en cambios de configuración.
        /// </summary>
        private void NotifyTrayActionConfigChanged()
        {
            try
            {
                if (_pipeServer == null || !_pipeServer.IsClientConnected)
                {
                    AlwaysPrintLogger.WriteInfo(
                        "NotifyTrayActionConfigChanged: pipe desconectado, notificación omitida (el Tray la recibirá al conectarse).");
                    return;
                }

                var msg = PipeMessage.Create(MessageType.ActionConfigChanged);
                bool sent = _pipeServer.SendToClient(msg);

                if (sent)
                    AlwaysPrintLogger.WriteInfo("NotifyTrayActionConfigChanged: notificación enviada al Tray.");
                else
                    AlwaysPrintLogger.WriteWarning(
                        "NotifyTrayActionConfigChanged: no se pudo enviar notificación al Tray.",
                        AlwaysPrintLogger.EvtGenericWarning);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"NotifyTrayActionConfigChanged: error al enviar notificación. {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
            }
        }
        
        /// <summary>
        /// Inicia o reinicia el watchdog de servicios según la configuración cargada.
        /// Si la config no tiene sección service_watchdog o está deshabilitada, detiene el watchdog.
        /// </summary>
        private void StartServiceWatchdog()
        {
            var watchdogConfig = _actionEngine.GetServiceWatchdogConfig();
            if (watchdogConfig != null && watchdogConfig.Enabled)
            {
                _watchdog.Start(watchdogConfig);
            }
            else
            {
                _watchdog.Stop();
            }
        }

        /// <summary>
        /// Inicia el timer periódico para ejecutar triggers OnScheduledTask.
        /// Lee el interval_seconds del trigger configurado en el .alwaysconfig.
        /// Mínimo 60 segundos. Si no hay trigger OnScheduledTask, no hace nada.
        /// </summary>
        private void StartScheduledTaskTimer()
        {
            // Detener timer anterior si existe (recarga de configuración)
            StopScheduledTaskTimer();

            if (!_actionEngine.HasTrigger(TriggerEvents.OnScheduledTask))
                return;

            // Obtener el intervalo del trigger configurado
            int intervalSeconds = _actionEngine.GetTriggerIntervalSeconds(TriggerEvents.OnScheduledTask);
            if (intervalSeconds < 60)
                intervalSeconds = 60; // Mínimo 60 segundos

            AlwaysPrintLogger.WriteInfo(
                $"ScheduledTask: timer periódico iniciado. Intervalo={intervalSeconds}s");

            _scheduledTaskTimer = new System.Threading.Timer(
                OnScheduledTaskTick,
                null,
                TimeSpan.FromSeconds(intervalSeconds),  // Primera ejecución después del intervalo
                TimeSpan.FromSeconds(intervalSeconds));  // Repetir cada intervalo
        }

        /// <summary>
        /// Detiene el timer periódico de OnScheduledTask.
        /// </summary>
        private void StopScheduledTaskTimer()
        {
            if (_scheduledTaskTimer != null)
            {
                _scheduledTaskTimer.Dispose();
                _scheduledTaskTimer = null;
            }
        }

        /// <summary>
        /// Callback del timer periódico. Ejecuta el trigger OnScheduledTask.
        /// </summary>
        private void OnScheduledTaskTick(object? state)
        {
            if (_cts.IsCancellationRequested) return;

            try
            {
                ExecuteActionTrigger(TriggerEvents.OnScheduledTask);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"ScheduledTask: error en ejecución periódica: {ex.Message}", ex);
            }
        }

        /// <summary>
        /// Ejecuta un trigger de acciones si está configurado.
        /// </summary>
        private void ExecuteActionTrigger(string eventName)
        {
            try
            {
                if (_actionEngine.HasTrigger(eventName))
                {
                    AlwaysPrintLogger.WriteInfo($"Ejecutando trigger de acciones para evento: {eventName}");
                    
                    bool success = _actionEngine.ExecuteTrigger(eventName);
                    
                    if (success)
                    {
                        AlwaysPrintLogger.WriteInfo($"Trigger '{eventName}' ejecutado exitosamente");
                    }
                    else
                    {
                        AlwaysPrintLogger.WriteWarning($"Trigger '{eventName}' completado con errores");
                    }
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"Error ejecutando trigger '{eventName}': {ex.Message}", ex);
            }
        }
    }
}
