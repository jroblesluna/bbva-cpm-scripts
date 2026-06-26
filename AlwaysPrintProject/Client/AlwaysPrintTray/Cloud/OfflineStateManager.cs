using System;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;
using AlwaysPrint.Shared.Logging;
using AlwaysPrintTray.Localization;
using Timer = System.Threading.Timer;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Gestiona el estado offline del Tray respecto a la nube.
    /// Controla la máquina de estados de desconexión, notificaciones balloon tip
    /// no invasivas, y cambio visual del icono del tray.
    /// Implementa IDisposable para liberar el timer de verificación periódica.
    /// </summary>
    public sealed class OfflineStateManager : IDisposable
    {
        // === Constantes de tiempo ===
        private static readonly TimeSpan GracePeriod = TimeSpan.FromHours(1);
        private static readonly TimeSpan NotifyRepeatEvery = TimeSpan.FromHours(2);
        private static readonly TimeSpan CheckInterval = TimeSpan.FromMinutes(5);

        // === Dependencias ===
        private readonly SynchronizationContext _uiContext;
        private readonly NotifyIcon _trayIcon;

        // === Estado protegido por lock ===
        private readonly object _lock = new object();
        private DateTime? _disconnectedAt;
        private DateTime? _lastNotifiedAt;
        private bool _iconIsOffline;
        private Timer? _checkTimer;
        private bool _disposed;

        /// <summary>
        /// Evento que se dispara cuando cambia el estado online/offline del WebSocket.
        /// Parámetros: (isOffline, disconnectedSince). 
        /// Se emite en OnDisconnected y OnReconnected para que el StatusForm
        /// pueda actualizar la sección de conectividad en tiempo real.
        /// </summary>
        public event Action<bool, DateTime?>? StateChanged;

        /// <summary>
        /// Crea una nueva instancia de OfflineStateManager.
        /// </summary>
        /// <param name="uiContext">Contexto de sincronización del hilo UI para despachar operaciones visuales.</param>
        /// <param name="trayIcon">Referencia al NotifyIcon del system tray para balloon tips e icono.</param>
        public OfflineStateManager(SynchronizationContext uiContext, NotifyIcon trayIcon)
        {
            _uiContext = uiContext ?? throw new ArgumentNullException(nameof(uiContext));
            _trayIcon = trayIcon ?? throw new ArgumentNullException(nameof(trayIcon));

            AlwaysPrintLogger.WriteTrayInfo(
                "OfflineStateManager: instancia creada.");
        }

        /// <summary>
        /// Indica si el sistema se encuentra actualmente en estado offline (desconectado de la nube).
        /// </summary>
        public bool IsOffline
        {
            get
            {
                lock (_lock)
                {
                    return _disconnectedAt.HasValue;
                }
            }
        }

        /// <summary>
        /// Duración transcurrida desde la desconexión, o null si no está offline.
        /// </summary>
        public TimeSpan? OfflineDuration
        {
            get
            {
                lock (_lock)
                {
                    if (!_disconnectedAt.HasValue)
                        return null;

                    return DateTime.UtcNow - _disconnectedAt.Value;
                }
            }
        }

        /// <summary>
        /// Registra una desconexión del WebSocket.
        /// Guarda el timestamp UTC, limpia el estado de última notificación,
        /// e inicia el timer de verificación periódica (cada 5 minutos).
        /// Si ya está offline, no hace nada (idempotente).
        /// </summary>
        public void OnDisconnected()
        {
            lock (_lock)
            {
                if (_disposed) return;

                // Si ya estamos offline, no re-registrar
                if (_disconnectedAt.HasValue)
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        "OfflineStateManager: OnDisconnected() llamado pero ya se encuentra offline. Ignorando.");
                    return;
                }

                _disconnectedAt = DateTime.UtcNow;
                _lastNotifiedAt = null;

                // Iniciar timer de verificación periódica (5 minutos)
                _checkTimer = new Timer(
                    OnTimerElapsed,
                    null,
                    CheckInterval,
                    CheckInterval);

                AlwaysPrintLogger.WriteTrayInfo(
                    $"OfflineStateManager: desconexión registrada a las {_disconnectedAt.Value:O}. " +
                    "Timer de verificación iniciado (intervalo: 5 min).");
            }

            // Notificar cambio de estado fuera del lock
            StateChanged?.Invoke(true, _disconnectedAt);
        }

        /// <summary>
        /// Registra una reconexión del WebSocket.
        /// Limpia el estado de desconexión, detiene el timer, restaura el icono normal
        /// y muestra un balloon tip de reconexión si se había notificado previamente.
        /// Si no estaba offline, no hace nada (idempotente).
        /// </summary>
        public void OnReconnected()
        {
            lock (_lock)
            {
                if (_disposed) return;

                // Si no estamos offline, no hay nada que hacer
                if (!_disconnectedAt.HasValue)
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        "OfflineStateManager: OnReconnected() llamado sin desconexión previa. Ignorando.");
                    return;
                }

                var wasNotified = _lastNotifiedAt.HasValue || _iconIsOffline;

                // Limpiar estado
                _disconnectedAt = null;
                _lastNotifiedAt = null;

                // Detener timer
                StopTimer();

                AlwaysPrintLogger.WriteTrayInfo(
                    "OfflineStateManager: reconexión registrada. Estado offline limpiado, timer detenido.");

                // Restaurar icono y tooltip normales
                SetNormalIcon();

                // Mostrar balloon tip de reconexión si se había notificado previamente
                if (wasNotified)
                {
                    ShowReconnectedNotification();
                }
            }

            // Notificar cambio de estado fuera del lock
            StateChanged?.Invoke(false, null);
        }

        /// <summary>
        /// Libera el timer de verificación y marca la instancia como dispuesta.
        /// Idempotente: llamadas múltiples no tienen efecto.
        /// </summary>
        public void Dispose()
        {
            lock (_lock)
            {
                if (_disposed) return;
                _disposed = true;

                StopTimer();

                AlwaysPrintLogger.WriteTrayInfo(
                    "OfflineStateManager: recursos liberados (Dispose).");
            }
        }

        // === Métodos privados ===

        /// <summary>
        /// Callback del timer de verificación periódica.
        /// Evalúa si corresponde mostrar una notificación según el grace period y la repetición.
        /// </summary>
        private void OnTimerElapsed(object? state)
        {
            try
            {
                CheckAndNotify();
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"OfflineStateManager: error en callback del timer. {ex.GetType().Name}: {ex.Message}");
            }
        }

        /// <summary>
        /// Verifica si corresponde mostrar una notificación balloon tip según la duración offline.
        /// - Si offline < 1 hora (grace period): sin acción.
        /// - Si offline >= 1 hora y no se ha notificado: primera notificación + cambio de icono.
        /// - Si ya se notificó y han pasado >= 2 horas desde la última: repetir notificación.
        /// </summary>
        private void CheckAndNotify()
        {
            lock (_lock)
            {
                if (_disposed || !_disconnectedAt.HasValue)
                    return;

                var offlineDuration = DateTime.UtcNow - _disconnectedAt.Value;

                // Grace period: si la duración offline es menor a 1 hora, no hacer nada
                if (offlineDuration < GracePeriod)
                    return;

                // Primera notificación: offline >= 1 hora y aún no se ha notificado
                if (!_lastNotifiedAt.HasValue)
                {
                    _lastNotifiedAt = DateTime.UtcNow;

                    AlwaysPrintLogger.WriteTrayInfo(
                        $"OfflineStateManager: duración offline ({offlineDuration.TotalMinutes:F0} min) " +
                        "superó el período de gracia (1 hora). Mostrando primera notificación.");

                    // Cambiar icono a offline (stub implementado en tarea 2.6)
                    SetOfflineIcon();

                    // Mostrar balloon tip de desconexión
                    ShowOfflineNotification();
                    return;
                }

                // Repetición: si ya se notificó y han pasado >= 2 horas desde la última notificación
                var sinceLastNotification = DateTime.UtcNow - _lastNotifiedAt.Value;
                if (sinceLastNotification >= NotifyRepeatEvery)
                {
                    _lastNotifiedAt = DateTime.UtcNow;

                    AlwaysPrintLogger.WriteTrayInfo(
                        $"OfflineStateManager: han pasado {sinceLastNotification.TotalHours:F1} horas " +
                        "desde la última notificación. Repitiendo notificación offline.");

                    ShowOfflineNotification();
                }
            }
        }

        /// <summary>
        /// Muestra la notificación balloon tip de desconexión offline.
        /// Usa SynchronizationContext.Post() para ejecutar en el hilo UI.
        /// Balloon tip con ToolTipIcon.Warning, duración 4000ms.
        /// </summary>
        private void ShowOfflineNotification()
        {
            _uiContext.Post(_ =>
            {
                try
                {
                    _trayIcon.ShowBalloonTip(
                        4000,
                        LocalizationManager.Get("BalloonOfflineTitle"),
                        LocalizationManager.Get("BalloonOfflineText"),
                        ToolTipIcon.Warning);
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"OfflineStateManager: error al mostrar balloon tip offline. " +
                        $"{ex.GetType().Name}: {ex.Message}");
                }
            }, null);
        }

        /// <summary>
        /// Muestra la notificación balloon tip de reconexión exitosa.
        /// Usa SynchronizationContext.Post() para ejecutar en el hilo UI.
        /// Balloon tip con ToolTipIcon.Info, duración 3000ms.
        /// </summary>
        private void ShowReconnectedNotification()
        {
            try
            {
                var title = LocalizationManager.Get("BalloonOfflineTitle");
                var text = LocalizationManager.Get("BalloonReconnected");

                _uiContext.Post(_ =>
                {
                    try
                    {
                        _trayIcon.ShowBalloonTip(3000, title, text, ToolTipIcon.Info);
                    }
                    catch (Exception ex)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"OfflineStateManager: error al mostrar balloon tip de reconexión en hilo UI. {ex.GetType().Name}: {ex.Message}");
                    }
                }, null);

                AlwaysPrintLogger.WriteTrayInfo(
                    "OfflineStateManager: notificación de reconexión mostrada al usuario.");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"OfflineStateManager: error al preparar notificación de reconexión. {ex.GetType().Name}: {ex.Message}");
            }
        }

        /// <summary>
        /// Cambia el icono del tray a la variante offline (gris/desaturada)
        /// y actualiza el tooltip. Ejecuta en el hilo UI vía SynchronizationContext.Post().
        /// </summary>
        private void SetOfflineIcon()
        {
            try
            {
                var assembly = Assembly.GetExecutingAssembly();
                using (var stream = assembly.GetManifestResourceStream("AlwaysPrintTray.Resources.logo_offline.ico"))
                {
                    if (stream == null)
                    {
                        AlwaysPrintLogger.WriteTrayError(
                            "OfflineStateManager: no se pudo cargar el recurso embebido 'logo_offline.ico'. El icono no se cambiará.");
                        return;
                    }

                    var offlineIcon = new Icon(stream);
                    var tooltipText = LocalizationManager.Get("TooltipOffline");

                    _uiContext.Post(_ =>
                    {
                        try
                        {
                            _trayIcon.Icon = offlineIcon;
                            _trayIcon.Text = tooltipText;
                        }
                        catch (Exception ex)
                        {
                            AlwaysPrintLogger.WriteTrayWarning(
                                $"OfflineStateManager: error al establecer icono offline en hilo UI. {ex.GetType().Name}: {ex.Message}");
                        }
                    }, null);

                    _iconIsOffline = true;

                    AlwaysPrintLogger.WriteTrayInfo(
                        "OfflineStateManager: icono del tray cambiado a variante offline.");
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"OfflineStateManager: error al cargar icono offline desde recursos embebidos. {ex.GetType().Name}: {ex.Message}");
            }
        }

        /// <summary>
        /// Restaura el icono del tray a la variante normal y actualiza el tooltip.
        /// Ejecuta en el hilo UI vía SynchronizationContext.Post().
        /// </summary>
        private void SetNormalIcon()
        {
            try
            {
                var assembly = Assembly.GetExecutingAssembly();
                using (var stream = assembly.GetManifestResourceStream("AlwaysPrintTray.Resources.logo.ico"))
                {
                    if (stream == null)
                    {
                        AlwaysPrintLogger.WriteTrayError(
                            "OfflineStateManager: no se pudo cargar el recurso embebido 'logo.ico'. El icono no se restaurará.");
                        return;
                    }

                    var normalIcon = new Icon(stream);
                    var tooltipText = LocalizationManager.Get("TrayTooltip");

                    _uiContext.Post(_ =>
                    {
                        try
                        {
                            _trayIcon.Icon = normalIcon;
                            _trayIcon.Text = tooltipText;
                        }
                        catch (Exception ex)
                        {
                            AlwaysPrintLogger.WriteTrayWarning(
                                $"OfflineStateManager: error al restaurar icono normal en hilo UI. {ex.GetType().Name}: {ex.Message}");
                        }
                    }, null);

                    _iconIsOffline = false;

                    AlwaysPrintLogger.WriteTrayInfo(
                        "OfflineStateManager: icono del tray restaurado a variante normal.");
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"OfflineStateManager: error al cargar icono normal desde recursos embebidos. {ex.GetType().Name}: {ex.Message}");
            }
        }

        /// <summary>
        /// Detiene y libera el timer de verificación periódica.
        /// </summary>
        private void StopTimer()
        {
            if (_checkTimer != null)
            {
                _checkTimer.Change(Timeout.Infinite, Timeout.Infinite);
                _checkTimer.Dispose();
                _checkTimer = null;
            }
        }
    }
}
