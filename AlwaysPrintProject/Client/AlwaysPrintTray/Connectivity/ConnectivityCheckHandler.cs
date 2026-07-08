using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintTray.Cloud;
using AlwaysPrintTray.Forms;

namespace AlwaysPrintTray.Connectivity
{
    /// <summary>
    /// Orquestador de checks de conectividad de TRANSPORTE. Verifica que las URLs
    /// de Lexmark Cloud Services (US Data Center) sean alcanzables a nivel de red.
    /// Cualquier respuesta HTTP (2xx-5xx) = OK. Solo excepciones de transporte = FALLO.
    /// </summary>
    public class ConnectivityCheckHandler
    {
        private volatile bool _checkInProgress;
        private readonly SynchronizationContext _uiContext;

        public ConnectivityCheckHandler(SynchronizationContext uiContext)
        {
            _uiContext = uiContext ?? throw new ArgumentNullException(nameof(uiContext));
        }

        /// <summary>
        /// Ejecuta el check de conectividad de transporte completo: detecta proxy,
        /// verifica cada URL con paralelismo de 4, calcula severidad basada en URLs
        /// críticas, escribe en log y muestra notificación si hay fallos.
        /// </summary>
        public async Task ExecuteCheckAsync(ConnectivityCheckPayload payload)
        {
            if (_checkInProgress)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "ConnectivityCheck: ya hay un check en curso, se descarta esta solicitud.",
                    AlwaysPrintLogger.EvtGenericWarning);
                return;
            }

            _checkInProgress = true;

