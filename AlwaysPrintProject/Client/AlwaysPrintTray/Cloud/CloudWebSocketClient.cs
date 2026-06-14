using System;
using System.Net;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Cliente WebSocket para comunicación con AlwaysPrint Cloud Manager.
    /// Usa System.Net.WebSockets.ClientWebSocket nativo de .NET 4.8.
    /// ClientWebSocket maneja ping/pong RFC 6455 automáticamente a nivel de protocolo.
    /// </summary>
    public sealed class CloudWebSocketClient : IDisposable
    {
        // === Eventos públicos ===
        public event Action?                 Connected;
        public event Action?                 Disconnected;
        public event Action<string, string>? MessageReceived;  // (type, fullJson)
        public event Action<Exception>?      Error;

        // === Estado ===
        public bool IsConnected { get; private set; }

        // === HttpClient compartido para requests HTTP ===
        public System.Net.Http.HttpClient HttpClient { get; private set; }

        // === Backoff ===
        private const int InitialDelayMs   = 1_000;
        private const int MaxDelayMs       = 60_000;
        private const int LongRetryDelayMs = 300_000;  // 5 min para código 1008

        private int  _currentDelayMs = InitialDelayMs;
        private bool _longRetryMode  = false;

        // Flag de primer reconexión: usa jitter distribuido en vez de delay fijo.
        // Se resetea a true cuando la conexión se establece exitosamente.
        private bool _isFirstReconnect = true;

        // === Internos ===
        private readonly string _wsUrl;
        private readonly Uri?   _proxyUri;
        private readonly object _lock = new object();
        private ClientWebSocket?        _ws;
        private CancellationTokenSource  _cts = new CancellationTokenSource();
        private bool _disposed;

        // === Serialización de envíos ===
        // ClientWebSocket solo permite un SendAsync en vuelo a la vez.
        // Sin este semáforo, envíos concurrentes (pong + status_update + resources)
        // abortan el socket con "There is already one outstanding SendAsync call".
        private readonly SemaphoreSlim _sendLock = new SemaphoreSlim(1, 1);

        // === Diagnóstico de conexión ===
        private DateTime _connectedSince = DateTime.MinValue;
        private DateTime _lastPingReceived = DateTime.MinValue;

        // Tamaño del buffer de recepción (16 KB)
        private const int ReceiveBufferSize = 16 * 1024;

        public CloudWebSocketClient(string cloudApiUrl)
        {
            // Forzar TLS 1.2 para conexiones seguras
            ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;

            // Derivar URL WSS: https://host → wss://host/ws/workstation
            _wsUrl = cloudApiUrl
                .Replace("https://", "wss://")
                .Replace("http://", "ws://")
                .TrimEnd('/') + "/ws/workstation";

            // Detectar proxy del sistema
            var targetUri = new Uri(cloudApiUrl);
            _proxyUri = ProxyHelper.GetSystemProxyUri(targetUri);

            // Inicializar HttpClient con proxy si es necesario
            var handler = new System.Net.Http.HttpClientHandler();
            if (_proxyUri != null)
            {
                handler.Proxy = new System.Net.WebProxy(_proxyUri);
                handler.UseProxy = true;
            }
            HttpClient = new System.Net.Http.HttpClient(handler)
            {
                Timeout = TimeSpan.FromSeconds(30)
            };

            AlwaysPrintLogger.WriteTrayInfo(
                $"CloudWebSocketClient: URL WebSocket derivada = {_wsUrl}" +
                (_proxyUri != null ? $" (proxy: {_proxyUri})" : " (conexión directa)"));
        }

        /// <summary>
        /// Inicia la conexión WebSocket. Dispara el evento Connected al establecerse.
        /// Usa fire-and-forget internamente (los llamadores usan eventos, no await).
        /// </summary>
        public void Connect()
        {
            lock (_lock)
            {
                if (_disposed) return;

                // Recrear CancellationTokenSource si fue cancelado previamente
                if (_cts.IsCancellationRequested)
                {
                    _cts.Dispose();
                    _cts = new CancellationTokenSource();
                }
            }

            // Lanzar conexión asíncrona sin bloquear (fire-and-forget)
            Task.Run(() => ConnectInternalAsync());
        }

        /// <summary>
        /// Envía un mensaje JSON al servidor con el tipo y payload especificados.
        /// Serializa las llamadas a SendAsync mediante SemaphoreSlim para evitar
        /// que dos envíos concurrentes aborten el socket.
        /// </summary>
        public void Send(string type, object? payload)
        {
            ClientWebSocket? ws;
            lock (_lock)
            {
                ws = _ws;
                if (ws?.State != WebSocketState.Open) return;
            }

            var msg = payload != null
                ? JObject.FromObject(payload)
                : new JObject();
            msg["type"] = type;

            var json = msg.ToString(Formatting.None);
            var bytes = Encoding.UTF8.GetBytes(json);

            // Enviar de forma asíncrona sin bloquear, serializado por semáforo
            Task.Run(async () =>
            {
                if (!await _sendLock.WaitAsync(TimeSpan.FromSeconds(10)).ConfigureAwait(false))
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"CloudWebSocketClient: timeout esperando turno de envío para mensaje tipo='{type}'. Descartando.");
                    return;
                }

                try
                {
                    // Verificar estado del socket dentro del lock (pudo cerrarse mientras esperaba)
                    if (ws.State != WebSocketState.Open) return;

                    var segment = new ArraySegment<byte>(bytes);
                    await ws.SendAsync(segment, WebSocketMessageType.Text, true, _cts.Token)
                        .ConfigureAwait(false);
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"CloudWebSocketClient: error enviando mensaje tipo='{type}'. {ex.Message}");
                }
                finally
                {
                    _sendLock.Release();
                }
            });
        }

        /// <summary>
        /// Desconecta el WebSocket y cancela operaciones pendientes.
        /// </summary>
        public void Disconnect()
        {
            lock (_lock)
            {
                _cts.Cancel();
                CloseSocketSafe();
                IsConnected = false;
            }
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            Disconnect();
            _cts.Dispose();
            _sendLock.Dispose();
            HttpClient?.Dispose();
        }

        // === Métodos privados asíncronos ===

        /// <summary>
        /// Lógica interna de conexión asíncrona.
        /// Crea el ClientWebSocket, conecta, y lanza el bucle de recepción.
        /// </summary>
        private async Task ConnectInternalAsync()
        {
            ClientWebSocket ws;
            CancellationToken token;

            lock (_lock)
            {
                if (_disposed || _cts.IsCancellationRequested) return;

                // Limpiar socket anterior si existe
                CloseSocketSafe();

                // Crear nuevo ClientWebSocket
                ws = new ClientWebSocket();

                // Configurar proxy si se detectó uno
                if (_proxyUri != null)
                {
                    ws.Options.Proxy = new WebProxy(_proxyUri);
                }

                _ws = ws;
                token = _cts.Token;
            }

            try
            {
                // Conectar al servidor WebSocket
                await ws.ConnectAsync(new Uri(_wsUrl), token).ConfigureAwait(false);

                lock (_lock)
                {
                    IsConnected     = true;
                    _currentDelayMs = InitialDelayMs;
                    _longRetryMode  = false;
                    _isFirstReconnect = true;
                    _connectedSince = DateTime.UtcNow;
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    "CloudWebSocketClient: conexión WebSocket establecida exitosamente.");
                Connected?.Invoke();

                // Iniciar bucle de recepción de mensajes
                await ReceiveLoopAsync(ws, token).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                // Desconexión intencional, no reconectar
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudWebSocketClient: error al conectar. {ex.Message}");
                Error?.Invoke(ex);

                // Programar reconexión
                ScheduleReconnect();
            }
        }

        /// <summary>
        /// Bucle de recepción continua de mensajes.
        /// Lee mensajes completos y dispara el evento MessageReceived.
        /// Al cerrarse la conexión, dispara Disconnected y programa reconexión.
        /// </summary>
        private async Task ReceiveLoopAsync(ClientWebSocket ws, CancellationToken token)
        {
            var buffer = new byte[ReceiveBufferSize];
            var messageBuilder = new StringBuilder();

            try
            {
                while (ws.State == WebSocketState.Open && !token.IsCancellationRequested)
                {
                    messageBuilder.Clear();
                    WebSocketReceiveResult result;

                    // Leer fragmentos hasta obtener el mensaje completo
                    do
                    {
                        var segment = new ArraySegment<byte>(buffer);
                        result = await ws.ReceiveAsync(segment, token).ConfigureAwait(false);

                        if (result.MessageType == WebSocketMessageType.Close)
                        {
                            // El servidor cerró la conexión
                            HandleRemoteClose(ws, result);
                            return;
                        }

                        if (result.MessageType == WebSocketMessageType.Text)
                        {
                            messageBuilder.Append(Encoding.UTF8.GetString(buffer, 0, result.Count));
                        }
                    }
                    while (!result.EndOfMessage);

                    // Procesar mensaje completo
                    if (messageBuilder.Length > 0)
                    {
                        ProcessMessage(messageBuilder.ToString());
                    }
                }
            }
            catch (OperationCanceledException)
            {
                // Desconexión intencional
            }
            catch (WebSocketException ex)
            {
                // Diagnóstico detallado de desconexión no limpia
                var duration = _connectedSince != DateTime.MinValue
                    ? (DateTime.UtcNow - _connectedSince)
                    : TimeSpan.Zero;
                var lastPingAgo = _lastPingReceived != DateTime.MinValue
                    ? (DateTime.UtcNow - _lastPingReceived)
                    : TimeSpan.Zero;

                string wsState = "desconocido";
                string closeStatus = "N/A";
                try { wsState = ws.State.ToString(); } catch { }
                try { closeStatus = ws.CloseStatus?.ToString() ?? "null"; } catch { }

                var innerMsg = ex.InnerException != null
                    ? $"{ex.InnerException.GetType().Name}: {ex.InnerException.Message}"
                    : "ninguna";

                AlwaysPrintLogger.WriteTrayError(
                    $"CloudWebSocketClient: desconexión no limpia detectada. " +
                    $"WebSocketError={ex.WebSocketErrorCode}, " +
                    $"State={wsState}, " +
                    $"CloseStatus={closeStatus}, " +
                    $"InnerException=[{innerMsg}], " +
                    $"DuraciónConexión={duration.TotalMinutes:F1}min, " +
                    $"ÚltimoPingServidor=hace {lastPingAgo.TotalSeconds:F0}s, " +
                    $"Mensaje={ex.Message}");
                Error?.Invoke(ex);
            }
            catch (Exception ex)
            {
                // Diagnóstico para errores inesperados (no WebSocketException)
                var duration = _connectedSince != DateTime.MinValue
                    ? (DateTime.UtcNow - _connectedSince)
                    : TimeSpan.Zero;
                var lastPingAgo = _lastPingReceived != DateTime.MinValue
                    ? (DateTime.UtcNow - _lastPingReceived)
                    : TimeSpan.Zero;

                string wsState = "desconocido";
                try { wsState = ws.State.ToString(); } catch { }

                var innerMsg = ex.InnerException != null
                    ? $"{ex.InnerException.GetType().Name}: {ex.InnerException.Message}"
                    : "ninguna";

                AlwaysPrintLogger.WriteTrayError(
                    $"CloudWebSocketClient: error inesperado en recepción. " +
                    $"Tipo={ex.GetType().Name}, " +
                    $"State={wsState}, " +
                    $"InnerException=[{innerMsg}], " +
                    $"DuraciónConexión={duration.TotalMinutes:F1}min, " +
                    $"ÚltimoPingServidor=hace {lastPingAgo.TotalSeconds:F0}s, " +
                    $"Mensaje={ex.Message}");
                Error?.Invoke(ex);
            }
            finally
            {
                // Notificar desconexión y programar reconexión
                bool wasConnected;
                lock (_lock)
                {
                    wasConnected = IsConnected;
                    IsConnected = false;
                }

                if (wasConnected)
                {
                    Disconnected?.Invoke();
                }

                if (!token.IsCancellationRequested)
                {
                    ScheduleReconnect();
                }
            }
        }

        /// <summary>
        /// Maneja el cierre remoto del WebSocket.
        /// Detecta código 1008 (IP no autorizada) para activar modo de reintento largo.
        /// Incluye diagnóstico de duración de conexión para análisis de patrones.
        /// </summary>
        private void HandleRemoteClose(ClientWebSocket ws, WebSocketReceiveResult result)
        {
            var closeStatus = result.CloseStatus ?? WebSocketCloseStatus.Empty;
            var closeDescription = result.CloseStatusDescription ?? "";
            var duration = _connectedSince != DateTime.MinValue
                ? (DateTime.UtcNow - _connectedSince)
                : TimeSpan.Zero;

            // Código 1008 = Policy Violation (IP no autorizada en APCM)
            if ((int)closeStatus == 1008)
            {
                if (closeDescription.Contains("no autorizada") || closeDescription.Contains("not authorized"))
                {
                    _longRetryMode = true;
                    AlwaysPrintLogger.WriteTrayWarning(
                        "CloudWebSocketClient: conexión rechazada por APCM (código 1008 — IP no autorizada). " +
                        $"DuraciónConexión={duration.TotalMinutes:F1}min. " +
                        $"Reintentando cada {LongRetryDelayMs / 1000}s.");
                }
                else
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"CloudWebSocketClient: conexión cerrada con código 1008 pero razón no indica IP no autorizada " +
                        $"(razón: '{closeDescription}'). DuraciónConexión={duration.TotalMinutes:F1}min. Usando backoff normal.");
                }
            }
            else
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"CloudWebSocketClient: servidor cerró conexión. " +
                    $"Código: {(int)closeStatus}, Razón: '{closeDescription}', " +
                    $"DuraciónConexión={duration.TotalMinutes:F1}min");
            }

            // Intentar cerrar limpiamente desde nuestro lado
            try
            {
                ws.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, "Cierre confirmado", CancellationToken.None)
                    .GetAwaiter().GetResult();
            }
            catch { /* Ignorar errores al confirmar cierre */ }
        }

        /// <summary>
        /// Parsea el mensaje JSON recibido y dispara el evento MessageReceived.
        /// Registra timestamp del último ping recibido del servidor para diagnóstico.
        /// </summary>
        private void ProcessMessage(string json)
        {
            try
            {
                var obj  = JObject.Parse(json);
                var type = obj["type"]?.ToString() ?? "unknown";

                // Trackear último ping del servidor para diagnóstico de desconexiones
                if (type == "ping")
                {
                    _lastPingReceived = DateTime.UtcNow;
                }

                MessageReceived?.Invoke(type, json);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"CloudWebSocketClient: error parseando mensaje. {ex.Message}");
            }
        }

        /// <summary>
        /// Programa la reconexión con jitter (primer intento) o backoff exponencial.
        /// Primer intento post-desconexión: delay aleatorio U(0, JitterWindowSeconds) para evitar thundering herd.
        /// Intentos subsecuentes: backoff exponencial 2s, 4s, 8s... hasta 60s.
        /// En modo largo (código 1008): cada 5 minutos.
        /// </summary>
        private void ScheduleReconnect()
        {
            if (_disposed || _cts.IsCancellationRequested) return;

            int delay;

            if (_isFirstReconnect && !_longRetryMode)
            {
                // Primer intento tras desconexión: aplicar jitter distribuido
                var registry = new RegistryConfigManager();
                int jitterWindow = registry.LoadJitterWindowSeconds();
                jitterWindow = JitterCalculator.NormalizeJitterWindow(jitterWindow);
                delay = JitterCalculator.ComputeReconnectionDelay(jitterWindow);

                _isFirstReconnect = false;
                _currentDelayMs = 2000; // Siguiente intento arranca en 2s (backoff exponencial)

                AlwaysPrintLogger.WriteTrayInfo(
                    $"CloudWebSocketClient: primer reconexión con jitter distribuido. " +
                    $"Ventana={jitterWindow}s, delay={delay / 1000.0:F1}s");
            }
            else if (_longRetryMode)
            {
                delay = LongRetryDelayMs;
            }
            else
            {
                delay = _currentDelayMs;
                _currentDelayMs = Math.Min(_currentDelayMs * 2, MaxDelayMs);
            }

            AlwaysPrintLogger.WriteTrayWarning(
                $"CloudWebSocketClient: reconectando en {delay / 1000.0:F1}s...");

            // Programar reconexión en el ThreadPool
            ThreadPool.QueueUserWorkItem(_ =>
            {
                try
                {
                    _cts.Token.WaitHandle.WaitOne(delay);
                    if (!_cts.IsCancellationRequested && !_disposed)
                    {
                        Task.Run(() => ConnectInternalAsync());
                    }
                }
                catch (ObjectDisposedException) { /* Token ya fue disposed */ }
            });
        }

        /// <summary>
        /// Cierra el socket actual de forma segura sin lanzar excepciones.
        /// Debe llamarse dentro del lock.
        /// </summary>
        private void CloseSocketSafe()
        {
            if (_ws != null)
            {
                try
                {
                    if (_ws.State == WebSocketState.Open || _ws.State == WebSocketState.CloseReceived)
                    {
                        _ws.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, "Desconexión solicitada", CancellationToken.None)
                            .GetAwaiter().GetResult();
                    }
                }
                catch { /* Ignorar errores al cerrar */ }
                finally
                {
                    _ws.Dispose();
                    _ws = null;
                }
            }
        }
    }
}
