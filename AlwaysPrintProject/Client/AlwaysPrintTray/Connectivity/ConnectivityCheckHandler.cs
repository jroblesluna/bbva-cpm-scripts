using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
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
    /// Orquestador de checks de conectividad. Recibe un ConnectivityCheckPayload
    /// vía Named Pipe desde el Service, ejecuta verificaciones HTTP contra cada URL,
    /// registra resultados en log y muestra notificación al usuario.
    /// </summary>
    public class ConnectivityCheckHandler
    {
        /// <summary>
        /// Flag para evitar ejecuciones superpuestas. Si un check está en curso,
        /// las solicitudes adicionales se descartan con un warning en log.
        /// </summary>
        private volatile bool _checkInProgress;

        /// <summary>
        /// Contexto de sincronización del hilo UI para mostrar notificaciones
        /// en el thread correcto (WinForms requiere crear controles en el UI thread).
        /// </summary>
        private readonly SynchronizationContext _uiContext;

        /// <summary>
        /// Crea una nueva instancia del handler de conectividad.
        /// </summary>
        /// <param name="uiContext">Contexto de sincronización del hilo UI para marshaling de notificaciones.</param>
        public ConnectivityCheckHandler(SynchronizationContext uiContext)
        {
            _uiContext = uiContext ?? throw new ArgumentNullException(nameof(uiContext));
        }

        /// <summary>
        /// Ejecuta el check de conectividad completo: detecta proxy, verifica cada URL
        /// con reintentos, calcula porcentaje de éxito, escribe en log y muestra notificación.
        /// Si ya hay un check en curso, retorna inmediatamente con un warning.
        /// </summary>
        /// <param name="payload">Payload con URLs y parámetros de configuración.</param>
        public async Task ExecuteCheckAsync(ConnectivityCheckPayload payload)
        {
            // Evitar ejecuciones superpuestas
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

                // Timeout global de 3 minutos para evitar que el check se quede colgado indefinidamente
                // (puede ocurrir si el proxy no responde durante la negociación)
                using var totalCts = new CancellationTokenSource(TimeSpan.FromMinutes(3));

                // 1. Detectar proxy del sistema (buscar una URL que no esté en bypass)
                Uri proxyUri = null;
                bool proxyActive = false;

                foreach (var url in payload.Urls)
                {
                    try
                    {
                        var uri = new Uri(url.StartsWith("http") ? url : "https://" + url);
                        proxyUri = ProxyHelper.GetSystemProxyUri(uri);
                        if (proxyUri != null) break; // Encontramos un proxy configurado
                    }
                    catch { /* URL inválida, seguir con la siguiente */ }
                }

                if (proxyUri != null)
                {
                    // Verificar que el proxy esté activo con TCP connect (2s timeout)
                    proxyActive = await TestTcpConnectAsync(proxyUri.Host, proxyUri.Port, 2000);
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"ConnectivityCheck: proxy {proxyUri.Host}:{proxyUri.Port} — " +
                        (proxyActive ? "activo" : "inactivo"),
                        AlwaysPrintLogger.EvtConnectivitySummary);
                }
                else
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        "ConnectivityCheck: no se detectó proxy del sistema (todas las URLs en bypass o conexión directa).",
                        AlwaysPrintLogger.EvtConnectivitySummary);
                }

                // 2. Crear HttpClient — CON proxy solo si está activo y accesible
                // Si el proxy no responde, usar conexión directa para evitar hang infinito
                // durante la negociación HTTP en .NET Framework 4.8
                HttpClientHandler httpHandler;
                if (proxyUri != null && proxyActive)
                {
                    httpHandler = ProxyHelper.CreateHandler();
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"ConnectivityCheck: usando proxy {proxyUri.Host}:{proxyUri.Port}",
                        AlwaysPrintLogger.EvtConnectivitySummary);
                }
                else
                {
                    httpHandler = new HttpClientHandler { UseProxy = false };
                    AlwaysPrintLogger.WriteTrayInfo(
                        "ConnectivityCheck: usando conexión directa (proxy no disponible o inactivo).",
                        AlwaysPrintLogger.EvtConnectivitySummary);
                }

                // Timeout = Infinite porque gestionamos timeouts por request con CancellationToken
                // (HttpClient.Timeout no es confiable con proxies en .NET Framework 4.8)
                using var client = new HttpClient(httpHandler)
                {
                    Timeout = System.Threading.Timeout.InfiniteTimeSpan
                };

                // 3. Ejecutar checks secuencialmente (medir duración total)
                var totalSw = Stopwatch.StartNew();
                var results = new List<UrlCheckResult>();
                foreach (var url in payload.Urls)
                {
                    var result = await CheckUrlWithRetriesAsync(client, url, payload, totalCts.Token);
                    results.Add(result);
                }
                totalSw.Stop();

                // 4. Calcular porcentaje de éxito
                int total = results.Count;
                int okCount = results.Count(r => r.Success);
                int percent = (okCount * 100) / total;

                // 5. Registrar resumen en log (Event ID 1090)
                string proxyDisplay = proxyUri != null
                    ? $"{proxyUri.Host}:{proxyUri.Port}"
                    : "directo";
                string proxyStatus = proxyUri != null
                    ? (proxyActive ? "activo" : "inactivo")
                    : "inactivo";

                AlwaysPrintLogger.WriteTrayInfo(
                    $"ConnectivityCheck: completado. OK={okCount}/{total} ({percent}%). " +
                    $"Proxy={proxyDisplay} ({proxyStatus}). " +
                    $"Duración={totalSw.ElapsedMilliseconds}ms",
                    AlwaysPrintLogger.EvtConnectivitySummary);

                // Registrar fallos individuales (Event ID 1091)
                foreach (var fail in results.Where(r => !r.Success))
                {
                    AlwaysPrintLogger.WriteTrayError(
                        $"ConnectivityCheck: FALLO {fail.Url} — {fail.Error} " +
                        $"({fail.Attempts} intentos, latencia={fail.LatencyMs}ms)",
                        AlwaysPrintLogger.EvtConnectivityFail);
                }

                // 6. Mostrar notificación en un thread STA dedicado para evitar conflictos
                // con diálogos modales (StatusForm usa ShowDialog que bloquea el UI thread principal)
                ShowNotificationOnDedicatedThread(results, percent, payload);
            }
            catch (OperationCanceledException)
            {
                AlwaysPrintLogger.WriteTrayError(
                    "ConnectivityCheck: timeout global de 3 minutos alcanzado, abortando check.",
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
        /// Muestra la notificación en un thread STA dedicado con su propio message loop.
        /// Esto evita conflictos con ShowDialog() del StatusForm que bloquea el UI thread principal.
        /// </summary>
        private void ShowNotificationOnDedicatedThread(
            List<UrlCheckResult> results, int percent, ConnectivityCheckPayload payload)
        {
            var thread = new Thread(() =>
            {
                try
                {
                    Application.EnableVisualStyles();
                    ConnectivityNotificationForm.ShowResult(results, percent, payload);
                    Application.Run(); // Message loop propio para esta notificación
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
        /// Verifica una URL individual con reintentos. Primero intenta HEAD;
        /// si el servidor responde 405 (Method Not Allowed), reintenta con GET.
        /// Considera exitosos: 2xx, 301, 302, 403 (el servidor respondió).
        /// </summary>
        /// <param name="client">HttpClient configurado con proxy.</param>
        /// <param name="url">URL a verificar.</param>
        /// <param name="payload">Payload con parámetros de reintentos y delays.</param>
        /// <param name="cancellationToken">Token de cancelación global para abortar si se excede el timeout total.</param>
        /// <returns>Resultado del check para esta URL.</returns>
        private async Task<UrlCheckResult> CheckUrlWithRetriesAsync(
            HttpClient client, string url, ConnectivityCheckPayload payload,
            CancellationToken cancellationToken = default)
        {
            int attempts = 0;
            string lastError = null;
            int lastStatusCode = 0;
            long lastLatencyMs = 0;

            for (int i = 0; i <= payload.MaxRetries; i++)
            {
                // Verificar cancelación global antes de cada intento
                if (cancellationToken.IsCancellationRequested)
                {
                    lastError = "Cancelado (timeout global)";
                    break;
                }

                attempts++;

                // Esperar entre reintentos (no en el primer intento)
                if (i > 0)
                    await Task.Delay(payload.RetryDelaySeconds * 1000, cancellationToken);

                var sw = Stopwatch.StartNew();
                try
                {
                    // Timeout per-request con CancellationTokenSource enlazado al token global
                    // Esto asegura que el request se cancela tanto si excede su propio timeout
                    // como si se alcanza el timeout global de 3 minutos
                    using var requestCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                    requestCts.CancelAfter(TimeSpan.FromSeconds(payload.TimeoutSeconds));

                    // Intentar con HEAD primero
                    var request = new HttpRequestMessage(HttpMethod.Head, url);
                    var response = await client.SendAsync(request, requestCts.Token);
                    sw.Stop();
                    lastLatencyMs = sw.ElapsedMilliseconds;
                    lastStatusCode = (int)response.StatusCode;

                    // Si el servidor no soporta HEAD, reintentar con GET
                    if (lastStatusCode == 405)
                    {
                        sw = Stopwatch.StartNew();
                        using var getCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                        getCts.CancelAfter(TimeSpan.FromSeconds(payload.TimeoutSeconds));
                        var getRequest = new HttpRequestMessage(HttpMethod.Get, url);
                        response = await client.SendAsync(getRequest, getCts.Token);
                        sw.Stop();
                        lastLatencyMs = sw.ElapsedMilliseconds;
                        lastStatusCode = (int)response.StatusCode;
                    }

                    // Éxito: 2xx, 301, 302 o 403 (el servidor respondió)
                    if (response.IsSuccessStatusCode ||
                        lastStatusCode == 301 ||
                        lastStatusCode == 302 ||
                        lastStatusCode == 403)
                    {
                        return new UrlCheckResult
                        {
                            Url = url,
                            Success = true,
                            LatencyMs = lastLatencyMs,
                            StatusCode = lastStatusCode,
                            Attempts = attempts
                        };
                    }

                    lastError = $"HTTP {lastStatusCode}";
                }
                catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
                {
                    sw.Stop();
                    lastLatencyMs = sw.ElapsedMilliseconds;
                    lastError = "Cancelado (timeout global)";
                    break; // No reintentar si el timeout global se alcanzó
                }
                catch (OperationCanceledException)
                {
                    sw.Stop();
                    lastLatencyMs = sw.ElapsedMilliseconds;
                    lastError = "Timeout";
                }
                catch (HttpRequestException ex)
                {
                    sw.Stop();
                    lastLatencyMs = sw.ElapsedMilliseconds;
                    lastError = ex.InnerException?.Message ?? ex.Message;
                }
            }

            return new UrlCheckResult
            {
                Url = url,
                Success = false,
                LatencyMs = lastLatencyMs,
                StatusCode = lastStatusCode,
                Attempts = attempts,
                Error = lastError
            };
        }

        /// <summary>
        /// Verifica conectividad TCP a un host:puerto con timeout.
        /// Se usa para verificar que el proxy está activo antes de intentar HTTP.
        /// </summary>
        /// <param name="host">Host destino (IP o hostname del proxy).</param>
        /// <param name="port">Puerto destino.</param>
        /// <param name="timeoutMs">Timeout de conexión en milisegundos.</param>
        /// <returns>true si la conexión TCP fue exitosa dentro del timeout.</returns>
        private async Task<bool> TestTcpConnectAsync(string host, int port, int timeoutMs)
        {
            try
            {
                using var tcp = new TcpClient();
                var connectTask = tcp.ConnectAsync(host, port);
                var timeoutTask = Task.Delay(timeoutMs);

                var completed = await Task.WhenAny(connectTask, timeoutTask);
                if (completed == connectTask && !connectTask.IsFaulted)
                {
                    return true;
                }

                return false;
            }
            catch
            {
                return false;
            }
        }
    }
}
