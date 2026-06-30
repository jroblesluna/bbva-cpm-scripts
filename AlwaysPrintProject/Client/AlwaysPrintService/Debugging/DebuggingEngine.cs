using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using AlwaysPrint.Shared.Logging;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintService.Debugging
{
    /// <summary>
    /// Motor principal de debugging. Orquesta el ciclo de vida completo
    /// de una sesión de captura: inicio, monitoreo, finalización y empaquetado.
    /// Solo permite una sesión activa a la vez.
    /// Máximo hard-limit: 300 segundos (5 minutos).
    /// </summary>
    public class DebuggingEngine
    {
        private const int MAX_DURATION_SECONDS = 300;

        private static readonly string DebugBasePath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
            "AlwaysPrint", "Debug");
        private const long MAX_FOLDER_SIZE_BYTES = 50L * 1024 * 1024; // 50MB

        private DebuggingSession? _activeSession;
        private Timer? _durationTimer;
        private readonly object _lock = new object();

        /// <summary>Indica si hay una sesión de debugging activa.</summary>
        public bool HasActiveSession => _activeSession != null;

        /// <summary>ID de la sesión activa (null si no hay).</summary>
        public string? ActiveDebuggingId => _activeSession?.DebuggingId;

        /// <summary>
        /// Evento disparado cuando la captura finaliza (timeout o stop manual).
        /// El handler debe enviar la notificación debugging_ready al backend.
        /// </summary>
        public event Action<string, long>? OnCaptureComplete;

        /// <summary>
        /// Evento disparado cuando ocurre un error durante la captura.
        /// El handler debe enviar debugging_error al backend.
        /// </summary>
        public event Action<string, string>? OnCaptureError;

        /// <summary>
        /// Inicia una nueva sesión de debugging.
        /// </summary>
        /// <param name="debuggingId">UUID único generado por el backend.</param>
        /// <param name="profile">Definición del perfil (targets a monitorear).</param>
        /// <param name="durationSeconds">Duración configurada (15-300s).</param>
        /// <returns>True si se inició correctamente, false si ya hay una activa.</returns>
        public bool StartSession(string debuggingId, JObject profile, int durationSeconds)
        {
            lock (_lock)
            {
                if (_activeSession != null)
                {
                    AlwaysPrintLogger.WriteWarning(
                        $"DebuggingEngine: Ya hay una sesión activa ({_activeSession.DebuggingId}). " +
                        $"No se puede iniciar {debuggingId}.");
                    return false;
                }

                // Enforce hard max
                int effectiveDuration = Math.Min(durationSeconds, MAX_DURATION_SECONDS);

                try
                {
                    // Crear carpeta temporal
                    string basePath = Path.Combine(DebugBasePath, debuggingId);
                    Directory.CreateDirectory(basePath);

                    var session = new DebuggingSession
                    {
                        DebuggingId = debuggingId,
                        Profile = profile,
                        DurationSeconds = effectiveDuration,
                        StartTime = DateTime.UtcNow,
                        FolderPath = basePath
                    };

                    // Capturar snapshots iniciales
                    var snapshotMgr = new SnapshotManager();
                    var logExtractor = new LogExtractor();
                    var indexBuilder = new IndexBuilder();

                    // Servicios
                    var services = profile["monitored_services"]?.ToObject<string[]>() ?? Array.Empty<string>();
                    string servicesInitial = snapshotMgr.CaptureServicesSnapshot(services);
                    string servicesPath = Path.Combine(basePath, "services_initial.json");
                    File.WriteAllText(servicesPath, servicesInitial);

                    // Registro
                    var registryKeys = profile["registry_keys"]?.ToObject<string[]>() ?? Array.Empty<string>();
                    string registryInitial = snapshotMgr.CaptureRegistrySnapshot(registryKeys);
                    string registryPath = Path.Combine(basePath, "registry_initial.json");
                    File.WriteAllText(registryPath, registryInitial);

                    // Anotar líneas de logs externos
                    var externalLogs = profile["external_logs"]?.ToObject<string[]>() ?? Array.Empty<string>();
                    session.InitialLogLineCounts = logExtractor.GetInitialLineCounts(externalLogs);

                    // Anotar línea del log de AlwaysPrint
                    session.AlwaysPrintLogStartLine = logExtractor.GetAlwaysPrintCurrentLineCount();

                    // Crear índice inicial
                    string profileName = profile["name"]?.ToString() ?? "Perfil de Debugging";
                    indexBuilder.CreateIndex(debuggingId, profileName, session.StartTime, effectiveDuration, profile);
                    indexBuilder.AddFileReference("services_initial.json",
                        "Estado inicial de servicios monitoreados",
                        new FileInfo(servicesPath).Length);
                    indexBuilder.AddFileReference("registry_initial.json",
                        "Valores iniciales de llaves de registro",
                        new FileInfo(registryPath).Length);

                    session.IndexBuilder = indexBuilder;
                    _activeSession = session;

                    // Persistir checkpoint en disco (sobrevive reinicios del servicio)
                    PersistCheckpoint(session);

                    // Iniciar timer de duración
                    _durationTimer = new Timer(
                        OnTimerExpired,
                        debuggingId,
                        effectiveDuration * 1000,
                        Timeout.Infinite
                    );

                    AlwaysPrintLogger.WriteInfo(
                        $"DebuggingEngine: Sesión iniciada. ID={debuggingId}, " +
                        $"duración={effectiveDuration}s, carpeta={basePath}");

                    return true;
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteError(
                        $"DebuggingEngine: Error iniciando sesión {debuggingId}: {ex.Message}");
                    _activeSession = null;
                    OnCaptureError?.Invoke(debuggingId, ex.Message);
                    return false;
                }
            }
        }

        /// <summary>Detiene la sesión activa (llamado por StopDebugging o por timer).</summary>
        public void StopSession(string debuggingId)
        {
            lock (_lock)
            {
                if (_activeSession == null || _activeSession.DebuggingId != debuggingId)
                {
                    AlwaysPrintLogger.WriteWarning(
                        $"DebuggingEngine: No hay sesión activa con ID {debuggingId} para detener.");
                    return;
                }

                FinalizeCapture();
            }
        }

        /// <summary>Comprime la carpeta de debugging y retorna la ruta del ZIP.</summary>
        public string? PackageForUpload(string debuggingId)
        {
            lock (_lock)
            {
                string basePath = Path.Combine(DebugBasePath, debuggingId);
                if (!Directory.Exists(basePath))
                {
                    AlwaysPrintLogger.WriteWarning(
                        $"DebuggingEngine: Carpeta no encontrada para {debuggingId}");
                    return null;
                }

                var packer = new ZipPacker();
                return packer.PackFolder(basePath, debuggingId);
            }
        }

        /// <summary>Elimina la carpeta de debugging (ZIP y originales).</summary>
        public void DeleteSession(string debuggingId)
        {
            lock (_lock)
            {
                string basePath = Path.Combine(DebugBasePath, debuggingId);
                if (Directory.Exists(basePath))
                {
                    try
                    {
                        Directory.Delete(basePath, recursive: true);
                        AlwaysPrintLogger.WriteInfo(
                            $"DebuggingEngine: Carpeta eliminada para {debuggingId}");
                    }
                    catch (Exception ex)
                    {
                        AlwaysPrintLogger.WriteError(
                            $"DebuggingEngine: Error eliminando carpeta {debuggingId}: {ex.Message}");
                    }
                }

                // Si es la sesión activa, limpiar
                if (_activeSession?.DebuggingId == debuggingId)
                {
                    _durationTimer?.Dispose();
                    _durationTimer = null;
                    _activeSession = null;
                }
            }
        }

        /// <summary>Verifica si existe el ZIP para un debugging_id dado.</summary>
        public bool HasZipAvailable(string debuggingId)
        {
            string zipPath = GetZipPath(debuggingId);
            return zipPath != null && File.Exists(zipPath);
        }

        /// <summary>Obtiene la ruta del ZIP si existe.</summary>
        public string? GetZipPath(string debuggingId)
        {
            string basePath = Path.Combine(DebugBasePath, debuggingId);
            string zipFile = Path.Combine(basePath, $"debug_{debuggingId}.zip");
            return File.Exists(zipFile) ? zipFile : null;
        }

        // ═══════════════════════════════════════════════════════════════════════
        // MÉTODOS PRIVADOS
        // ═══════════════════════════════════════════════════════════════════════

        private void OnTimerExpired(object? state)
        {
            string debuggingId = state as string ?? "";
            AlwaysPrintLogger.WriteInfo(
                $"DebuggingEngine: Timer expirado para sesión {debuggingId}");

            lock (_lock)
            {
                if (_activeSession != null && _activeSession.DebuggingId == debuggingId)
                {
                    FinalizeCapture();
                }
            }
        }

        private void FinalizeCapture()
        {
            if (_activeSession == null) return;

            var session = _activeSession;
            _durationTimer?.Dispose();
            _durationTimer = null;

            try
            {
                session.EndTime = DateTime.UtcNow;
                string basePath = session.FolderPath;

                var snapshotMgr = new SnapshotManager();
                var logExtractor = new LogExtractor();
                var eventExtractor = new EventLogExtractor();
                var indexBuilder = session.IndexBuilder!;

                // Extraer log de AlwaysPrint
                string apLog = logExtractor.ExtractAlwaysPrintLog(session.AlwaysPrintLogStartLine);
                string apLogPath = Path.Combine(basePath, "alwaysprint_log.txt");
                File.WriteAllText(apLogPath, apLog);
                indexBuilder.AddFileReference("alwaysprint_log.txt",
                    "Log AlwaysPrint durante período de debugging",
                    new FileInfo(apLogPath).Length);

                // Extraer logs externos
                var externalLogs = session.Profile?["external_logs"]?.ToObject<string[]>() ?? Array.Empty<string>();
                var extractedLogs = logExtractor.ExtractNewLines(session.InitialLogLineCounts!);
                foreach (var kvp in extractedLogs)
                {
                    string filename = $"ext_log_{kvp.Key}.txt";
                    string filePath = Path.Combine(basePath, filename);
                    File.WriteAllText(filePath, kvp.Value);
                    indexBuilder.AddFileReference(filename,
                        $"Log externo: {kvp.Key}",
                        new FileInfo(filePath).Length);
                }

                // Reportar targets de logs externos que no resolvieron archivos
                if (externalLogs.Length > 0 && extractedLogs.Count == 0)
                {
                    foreach (var pattern in externalLogs)
                    {
                        indexBuilder.AddError(pattern, "No se encontraron archivos que coincidan con el patrón");
                    }
                }

                // Extraer eventos Windows
                var eventGroups = session.Profile?["eventlog_groups"]?.ToObject<string[]>() ?? Array.Empty<string>();
                if (eventGroups.Length > 0)
                {
                    var events = eventExtractor.ExtractEvents(eventGroups, session.StartTime, session.EndTime);
                    foreach (var kvp in events)
                    {
                        string filename = $"events_{kvp.Key.ToLower()}.txt";
                        string filePath = Path.Combine(basePath, filename);
                        File.WriteAllText(filePath, kvp.Value);
                        indexBuilder.AddFileReference(filename,
                            $"Eventos Windows - {kvp.Key} ({session.StartTime:HH:mm:ss} a {session.EndTime:HH:mm:ss})",
                            new FileInfo(filePath).Length);
                    }
                }

                // Snapshot final de servicios
                var services = session.Profile?["monitored_services"]?.ToObject<string[]>() ?? Array.Empty<string>();
                string servicesFinal = snapshotMgr.CaptureServicesSnapshot(services);
                string servicesFinalPath = Path.Combine(basePath, "services_final.json");
                File.WriteAllText(servicesFinalPath, servicesFinal);
                indexBuilder.AddFileReference("services_final.json",
                    "Estado final de servicios monitoreados",
                    new FileInfo(servicesFinalPath).Length);

                // Snapshot final de registro
                var registryKeys = session.Profile?["registry_keys"]?.ToObject<string[]>() ?? Array.Empty<string>();
                string registryFinal = snapshotMgr.CaptureRegistrySnapshot(registryKeys);
                string registryFinalPath = Path.Combine(basePath, "registry_final.json");
                File.WriteAllText(registryFinalPath, registryFinal);
                indexBuilder.AddFileReference("registry_final.json",
                    "Valores finales de llaves de registro",
                    new FileInfo(registryFinalPath).Length);

                // Finalizar índice
                indexBuilder.Finalize(session.EndTime);
                indexBuilder.Save(basePath);

                // Calcular tamaño total
                long totalSize = GetFolderSize(basePath);

                AlwaysPrintLogger.WriteInfo(
                    $"DebuggingEngine: Captura finalizada. ID={session.DebuggingId}, " +
                    $"archivos recopilados, tamaño total={totalSize} bytes");

                _activeSession = null;
                RemoveCheckpoint(basePath);
                OnCaptureComplete?.Invoke(session.DebuggingId, totalSize);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"DebuggingEngine: Error finalizando captura {session.DebuggingId}: {ex.Message}");
                _activeSession = null;
                OnCaptureError?.Invoke(session.DebuggingId, ex.Message);
            }
        }

        private long GetFolderSize(string folderPath)
        {
            long size = 0;
            foreach (var file in Directory.GetFiles(folderPath, "*", SearchOption.AllDirectories))
            {
                size += new FileInfo(file).Length;
            }
            return size;
        }

    /// <summary>
    /// Al iniciar el servicio, busca sesiones activas no expiradas y las retoma.
    /// Si el checkpoint está expirado, limpia la carpeta.
    /// </summary>
    public void TryResumeFromCheckpoint()
    {
        try
        {
            if (!Directory.Exists(DebugBasePath)) return;

            foreach (var dir in Directory.GetDirectories(DebugBasePath))
            {
                string checkpointPath = Path.Combine(dir, "session_checkpoint.json");
                if (!File.Exists(checkpointPath)) continue;

                try
                {
                    string json = File.ReadAllText(checkpointPath);
                    var checkpoint = JObject.Parse(json);

                    string debuggingId = checkpoint["debugging_id"]?.ToString() ?? "";
                    DateTime expiresAt = checkpoint["expires_at"]?.ToObject<DateTime>() ?? DateTime.MinValue;

                    if (DateTime.UtcNow > expiresAt)
                    {
                        // Sesión expirada: limpiar checkpoint, dejar archivos para posible análisis
                        File.Delete(checkpointPath);
                        AlwaysPrintLogger.WriteInfo(
                            $"DebuggingEngine: Checkpoint expirado eliminado: {debuggingId}");
                        continue;
                    }

                    // Sesión no expirada: retomar captura
                    var profile = checkpoint["profile"] as JObject;
                    int durationSeconds = checkpoint["duration_seconds"]?.ToObject<int>() ?? 60;
                    DateTime startTime = checkpoint["start_time"]?.ToObject<DateTime>() ?? DateTime.UtcNow;
                    var initialLogCounts = checkpoint["initial_log_line_counts"]?.ToObject<Dictionary<string, long>>()
                        ?? new Dictionary<string, long>();
                    long apLogStartLine = checkpoint["alwaysprint_log_start_line"]?.ToObject<long>() ?? 0;

                    int remainingSeconds = Math.Max(1, (int)(expiresAt - DateTime.UtcNow).TotalSeconds);

                    var session = new DebuggingSession
                    {
                        DebuggingId = debuggingId,
                        Profile = profile,
                        DurationSeconds = durationSeconds,
                        StartTime = startTime,
                        FolderPath = dir,
                        InitialLogLineCounts = initialLogCounts,
                        AlwaysPrintLogStartLine = apLogStartLine,
                        IndexBuilder = new IndexBuilder()
                    };

                    // Recrear el index builder con la info del checkpoint
                    string profileName = profile?["name"]?.ToString() ?? "Perfil de Debugging";
                    session.IndexBuilder.CreateIndex(debuggingId, profileName, startTime, durationSeconds, profile);

                    _activeSession = session;

                    // Iniciar timer con el tiempo restante
                    _durationTimer = new Timer(
                        OnTimerExpired,
                        debuggingId,
                        remainingSeconds * 1000,
                        Timeout.Infinite
                    );

                    AlwaysPrintLogger.WriteInfo(
                        $"DebuggingEngine: Sesión retomada desde checkpoint. ID={debuggingId}, " +
                        $"restante={remainingSeconds}s");
                    return; // Solo una sesión a la vez
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteWarning(
                        $"DebuggingEngine: Error leyendo checkpoint en {dir}: {ex.Message}");
                }
            }
        }
        catch (Exception ex)
        {
            AlwaysPrintLogger.WriteError(
                $"DebuggingEngine: Error en TryResumeFromCheckpoint: {ex.Message}");
        }
    }

    /// <summary>Persiste el estado de la sesión en disco.</summary>
    private void PersistCheckpoint(DebuggingSession session)
    {
        try
        {
            var checkpoint = new JObject
            {
                ["debugging_id"] = session.DebuggingId,
                ["profile"] = session.Profile,
                ["duration_seconds"] = session.DurationSeconds,
                ["start_time"] = session.StartTime,
                ["expires_at"] = session.StartTime.AddSeconds(session.DurationSeconds),
                ["initial_log_line_counts"] = JObject.FromObject(session.InitialLogLineCounts ?? new Dictionary<string, long>()),
                ["alwaysprint_log_start_line"] = session.AlwaysPrintLogStartLine,
            };

            string checkpointPath = Path.Combine(session.FolderPath, "session_checkpoint.json");
            File.WriteAllText(checkpointPath, checkpoint.ToString());
        }
        catch (Exception ex)
        {
            AlwaysPrintLogger.WriteWarning(
                $"DebuggingEngine: Error persistiendo checkpoint: {ex.Message}");
        }
    }

    /// <summary>Elimina el checkpoint de disco (sesión finalizada correctamente).</summary>
    private void RemoveCheckpoint(string folderPath)
    {
        try
        {
            string checkpointPath = Path.Combine(folderPath, "session_checkpoint.json");
            if (File.Exists(checkpointPath))
                File.Delete(checkpointPath);
        }
        catch { /* Best-effort cleanup */ }
    }
    }

    /// <summary>
    /// Datos internos de una sesión de debugging activa.
    /// </summary>
    internal class DebuggingSession
    {
        public string DebuggingId { get; set; } = "";
        public JObject? Profile { get; set; }
        public int DurationSeconds { get; set; }
        public DateTime StartTime { get; set; }
        public DateTime EndTime { get; set; }
        public string FolderPath { get; set; } = "";
        public Dictionary<string, long>? InitialLogLineCounts { get; set; }
        public long AlwaysPrintLogStartLine { get; set; }
        public IndexBuilder? IndexBuilder { get; set; }
    }
}
