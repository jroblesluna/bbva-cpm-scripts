using System;
using System.Diagnostics;
using System.IO;
using System.ServiceProcess;
using System.Threading;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrint.Shared.Models;
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
        private MessageDispatcher?   _dispatcher;
        private PipeServer?          _pipeServer;

        // Gate de handshake con el Tray.
        private readonly ManualResetEventSlim _trayInitGate   = new ManualResetEventSlim(false);

        // Gate para despertar WaitForUser cuando llega un evento de sesión.
        private readonly ManualResetEventSlim _userArrivedGate = new ManualResetEventSlim(false);

        private Thread? _startupThread;
        private CancellationTokenSource _cts = new CancellationTokenSource();

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
                               reason == SessionChangeReason.ConsoleConnect  ||
                               reason == SessionChangeReason.SessionUnlock;

            bool userLeft = reason == SessionChangeReason.SessionLogoff     ||
                            reason == SessionChangeReason.ConsoleDisconnect;

            if (userArrived && _state.Is(ServiceState.WaitingUser))
                _userArrivedGate.Set();

            if (userLeft && (_state.Is(ServiceState.TrayStarted) || _state.Is(ServiceState.Running)))
            {
                AlwaysPrintLogger.WriteWarning("Sesión de usuario finalizada. Eliminando Tray y esperando nueva sesión.",
                    AlwaysPrintLogger.EvtTrayKilled);
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
                int killedTrays = KillExistingTray();
                if (killedTrays > 0)
                    AlwaysPrintLogger.WriteWarning($"Se eliminaron {killedTrays} instancia(s) huérfana(s) de AlwaysPrintTray.",
                        AlwaysPrintLogger.EvtTrayKilled);
                else
                    AlwaysPrintLogger.WriteInfo("No se encontraron instancias huérfanas del Tray.", AlwaysPrintLogger.EvtTrayKilled);

                // 3. Asegurar valores por defecto en registro.
                _registry.EnsureDefaults();

                // 4. Inicializar cola de tareas.
                _taskQueue.Start();
                int cleared = _taskQueue.ClearAll();
                if (cleared > 0)
                    AlwaysPrintLogger.WriteWarning($"Se descartaron {cleared} tarea(s) pendiente(s) al iniciar.",
                        AlwaysPrintLogger.EvtQueueCleared);
                else
                    AlwaysPrintLogger.WriteInfo("Cola de tareas inicializada vacía.", AlwaysPrintLogger.EvtQueueCleared);

                // 5. Iniciar servidor Named Pipe.
                _dispatcher = new MessageDispatcher(_registry, _taskQueue, _state);
                _dispatcher.TrayInitializedReceived += OnTrayInitialized;
                _pipeServer = new PipeServer(_dispatcher);
                _pipeServer.Start();

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
        }

        private void MonitoringLoop()
        {
            while (!_cts.IsCancellationRequested && _state.Is(ServiceState.Running))
            {
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

        private static bool IsDuplicateServiceRunning()
        {
            int ownPid = Process.GetCurrentProcess().Id;
            foreach (var p in Process.GetProcessesByName("AlwaysPrintService"))
                if (p.Id != ownPid) return true;
            return false;
        }

        private static int KillExistingTray()
        {
            int count = 0;
            foreach (var p in Process.GetProcessesByName("AlwaysPrintTray"))
                try { p.Kill(); count++; } catch { /* already gone */ }
            return count;
        }

        public void TestStartFromConsole()  => OnStart(Array.Empty<string>());
        public void TestStopFromConsole()   => OnStop();
    }
}
