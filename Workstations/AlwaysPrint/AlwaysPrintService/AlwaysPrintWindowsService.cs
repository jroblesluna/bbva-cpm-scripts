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
        public const  string ServiceName = "AlwaysPrintService";
        private const int    TrayTimeoutSeconds = 300;   // 5 minutes
        private const int    UserPollSeconds    = 60;

        // ── Components ──────────────────────────────────────────────────────────
        private readonly ServiceStateMachine   _state    = new ServiceStateMachine();
        private readonly RegistryConfigManager _registry = new RegistryConfigManager();
        private readonly TaskQueueManager      _taskQueue = new TaskQueueManager();
        private MessageDispatcher?   _dispatcher;
        private PipeServer?          _pipeServer;

        // Tray handshake gate.
        private readonly ManualResetEventSlim _trayInitGate = new ManualResetEventSlim(false);

        // Background worker thread for startup orchestration.
        private Thread? _startupThread;
        private CancellationTokenSource _cts = new CancellationTokenSource();

        // Tells SCM that session-change notifications should be delivered.
        private const bool CanHandleSessionChangeEvent = true;

        public AlwaysPrintWindowsService()
        {
            base.ServiceName         = ServiceName;
            base.CanStop             = true;
            base.CanShutdown         = true;
            base.CanHandleSessionChangeEvent = CanHandleSessionChangeEvent;
            base.CanPauseAndContinue = false;
            base.AutoLog             = false;   // we write our own events
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
            _pipeServer?.Stop();
            _taskQueue.Stop();
            KillExistingTray();
            _state.Transition(ServiceState.Stopped);
            EventLogWriter.WriteInfo("AlwaysPrintService stopped.", EventLogWriter.EvtServiceStopped);
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
                // Wake the startup thread that is polling for a user.
                Monitor.PulseAll(_cts);
            }

            if (userLeft && (_state.Is(ServiceState.TrayStarted) || _state.Is(ServiceState.Running)))
            {
                EventLogWriter.WriteWarning("User session ended. Killing Tray and waiting for next user.",
                    EventLogWriter.EvtTrayKilled);
                KillExistingTray();
                _trayInitGate.Reset();
                _state.Transition(ServiceState.WaitingUser);
            }
        }

        // ── Startup sequence ────────────────────────────────────────────────────

        private void RunStartupSequence()
        {
            try
            {
                EventLogWriter.WriteInfo("AlwaysPrintService starting...", EventLogWriter.EvtServiceStarted);
                _state.Transition(ServiceState.Starting);

                // 1. Guard against duplicate service instances.
                if (IsDuplicateServiceRunning())
                {
                    EventLogWriter.WriteWarning("Duplicate AlwaysPrintService instance detected. Aborting start.",
                        EventLogWriter.EvtDuplicateInstance);
                    Stop();
                    return;
                }

                // 2. Kill any orphaned Tray instances.
                int killedTrays = KillExistingTray();
                if (killedTrays > 0)
                    EventLogWriter.WriteWarning($"Killed {killedTrays} orphaned AlwaysPrintTray instance(s).",
                        EventLogWriter.EvtTrayKilled);
                else
                    EventLogWriter.WriteInfo("No orphaned Tray instances found.", EventLogWriter.EvtTrayKilled);

                // 3. Ensure registry defaults and load config.
                _registry.EnsureDefaults();
                var cfg = _registry.Load();

                // 4. Initialize task queue.
                _taskQueue.Start();
                int cleared = _taskQueue.ClearAll();
                if (cleared > 0)
                    EventLogWriter.WriteWarning($"Cleared {cleared} stale tasks from queue on startup.",
                        EventLogWriter.EvtQueueCleared);
                else
                    EventLogWriter.WriteInfo("Task queue initialized empty.", EventLogWriter.EvtQueueCleared);

                // 5. Start Named Pipe server.
                _dispatcher = new MessageDispatcher(_registry, _taskQueue, _state);
                _dispatcher.TrayInitializedReceived += OnTrayInitialized;
                _pipeServer = new PipeServer(_dispatcher);
                _pipeServer.Start();

                // 6. Wait for an interactive user.
                _state.Transition(ServiceState.WaitingUser);
                WaitForUser();
                if (_cts.IsCancellationRequested) return;

                // 7. Launch Tray in the user's session.
                _state.Transition(ServiceState.TrayStarting);
                LaunchTray();

                // 8. Wait for Tray handshake.
                bool trayOk = _trayInitGate.Wait(TimeSpan.FromSeconds(TrayTimeoutSeconds), _cts.Token);
                if (!trayOk)
                {
                    _state.Transition(ServiceState.TrayError);
                    EventLogWriter.WriteError(
                        "Tray did not confirm initialization within the timeout. Stopping service for SCM recovery.",
                        EventLogWriter.EvtTrayError);
                    Stop();
                    return;
                }

                _state.Transition(ServiceState.TrayStarted);
                _state.Transition(ServiceState.Running);

                // 9. Periodic monitoring loop.
                MonitoringLoop(cfg.PendingTaskPollingMinutes);
            }
            catch (OperationCanceledException)
            {
                EventLogWriter.WriteInfo("Startup sequence cancelled.");
            }
            catch (Exception ex)
            {
                EventLogWriter.WriteError("Fatal error in startup sequence.", ex);
                Stop();
            }
        }

        private void WaitForUser()
        {
            while (!SessionMonitor.IsUserLoggedIn())
            {
                if (_cts.IsCancellationRequested) return;
                EventLogWriter.WriteInfo("Waiting for interactive user session...", EventLogWriter.EvtWaitingUser);
                _cts.Token.WaitHandle.WaitOne(TimeSpan.FromSeconds(UserPollSeconds));
            }
            EventLogWriter.WriteInfo("Interactive user session detected.", EventLogWriter.EvtUserDetected);
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

        private void MonitoringLoop(int pollMinutes)
        {
            while (!_cts.IsCancellationRequested)
            {
                // Re-read polling interval in case it was updated via config.
                var cfg = _registry.Load();
                int interval = Math.Max(1, cfg.PendingTaskPollingMinutes);

                // Heartbeat log.
                EventLogWriter.WriteInfo(
                    $"AlwaysPrint running. State={_state.Current} QueueDepth={_taskQueue.PendingCount}",
                    EventLogWriter.EvtServiceStarted);

                _cts.Token.WaitHandle.WaitOne(TimeSpan.FromMinutes(interval));
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