            try
            {
                if (payload.Urls == null || payload.Urls.Count == 0)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "ConnectivityCheck: payload sin URLs, abortando.",
                        AlwaysPrintLogger.EvtGenericWarning);
                    return;
                }

                // Timeout global 90 segundos
                using var totalCts = new CancellationTokenSource(TimeSpan.FromSeconds(90));

                // Detectar proxy
                Uri proxyUri = null;
                bool proxyActive = false;
                foreach (var entry in payload.Urls)
                {
                    try
                    {
                        var rawUrl = entry.Url;
                        var uri = new Uri(rawUrl.StartsWith("http") ? rawUrl : "https://" + rawUrl);
                        proxyUri = ProxyHelper.GetSystemProxyUri(uri);
                        if (proxyUri != null) break;
                    }
                    catch { }
                }

                if (proxyUri != null)
                {
                    proxyActive = await TestTcpConnectAsync(proxyUri.Host, proxyUri.Port, 2000);
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"ConnectivityCheck: proxy {proxyUri.Host}:{proxyUri.Port} — " +
                        (proxyActive ? "activo" : "inactivo"),
                        AlwaysPrintLogger.EvtConnectivitySummary);
                }

                // Crear HttpClient
                HttpClientHandler httpHandler;
                if (proxyUri != null && proxyActive)
                {
                    httpHandler = ProxyHelper.CreateHandler();
                }
                else
                {
                    httpHandler = new HttpClientHandler { UseProxy = false };
                }
                // AllowAutoRedirect=false: un 3xx ya prueba conectividad
                httpHandler.AllowAutoRedirect = false;

                using var client = new HttpClient(httpHandler)
                {
                    Timeout = System.Threading.Timeout.InfiniteTimeSpan
                };

                string proxyMode = proxyUri != null && proxyActive
                    ? $"{proxyUri.Host}:{proxyUri.Port}"
                    : "directo";

                AlwaysPrintLogger.WriteTrayInfo(
                    $"ConnectivityCheck: iniciando ({payload.Urls.Count} URLs, proxy={proxyMode}).",
                    AlwaysPrintLogger.EvtConnectivitySummary);

                // Ejecutar checks con paralelismo de 4
                var totalSw = Stopwatch.StartNew();
                var semaphore = new SemaphoreSlim(4);
                var tasks = new List<Task<UrlCheckResult>>();
                int index = 0;

                foreach (var entry in payload.Urls)
                {
                    int idx = ++index;
                    tasks.Add(CheckSingleUrlAsync(client, entry.Url, idx, payload.Urls.Count,
                        payload.TimeoutSeconds, entry.Critical, entry.Function,
                        semaphore, totalCts.Token));
                }

                var results = await Task.WhenAll(tasks);
                totalSw.Stop();

                // Calcular resultados
                int total = results.Length;
                int okCount = results.Count(r => r.Success);
                int percent = total > 0 ? (okCount * 100) / total : 0;
                int criticalTotal = results.Count(r => r.Critical);
                int criticalOk = results.Count(r => r.Critical && r.Success);

                // Log resumen
                AlwaysPrintLogger.WriteTrayInfo(
                    $"ConnectivityCheck: completado. OK={okCount}/{total} ({percent}%). " +
                    $"Críticos OK={criticalOk}/{criticalTotal}. " +
                    $"Proxy={proxyMode}. Duración={totalSw.ElapsedMilliseconds}ms",
                    AlwaysPrintLogger.EvtConnectivitySummary);

                // Log fallos individuales
                foreach (var fail in results.Where(r => !r.Success))
                {
                    AlwaysPrintLogger.WriteTrayError(
                        $"ConnectivityCheck: FALLO {fail.Url} — {fail.Error} " +
                        $"({fail.Attempts} intentos, latencia={fail.LatencyMs}ms)",
                        AlwaysPrintLogger.EvtConnectivityFail);
                }

                // Determinar severidad 4 niveles
                int totalFails = results.Count(r => !r.Success);
                int criticalFails = results.Count(r => r.Critical && !r.Success);
                int totalOk = results.Count(r => r.Success);

                // Verde: todo OK → verificar si notificación verde está habilitada
                if (totalFails == 0)
                {
                    var greenConfig = payload.Notifications?.Green;
                    if (greenConfig != null && greenConfig.Enabled)
                    {
                        ShowNotificationOnDedicatedThread(results.ToList(), percent, payload,
                            ConnectivitySeverity.Green, greenConfig);
                    }
                    else
                    {
                        AlwaysPrintLogger.WriteTrayInfo(
                            "ConnectivityCheck: todos los servicios accesibles. Notificación verde deshabilitada.",
                            AlwaysPrintLogger.EvtConnectivitySummary);
                    }
                    return;
                }

                // Determinar severidad:
                // Rojo: fallan TODOS (sin conectividad)
                // Naranja: falla al menos 1 crítico pero hay conectividad parcial
                // Amarillo: solo fallan no-críticos, todos los críticos OK
                ConnectivitySeverity severity;
                if (totalOk == 0)
                    severity = ConnectivitySeverity.Red;
                else if (criticalFails > 0)
                    severity = ConnectivitySeverity.Orange;
                else
                    severity = ConnectivitySeverity.Yellow;

                // Obtener configuración de notificación para este nivel
                var notifConfig = GetNotificationConfig(payload.Notifications, severity);

                if (!notifConfig.Enabled)
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"ConnectivityCheck: severidad {severity} — notificación deshabilitada en config.",
                        AlwaysPrintLogger.EvtConnectivitySummary);
                    return;
                }

                ShowNotificationOnDedicatedThread(results.ToList(), percent, payload, severity, notifConfig);
            }
            catch (OperationCanceledException)
            {
                AlwaysPrintLogger.WriteTrayError(
                    "ConnectivityCheck: timeout global de 90 segundos alcanzado, abortando check.",
                    AlwaysPrintLogger.EvtGenericError);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    "ConnectivityCheck: error inesperado durante la ejecución.", ex,
                    AlwaysPrintLogger.EvtGenericError);
            }
            finally
            {
                _checkInProgress = false;
            }
        }

        /// <summary>
        /// Verifica una URL individual. Cualquier respuesta HTTP = OK.
        /// Solo excepciones de transporte = FALLO (con 1 retry, 500ms backoff).
        /// </summary>
        private async Task<UrlCheckResult> CheckSingleUrlAsync(
            HttpClient client, string url, int index, int total,
            int timeoutSeconds, bool critical, string function,
            SemaphoreSlim semaphore, CancellationToken cancellationToken)
        {
            await semaphore.WaitAsync(cancellationToken);
            try
            {
                return await CheckUrlWithTransportRetry(client, url, index, total,
                    timeoutSeconds, critical, function, cancellationToken);
            }
            finally
            {
                semaphore.Release();
            }
        }

        private async Task<UrlCheckResult> CheckUrlWithTransportRetry(
            HttpClient client, string url, int index, int total,
            int timeoutSeconds, bool critical, string function,
            CancellationToken cancellationToken)
        {
            int maxAttempts = 2; // 1 intento + 1 retry
            int attempts = 0;
            string lastError = null;
            long lastLatencyMs = 0;

            for (int attempt = 0; attempt < maxAttempts; attempt++)
            {
                if (cancellationToken.IsCancellationRequested)
                {
                    lastError = "Cancelado (timeout global)";
                    break;
                }

                attempts++;

                // 500ms backoff antes del retry (no en el primer intento)
                if (attempt > 0)
                {
                    try { await Task.Delay(500, cancellationToken); }
                    catch (OperationCanceledException) { lastError = "Cancelado (timeout global)"; break; }
                }

                var sw = Stopwatch.StartNew();
                try
                {
                    var request = new HttpRequestMessage(HttpMethod.Get, url);
                    var sendTask = client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead);
                    var timeoutTask = Task.Delay(timeoutSeconds * 1000, cancellationToken);

                    var completed = await Task.WhenAny(sendTask, timeoutTask);
                    sw.Stop();
                    lastLatencyMs = sw.ElapsedMilliseconds;

                    if (completed == timeoutTask)
                    {
                        lastError = "Timeout";
                        continue; // Retry on timeout (excepción de transporte)
                    }

                    if (sendTask.IsFaulted)
                    {
                        var ex = sendTask.Exception?.InnerException ?? sendTask.Exception;
                        lastError = ClassifyTransportError(ex);
                        continue; // Retry on transport exception
                    }

                    // CUALQUIER respuesta HTTP = SUCCESS (conectividad de transporte probada)
                    var response = sendTask.Result;
                    int statusCode = (int)response.StatusCode;

                    // Log OK con código de estado (valor diagnóstico)
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"ConnectivityCheck: [{index}/{total}] {url} — OK (HTTP {statusCode}, {lastLatencyMs}ms, {attempts} intento(s))",
                        AlwaysPrintLogger.EvtConnectivitySummary);

                    return new UrlCheckResult
                    {
                        Url = url,
                        Success = true,
                        LatencyMs = lastLatencyMs,
                        StatusCode = statusCode,
                        Attempts = attempts,
                        Critical = critical,
                        Function = function
                    };
                }
                catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
                {
                    sw.Stop();
                    lastLatencyMs = sw.ElapsedMilliseconds;
                    lastError = "Cancelado (timeout global)";
                    break; // No reintentar si el timeout global se alcanzó
                }
                catch (Exception ex)
                {
                    sw.Stop();
                    lastLatencyMs = sw.ElapsedMilliseconds;
                    lastError = ClassifyTransportError(ex);
                    continue; // Retry on transport exception
                }
            }

            // Todos los intentos fallaron — log FALLO
            AlwaysPrintLogger.WriteTrayInfo(
                $"ConnectivityCheck: [{index}/{total}] {url} — FALLO ({lastError}, {attempts} intento(s))",
                AlwaysPrintLogger.EvtConnectivitySummary);

            return new UrlCheckResult
            {
                Url = url,
                Success = false,
                LatencyMs = lastLatencyMs,
                StatusCode = 0,
                Attempts = attempts,
                Error = lastError,
                Critical = critical,
                Function = function
            };
        }

        /// <summary>
        /// Clasifica el tipo de excepción de transporte para el log.
        /// </summary>
        private static string ClassifyTransportError(Exception ex)
        {
            if (ex == null) return "Error desconocido";

            // Unwrap AggregateException
            if (ex is AggregateException agg && agg.InnerException != null)
                ex = agg.InnerException;

            if (ex is HttpRequestException httpEx)
            {
                var inner = httpEx.InnerException;
                if (inner is WebException webEx)
                {
                    switch (webEx.Status)
                    {
                        case WebExceptionStatus.NameResolutionFailure:
                            return "DNS: no se pudo resolver";
                        case WebExceptionStatus.ConnectFailure:
                            return "TCP: conexión rechazada";
                        case WebExceptionStatus.Timeout:
                            return "Timeout";
                        case WebExceptionStatus.SecureChannelFailure:
                        case WebExceptionStatus.TrustFailure:
                            return $"TLS: {inner.Message}";
                        default:
                            return $"Red: {webEx.Status} — {webEx.Message}";
                    }
                }
                if (inner is SocketException sockEx)
                {
                    return $"Socket: {sockEx.SocketErrorCode} — {sockEx.Message}";
                }
                // Errores TLS
                if (inner != null && inner.GetType().Name.Contains("Authentication"))
                {
                    return $"TLS: {inner.Message}";
                }
                return $"HTTP: {httpEx.Message}";
            }

            if (ex is SocketException socketEx)
            {
                return $"Socket: {socketEx.SocketErrorCode}";
            }

            if (ex is OperationCanceledException || ex is TaskCanceledException)
            {
                return "Timeout";
            }

            return $"{ex.GetType().Name}: {ex.Message}";
        }

        /// <summary>
        /// Muestra la notificación en un thread STA dedicado con su propio message loop.
        /// </summary>
        private void ShowNotificationOnDedicatedThread(
            List<UrlCheckResult> results, int percent, ConnectivityCheckPayload payload,
            ConnectivitySeverity severity, NotificationLevel notifConfig)
        {
            var thread = new Thread(() =>
            {
                try
                {
                    Application.EnableVisualStyles();
                    ConnectivityNotificationForm.ShowResult(results, percent, payload, severity, notifConfig);
                    Application.Run();
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        $"ConnectivityCheck: error mostrando notificación: {ex.Message}",
                        AlwaysPrintLogger.EvtGenericError);
                }
            });
            thread.SetApartmentState(ApartmentState.STA);
            thread.IsBackground = true;
            thread.Name = "ConnectivityNotification";
            thread.Start();
        }

        /// <summary>
        /// Obtiene la configuración de notificación para un nivel de severidad dado.
        /// </summary>
        private static NotificationLevel GetNotificationConfig(NotificationConfig config, ConnectivitySeverity severity)
        {
            if (config == null) return new NotificationLevel { Enabled = true, Text = "Conectividad", TimeoutSeconds = 0, Color = "#FFF3E0" };

            switch (severity)
            {
                case ConnectivitySeverity.Green: return config.Green ?? new NotificationLevel { Enabled = false };
                case ConnectivitySeverity.Yellow: return config.Yellow ?? new NotificationLevel { Enabled = true, Text = "Conectividad: servicios no críticos inaccesibles", TimeoutSeconds = 10, Color = "#FFF8E1" };
                case ConnectivitySeverity.Orange: return config.Orange ?? new NotificationLevel { Enabled = true, Text = "Conectividad: servicios críticos inaccesibles", TimeoutSeconds = 0, Color = "#FFF3E0" };
                case ConnectivitySeverity.Red: return config.Red ?? new NotificationLevel { Enabled = true, Text = "Sin conectividad a Internet", TimeoutSeconds = 0, Color = "#FFEBEE" };
                default: return new NotificationLevel { Enabled = true };
            }
        }

        /// <summary>
        /// Verifica conectividad TCP a un host:puerto con timeout.
        /// </summary>
        private async Task<bool> TestTcpConnectAsync(string host, int port, int timeoutMs)
        {
            try
            {
                using var tcp = new TcpClient();
                var connectTask = tcp.ConnectAsync(host, port);
                var timeoutTask = Task.Delay(timeoutMs);
                var completed = await Task.WhenAny(connectTask, timeoutTask);
                return completed == connectTask && !connectTask.IsFaulted;
            }
            catch { return false; }
        }
    }
}
