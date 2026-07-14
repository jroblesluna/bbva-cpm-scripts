using System;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.RemoteView
{
    /// <summary>
    /// Puente bidireccional de clipboard entre la workstation local y el admin remoto.
    /// Usa AddClipboardFormatListener para detectar cambios en el clipboard local
    /// y envía/recibe contenido de texto vía callbacks WebSocket.
    /// 
    /// Requiere un hilo STA dedicado para las operaciones de clipboard y la ventana receptora
    /// de mensajes WM_CLIPBOARDUPDATE.
    /// 
    /// Solo activo cuando clipboard_sharing_enabled=true en la configuración de la sesión.
    /// </summary>
    public sealed class ClipboardBridge : IDisposable
    {
        #region P/Invoke Declarations

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool AddClipboardFormatListener(IntPtr hwnd);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool RemoveClipboardFormatListener(IntPtr hwnd);

        private const int WM_CLIPBOARDUPDATE = 0x031D;

        #endregion

        #region Eventos y Callbacks

        /// <summary>
        /// Se dispara cuando el clipboard local cambia y hay texto disponible.
        /// El consumidor debe enviar el texto como rv_clipboard direction=to_admin.
        /// </summary>
        public event Action<string>? OnClipboardTextChanged;

        #endregion

        #region Estado interno

        private readonly bool _enabled;
        private Thread? _staThread;
        private ClipboardListenerWindow? _listenerWindow;
        private volatile bool _disposed;
        private volatile bool _running;

        /// <summary>
        /// Flag para ignorar el cambio de clipboard que nosotros mismos provocamos
        /// al hacer SetText (evitar eco/loop infinito).
        /// </summary>
        private volatile bool _ignoreNextChange;

        /// <summary>
        /// Último texto enviado al admin, para evitar re-enviar el mismo contenido.
        /// </summary>
        private string? _lastSentText;

        /// <summary>
        /// Referencia al SynchronizationContext del hilo STA para ejecutar SetText.
        /// </summary>
        private SynchronizationContext? _staContext;

        /// <summary>
        /// ManualResetEvent que señala cuando el hilo STA está listo.
        /// </summary>
        private readonly ManualResetEventSlim _staReady = new ManualResetEventSlim(false);

        #endregion

        /// <summary>
        /// Crea una instancia de ClipboardBridge.
        /// </summary>
        /// <param name="clipboardSharingEnabled">
        /// Si es false, el bridge no se activa (no escucha clipboard ni procesa mensajes entrantes).
        /// </param>
        public ClipboardBridge(bool clipboardSharingEnabled)
        {
            _enabled = clipboardSharingEnabled;
        }

        /// <summary>
        /// Indica si el bridge está activo (clipboard_sharing_enabled y no disposed).
        /// </summary>
        public bool IsActive => _enabled && _running && !_disposed;

        /// <summary>
        /// Inicia el monitoreo del clipboard local.
        /// Crea un hilo STA dedicado con una ventana oculta para recibir WM_CLIPBOARDUPDATE.
        /// </summary>
        public void Start()
        {
            if (!_enabled)
            {
                AlwaysPrintLogger.WriteTrayInfo(
                    "ClipboardBridge: clipboard_sharing_enabled=false, bridge deshabilitado.");
                return;
            }

            if (_disposed)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "ClipboardBridge: intento de Start() en instancia disposed. Ignorando.");
                return;
            }

            if (_running)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "ClipboardBridge: ya está en ejecución. Ignorando Start() duplicado.");
                return;
            }

            _running = true;

            // Crear hilo STA dedicado para la ventana de clipboard y operaciones Clipboard.*
            _staThread = new Thread(StaThreadProc)
            {
                Name = "ClipboardBridge_STA",
                IsBackground = true
            };
            _staThread.SetApartmentState(ApartmentState.STA);
            _staThread.Start();

            // Esperar a que el hilo STA esté listo (máximo 5 segundos)
            if (!_staReady.Wait(TimeSpan.FromSeconds(5)))
            {
                AlwaysPrintLogger.WriteTrayError(
                    "ClipboardBridge: timeout esperando inicialización del hilo STA.");
                _running = false;
                return;
            }

            AlwaysPrintLogger.WriteTrayInfo(
                "ClipboardBridge: iniciado correctamente. Monitoreando clipboard local.");
        }

        /// <summary>
        /// Procesa un mensaje rv_clipboard entrante con direction=to_ws.
        /// Establece el texto en el clipboard local de la workstation.
        /// </summary>
        /// <param name="text">Texto a colocar en el clipboard local.</param>
        public void SetClipboardFromRemote(string text)
        {
            if (!_enabled || _disposed || !_running)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "ClipboardBridge: SetClipboardFromRemote llamado pero bridge no activo. Ignorando.");
                return;
            }

            if (string.IsNullOrEmpty(text))
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "ClipboardBridge: SetClipboardFromRemote con texto vacío. Ignorando.");
                return;
            }

            // Marcar para ignorar el próximo cambio (el que nosotros provocamos)
            _ignoreNextChange = true;

            // Ejecutar SetText en el hilo STA (requerido por Clipboard.SetText)
            if (_listenerWindow != null && !_listenerWindow.IsDisposed)
            {
                try
                {
                    _listenerWindow.Invoke(new Action(() =>
                    {
                        try
                        {
                            Clipboard.SetText(text, TextDataFormat.UnicodeText);
                            _lastSentText = text;
                            AlwaysPrintLogger.WriteTrayInfo(
                                $"ClipboardBridge: clipboard local actualizado desde admin. " +
                                $"Longitud={text.Length} caracteres.");
                        }
                        catch (ExternalException ex)
                        {
                            // Otro proceso puede tener el clipboard bloqueado
                            AlwaysPrintLogger.WriteTrayWarning(
                                $"ClipboardBridge: no se pudo establecer clipboard (bloqueado por otro proceso). {ex.Message}");
                            _ignoreNextChange = false;
                        }
                    }));
                }
                catch (ObjectDisposedException)
                {
                    _ignoreNextChange = false;
                    AlwaysPrintLogger.WriteTrayWarning(
                        "ClipboardBridge: ventana listener disposed durante SetClipboardFromRemote.");
                }
                catch (InvalidOperationException)
                {
                    _ignoreNextChange = false;
                    AlwaysPrintLogger.WriteTrayWarning(
                        "ClipboardBridge: no se pudo invocar en el hilo STA (ventana no creada).");
                }
            }
            else
            {
                _ignoreNextChange = false;
                AlwaysPrintLogger.WriteTrayWarning(
                    "ClipboardBridge: ventana listener no disponible para SetClipboardFromRemote.");
            }
        }

        /// <summary>
        /// Detiene el monitoreo del clipboard y libera recursos.
        /// </summary>
        public void Stop()
        {
            if (!_running)
                return;

            _running = false;

            // Cerrar la ventana listener desde su propio hilo STA
            if (_listenerWindow != null && !_listenerWindow.IsDisposed)
            {
                try
                {
                    _listenerWindow.Invoke(new Action(() =>
                    {
                        _listenerWindow.Close();
                    }));
                }
                catch (ObjectDisposedException) { }
                catch (InvalidOperationException) { }
            }

            // Esperar a que el hilo STA termine (máximo 3 segundos)
            if (_staThread != null && _staThread.IsAlive)
            {
                _staThread.Join(TimeSpan.FromSeconds(3));
            }

            _staThread = null;
            _listenerWindow = null;
            _lastSentText = null;

            AlwaysPrintLogger.WriteTrayInfo("ClipboardBridge: detenido.");
        }

        /// <summary>
        /// Libera todos los recursos. Equivale a Stop() + marca como disposed.
        /// </summary>
        public void Dispose()
        {
            if (_disposed)
                return;

            _disposed = true;
            Stop();
            _staReady.Dispose();
        }

        #region Hilo STA

        /// <summary>
        /// Procedimiento del hilo STA dedicado.
        /// Crea la ventana oculta, registra el listener de clipboard y ejecuta el message loop.
        /// </summary>
        private void StaThreadProc()
        {
            try
            {
                // Crear la ventana oculta que recibirá WM_CLIPBOARDUPDATE
                _listenerWindow = new ClipboardListenerWindow(this);

                // Registrar como listener de cambios de clipboard
                if (!AddClipboardFormatListener(_listenerWindow.Handle))
                {
                    int error = Marshal.GetLastWin32Error();
                    AlwaysPrintLogger.WriteTrayError(
                        $"ClipboardBridge: AddClipboardFormatListener falló. Win32 error={error}.");
                    _running = false;
                    _staReady.Set();
                    return;
                }

                // Guardar referencia al contexto de sincronización STA
                _staContext = SynchronizationContext.Current;

                // Señalar que estamos listos
                _staReady.Set();

                // Ejecutar message loop (bloquea hasta que se cierra la ventana)
                Application.Run(_listenerWindow);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ClipboardBridge: error en hilo STA. {ex.Message}");
                _running = false;
                _staReady.Set();
            }
            finally
            {
                _running = false;
            }
        }

        #endregion

        #region Procesamiento de cambios de clipboard

        /// <summary>
        /// Invocado por la ventana listener cuando se recibe WM_CLIPBOARDUPDATE.
        /// Lee el texto del clipboard y dispara el evento si hay contenido nuevo.
        /// </summary>
        internal void HandleClipboardUpdate()
        {
            if (_disposed || !_running)
                return;

            // Si nosotros provocamos este cambio (SetClipboardFromRemote), ignorar
            if (_ignoreNextChange)
            {
                _ignoreNextChange = false;
                return;
            }

            try
            {
                // Leer texto del clipboard (ya estamos en el hilo STA)
                if (!Clipboard.ContainsText())
                    return;

                string? text = Clipboard.GetText(TextDataFormat.UnicodeText);

                if (string.IsNullOrEmpty(text))
                    return;

                // Evitar re-enviar el mismo texto (ej: operaciones repetidas de copy)
                if (text == _lastSentText)
                    return;

                _lastSentText = text;

                // Notificar al consumidor para que envíe rv_clipboard direction=to_admin
                OnClipboardTextChanged?.Invoke(text);

                AlwaysPrintLogger.WriteTrayInfo(
                    $"ClipboardBridge: cambio de clipboard detectado. " +
                    $"Longitud={text.Length} caracteres. Enviando a admin.");
            }
            catch (ExternalException ex)
            {
                // Otro proceso puede tener el clipboard bloqueado
                AlwaysPrintLogger.WriteTrayWarning(
                    $"ClipboardBridge: no se pudo leer clipboard (bloqueado por otro proceso). {ex.Message}");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"ClipboardBridge: error procesando cambio de clipboard. {ex.Message}");
            }
        }

        #endregion

        #region Ventana oculta para mensajes de clipboard

        /// <summary>
        /// Ventana WinForms oculta cuyo único propósito es recibir el mensaje
        /// WM_CLIPBOARDUPDATE del sistema operativo.
        /// </summary>
        private sealed class ClipboardListenerWindow : Form
        {
            private readonly ClipboardBridge _bridge;

            public ClipboardListenerWindow(ClipboardBridge bridge)
            {
                _bridge = bridge;

                // Configurar como ventana invisible (sin borde, sin taskbar, tamaño mínimo)
                Text = "ClipboardBridge_Listener";
                FormBorderStyle = FormBorderStyle.None;
                ShowInTaskbar = false;
                WindowState = FormWindowState.Minimized;
                Visible = false;
                Width = 1;
                Height = 1;
            }

            protected override void WndProc(ref Message m)
            {
                if (m.Msg == WM_CLIPBOARDUPDATE)
                {
                    _bridge.HandleClipboardUpdate();
                }

                base.WndProc(ref m);
            }

            protected override void OnFormClosing(FormClosingEventArgs e)
            {
                // Desregistrar el listener antes de cerrar
                RemoveClipboardFormatListener(this.Handle);
                base.OnFormClosing(e);
            }

            // No mostrar la ventana al usuario
            protected override void SetVisibleCore(bool value)
            {
                base.SetVisibleCore(false);
            }
        }

        #endregion
    }
}
