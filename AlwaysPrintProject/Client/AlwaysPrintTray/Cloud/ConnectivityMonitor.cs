using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Security;
using System.Threading;
using System.Threading.Tasks;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Models;
using AlwaysPrintTray.Bootstrap;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Ejecuta verificaciones de conectividad configurables (HTTP, TCP, DNS, ICMP) en paralelo
    /// y reporta cada resultado individualmente a APCM vía WebSocket.
    /// Implementa IDisposable para liberar el timer y recursos asociados.
    /// </summary>
    public sealed class ConnectivityMonitor : IDisposable
    {
        // === Constantes ===
        private const int MinIntervalSeconds = 60;
        private const int MaxErrorLength = 256;

        // === Dependencias ===
        private readonly CloudWebSocketClient _wsClient;

        // === Intervalo efectivo ===
        private readonly int _intervalSeconds;

        // === Lista de checks (volatile para swap atómico de referencia) ===
        private volatile List<ConnectivityCheck> _checks;

        // === Timer y estado de ciclo de vida ===
        private Timer? _timer;
        private bool _started;
        private bool _disposed;
        private readonly object _lock = new object();

        /// <summary>
        /// Crea una nueva instancia de ConnectivityMonitor.
        /// </summary>
        /// <param name="wsClient">Cliente WebSocket para envío de resultados a APCM.</param>
        /// <param name="checks">Lista inicial de checks de conectividad a ejecutar.</param>
        /// <param name="intervalSeconds">Intervalo en segundos entre ciclos de ejecución (mínimo 60).</param>
        public ConnectivityMonitor(
            CloudWebSocketClient wsClient,
            List<ConnectivityCheck> checks,
            int intervalSeconds = 60)
        {
            _wsClient = wsClient ?? throw new ArgumentNullException(nameof(wsClient));
            _checks = checks ?? new List<ConnectivityCheck>();
            _intervalSeconds = Math.Max(intervalSeconds, MinIntervalSeconds);

            AlwaysPrintLogger.WriteTrayInfo(
                $"ConnectivityMonitor: instancia creada. Intervalo = {_intervalSeconds}s, " +
                $"checks configurados = {_checks.Count}.");
        }

        /// <summary>
        /// Inicia el timer de verificación de conectividad. Si ya está iniciado, no hace nada.
        /// </summary>
        public void Start()
        {
            lock (_lock)
            {
                if (_disposed)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "ConnectivityMonitor: intento de iniciar un monitor ya dispuesto. Ignorando.");
                    return;
                }

                if (_started)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "ConnectivityMonitor: ya se encuentra iniciado. Ignorando llamada a Start().");
                    return;
                }

                var intervalMs = _intervalSeconds * 1000;
                _timer = new Timer(OnTimerElapsed, null, intervalMs, intervalMs);
                _started = true;

                AlwaysPrintLogger.WriteTrayInfo(
                    $"ConnectivityMonitor: iniciado. Primer ciclo en {_intervalSeconds}s.");
            }
        }

        /// <summary>
        /// Detiene el timer de verificación de conectividad.
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

                AlwaysPrintLogger.WriteTrayInfo("ConnectivityMonitor: detenido.");
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
                }

                AlwaysPrintLogger.WriteTrayInfo("ConnectivityMonitor: recursos liberados (Dispose).");
            }
        }

        /// <summary>
        /// Actualiza la lista de checks de conectividad de forma thread-safe.
        /// Los nuevos checks se aplicarán en el siguiente ciclo de ejecución.
        /// </summary>
        /// <param name="newChecks">Nueva lista de checks de conectividad.</param>
        public void UpdateChecks(List<ConnectivityCheck> newChecks)
        {
            var updatedList = newChecks ?? new List<ConnectivityCheck>();

            // Swap atómico de referencia (volatile garantiza visibilidad entre hilos)
            _checks = updatedList;

            AlwaysPrintLogger.WriteTrayInfo(
                $"ConnectivityMonitor: lista de checks actualizada. Nuevos checks = {updatedList.Count}.");
        }

        // === Callback del timer ===

        /// <summary>
        /// Callback del timer. Lee la lista de checks una vez, ejecuta todos en paralelo,
        /// y envía cada resultado individualmente vía WebSocket.
        /// </summary>
        private void OnTimerElapsed(object? state)
        {
            try
            {
                // 1. Leer la referencia volátil una sola vez para este ciclo
                var currentChecks = _checks;

                // 2. Si la lista está vacía, no hacer nada
                if (currentChecks == null || currentChecks.Count == 0)
                {
                    return;
                }

                // 3. Ejecutar todos los checks en paralelo
                var tasks = new Task<ConnectivityCheckResult>[currentChecks.Count];
                for (int i = 0; i < currentChecks.Count; i++)
                {
                    var check = currentChecks[i];
                    tasks[i] = Task.Run(() => ExecuteCheck(check));
                }

                // Esperar a que todos completen
                Task.WaitAll(tasks);

                // 4. Enviar cada resultado individualmente vía WebSocket
                for (int i = 0; i < tasks.Length; i++)
                {
                    var result = tasks[i].Result;
                    SendResult(result);
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ConnectivityMonitor: error durante el ciclo de verificación. " +
                    $"{ex.GetType().Name}: {ex.Message}");
            }
        }

        /// <summary>
        /// Envía un resultado de check vía WebSocket. Si el WebSocket no está disponible,
        /// descarta el resultado y registra una advertencia.
        /// </summary>
        private void SendResult(ConnectivityCheckResult result)
        {
            try
            {
                if (!_wsClient.IsConnected)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"ConnectivityMonitor: WebSocket no disponible. Descartando resultado del check '{result.CheckId}'.");
                    return;
                }

                _wsClient.Send("connectivity_result", result);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"ConnectivityMonitor: error al enviar resultado del check '{result.CheckId}'. " +
                    $"{ex.GetType().Name}: {ex.Message}");
            }
        }

        // === Métodos de ejecución de checks ===

        /// <summary>
        /// Despacha la ejecución del check según su tipo.
        /// </summary>
        private ConnectivityCheckResult ExecuteCheck(ConnectivityCheck check)
        {
            try
            {
                switch (check.Type?.ToLowerInvariant())
                {
                    case "http":
                        return ExecuteHttpCheck(check);
                    case "tcp":
                        return ExecuteTcpCheck(check);
                    case "dns":
                        return ExecuteDnsCheck(check);
                    case "ping":
                        return ExecutePingCheck(check);
                    default:
                        return new ConnectivityCheckResult
                        {
                            CheckId = check.Id ?? string.Empty,
                            Success = false,
                            LatencyMs = null,
                            Error = $"Tipo de check no soportado: '{check.Type}'"
                        };
                }
            }
            catch (Exception ex)
            {
                return new ConnectivityCheckResult
                {
                    CheckId = check.Id ?? string.Empty,
                    Success = false,
                    LatencyMs = null,
                    Error = TruncateError(ex.Message)
                };
            }
        }

        /// <summary>
        /// Ejecuta un check HTTP GET contra la URL configurada.
        /// Éxito solo si el código de respuesta es exactamente 200.
        /// Mide latencia desde el inicio de la solicitud hasta la recepción de la respuesta.
        /// </summary>
        private ConnectivityCheckResult ExecuteHttpCheck(ConnectivityCheck check)
        {
            var checkId = check.Id ?? string.Empty;

            // Validar URL: vacía o no es URI absoluta
            if (string.IsNullOrWhiteSpace(check.Url) ||
                !Uri.TryCreate(check.Url, UriKind.Absolute, out var uri))
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"ConnectivityMonitor: check HTTP '{checkId}' tiene URL inválida: '{check.Url ?? "(null)"}'.");

                return new ConnectivityCheckResult
                {
                    CheckId = checkId,
                    Success = false,
                    LatencyMs = null,
                    Error = "URL inválida"
                };
            }

            var timeoutMs = check.TimeoutMs > 0 ? check.TimeoutMs : 5000;

            try
            {
                using (var cts = new CancellationTokenSource(timeoutMs))
                {
                    var sw = Stopwatch.StartNew();

                    var response = DomainHealthChecker.Http
                        .GetAsync(uri, cts.Token)
                        .GetAwaiter()
                        .GetResult();

                    sw.Stop();

                    var statusCode = (int)response.StatusCode;
                    bool success = statusCode == 200;

                    if (success)
                    {
                        return new ConnectivityCheckResult
                        {
                            CheckId = checkId,
                            Success = true,
                            LatencyMs = sw.ElapsedMilliseconds,
                            Error = null
                        };
                    }
                    else
                    {
                        // Código de estado distinto de 200: fallo sin latencia
                        return new ConnectivityCheckResult
                        {
                            CheckId = checkId,
                            Success = false,
                            LatencyMs = null,
                            Error = $"HTTP {statusCode}"
                        };
                    }
                }
            }
            catch (OperationCanceledException)
            {
                // Timeout: la solicitud fue cancelada por exceder TimeoutMs
                AlwaysPrintLogger.WriteTrayWarning(
                    $"ConnectivityMonitor: check HTTP '{checkId}' timeout ({timeoutMs} ms) para URL '{check.Url}'.");

                return new ConnectivityCheckResult
                {
                    CheckId = checkId,
                    Success = false,
                    LatencyMs = null,
                    Error = $"Timeout: la solicitud excedió {timeoutMs} ms"
                };
            }
            catch (AggregateException agEx) when (agEx.InnerException is OperationCanceledException)
            {
                // Timeout envuelto en AggregateException (posible con .GetAwaiter().GetResult())
                AlwaysPrintLogger.WriteTrayWarning(
                    $"ConnectivityMonitor: check HTTP '{checkId}' timeout ({timeoutMs} ms) para URL '{check.Url}'.");

                return new ConnectivityCheckResult
                {
                    CheckId = checkId,
                    Success = false,
                    LatencyMs = null,
                    Error = $"Timeout: la solicitud excedió {timeoutMs} ms"
                };
            }
            catch (Exception ex)
            {
                // Cualquier otra excepción (red, DNS, TLS, etc.)
                var errorMessage = ex.InnerException != null
                    ? ex.InnerException.Message
                    : ex.Message;

                AlwaysPrintLogger.WriteTrayError(
                    $"ConnectivityMonitor: check HTTP '{checkId}' falló. {ex.GetType().Name}: {errorMessage}");

                return new ConnectivityCheckResult
                {
                    CheckId = checkId,
                    Success = false,
                    LatencyMs = null,
                    Error = TruncateError(errorMessage)
                };
            }
        }

        /// <summary>
        /// Ejecuta un check TCP: intenta conexión al host:puerto configurado con el timeout especificado.
        /// Mide latencia desde inicio de conexión hasta establecida. Reporta timeout o excepción si falla.
        /// </summary>
        private ConnectivityCheckResult ExecuteTcpCheck(ConnectivityCheck check)
        {
            var checkId = check.Id ?? string.Empty;

            // Validar que Host no sea nulo/vacío y Port tenga valor
            if (string.IsNullOrWhiteSpace(check.Host) || !check.Port.HasValue)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"ConnectivityMonitor: check TCP '{checkId}' tiene configuración inválida " +
                    $"(Host vacío o Puerto no definido). Omitiendo.");
                return new ConnectivityCheckResult
                {
                    CheckId = checkId,
                    Success = false,
                    LatencyMs = null,
                    Error = "Configuración TCP inválida: host o puerto no definido"
                };
            }

            var host = check.Host!;
            var port = check.Port!.Value;
            var timeoutMs = check.TimeoutMs > 0 ? check.TimeoutMs : 5000;

            var sw = new Stopwatch();

            try
            {
                using (var client = new TcpClient())
                {
                    sw.Start();
                    var connectTask = client.ConnectAsync(host, port);
                    var timeoutTask = Task.Delay(timeoutMs);

                    // Esperar a que se complete la conexión o el timeout
                    var completedTask = Task.WhenAny(connectTask, timeoutTask).Result;
                    sw.Stop();

                    if (completedTask == timeoutTask)
                    {
                        // Timeout: la conexión no se estableció a tiempo
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"ConnectivityMonitor: check TCP '{checkId}' a {host}:{port} — " +
                            $"tiempo de espera agotado ({timeoutMs}ms).");
                        return new ConnectivityCheckResult
                        {
                            CheckId = checkId,
                            Success = false,
                            LatencyMs = null,
                            Error = "Tiempo de espera agotado (TCP)"
                        };
                    }

                    // Si connectTask completó pero con excepción, propagarla
                    if (connectTask.IsFaulted)
                    {
                        var innerEx = connectTask.Exception?.InnerException ?? connectTask.Exception;
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"ConnectivityMonitor: check TCP '{checkId}' a {host}:{port} — " +
                            $"error de conexión: {innerEx?.Message}");
                        return new ConnectivityCheckResult
                        {
                            CheckId = checkId,
                            Success = false,
                            LatencyMs = null,
                            Error = TruncateError(innerEx?.Message)
                        };
                    }

                    // Conexión exitosa
                    var latency = sw.ElapsedMilliseconds;
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"ConnectivityMonitor: check TCP '{checkId}' a {host}:{port} — " +
                        $"exitoso, latencia = {latency}ms.");
                    return new ConnectivityCheckResult
                    {
                        CheckId = checkId,
                        Success = true,
                        LatencyMs = latency,
                        Error = null
                    };
                }
            }
            catch (AggregateException agEx)
            {
                sw.Stop();
                var innerEx = agEx.InnerException ?? agEx;
                AlwaysPrintLogger.WriteTrayWarning(
                    $"ConnectivityMonitor: check TCP '{checkId}' a {host}:{port} — " +
                    $"excepción: {innerEx.Message}");
                return new ConnectivityCheckResult
                {
                    CheckId = checkId,
                    Success = false,
                    LatencyMs = null,
                    Error = TruncateError(innerEx.Message)
                };
            }
            catch (Exception ex)
            {
                sw.Stop();
                AlwaysPrintLogger.WriteTrayWarning(
                    $"ConnectivityMonitor: check TCP '{checkId}' a {host}:{port} — " +
                    $"excepción: {ex.Message}");
                return new ConnectivityCheckResult
                {
                    CheckId = checkId,
                    Success = false,
                    LatencyMs = null,
                    Error = TruncateError(ex.Message)
                };
            }
        }

        /// <summary>
        /// Ejecuta un check DNS resolviendo el hostname configurado mediante System.Net.Dns.
        /// Reporta éxito si se obtiene al menos una dirección IP, fallo en caso contrario.
        /// </summary>
        private ConnectivityCheckResult ExecuteDnsCheck(ConnectivityCheck check)
        {
            var checkId = check.Id ?? string.Empty;

            // Validar que el hostname no sea nulo o vacío
            if (string.IsNullOrWhiteSpace(check.Hostname))
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"ConnectivityMonitor: check DNS '{checkId}' tiene hostname inválido o vacío.");
                return new ConnectivityCheckResult
                {
                    CheckId = checkId,
                    Success = false,
                    LatencyMs = null,
                    Error = "Hostname inválido o vacío"
                };
            }

            var sw = Stopwatch.StartNew();
            try
            {
                var addresses = Dns.GetHostAddresses(check.Hostname);
                sw.Stop();

                if (addresses == null || addresses.Length == 0)
                {
                    // Resolución exitosa pero sin direcciones
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"ConnectivityMonitor: check DNS '{checkId}' — sin direcciones resueltas para '{check.Hostname}'.");
                    return new ConnectivityCheckResult
                    {
                        CheckId = checkId,
                        Success = false,
                        LatencyMs = null,
                        Error = "Sin direcciones resueltas"
                    };
                }

                // Éxito: al menos una dirección resuelta
                var latencyMs = sw.ElapsedMilliseconds;
                AlwaysPrintLogger.WriteTrayInfo(
                    $"ConnectivityMonitor: check DNS '{checkId}' exitoso. " +
                    $"Hostname='{check.Hostname}', direcciones={addresses.Length}, latencia={latencyMs}ms.");
                return new ConnectivityCheckResult
                {
                    CheckId = checkId,
                    Success = true,
                    LatencyMs = latencyMs,
                    Error = null
                };
            }
            catch (Exception ex)
            {
                sw.Stop();
                AlwaysPrintLogger.WriteTrayError(
                    $"ConnectivityMonitor: check DNS '{checkId}' falló. " +
                    $"Hostname='{check.Hostname}', error: {ex.GetType().Name}: {ex.Message}");
                return new ConnectivityCheckResult
                {
                    CheckId = checkId,
                    Success = false,
                    LatencyMs = null,
                    Error = TruncateError(ex.Message)
                };
            }
        }

        /// <summary>
        /// Ejecuta un check ICMP (ping) enviando un echo request al host configurado.
        /// Reporta latencia en caso de éxito, o el estado/error correspondiente en caso de fallo.
        /// </summary>
        private ConnectivityCheckResult ExecutePingCheck(ConnectivityCheck check)
        {
            var checkId = check.Id ?? string.Empty;

            // Validar que el host no sea nulo o vacío
            if (string.IsNullOrWhiteSpace(check.Host))
            {
                return new ConnectivityCheckResult
                {
                    CheckId = checkId,
                    Success = false,
                    LatencyMs = null,
                    Error = "Host inválido o vacío"
                };
            }

            try
            {
                using (var ping = new Ping())
                {
                    var timeoutMs = check.TimeoutMs > 0 ? check.TimeoutMs : 5000;
                    var reply = ping.Send(check.Host, timeoutMs);

                    if (reply.Status == IPStatus.Success)
                    {
                        return new ConnectivityCheckResult
                        {
                            CheckId = checkId,
                            Success = true,
                            LatencyMs = reply.RoundtripTime,
                            Error = null
                        };
                    }
                    else
                    {
                        // Estado no exitoso: reportar el nombre del enum IPStatus
                        return new ConnectivityCheckResult
                        {
                            CheckId = checkId,
                            Success = false,
                            LatencyMs = null,
                            Error = TruncateError(reply.Status.ToString())
                        };
                    }
                }
            }
            catch (UnauthorizedAccessException)
            {
                // Permisos insuficientes para ICMP
                AlwaysPrintLogger.WriteTrayWarning(
                    $"ConnectivityMonitor: permisos insuficientes para ejecutar ping ICMP al host '{check.Host}'. " +
                    "ICMP no permitido en este entorno.");

                return new ConnectivityCheckResult
                {
                    CheckId = checkId,
                    Success = false,
                    LatencyMs = null,
                    Error = "ICMP no permitido"
                };
            }
            catch (PingException pex) when (pex.InnerException is UnauthorizedAccessException
                                            || pex.InnerException is System.Security.SecurityException)
            {
                // PingException con excepción interna relacionada a permisos
                AlwaysPrintLogger.WriteTrayWarning(
                    $"ConnectivityMonitor: permisos insuficientes para ejecutar ping ICMP al host '{check.Host}'. " +
                    "ICMP no permitido en este entorno.");

                return new ConnectivityCheckResult
                {
                    CheckId = checkId,
                    Success = false,
                    LatencyMs = null,
                    Error = "ICMP no permitido"
                };
            }
            catch (Exception ex)
            {
                // Cualquier otra excepción: reportar con mensaje de error
                return new ConnectivityCheckResult
                {
                    CheckId = checkId,
                    Success = false,
                    LatencyMs = null,
                    Error = TruncateError(ex.Message)
                };
            }
        }

        // === Utilidades ===

        /// <summary>
        /// Trunca un mensaje de error al máximo de 256 caracteres.
        /// </summary>
        internal static string TruncateError(string? message)
        {
            if (message == null || message.Length == 0) return string.Empty;
            return message.Length <= MaxErrorLength ? message : message.Substring(0, MaxErrorLength);
        }
    }
}
