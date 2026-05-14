using System;
using System.Threading;
using AlwaysPrint.Shared.Logging;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using WebSocket4Net;

namespace AlwaysPrintTray.Cloud
{
    public sealed class CloudWebSocketClient : IDisposable
    {
        // === Eventos públicos ===
        public event Action?                 Connected;
        public event Action?                 Disconnected;
        public event Action<string, string>? MessageReceived;  // (type, fullJson)
        public event Action<Exception>?      Error;

        // === Estado ===
        public bool IsConnected { get; private set; }

        // === Backoff ===
        private const int InitialDelayMs   = 1_000;
        private const int MaxDelayMs       = 60_000;
        private const int LongRetryDelayMs = 300_000;  // 5 min para código 1008

        private int  _currentDelayMs = InitialDelayMs;
        private bool _longRetryMode  = false;

        // === Internos ===
        private readonly string _wsUrl;
        private readonly Uri?   _proxyUri;
        private readonly object _lock = new object();
        private WebSocket?      _ws;
        private CancellationTokenSource _cts = new CancellationTokenSource();
        private bool _disposed;

        public CloudWebSocketClient(string cloudApiUrl)
        {
            // Derivar URL WSS: https://host → wss://host/ws/workstation
            _wsUrl = cloudApiUrl
                .Replace("https://", "wss://")
                .Replace("http://", "ws://")
                .TrimEnd('/') + "/ws/workstation";

            // Detectar proxy
            var targetUri = new Uri(cloudApiUrl);
            _proxyUri = ProxyHelper.GetSystemProxyUri(targetUri);

            AlwaysPrintLogger.WriteTrayInfo(
                $"CloudWebSocketClient: URL WebSocket derivada = {_wsUrl}" +
                (_proxyUri != null ? $" (proxy: {_proxyUri})" : " (conexión directa)"));
        }

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

                CreateAndOpenSocket();
            }
        }

        public void Send(string type, object? payload)
        {
            lock (_lock)
            {
                if (_ws?.State != WebSocketState.Open) return;

                var msg = payload != null
                    ? JObject.FromObject(payload)
                    : new JObject();
                msg["type"] = type;

                _ws.Send(msg.ToString(Formatting.None));
            }
        }

        public void Disconnect()
        {
            lock (_lock)
            {
                _cts.Cancel();
                if (_ws != null)
                {
                    _ws.Close();
                    _ws = null;
                }
                IsConnected = false;
            }
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            Disconnect();
            _cts.Dispose();
        }

        // === Privados ===

        private void CreateAndOpenSocket()
        {
            _ws?.Dispose();

            if (_proxyUri != null)
            {
                var endpoint = new SuperSocket.ClientEngine.Proxy.HttpConnectProxy(
                    new System.Net.IPEndPoint(
                        System.Net.Dns.GetHostAddresses(_proxyUri.Host)[0],
                        _proxyUri.Port));
                _ws = new WebSocket(_wsUrl);
                _ws.Proxy = endpoint;
            }
            else
            {
                _ws = new WebSocket(_wsUrl);
            }

            _ws.Opened          += OnOpened;
            _ws.Closed           += OnClosed;
            _ws.MessageReceived  += OnMessage;
            _ws.Error            += OnError;

            _ws.Open();
        }

        private void OnOpened(object? sender, EventArgs e)
        {
            lock (_lock)
            {
                IsConnected    = true;
                _currentDelayMs = InitialDelayMs;
                _longRetryMode  = false;
            }
            AlwaysPrintLogger.WriteTrayInfo(
                "CloudWebSocketClient: conexión WebSocket establecida exitosamente.");
            Connected?.Invoke();
        }

        private void OnClosed(object? sender, EventArgs e)
        {
            bool wasConnected;
            lock (_lock)
            {
                wasConnected = IsConnected;
                IsConnected  = false;
            }

            // Detectar código 1008 (IP no autorizada) — solo activar long retry
            // si la razón indica explícitamente que la IP no está autorizada.
            // Si ya estábamos registrados previamente, no entrar en long retry
            // (podría ser un error transitorio del servidor).
            if (e is ClosedEventArgs closedArgs && closedArgs.Code == 1008)
            {
                var reason = closedArgs.Reason ?? "";
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

        private void OnMessage(object? sender, MessageReceivedEventArgs e)
        {
            try
            {
                var json = e.Message;
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

        private void OnError(object? sender, SuperSocket.ClientEngine.ErrorEventArgs e)
        {
            AlwaysPrintLogger.WriteTrayError(
                $"CloudWebSocketClient: error WebSocket. {e.Exception.Message}");
            Error?.Invoke(e.Exception);
        }

        private void ScheduleReconnect()
        {
            if (_disposed || _cts.IsCancellationRequested) return;

            var delay = _longRetryMode ? LongRetryDelayMs : _currentDelayMs;

            AlwaysPrintLogger.WriteTrayWarning(
                $"CloudWebSocketClient: reconectando en {delay / 1000}s...");

            // Avanzar backoff exponencial (solo en modo normal)
            if (!_longRetryMode)
                _currentDelayMs = Math.Min(_currentDelayMs * 2, MaxDelayMs);

            ThreadPool.QueueUserWorkItem(_ =>
            {
                try
                {
                    _cts.Token.WaitHandle.WaitOne(delay);
                    if (!_cts.IsCancellationRequested)
                    {
                        lock (_lock) { CreateAndOpenSocket(); }
                    }
                }
                catch (ObjectDisposedException) { }
            });
        }
    }
}
