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

                // Timeout = Infinite porque gestionamos timeouts por request con Task.WhenAny + Task.Delay.
                // En .NET Framework 4.8, ni HttpClient.Timeout ni CancellationToken interrumpen
                // la resolución DNS o la conexión TCP — Task.WhenAny es el único mecanismo fiable.
                using var client = new HttpClient(httpHandler)
                {
                    Timeout = System.Threading.Timeout.InfiniteTimeSpan
                };

                // 3. Ejecutar checks secuencialmente (medir duración total)
                var totalSw = Stopwatch.StartNew();
                var results = new List<UrlCheckResult>();
                int urlIndex = 0;
                foreach (var url in payload.Urls)
                {
                    urlIndex++;
                    var result = await CheckUrlWithRetriesAsync(client, url, payload, totalCts.Token);
                    results.Add(result);

                    // Log progreso por URL para diagnóstico
                    if (result.Success)
                    {
                        AlwaysPrintLogger.WriteTrayInfo(
                            $"ConnectivityCheck: [{urlIndex}/{payload.Urls.Count}] {result.Url} — OK ({result.LatencyMs}ms, {result.Attempts} intento(s))",
                            AlwaysPrintLogger.EvtConnectivitySummary);
                    }
                    else
                    {
                        AlwaysPrintLogger.WriteTrayInfo(
                            $"ConnectivityCheck: [{urlIndex}/{payload.Urls.Count}] {result.Url} — FALLO ({result.Error}, {result.Attempts} intento(s))",
                            AlwaysPrintLogger.EvtConnectivitySummary);
                    }
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
                AlwaysPrintLogger.WriteTrayInfo(
                    $"ConnectivityCheck: mostrando notificación ({(percent == 100 ? "verde" : percent > 0 ? "amarilla" : "roja")}, {percent}%).",
                    AlwaysPrintLogger.EvtConnectivitySummary);
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
        /// 
        /// IMPORTANTE: Usa Task.WhenAny con Task.Delay para timeout REAL.
        /// En .NET Framework 4.8, CancellationToken NO puede interrumpir la resolución DNS
        /// ni la conexión TCP — esas operaciones de sistema ignoran el token y se cuelgan
        /// indefinidamente. Task.WhenAny garantiza que si el Delay gana, continuamos
        /// sin esperar a que la request bloqueada termine (se abandona en background).
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
                if (cancellationToken.IsCancellationRequested)
                {
                    lastError = "Cancelado (timeout global)";
                    break;
                }

                attempts++;

                // Esperar entre reintentos (no en el primer intento)
                if (i > 0)
                {
                    try { await Task.Delay(payload.RetryDelaySeconds * 1000, cancellationToken); }
                    catch (OperationCanceledException) { lastError = "Cancelado (timeout global)"; break; }
                }

                var sw = Stopwatch.StartNew();
                try
                {
                    // REAL timeout usando Task.WhenAny — .NET Framework 4.8 CancellationToken
                    // NO cancela de forma fiable la resolución DNS ni la conexión TCP
                    var request = new HttpRequestMessage(HttpMethod.Head, url);
                    var sendTask = client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead);
                    var timeoutTask = Task.Delay(payload.TimeoutSeconds * 1000, cancellationToken);

                    var completed = await Task.WhenAny(sendTask, timeoutTask);
                    sw.Stop();
                    lastLatencyMs = sw.ElapsedMilliseconds;

                    if (completed == timeoutTask)
                    {
                        // Timeout — la request sigue corriendo en background pero no la esperamos
                        lastError = "Timeout";
                        continue; // Reintentar
                    }

                    // sendTask completó — verificar si falló
                    if (sendTask.IsFaulted)
                    {
                        var ex = sendTask.Exception?.InnerException;
                        lastError = ex?.Message ?? "Error desconocido";
                        continue;
                    }

                    var response = sendTask.Result;
                    lastStatusCode = (int)response.StatusCode;

                    // Si el servidor no soporta HEAD, reintentar con GET
                    if (lastStatusCode == 405)
                    {
                        sw = Stopwatch.StartNew();
                        var getRequest = new HttpRequestMessage(HttpMethod.Get, url);
                        var getSendTask = client.SendAsync(getRequest, HttpCompletionOption.ResponseHeadersRead);
                        var getTimeoutTask = Task.Delay(payload.TimeoutSeconds * 1000, cancellationToken);

                        var getCompleted = await Task.WhenAny(getSendTask, getTimeoutTask);
                        sw.Stop();
                        lastLatencyMs = sw.ElapsedMilliseconds;

                        if (getCompleted == getTimeoutTask)
                        {
                            lastError = "Timeout (GET fallback)";
                            continue;
                        }

                        if (getSendTask.IsFaulted)
                        {
                            var ex = getSendTask.Exception?.InnerException;
                            lastError = ex?.Message ?? "Error desconocido";
                            continue;
                        }

                        response = getSendTask.Result;
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
                catch (Exception ex)
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
