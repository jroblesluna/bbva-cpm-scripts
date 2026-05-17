using System;
using System.Net;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using AlwaysPrint.Shared.Logging;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Cliente WebSocket para la conexión con AlwaysPrint Cloud Manager.
    /// Usa System.Net.WebSockets.ClientWebSocket nativo de .NET Framework 4.8.
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

        // === Internos ===
        private readonly string _wsUrl;
        private readonly Uri    _wsUri;
        private readonly Uri?   _proxyUri;
        private readonly object _lock = new object();
        private readonly object _sendLock = new object();  // Lock dedicado para envíos thread-safe

        private ClientWebSocket?        _ws;
        private CancellationTokenSource _cts = new CancellationTokenSource();
        private bool _disposed;

        // Tamaño del buffer de recepción (64 KB — suficiente para mensajes JSON)
        private const int ReceiveBufferSize = 65_536;

        public CloudWebSocketClient(string cloudApiUrl)
        {
            // Forzar TLS 1.2 a nivel de proceso (necesario en .NET 4.8)
            ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;

            // Derivar URL WSS: https://host → wss://host/ws/workstation
            _wsUrl = cloudApiUrl
                .Replace("https://", "wss://")
                .Replace("http://", "ws://")
                .TrimEnd('/') + "/ws/workstation";
            _wsUri = new Uri(_wsUrl);

            // Detectar proxy del sistema
            var targetUri = new Uri(cloudApiUrl);
            _proxyUri = ProxyHelper.GetSystemProxyUri(targetUri);

            // Inicializar HttpClient con proxy si es necesario
            var handler = new System.Net.Http.HttpClientHandler();
            if (_proxyUri != null)
            {
                handler.Proxy = new WebProxy(_proxyUri);
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
        /// Inicia la conexión WebSocket. Si ya estaba cancelado, recrea el CancellationTokenSource.
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

                ConnectAndReceiveAsync();
            }
        }

        /// <summary>
        /// Envía un mensaje JSON al servidor. Thread-safe.
        /// </summary>
        public void Send(string type, object? payload)
        {
            // Capturar referencia local para evitar race conditions
            var ws = _ws;
            if (ws == null || ws.State != WebSocketState.Open) return;

            var msg = payload != null
                ? JObject.FromObject(payload)
                : new JObject();
            msg["type"] = type;

            var json  = msg.ToString(Formatting.None);
            var bytes = Encoding.UTF8.GetBytes(json);
            var segment = new ArraySegment<byte>(bytes);

            // Lock dedicado para serializar envíos (ClientWebSocket no permite envíos concurrentes)
            lock (_sendLock)
            {
                try
                {
                    // Verificar estado de nuevo dentro del lock
                    if (ws.State != WebSocketState.Open) return;

                    // SendAsync con Wait() — seguro porque los mensajes JSON son pequeños
                    ws.SendAsync(segment, WebSocketMessageType.Text, true, _cts.Token)
                      .GetAwaiter().GetResult();
                }
                catch (OperationCanceledException)
                {
                    // Desconexión solicitada, ignorar
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        $"CloudWebSocketClient: error enviando mensaje. {ex.Message}");
                    Error?.Invoke(ex);
                }
            }
        }

        /// <summary>
        /// Desconecta el WebSocket y cancela operaciones pendientes.
        /// </summary>
        public void Disconnect()
        {
            lock (_lock)
            {
                _cts.Cancel();
                CloseSocketGracefully();
                IsConnected = false;
            }
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            Disconnect();
            _cts.Dispose();
            HttpClient?.Dispose();
        }

        // === Métodos privados ===

        /// <summary>
        /// Lanza la conexión y el bucle de recepción en un Task en background.
        /// No bloquea el hilo llamante.
        /// </summary>
        private void ConnectAndReceiveAsync()
        {
            var token = _cts.Token;

            Task.Run(async () =>
            {
                try
                {
                    await ConnectInternalAsync(token).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    // Desconexión solicitada
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        $"CloudWebSocketClient: error en conexión/recepción. {ex.Message}");
                    Error?.Invoke(ex);
                    HandleDisconnection(null, null);
                }
            });
        }

        /// <summary>
        /// Conecta al servidor WebSocket y ejecuta el bucle de recepción.
        /// </summary>
        private async Task ConnectInternalAsync(CancellationToken token)
        {
            // Crear nueva instancia de ClientWebSocket
            var ws = new ClientWebSocket();

            // Configurar proxy si es necesario
            if (_proxyUri != null)
            {
                ws.Options.Proxy = new WebProxy(_proxyUri);
            }

            // Asignar al campo de instancia
            lock (_lock)
            {
                _ws?.Dispose();
                _ws = ws;
            }

            // Conectar
            await ws.ConnectAsync(_wsUri, token).ConfigureAwait(false);

            // Conexión exitosa
            lock (_lock)
            {
                IsConnected     = true;
                _currentDelayMs = InitialDelayMs;
                _longRetryMode  = false;
            }

            AlwaysPrintLogger.WriteTrayInfo(
                "CloudWebSocketClient: conexión WebSocket establecida exitosamente.");
            Connected?.Invoke();

            // Bucle de recepción
            await ReceiveLoopAsync(ws, token).ConfigureAwait(false);
        }

        /// <summary>
        /// Bucle de recepción de mensajes. Se ejecuta hasta que el servidor cierra
        /// la conexión o se cancela el token.
        /// </summary>
        private async Task ReceiveLoopAsync(ClientWebSocket ws, CancellationToken token)
        {
            var buffer = new byte[ReceiveBufferSize];
            var messageBuffer = new StringBuilder();

            try
            {
                while (ws.State == WebSocketState.Open && !token.IsCancellationRequested)
                {
                    var segment = new ArraySegment<byte>(buffer);
                    WebSocketReceiveResult result;

                    try
                    {
                        result = await ws.ReceiveAsync(segment, token).ConfigureAwait(false);
                    }
                    catch (OperationCanceledException)
                    {
                        break;
                    }
                    catch (WebSocketException ex)
                    {
                        AlwaysPrintLogger.WriteTrayError(
                            $"CloudWebSocketClient: error en recepción WebSocket. {ex.Message}");
                        Error?.Invoke(ex);
                        break;
                    }

                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        // El servidor cerró la conexión
                        var closeStatus = result.CloseStatus;
                        var closeDescription = result.CloseStatusDescription;

                        AlwaysPrintLogger.WriteTrayWarning(
                            $"CloudWebSocketClient: servidor cerró conexión. " +
                            $"Código: {(int?)closeStatus}, Razón: '{closeDescription ?? ""}'");

                        HandleDisconnection(closeStatus, closeDescription);
                        return;
                    }

                    if (result.MessageType == WebSocketMessageType.Text)
                    {
                        // Acumular fragmentos del mensaje
                        messageBuffer.Append(Encoding.UTF8.GetString(buffer, 0, result.Count));

                        if (result.EndOfMessage)
                        {
                            var json = messageBuffer.ToString();
                            messageBuffer.Clear();
                            ProcessMessage(json);
                        }
                    }
                    // Nota: WebSocketMessageType.Binary se ignora (no se usa en este protocolo)
                }
            }
            catch (OperationCanceledException)
            {
                // Desconexión solicitada
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudWebSocketClient: error inesperado en bucle de recepción. {ex.Message}");
                Error?.Invoke(ex);
            }

            // Si salimos del bucle sin haber procesado un Close explícito
            if (!token.IsCancellationRequested)
            {
                HandleDisconnection(null, null);
            }
        }

        /// <summary>
        /// Procesa un mensaje JSON recibido del servidor.
        /// </summary>
        private void ProcessMessage(string json)
        {
            try
            {
                var obj  = JObject.Parse(json);
                var type = obj["type"]?.ToString() ?? "unknown";
                MessageReceived?.Invoke(type, json);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"CloudWebSocketClient: error parseando mensaje. {ex.Message}");
            }
        }

        /// <summary>
        /// Maneja la desconexión: detecta código 1008, notifica evento y programa reconexión.
        /// </summary>
        private void HandleDisconnection(WebSocketCloseStatus? closeStatus, string? closeDescription)
        {
            bool wasConnected;
            lock (_lock)
            {
                wasConnected = IsConnected;
                IsConnected  = false;
            }

            // Detectar código 1008 (IP no autorizada) — solo activar long retry
            // si la razón indica explícitamente que la IP no está autorizada.
            if (closeStatus.HasValue && (int)closeStatus.Value == 1008)
            {
                var reason = closeDescription ?? "";
                if (reason.Contains("no autorizada") || reason.Contains("not authorized"))
                {
                    _longRetryMode = true;
                    AlwaysPrintLogger.WriteTrayWarning(
                        "CloudWebSocketClient: conexión rechazada por APCM (código 1008 — IP no autorizada). " +
                        $"Reintentando cada {LongRetryDelayMs / 1000}s.");
                }
                else
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"CloudWebSocketClient: conexión cerrada con código 1008 pero razón no indica IP no autorizada " +
                        $"(razón: '{reason}'). Usando backoff normal.");
                }
            }

            if (wasConnected) Disconnected?.Invoke();
            ScheduleReconnect();
        }

        /// <summary>
        /// Programa la reconexión con backoff exponencial.
        /// </summary>
        private void ScheduleReconnect()
        {
            if (_disposed || _cts.IsCancellationRequested) return;

            var delay = _longRetryMode ? LongRetryDelayMs : _currentDelayMs;

            AlwaysPrintLogger.WriteTrayWarning(
                $"CloudWebSocketClient: reconectando en {delay / 1000}s...");

            // Avanzar backoff exponencial (solo en modo normal)
            if (!_longRetryMode)
                _currentDelayMs = Math.Min(_currentDelayMs * 2, MaxDelayMs);

            var token = _cts.Token;

            Task.Run(async () =>
            {
                try
                {
                    await Task.Delay(delay, token).ConfigureAwait(false);
                    if (!token.IsCancellationRequested)
                    {
                        await ConnectInternalAsync(token).ConfigureAwait(false);
                    }
                }
                catch (OperationCanceledException)
                {
                    // Desconexión solicitada durante espera
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        $"CloudWebSocketClient: error en reconexión. {ex.Message}");
                    Error?.Invoke(ex);
                    HandleDisconnection(null, null);
                }
            });
        }

        /// <summary>
        /// Cierra el WebSocket de forma ordenada (envía Close frame si es posible).
        /// </summary>
        private void CloseSocketGracefully()
        {
            var ws = _ws;
            if (ws == null) return;

            try
            {
                if (ws.State == WebSocketState.Open || ws.State == WebSocketState.CloseReceived)
                {
                    // Intentar cierre ordenado con timeout corto
                    using (var closeCts = new CancellationTokenSource(TimeSpan.FromSeconds(3)))
                    {
                        ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "Desconexión solicitada", closeCts.Token)
                          .GetAwaiter().GetResult();
                    }
                }
            }
            catch
            {
                // Ignorar errores durante cierre — puede que ya esté cerrado
            }
            finally
            {
                ws.Dispose();
                _ws = null;
            }
        }
    }
}
