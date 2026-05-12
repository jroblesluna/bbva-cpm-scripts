using System;
using System.Linq;
using System.Management;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Threading;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintTray.Localization;
using AlwaysPrintTray.Pipe;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Orquestador principal de la integración Cloud.
    /// Gestiona el ciclo de vida completo de la conexión WebSocket hacia APCM:
    /// inicio, registro de workstation, heartbeat (pong), y notificación al Service.
    /// </summary>
    public sealed class CloudManager : IDisposable
    {
        /// <summary>Estado actual de conexión Cloud.</summary>
        public bool IsConnected { get; private set; }

        private readonly AppConfiguration _config;
        private readonly CloudCredentialsManager _credentials;
        private readonly PipeClient _pipe;
        private readonly SynchronizationContext _uiContext;

        private CloudWebSocketClient? _wsClient;
        private bool _disposed;

        /// <summary>
        /// Crea una nueva instancia de CloudManager.
        /// </summary>
        /// <param name="config">Configuración de la aplicación con CloudApiUrl.</param>
        /// <param name="credentials">Gestor de credenciales Cloud en HKCU.</param>
        /// <param name="pipe">Cliente Named Pipe para notificar al Service.</param>
        /// <param name="uiContext">Contexto de sincronización del hilo UI.</param>
        public CloudManager(
            AppConfiguration config,
            CloudCredentialsManager credentials,
            PipeClient pipe,
            SynchronizationContext uiContext)
        {
            _config = config;
            _credentials = credentials;
            _pipe = pipe;
            _uiContext = uiContext;
        }

        /// <summary>
        /// Inicia la integración Cloud: carga credenciales, crea el cliente WebSocket,
        /// suscribe eventos y conecta.
        /// </summary>
        public void Start()
        {
            _credentials.Load();

            _wsClient = new CloudWebSocketClient(_config.CloudApiUrl);
            _wsClient.Connected += OnConnected;
            _wsClient.Disconnected += OnDisconnected;
            _wsClient.MessageReceived += OnMessageReceived;
            _wsClient.Error += OnError;

            _wsClient.Connect();
            AlwaysPrintLogger.WriteTrayInfo("CloudManager: conexión WebSocket iniciada.");
        }

        /// <summary>
        /// Detiene la integración Cloud: desconecta el WebSocket y actualiza el estado.
        /// </summary>
        public void Stop()
        {
            _wsClient?.Disconnect();
            IsConnected = false;
        }

        /// <summary>
        /// Libera todos los recursos: detiene la conexión y dispone el cliente WebSocket.
        /// </summary>
        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            Stop();
            _wsClient?.Dispose();
        }

        // === Handlers de eventos ===

        private void OnConnected()
        {
            IsConnected = true;
            AlwaysPrintLogger.WriteTrayInfo("CloudManager: conectado a APCM.");

            SendRegistration();
            NotifyServiceCloudStatus(connected: true);
        }

        private void OnDisconnected()
        {
            IsConnected = false;
            AlwaysPrintLogger.WriteTrayWarning("CloudManager: desconectado de APCM.");
            NotifyServiceCloudStatus(connected: false);
        }

        private void OnMessageReceived(string type, string json)
        {
            switch (type)
            {
                case "ping":
                    HandlePing();
                    break;
                case "registered":
                    HandleRegistered(json);
                    break;
                default:
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudManager: mensaje recibido tipo='{type}' (sin handler).");
                    break;
            }
        }

        private void OnError(Exception ex)
        {
            AlwaysPrintLogger.WriteTrayError(
                $"CloudManager: error en WebSocket. {ex.Message}");
        }

        // === Registro ===

        private void SendRegistration()
        {
            try
            {
                var payload = new JObject
                {
                    ["ip_private"] = GetPrivateIp(),
                    ["hostname"] = Environment.MachineName,
                    ["os_serial"] = GetOsSerial(),
                    ["current_user"] = Environment.UserName,
                    ["locale"] = LocalizationManager.CurrentLocale,
                    ["client_version"] = Assembly.GetExecutingAssembly()
                                            .GetName().Version?.ToString() ?? "0.0.0.0",
                    ["workstation_id"] = _credentials.IsRegistered
                                            ? _credentials.WorkstationId
                                            : null
                };

                _wsClient!.Send("register", payload);
                AlwaysPrintLogger.WriteTrayInfo("CloudManager: mensaje de registro enviado.");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error enviando registro. {ex.Message}");
            }
        }

        private void HandleRegistered(string json)
        {
            try
            {
                var obj = JObject.Parse(json);
                var workstationId = obj["workstation_id"]?.ToString();

                if (!string.IsNullOrEmpty(workstationId))
                {
                    _credentials.SaveWorkstationId(workstationId!);
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"CloudManager: WorkstationId registrado = {workstationId}");
                }

                _credentials.SaveLastConnected(DateTime.UtcNow);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error procesando respuesta de registro. {ex.Message}");
            }
        }

        // === Heartbeat ===

        private void HandlePing()
        {
            try
            {
                _wsClient!.Send("pong", null);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"CloudManager: error enviando pong. {ex.Message}");
            }
        }

        // === Notificación al Service ===

        private void NotifyServiceCloudStatus(bool connected)
        {
            try
            {
                if (!_pipe.IsConnected)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        "CloudManager: pipe no conectado, no se puede notificar estado Cloud.");
                    return;
                }

                var payload = new CloudStatusResponsePayload
                {
                    IsConnected = connected,
                    LastConnectedAt = connected
                        ? DateTime.UtcNow.ToString("o")
                        : _credentials.LastConnectedAt?.ToString("o"),
                    ConfigHash = _credentials.ConfigHash,
                    UsingCachedConfig = !connected
                };

                _pipe.Send(PipeMessage.Create(MessageType.CloudStatusResponse, payload));
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CloudManager: error notificando estado Cloud al Service. {ex.Message}");
            }
        }

        // === Utilidades ===

        private static string GetPrivateIp()
        {
            try
            {
                var addresses = Dns.GetHostAddresses(Dns.GetHostName());
                var privateIp = addresses.FirstOrDefault(a =>
                    a.AddressFamily == AddressFamily.InterNetwork &&
                    IsPrivateIp(a));
                return privateIp?.ToString() ?? "0.0.0.0";
            }
            catch
            {
                return "0.0.0.0";
            }
        }

        private static bool IsPrivateIp(IPAddress ip)
        {
            var bytes = ip.GetAddressBytes();
            return bytes[0] == 10 ||
                   (bytes[0] == 172 && bytes[1] >= 16 && bytes[1] <= 31) ||
                   (bytes[0] == 192 && bytes[1] == 168);
        }

        private static string GetOsSerial()
        {
            try
            {
                using (var searcher = new ManagementObjectSearcher(
                    "SELECT SerialNumber FROM Win32_OperatingSystem"))
                {
                    foreach (var obj in searcher.Get())
                    {
                        return obj["SerialNumber"]?.ToString() ?? "";
                    }
                }
                return "";
            }
            catch
            {
                return "";
            }
        }
    }
}
