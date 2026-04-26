using System;
using System.Diagnostics;
using System.IO;
using System.ServiceProcess;
using System.Threading;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
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
        private const int TrayTimeoutSeconds = 300;   // 5 minutos
        private const int UserPollSeconds    = 60;

        // ── Components ──────────────────────────────────────────────────────────
        private readonly ServiceStateMachine   _state    = new ServiceStateMachine();
        private readonly RegistryConfigManager _registry = new RegistryConfigManager();
        private readonly TaskQueueManager      _taskQueue = new TaskQueueManager();
        private MessageDispatcher?   _dispatcher;
        private PipeServer?          _pipeServer;

        // Tray handshake gate.
        private readonly ManualResetEventSlim _trayInitGate = new ManualResetEventSlim(false);

        // Gate para despertar WaitForUser cuando llega un evento de sesión antes del timeout.
        private readonly ManualResetEventSlim _userArrivedGate = new ManualResetEventSlim(false);

        // Background worker thread for startup orchestration.
        private Thread? _startupThread;
        private CancellationTokenSource _cts = new CancellationTokenSource();

        // Tells SCM that session-change notifications should be delivered.
        // 'new' suprime CS0108 — ocultamos intencionalmente la propiedad heredada para
        // definir la constante en tiempo de compilación.
        private new const bool CanHandleSessionChangeEvent = true;

        public AlwaysPrintWindowsService()
        {
            base.ServiceName                 = ServiceName;
            base.CanStop                     = true;
            base.CanShutdown                 = true;
            base.CanHandleSessionChangeEvent = CanHandleSessionChangeEvent;
            base.CanPauseAndContinue         = false;
            base.AutoLog                     = false;   // escribimos nuestros propios eventos
        }

        // ── Service entry points ────────────────────────────────────────────────

        protected override void OnStart(string[] args)
        {
            // Perform expensive startup off the SCM thread to avoid 30-second timeout.
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
            _userArrivedGate.Set();   // desbloquea WaitForUser si está esperando
            _pipeServer?.Stop();
            _taskQueue.Stop();
            KillExistingTray();
            _state.Transition(ServiceState.Stopped);
            EventLogWriter.WriteInfo("AlwaysPrintService detenido.", EventLogWriter.EvtServiceStopped);
        }

        protected override void OnShutdown()
        {
            OnStop();
        }

        protected override void OnSessionChange(SessionChangeDescription changeDescription)
        {
            EventLogWriter.WriteInfo(
                $"Session change: {SessionMonitor.DescribeReason(changeDescription.Reason)} (session {changeDescription.SessionId})",
                EventLogWriter.EvtUserDetected);

            var reason = changeDescription.Reason;
            bool userArrived = reason == SessionChangeReason.SessionLogon ||
                               reason == SessionChangeReason.ConsoleConnect ||
                               reason == SessionChangeReason.SessionUnlock;

            bool userLeft = reason == SessionChangeReason.SessionLogoff ||
                            reason == SessionChangeReason.ConsoleDisconnect;

            if (userArrived && _state.Is(ServiceState.WaitingUser))
            {
                // Despierta WaitForUser inmediatamente sin esperar el timeout de polling.
                _userArrivedGate.Set();
            }

            if (userLeft && (_state.Is(ServiceState.TrayStarted) || _state.Is(ServiceState.Running)))
            {
                EventLogWriter.WriteWarning("Sesión de usuario finalizada. Eliminando Tray y esperando nueva sesión.",
                    EventLogWriter.EvtTrayKilled);
                KillExistingTray();
                _trayInitGate.Reset();
                _state.Transition(ServiceState.WaitingUser);
                // Despierta MonitoringLoop para que detecte el cambio de estado y salga.
                _userArrivedGate.Set();
            }
        }

        // ── Startup sequence ────────────────────────────────────────────────────

        private void RunStartupSequence()
        {
            try
            {
                EventLogWriter.WriteInfo("AlwaysPrintService iniciando...", EventLogWriter.EvtServiceStarted);
                _state.Transition(ServiceState.Starting);

                // 1. Guardia contra instancias duplicadas del servicio.
                if (IsDuplicateServiceRunning())
                {
                    EventLogWriter.WriteWarning("Instancia duplicada de AlwaysPrintService detectada. Abortando inicio.",
                        EventLogWriter.EvtDuplicateInstance);
                    Stop();
                    return;
                }

                // 2. Matar instancias huérfanas del Tray.
                int killedTrays = KillExistingTray();
                if (killedTrays > 0)
                    EventLogWriter.WriteWarning($"Se eliminaron {killedTrays} instancia(s) huérfana(s) de AlwaysPrintTray.",
                        EventLogWriter.EvtTrayKilled);
                else
                    EventLogWriter.WriteInfo("No se encontraron instancias huérfanas del Tray.", EventLogWriter.EvtTrayKilled);

                // 3. Asegurar valores por defecto en registro y cargar configuración.
                _registry.EnsureDefaults();

                // 4. Inicializar cola de tareas.
                _taskQueue.Start();
                int cleared = _taskQueue.ClearAll();
                if (cleared > 0)
                    EventLogWriter.WriteWarning($"Se descartaron {cleared} tarea(s) pendiente(s) al iniciar.",
                        EventLogWriter.EvtQueueCleared);
                else
                    EventLogWriter.WriteInfo("Cola de tareas inicializada vacía.", EventLogWriter.EvtQueueCleared);

                // 5. Iniciar servidor Named Pipe.
                _dispatcher = new MessageDispatcher(_registry, _taskQueue, _state);
                _dispatcher.TrayInitializedReceived += OnTrayInitialized;
                _pipeServer = new PipeServer(_dispatcher);
                _pipeServer.Start();

                // 6. Bucle principal: esperar usuario → lanzar Tray → monitorear.
                //    Se repite tras cada logoff para relanzar el Tray en la siguiente sesión.
                RunSessionLoop();
            }
            catch (OperationCanceledException)
            {
                EventLogWriter.WriteInfo("Secuencia de inicio cancelada.");
            }
            catch (Exception ex)
            {
                EventLogWriter.WriteError("Error fatal en la secuencia de inicio.", ex);
                Stop();
            }
        }

        /// <summary>
        /// Bucle que gestiona el ciclo completo de sesión de usuario:
        /// WaitingUser → TrayStarting → TrayStarted → Running → (logoff) → WaitingUser → …
        /// Se repite indefinidamente hasta que se cancele el servicio.
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

                // ── Esperar handshake del Tray (máx. 5 min) ─────────────────────
                bool trayOk = _trayInitGate.Wait(TimeSpan.FromSeconds(TrayTimeoutSeconds), _cts.Token);
                if (_cts.IsCancellationRequested) return;

                if (!trayOk)
                {
                    _state.Transition(ServiceState.TrayError);
                    EventLogWriter.WriteError(
                        "El Tray no confirmó la inicialización en el tiempo límite. Deteniendo el servicio para recuperación SCM.",
                        EventLogWriter.EvtTrayError);
                    Stop();
                    return;
                }

                _state.Transition(ServiceState.TrayStarted);
                _state.Transition(ServiceState.Running);

                // ── Bucle de monitoreo: activo mientras el usuario esté en sesión ─
                MonitoringLoop();

                // Si llegamos aquí sin cancelación, fue un logoff → volver al inicio del bucle.
                if (!_cts.IsCancellationRequested)
                    EventLogWriter.WriteInfo("Sesión de usuario finalizada. Esperando nueva sesión.",
                        EventLogWriter.EvtWaitingUser);
            }
        }

        private void WaitForUser()
        {
            while (!SessionMonitor.IsUserLoggedIn())
            {
                if (_cts.IsCancellationRequested) return;
                EventLogWriter.WriteInfo("Esperando sesión interactiva de usuario...", EventLogWriter.EvtWaitingUser);

                // Espera hasta UserPollSeconds o hasta que OnSessionChange señale _userArrivedGate.
                // WaitAny devuelve el índice del handle que se señalizó primero.
                int signaled = WaitHandle.WaitAny(
                    new[] { _userArrivedGate.WaitHandle, _cts.Token.WaitHandle },
                    TimeSpan.FromSeconds(UserPollSeconds));

                _userArrivedGate.Reset();

                if (signaled == 1) return; // CancellationToken señalizado → salir
            }
            EventLogWriter.WriteInfo("Sesión interactiva de usuario detectada.", EventLogWriter.EvtUserDetected);
        }

        private void LaunchTray()
        {
            string trayExe = Path.Combine(
                Path.GetDirectoryName(Process.GetCurrentProcess().MainModule!.FileName)!,
                "AlwaysPrintTray.exe");

            bool ok = InteractiveProcessLauncher.Launch(trayExe);
            if (!ok)
                EventLogWriter.WriteError($"Failed to launch Tray from '{trayExe}'.", EventLogWriter.EvtTrayError);
        }

        private void OnTrayInitialized(bool success, string? details)
        {
            if (success)
                _trayInitGate.Set();
            else
                EventLogWriter.WriteWarning($"Tray reported failed initialization: {details}", EventLogWriter.EvtTrayError);
        }

        private void MonitoringLoop()
        {
            while (!_cts.IsCancellationRequested && _state.Is(ServiceState.Running))
            {
                // Re-leer intervalo por si fue actualizado vía configuración.
                var cfg = _registry.Load();
                int interval = Math.Max(1, cfg.PendingTaskPollingMinutes);

                // Heartbeat.
                EventLogWriter.WriteInfo(
                    $"AlwaysPrint activo. Estado={_state.Current} TareasPendientes={_taskQueue.PendingCount}",
                    EventLogWriter.EvtServiceStarted);

                // Espera el intervalo o hasta que _userArrivedGate sea señalizado (logoff/logon).
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
            var others = Process.GetProcessesByName("AlwaysPrintService");
            foreach (var p in others)
            {
                if (p.Id != ownPid) return true;
            }
            return false;
        }

        private static int KillExistingTray()
        {
            int count = 0;
            foreach (var p in Process.GetProcessesByName("AlwaysPrintTray"))
            {
                try { p.Kill(); count++; } catch { /* already gone */ }
            }
            return count;
        }

        // ── Console debug helpers (for /console mode) ───────────────────────────

        public void TestStartFromConsole()  => OnStart(Array.Empty<string>());
        public void TestStopFromConsole()   => OnStop();
    }
}
