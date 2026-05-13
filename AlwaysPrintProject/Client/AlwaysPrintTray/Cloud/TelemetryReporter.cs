using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintTray.Pipe;
using DisconnectionEvent = AlwaysPrint.Shared.Models.DisconnectionEvent;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Recopila métricas operacionales periódicamente y las envía a APCM vía WebSocket.
    /// Acumula eventos de desconexión, conteo de trabajos y tiempos de liberación en memoria.
    /// Implementa IDisposable para liberar el timer y recursos asociados.
    /// </summary>
    public sealed class TelemetryReporter : IDisposable
    {
        // === Constantes de clamping del intervalo ===
        private const int MinIntervalSeconds = 60;
        private const int MaxIntervalSeconds = 3600;
        private const int MaxDisconnectionEvents = 1000;

        // === Dependencias ===
        private readonly CloudWebSocketClient _wsClient;
        private readonly PipeClient _pipeClient;

        // === Intervalo efectivo (clamped) ===
        private readonly int _intervalSeconds;

        // === Estado protegido por lock ===
        private readonly object _lock = new object();
        private readonly List<DisconnectionEvent> _disconnectionLog = new List<DisconnectionEvent>();
        private int _jobsIdentified;
        private readonly List<long> _releaseTimes = new List<long>();
        private bool _contingencyActive;

        // === Timer ===
        private Timer? _timer;
        private bool _started;
        private bool _disposed;

        /// <summary>
        /// Crea una nueva instancia de TelemetryReporter.
        /// </summary>
        /// <param name="wsClient">Cliente WebSocket para envío de telemetría a APCM.</param>
        /// <param name="pipeClient">Cliente Named Pipe para consultar estado de cola al Service.</param>
        /// <param name="intervalSeconds">Intervalo en segundos entre envíos (se clampea a [60, 3600]).</param>
        /// <param name="contingencyActive">Estado inicial de contingencia.</param>
        public TelemetryReporter(
            CloudWebSocketClient wsClient,
            PipeClient pipeClient,
            int intervalSeconds,
            bool contingencyActive)
        {
            _wsClient = wsClient ?? throw new ArgumentNullException(nameof(wsClient));
            _pipeClient = pipeClient ?? throw new ArgumentNullException(nameof(pipeClient));
            _intervalSeconds = ClampInterval(intervalSeconds);
            _contingencyActive = contingencyActive;

            AlwaysPrintLogger.WriteTrayInfo(
                $"TelemetryReporter: instancia creada. Intervalo efectivo = {_intervalSeconds}s " +
                $"(solicitado: {intervalSeconds}s), contingencia = {contingencyActive}.");
        }

        /// <summary>
        /// Intervalo efectivo en segundos después del clamping [60, 3600].
        /// Expuesto para testing y diagnóstico.
        /// </summary>
        public int EffectiveIntervalSeconds => _intervalSeconds;

        /// <summary>
        /// Inicia el timer de telemetría. Si ya está iniciado, no hace nada.
        /// </summary>
        public void Start()
        {
            lock (_lock)
            {
                if (_disposed)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "TelemetryReporter: intento de iniciar un reporter ya dispuesto. Ignorando.");
                    return;
                }

                if (_started)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "TelemetryReporter: ya se encuentra iniciado. Ignorando llamada a Start().");
                    return;
                }

                var intervalMs = _intervalSeconds * 1000;
                _timer = new Timer(OnTimerElapsed, null, intervalMs, intervalMs);
                _started = true;

                AlwaysPrintLogger.WriteTrayInfo(
                    $"TelemetryReporter: iniciado. Primer envío en {_intervalSeconds}s.");
            }
        }

        /// <summary>
        /// Detiene el timer de telemetría y cierra eventos de desconexión abiertos.
        /// </summary>
        public void Stop()
        {
            lock (_lock)
            {
                if (!_started || _disposed) return;

                _timer?.Change(Timeout.Infinite, Timeout.Infinite);
                _timer?.Dispose();
                _timer = null;
                _started = false;

                // Cerrar eventos de desconexión abiertos con timestamp actual
                CloseOpenDisconnectionEvents();

                AlwaysPrintLogger.WriteTrayInfo("TelemetryReporter: detenido.");
            }
        }

        /// <summary>
        /// Libera todos los recursos. Llama a Stop() si aún está activo.
        /// </summary>
        public void Dispose()
        {
            if (_disposed) return;

            lock (_lock)
            {
                if (_disposed) return;
                _disposed = true;

                if (_started)
                {
                    _timer?.Change(Timeout.Infinite, Timeout.Infinite);
                    _timer?.Dispose();
                    _timer = null;
                    _started = false;

                    // Cerrar eventos de desconexión abiertos
                    CloseOpenDisconnectionEvents();
                }

                AlwaysPrintLogger.WriteTrayInfo("TelemetryReporter: recursos liberados (Dispose).");
            }
        }

        /// <summary>
        /// Registra un evento de desconexión WebSocket.
        /// Agrega un nuevo DisconnectionEvent con el timestamp de inicio.
        /// Si se excede el límite de 1000 eventos, descarta el más antiguo.
        /// </summary>
        /// <param name="utcStart">Momento UTC de la desconexión.</param>
        public void RecordDisconnection(DateTime utcStart)
        {
            lock (_lock)
            {
                // Si se alcanzó el límite, eliminar el evento más antiguo
                if (_disconnectionLog.Count >= MaxDisconnectionEvents)
                {
                    _disconnectionLog.RemoveAt(0);
                    AlwaysPrintLogger.WriteTrayWarning(
                        "TelemetryReporter: se alcanzó el límite de 1000 eventos de desconexión. " +
                        "Se descartó el evento más antiguo.");
                }

                _disconnectionLog.Add(new DisconnectionEvent
                {
                    StartedAt = utcStart,
                    ReconnectedAt = null,
                    DurationSeconds = null
                });

                AlwaysPrintLogger.WriteTrayInfo(
                    $"TelemetryReporter: desconexión registrada a las {utcStart:O}. " +
                    $"Eventos acumulados: {_disconnectionLog.Count}.");
            }
        }

        /// <summary>
        /// Registra la reconexión WebSocket, cerrando el último evento de desconexión abierto.
        /// Si no existe un evento abierto (sin ReconnectedAt), descarta la señal de reconexión.
        /// Calcula la duración como el piso de TotalSeconds entre inicio y reconexión.
        /// </summary>
        /// <param name="utcReconnected">Momento UTC de la reconexión.</param>
        public void RecordReconnection(DateTime utcReconnected)
        {
            lock (_lock)
            {
                // Buscar el último evento abierto (sin timestamp de reconexión)
                DisconnectionEvent? openEvent = null;
                for (int i = _disconnectionLog.Count - 1; i >= 0; i--)
                {
                    if (_disconnectionLog[i].ReconnectedAt == null)
                    {
                        openEvent = _disconnectionLog[i];
                        break;
                    }
                }

                if (openEvent == null)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "TelemetryReporter: se recibió señal de reconexión pero no existe " +
                        "un evento de desconexión abierto. Descartando.");
                    return;
                }

                openEvent.ReconnectedAt = utcReconnected;
                openEvent.DurationSeconds = (int)Math.Floor((utcReconnected - openEvent.StartedAt).TotalSeconds);

                AlwaysPrintLogger.WriteTrayInfo(
                    $"TelemetryReporter: reconexión registrada a las {utcReconnected:O}. " +
                    $"Duración de desconexión: {openEvent.DurationSeconds}s.");
            }
        }

        /// <summary>
        /// Acumula datos de un trabajo de impresión completado.
        /// Incrementa el contador de trabajos identificados y registra el tiempo de liberación.
        /// </summary>
        /// <param name="jobCount">Cantidad de trabajos a acumular.</param>
        /// <param name="releaseTimeMs">Tiempo de liberación en milisegundos.</param>
        public void AccumulateJobData(int jobCount, long releaseTimeMs)
        {
            lock (_lock)
            {
                _jobsIdentified += jobCount;
                _releaseTimes.Add(releaseTimeMs);

                AlwaysPrintLogger.WriteTrayInfo(
                    $"TelemetryReporter: datos de trabajo acumulados. " +
                    $"jobCount={jobCount}, releaseTimeMs={releaseTimeMs}, " +
                    $"total trabajos={_jobsIdentified}, total tiempos={_releaseTimes.Count}.");
            }
        }

        /// <summary>
        /// Calcula el tiempo promedio de liberación como media aritmética entera.
        /// Retorna null si no hay tiempos registrados.
        /// </summary>
        /// <returns>Media aritmética entera de los tiempos de liberación, o null si la lista está vacía.</returns>
        public long? GetAverageReleaseTimeMs()
        {
            lock (_lock)
            {
                if (_releaseTimes.Count == 0)
                    return null;

                long sum = 0;
                for (int i = 0; i < _releaseTimes.Count; i++)
                {
                    sum += _releaseTimes[i];
                }

                return sum / _releaseTimes.Count;
            }
        }

        /// <summary>
        /// Actualiza el estado de contingencia.
        /// </summary>
        /// <param name="active">Nuevo estado de contingencia.</param>
        public void UpdateContingencyState(bool active)
        {
            lock (_lock)
            {
                if (_contingencyActive != active)
                {
                    _contingencyActive = active;
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"TelemetryReporter: estado de contingencia actualizado a {active}.");
                }
            }
        }

        // === Métodos privados ===

        /// <summary>
        /// Callback del timer. Recopila estado de cola, ensambla el payload de telemetría
        /// y lo envía vía WebSocket. Si el WebSocket no está disponible, retiene los datos
        /// acumulados para el siguiente ciclo.
        /// </summary>
        private void OnTimerElapsed(object? state)
        {
            try
            {
                lock (_lock)
                {
                    if (_disposed || !_started) return;

                    // 1. Recopilar estado de cola desde el Service vía Named Pipe
                    string queueStatus = CollectQueueStatus();

                    // 2. Verificar disponibilidad del WebSocket
                    if (!_wsClient.IsConnected)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            "TelemetryReporter: WebSocket no disponible. Se retienen datos acumulados para el próximo ciclo.");
                        return;
                    }

                    // 3. Calcular avg_release_time_ms (null si no hay trabajos)
                    long? avgReleaseTimeMs = _releaseTimes.Count > 0
                        ? (long?)(_releaseTimes.Sum() / _releaseTimes.Count)
                        : null;

                    // 4. Ensamblar el payload de telemetría
                    var disconnectionLogPayload = _disconnectionLog.Select(evt => new
                    {
                        started_at = evt.StartedAt.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                        reconnected_at = evt.ReconnectedAt?.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                        duration_seconds = evt.DurationSeconds
                    }).ToList();

                    var payload = new
                    {
                        queue_status = queueStatus,
                        contingency_active = _contingencyActive,
                        jobs_identified = _jobsIdentified,
                        avg_release_time_ms = avgReleaseTimeMs,
                        disconnection_log = disconnectionLogPayload
                    };

                    // 5. Enviar vía WebSocket con tipo "telemetry"
                    _wsClient.Send("telemetry", payload);

                    // 6. Envío exitoso: limpiar acumuladores
                    _disconnectionLog.Clear();
                    _jobsIdentified = 0;
                    _releaseTimes.Clear();

                    AlwaysPrintLogger.WriteTrayInfo(
                        $"TelemetryReporter: telemetría enviada. queue_status={queueStatus}, " +
                        $"contingencia={_contingencyActive}, trabajos={payload.jobs_identified}, " +
                        $"avg_release_ms={avgReleaseTimeMs?.ToString() ?? "null"}, " +
                        $"desconexiones={disconnectionLogPayload.Count}.");
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"TelemetryReporter: error durante el ciclo de telemetría. {ex.GetType().Name}: {ex.Message}");
            }
        }

        /// <summary>
        /// Consulta el estado de la cola corporativa al Service vía Named Pipe.
        /// Retorna "ok" si la cola existe, "missing" si no existe, o "error" si el pipe
        /// está desconectado o la consulta falla.
        /// </summary>
        private string CollectQueueStatus()
        {
            try
            {
                if (!_pipeClient.IsConnected)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "TelemetryReporter: pipe desconectado al recopilar estado de cola. Reportando 'error'.");
                    return "error";
                }

                var request = PipeMessage.Create(MessageType.CheckCorporateQueue,
                    new CheckCorporateQueuePayload { QueueName = "LexmarkBBVA" });

                var response = _pipeClient.Send(request);

                if (response == null)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "TelemetryReporter: sin respuesta del Service al consultar cola. Reportando 'error'.");
                    return "error";
                }

                if (response.Type == MessageType.Error)
                {
                    return "error";
                }

                var queueResponse = response.GetPayload<CheckCorporateQueueResponsePayload>();
                if (queueResponse == null)
                {
                    return "error";
                }

                return queueResponse.Exists ? "ok" : "missing";
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"TelemetryReporter: excepción al consultar estado de cola. {ex.Message}. Reportando 'error'.");
                return "error";
            }
        }

        /// <summary>
        /// Clampea el intervalo al rango permitido [60, 3600] segundos.
        /// </summary>
        private static int ClampInterval(int intervalSeconds)
        {
            if (intervalSeconds < MinIntervalSeconds) return MinIntervalSeconds;
            if (intervalSeconds > MaxIntervalSeconds) return MaxIntervalSeconds;
            return intervalSeconds;
        }

        /// <summary>
        /// Cierra todos los eventos de desconexión que no tienen timestamp de reconexión,
        /// asignando DateTime.UtcNow como momento de reconexión y calculando la duración.
        /// </summary>
        private void CloseOpenDisconnectionEvents()
        {
            var now = DateTime.UtcNow;
            foreach (var evt in _disconnectionLog)
            {
                if (evt.ReconnectedAt == null)
                {
                    evt.ReconnectedAt = now;
                    evt.DurationSeconds = (int)Math.Floor((now - evt.StartedAt).TotalSeconds);
                }
            }
        }
    }
}
