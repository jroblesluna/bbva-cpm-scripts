using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.ServiceProcess;
using System.Threading;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintService.Watchdog
{
    /// <summary>
    /// Monitorea periódicamente los servicios Windows definidos en la sección
    /// service_watchdog del .alwaysconfig. Si un servicio está detenido y la
    /// acción es "restart", intenta reiniciarlo respetando el límite por hora.
    /// 
    /// Ciclo de vida:
    /// - Start(config): inicia el timer con el intervalo configurado
    /// - Stop(): detiene el timer (al recargar config o detener el Service)
    /// - El timer ejecuta CheckServices() en cada tick
    /// 
    /// Thread-safe: usa ConcurrentDictionary para contadores de reinicio.
    /// </summary>
    public sealed class ServiceWatchdogRunner : IDisposable
    {
        private Timer? _timer;
        private ServiceWatchdogConfig? _config;
        private bool _disposed;

        // Contadores de reinicios por servicio: {service_name: lista de timestamps de reinicios}
        private readonly ConcurrentDictionary<string, List<DateTime>> _restartHistory = new();

        // Servicios con un reinicio en curso ahora mismo (evita que dos ticks del timer
        // se pisen si un reinicio tarda más que el intervalo configurado).
        private readonly ConcurrentDictionary<string, byte> _restartInProgress = new();

        /// <summary>
        /// Inicia el watchdog con la configuración proporcionada.
        /// Si ya estaba corriendo, lo detiene primero.
        /// </summary>
        public void Start(ServiceWatchdogConfig config)
        {
            Stop();

            if (!config.Enabled || config.Services.Count == 0)
            {
                AlwaysPrintLogger.WriteInfo(
                    "ServiceWatchdog: deshabilitado o sin servicios configurados. No se inicia.");
                return;
            }

            _config = config;

            // Validar intervalo mínimo de 60 segundos
            int intervalMs = Math.Max(60, config.IntervalSeconds) * 1000;

            // Primer tick después de 30 segundos (dar tiempo a que servicios inicien)
            _timer = new Timer(OnTick, null, 30_000, intervalMs);

            string serviceNames = string.Join(", ", config.Services.Select(s => s.Name));
            AlwaysPrintLogger.WriteInfo(
                $"ServiceWatchdog: iniciado. Intervalo={config.IntervalSeconds}s, " +
                $"Servicios=[{serviceNames}]");
        }

        /// <summary>
        /// Detiene el watchdog. Seguro llamar múltiples veces.
        /// </summary>
        public void Stop()
        {
            if (_timer != null)
            {
                _timer.Dispose();
                _timer = null;
                AlwaysPrintLogger.WriteInfo(
                    "ServiceWatchdog: detenido.");
            }
            _config = null;
        }

        /// <summary>
        /// Callback del timer. Verifica el estado de cada servicio configurado.
        /// </summary>
        private void OnTick(object? state)
        {
            if (_config == null || _disposed) return;

            // Leer estado de contingencia una vez por tick (no por cada servicio)
            bool contingencyActive = IsContingencyActive();

            foreach (var entry in _config.Services)
            {
                try
                {
                    // Filtrar por monitor_when
                    if (!ShouldMonitor(entry, contingencyActive))
                        continue;

                    CheckService(entry);
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteError(
                        $"ServiceWatchdog: error verificando '{entry.Name}': {ex.Message}",
                        AlwaysPrintLogger.EvtGenericError);
                }
            }
        }

        /// <summary>
        /// Determina si un servicio debe monitorearse según el modo actual.
        /// </summary>
        private static bool ShouldMonitor(WatchdogServiceEntry entry, bool contingencyActive)
        {
            switch (entry.MonitorWhen?.ToLowerInvariant())
            {
                case "normal":
                    return !contingencyActive;
                case "contingency":
                    return contingencyActive;
                case "always":
                default:
                    return true;
            }
        }

        /// <summary>
        /// Lee el semáforo ContingencyEnabled del registro.
        /// Retorna true si contingencia está activa (valor = 1).
        /// </summary>
        private static bool IsContingencyActive()
        {
            try
            {
                using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                    RegistryConfigManager.RegistryPath);
                if (key == null) return false;
                var val = key.GetValue("ContingencyEnabled");
                return val != null && val.ToString() == "1";
            }
            catch
            {
                return false; // En caso de error, asumir modo normal
            }
        }

        /// <summary>
        /// Verifica un servicio individual y toma acción si está detenido.
        /// </summary>
        private void CheckService(WatchdogServiceEntry entry)
        {
            ServiceControllerStatus status;

            try
            {
                using var sc = new ServiceController(entry.Name);
                status = sc.Status;
            }
            catch (InvalidOperationException)
            {
                // Servicio no existe en esta máquina — no es un error del watchdog
                return;
            }

            string? stalledFile = status == ServiceControllerStatus.Running && entry.StallCheck != null
                ? FindStalledJobFile(entry.StallCheck)
                : null;

            if (status == ServiceControllerStatus.Running && stalledFile == null)
            {
                // Servicio OK, nada que hacer
                return;
            }

            // Servicio NO está corriendo, o está corriendo pero con trabajos atascados
            string statusStr = stalledFile != null
                ? $"Running con trabajo atascado ({stalledFile})"
                : status.ToString();
            AlwaysPrintLogger.WriteWarning(
                $"ServiceWatchdog: '{entry.Name}' detectado en estado '{statusStr}'.",
                AlwaysPrintLogger.EvtGenericWarning);

            if (entry.ActionOnDown == "log_only")
            {
                // Solo loguear, no reiniciar
                return;
            }

            // Verificar límite de reinicios por hora
            if (entry.MaxRestartsPerHour > 0 && IsRateLimited(entry.Name, entry.MaxRestartsPerHour))
            {
                AlwaysPrintLogger.WriteWarning(
                    $"ServiceWatchdog: '{entry.Name}' excedió el límite de {entry.MaxRestartsPerHour} " +
                    "reinicios/hora. No se reintenta hasta que pase el período.",
                    AlwaysPrintLogger.EvtGenericWarning);
                return;
            }

            // Evitar que dos ticks intenten reiniciar el mismo servicio a la vez
            if (!_restartInProgress.TryAdd(entry.Name, 0))
            {
                AlwaysPrintLogger.WriteInfo(
                    $"ServiceWatchdog: '{entry.Name}' ya tiene un reinicio en curso. Se omite este tick.");
                return;
            }

            try
            {
                TryRestartService(entry, status, stalledButRunning: stalledFile != null);
            }
            finally
            {
                _restartInProgress.TryRemove(entry.Name, out _);
            }
        }

        /// <summary>
        /// Intenta poner el servicio en estado Running. Si estaba "Running" pero atascado
        /// (trabajos viejos en su carpeta de pre), primero lo detiene.
        /// </summary>
        private void TryRestartService(WatchdogServiceEntry entry, ServiceControllerStatus status, bool stalledButRunning)
        {
            try
            {
                using var sc = new ServiceController(entry.Name);

                // Si está en estado intermedio, esperar un poco
                if (status == ServiceControllerStatus.StopPending ||
                    status == ServiceControllerStatus.StartPending)
                {
                    sc.WaitForStatus(
                        status == ServiceControllerStatus.StopPending
                            ? ServiceControllerStatus.Stopped
                            : ServiceControllerStatus.Running,
                        TimeSpan.FromSeconds(15));

                    sc.Refresh();
                    if (sc.Status == ServiceControllerStatus.Running)
                    {
                        AlwaysPrintLogger.WriteInfo(
                            $"ServiceWatchdog: '{entry.Name}' completó transición y ahora está Running.");
                        return;
                    }
                }

                if (stalledButRunning)
                {
                    sc.Stop();
                    sc.WaitForStatus(ServiceControllerStatus.Stopped, TimeSpan.FromSeconds(30));
                }

                // Iniciar el servicio
                sc.Start();
                sc.WaitForStatus(ServiceControllerStatus.Running, TimeSpan.FromSeconds(30));

                RecordRestart(entry.Name);

                AlwaysPrintLogger.WriteInfo(
                    $"ServiceWatchdog: '{entry.Name}' reiniciado exitosamente.");
            }
            catch (System.ServiceProcess.TimeoutException)
            {
                AlwaysPrintLogger.WriteError(
                    $"ServiceWatchdog: timeout reiniciando '{entry.Name}' (30s).",
                    AlwaysPrintLogger.EvtGenericError);
            }
            catch (InvalidOperationException ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"ServiceWatchdog: no se pudo reiniciar '{entry.Name}': {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
            }
        }

        /// <summary>
        /// Busca un archivo "atascado" (sin modificarse por más de stale_after_seconds)
        /// dentro de la carpeta de trabajos de cada usuario. Retorna la primera ruta
        /// encontrada, o null si no hay ninguna o la config/carpetas no existen.
        /// </summary>
        private static string? FindStalledJobFile(StallCheckConfig cfg)
        {
            if (string.IsNullOrEmpty(cfg.BasePath) || !Directory.Exists(cfg.BasePath))
                return null;

            var threshold = DateTime.UtcNow.AddSeconds(-Math.Max(1, cfg.StaleAfterSeconds));

            try
            {
                foreach (var userDir in Directory.EnumerateDirectories(cfg.BasePath))
                {
                    string jobsPath = Path.Combine(userDir, cfg.RelativePath);
                    if (!Directory.Exists(jobsPath))
                        continue;

                    string? stale = Directory.EnumerateFiles(jobsPath)
                        .FirstOrDefault(file => File.GetLastWriteTimeUtc(file) < threshold);
                    if (stale != null)
                        return stale;
                }
            }
            catch (IOException)
            {
                // Carpeta en uso/removida entre el listado y la lectura — ignorar este ciclo
            }
            catch (UnauthorizedAccessException)
            {
                // Sin permisos sobre alguna subcarpeta — ignorar este ciclo
            }

            return null;
        }

        /// <summary>
        /// Verifica si se excedió el límite de reinicios por hora para un servicio.
        /// </summary>
        private bool IsRateLimited(string serviceName, int maxPerHour)
        {
            var history = _restartHistory.GetOrAdd(serviceName, _ => new List<DateTime>());
            var oneHourAgo = DateTime.UtcNow.AddHours(-1);

            lock (history)
            {
                // Limpiar entradas antiguas
                history.RemoveAll(t => t < oneHourAgo);
                return history.Count >= maxPerHour;
            }
        }

        /// <summary>
        /// Registra un reinicio exitoso en el historial.
        /// </summary>
        private void RecordRestart(string serviceName)
        {
            var history = _restartHistory.GetOrAdd(serviceName, _ => new List<DateTime>());
            lock (history)
            {
                history.Add(DateTime.UtcNow);
            }
        }

        public void Dispose()
        {
            if (!_disposed)
            {
                _disposed = true;
                Stop();
            }
        }
    }
}
