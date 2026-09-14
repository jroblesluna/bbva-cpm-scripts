using System;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using Microsoft.Win32;

namespace AlwaysPrintTray.Forms
{
    /// <summary>
    /// EXCLUSIVO Lexmark CPM. Ventana modal que se muestra cuando el usuario logueado NO tiene
    /// su archivo 'token' de credencial del Lexmark CPM y NO hay contingencia activa.
    ///
    /// Guía al usuario:
    /// 1. Le indica que no tiene credencial de impresión y que al imprimir por primera vez el
    ///    navegador le pedirá autenticarse.
    /// 2. Le muestra el nombre de su navegador predeterminado (que puede quedar minimizado).
    /// 3. Ofrece un botón "Generar impresión de prueba" que dispara la impresión de prueba
    ///    (fuerza al CPM a solicitar credenciales) y luego monitorea la aparición del token.
    /// 4. Cuando el token aparece, muestra estado verde y confirma que ya puede imprimir seguro.
    ///
    /// La ventana es topmost + modal, centrada, y solo se cierra con el botón "Salir" o con Esc.
    /// El botón [X] y Alt+F4 están bloqueados hasta que el usuario decida salir.
    ///
    /// Layout basado en paneles con Dock (no coordenadas absolutas) para que los botones y el
    /// contenido se ubiquen correctamente independientemente del escalado DPI.
    /// </summary>
    public sealed class CpmTokenPromptForm : Form
    {
        // === COLORES DE ESTADO ===
        // Ámbar rojizo: sin token (pendiente de autenticación).
        private static readonly Color AmberRedBg = Color.FromArgb(255, 243, 224);
        private static readonly Color AmberRedAccent = Color.FromArgb(230, 81, 0);   // deep orange
        // Verde: token confirmado.
        private static readonly Color GreenBg = Color.FromArgb(232, 245, 233);
        private static readonly Color GreenAccent = Color.FromArgb(46, 125, 50);
        private static readonly Color TextDark = Color.FromArgb(30, 41, 59);
        private static readonly Color TextBody = Color.FromArgb(45, 55, 72);
        private static readonly Color FooterBg = Color.FromArgb(241, 245, 249);

        // === ESTADO ===
        private readonly string _username;
        private readonly string _tokenPath;
        private readonly string _testPrintLabel;
        private readonly int _pollTimeoutSeconds;
        private readonly Func<string, bool> _triggerTestPrint;

        private bool _allowClose;
        private bool _testPrintTriggered;   // true tras pulsar "Generar impresión de prueba"
        private System.Windows.Forms.Timer _pollTimer;
        private DateTime _pollStartedUtc;

        // Auto-cierre tras confirmar credencial (estado verde).
        private const int AutoCloseSeconds = 10;
        private System.Windows.Forms.Timer _autoCloseTimer;
        private int _autoCloseRemaining;

        // === SINGLETON (una sola ventana viva a la vez, aunque lleguen triggers sucesivos) ===
        private static readonly object _instanceLock = new object();
        private static CpmTokenPromptForm _instance;

        // === CONTROLES ===
        private Panel _headerBar;
        private PictureBox _statusIconBox;
        private Label _statusTitleLabel;
        private Label _userLabel;
        private Label _bodyLabel;
        private Label _pollStatusLabel;
        private Button _testPrintButton;
        private Button _exitButton;

        private CpmTokenPromptForm(ShowCpmTokenPromptPayload payload, Func<string, bool> triggerTestPrint)
        {
            _username = payload.Username ?? string.Empty;
            _tokenPath = payload.TokenPath ?? string.Empty;
            _testPrintLabel = string.IsNullOrWhiteSpace(payload.TestPrintLabel)
                ? "Imprimir Página de Prueba"
                : payload.TestPrintLabel;
            _pollTimeoutSeconds = payload.PollTimeoutSeconds > 0 ? payload.PollTimeoutSeconds : 180;
            _triggerTestPrint = triggerTestPrint;

            BuildUi();

            // Si el token ya existe al abrir (carrera con otra sesión), mostrar verde directo.
            if (TokenExists())
                SetConfirmedState();
        }

        /// <summary>
        /// Muestra la ventana de forma MODAL en el thread actual (debe ser STA).
        /// SINGLETON: si ya hay una ventana viva (de un trigger anterior), no abre otra —
        /// trae la existente al frente (cross-thread seguro) y retorna de inmediato.
        /// La primera aparición nace TopMost; una vez cerrada, la próxima vuelve a nacer TopMost.
        /// Bloquea hasta que el usuario cierre con Salir o Esc.
        /// </summary>
        public static void ShowModal(ShowCpmTokenPromptPayload payload, Func<string, bool> triggerTestPrint)
        {
            lock (_instanceLock)
            {
                var existing = _instance;
                if (existing != null && !existing.IsDisposed)
                {
                    // Ya hay una ventana abierta: traerla al frente en su propio thread UI.
                    try
                    {
                        existing.BeginInvoke(new Action(() => existing.BringExistingToFront()));
                    }
                    catch (Exception ex)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"CpmTokenPromptForm: no se pudo reactivar la ventana existente: {ex.Message}");
                    }
                    return;
                }
            }

            var form = new CpmTokenPromptForm(payload, triggerTestPrint);
            lock (_instanceLock) { _instance = form; }

            // IMPORTANTE: usar Application.Run(form), NO form.ShowDialog().
            // Este método corre en un thread STA dedicado. Application.Run crea un message
            // loop AISLADO para este thread; cuando el form se cierra, solo termina ESE loop.
            // Con ShowDialog() (sin Application.Run) el cierre del diálogo propaga el fin del
            // message loop al hilo principal del Tray, matando el NotifyIcon y dejando el
            // proceso vivo sin ícono. Application.Run aísla el ciclo de vida de esta ventana.
            try
            {
                Application.Run(form);
            }
            finally
            {
                lock (_instanceLock)
                {
                    if (ReferenceEquals(_instance, form)) _instance = null;
                }
                form.Dispose();
            }
        }

        /// <summary>
        /// Trae la ventana ya existente al frente. Si aún NO se ha disparado la impresión de
        /// prueba (sigue en estado inicial), se re-fuerza TopMost; si ya está en modo polling,
        /// solo se activa sin volverse TopMost (para no tapar el navegador).
        /// </summary>
        private void BringExistingToFront()
        {
            try
            {
                if (WindowState == FormWindowState.Minimized)
                    WindowState = FormWindowState.Normal;

                if (!_testPrintTriggered)
                {
                    TopMost = false;
                    TopMost = true;
                }
                Activate();
                BringToFront();
                Focus();
                SetForegroundWindow(Handle);
            }
            catch { /* no crítico */ }
        }

        private void BuildUi()
        {
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            AutoScaleMode = AutoScaleMode.Dpi;
            TopMost = true;
            ShowInTaskbar = true;             // visible en Alt+Tab por si pierde foco
            MaximizeBox = false;
            MinimizeBox = false;
            ControlBox = false;               // sin botón [X]
            ClientSize = new Size(580, 440);  // área CLIENTE (no incluye borde/título)
            MinimumSize = new Size(560, 400);
            Text = "AlwaysPrint - Credencial de impresión";
            BackColor = AmberRedBg;
            Font = new Font("Segoe UI", 9.75f);
            KeyPreview = true;                // para capturar Esc a nivel de form

            // ── Footer con botones (Dock=Bottom): se ancla SIEMPRE al fondo del área cliente ──
            var footer = new Panel
            {
                Dock = DockStyle.Bottom,
                Height = 68,
                BackColor = FooterBg,
                Padding = new Padding(16, 14, 16, 14)
            };

            _testPrintButton = new Button
            {
                Text = "Generar impresión de prueba",
                Dock = DockStyle.Left,
                Width = 260,
                FlatStyle = FlatStyle.Flat,
                BackColor = AmberRedAccent,
                ForeColor = Color.White,
                Font = new Font("Segoe UI", 9.75f, FontStyle.Bold),
                Cursor = Cursors.Hand
            };
            _testPrintButton.FlatAppearance.BorderSize = 0;
            _testPrintButton.Click += OnTestPrintClick;

            _exitButton = new Button
            {
                Text = "Salir",
                Dock = DockStyle.Right,
                Width = 130,
                FlatStyle = FlatStyle.Flat,
                BackColor = Color.FromArgb(226, 232, 240),
                ForeColor = TextDark,
                Font = new Font("Segoe UI", 9.75f, FontStyle.Bold),
                Cursor = Cursors.Hand
            };
            _exitButton.FlatAppearance.BorderSize = 0;
            _exitButton.Click += (s, e) => CloseByUser();

            footer.Controls.Add(_testPrintButton);
            footer.Controls.Add(_exitButton);

            // ── Barra de acento superior (Dock=Top) ──
            _headerBar = new Panel
            {
                Dock = DockStyle.Top,
                Height = 6,
                BackColor = AmberRedAccent
            };

            // ── Encabezado con ícono de Warning + título (Dock=Top) ──
            var headerPanel = new Panel
            {
                Dock = DockStyle.Top,
                Height = 64,
                BackColor = AmberRedBg,
                Padding = new Padding(20, 12, 20, 8)
            };

            _statusIconBox = new PictureBox
            {
                Dock = DockStyle.Left,
                Width = 48,
                SizeMode = PictureBoxSizeMode.CenterImage,
                Image = SystemIcons.Warning.ToBitmap()
            };

            _statusTitleLabel = new Label
            {
                Dock = DockStyle.Fill,
                TextAlign = ContentAlignment.MiddleLeft,
                Font = new Font("Segoe UI", 15f, FontStyle.Bold),
                ForeColor = AmberRedAccent,
                Text = "Falta tu credencial de impresión"
            };

            headerPanel.Controls.Add(_statusTitleLabel);
            headerPanel.Controls.Add(_statusIconBox);

            // ── Cuerpo (Dock=Fill): ocupa el resto entre header y footer ──
            var body = new Panel
            {
                Dock = DockStyle.Fill,
                BackColor = AmberRedBg,
                Padding = new Padding(22, 8, 22, 8)
            };

            _userLabel = new Label
            {
                Dock = DockStyle.Top,
                Height = 26,
                Font = new Font("Segoe UI", 10f, FontStyle.Bold),
                ForeColor = TextDark,
                Text = $"Usuario: {_username}"
            };

            _bodyLabel = new Label
            {
                Dock = DockStyle.Top,
                Height = 190,
                ForeColor = TextBody,
                Font = new Font("Segoe UI", 9.75f),
                Text = BuildInstructions()
            };

            _pollStatusLabel = new Label
            {
                Dock = DockStyle.Bottom,
                Height = 48,
                Font = new Font("Segoe UI", 9.75f, FontStyle.Bold),
                ForeColor = AmberRedAccent,
                Text = string.Empty
            };

            // Orden de inserción: los Dock=Top se apilan según orden inverso de Add.
            body.Controls.Add(_pollStatusLabel);
            body.Controls.Add(_bodyLabel);
            body.Controls.Add(_userLabel);

            // Agregar en orden: primero Fill, luego los Top/Bottom (WinForms respeta z-order).
            Controls.Add(body);
            Controls.Add(headerPanel);
            Controls.Add(_headerBar);
            Controls.Add(footer);

            // Esc cierra la ventana (mismo efecto que "Salir").
            KeyDown += (s, e) =>
            {
                if (e.KeyCode == Keys.Escape)
                {
                    e.Handled = true;
                    CloseByUser();
                }
            };

            // Bloquear cierre por medios distintos a Salir/Esc (ej: Alt+F4 residual).
            FormClosing += (s, e) =>
            {
                if (!_allowClose)
                    e.Cancel = true;
            };
        }

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool SetForegroundWindow(IntPtr hWnd);

        /// <summary>
        /// Fuerza que la ventana quede al frente y con foco. TopMost por sí solo no basta
        /// cuando la ventana se crea en un thread STA separado y otra app tiene el foco.
        /// Se combina toggle de TopMost + Activate + SetForegroundWindow (mismo patrón que
        /// ConsentPopup, probado para forzar la ventana sobre apps maximizadas).
        /// </summary>
        protected override void OnShown(EventArgs e)
        {
            base.OnShown(e);
            try
            {
                TopMost = true;
                // Toggle para forzar reevaluación del z-order por el window manager.
                TopMost = false;
                TopMost = true;
                Activate();
                BringToFront();
                Focus();
                SetForegroundWindow(Handle);
            }
            catch { /* no crítico */ }
        }

        private string BuildInstructions()
        {
            string browser = GetDefaultBrowserName();
            return
                "No se encontró tu credencial de impresión en este equipo.\r\n\r\n" +
                "La primera vez que envíes un documento a imprimir, deberás ingresar tus " +
                "credenciales corporativas para autenticarte.\r\n\r\n" +
                $"IMPORTANTE: después de enviar la impresión, revisa tu navegador predeterminado " +
                $"({browser}). Puede haberse abierto MINIMIZADO esperando que te autentiques.\r\n\r\n" +
                "Pulsa \"Generar impresión de prueba\" para forzar la solicitud de credenciales " +
                "y completar tu autenticación.";
        }

        private void OnTestPrintClick(object sender, EventArgs e)
        {
            _testPrintButton.Enabled = false;
            _pollStatusLabel.ForeColor = AmberRedAccent;
            _pollStatusLabel.Text = "Enviando impresión de prueba…";

            bool triggered = false;
            try
            {
                triggered = _triggerTestPrint?.Invoke(_testPrintLabel) ?? false;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"CpmTokenPromptForm: error disparando impresión de prueba: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
            }

            if (!triggered)
            {
                _pollStatusLabel.Text = "No se pudo enviar la impresión de prueba. Reintenta en unos segundos.";
                _testPrintButton.Enabled = true;
                return;
            }

            // A partir de aquí la ventana ya no debe tapar el navegador donde el usuario
            // se autentica: soltar TopMost (deja de estar siempre encima). Sigue visible y
            // usable, pero el foreground puede pasar al browser.
            _testPrintTriggered = true;
            TopMost = false;

            _pollStatusLabel.Text =
                "Impresión enviada. Revisa tu navegador (puede estar minimizado) y autentícate. " +
                "Verificando tu credencial…";

            StartPolling();
        }

        private void StartPolling()
        {
            _pollStartedUtc = DateTime.UtcNow;

            _pollTimer?.Dispose();
            _pollTimer = new System.Windows.Forms.Timer { Interval = 2000 };
            _pollTimer.Tick += (s, e) =>
            {
                if (TokenExists())
                {
                    _pollTimer.Stop();
                    SetConfirmedState();
                    return;
                }

                double elapsed = (DateTime.UtcNow - _pollStartedUtc).TotalSeconds;
                if (elapsed >= _pollTimeoutSeconds)
                {
                    _pollTimer.Stop();
                    _pollStatusLabel.Text =
                        "Aún no detectamos tu credencial. Autentícate en el navegador y vuelve a " +
                        "intentar la impresión de prueba.";
                    _testPrintButton.Enabled = true;
                }
            };
            _pollTimer.Start();
        }

        private bool TokenExists()
        {
            try
            {
                return !string.IsNullOrEmpty(_tokenPath) && File.Exists(_tokenPath);
            }
            catch
            {
                return false;
            }
        }

        private void SetConfirmedState()
        {
            BackColor = GreenBg;
            _headerBar.BackColor = GreenAccent;
            if (_statusIconBox.Parent != null)
                _statusIconBox.Parent.BackColor = GreenBg;
            _statusIconBox.Image = SystemIcons.Information.ToBitmap();
            _statusTitleLabel.Parent.BackColor = GreenBg;
            _statusTitleLabel.ForeColor = GreenAccent;
            _statusTitleLabel.Text = "Credencial verificada";
            _bodyLabel.Parent.BackColor = GreenBg;
            _bodyLabel.Text =
                "Tu credencial de impresión fue detectada correctamente.\r\n\r\n" +
                "Ya puedes enviar tus impresiones de forma segura. Puedes cerrar esta ventana.";
            _userLabel.Parent.BackColor = GreenBg;
            _pollStatusLabel.ForeColor = GreenAccent;
            _testPrintButton.Visible = false;

            // Resaltar el botón Salir como acción principal en estado verde.
            _exitButton.BackColor = GreenAccent;
            _exitButton.ForeColor = Color.White;
            _exitButton.Text = "Cerrar";

            AlwaysPrintLogger.WriteTrayInfo(
                $"CpmTokenPromptForm: token confirmado para '{_username}'.");

            // Volver a traer la ventana al frente (TopMost) para evidenciar que el flujo
            // terminó con éxito. Durante el polling se había soltado TopMost para no tapar
            // el navegador; ahora que ya se autenticó, sí queremos que el usuario lo vea.
            try
            {
                TopMost = true;
                TopMost = false;
                TopMost = true;
                Activate();
                BringToFront();
                Focus();
                SetForegroundWindow(Handle);
            }
            catch { /* no crítico */ }

            // Iniciar cuenta regresiva de auto-cierre para no estorbar al usuario.
            StartAutoClose();
        }

        /// <summary>
        /// Inicia la cuenta regresiva de auto-cierre (AutoCloseSeconds) tras confirmar la
        /// credencial. Actualiza el mensaje con los segundos restantes y cierra la ventana
        /// al llegar a cero. El usuario puede cerrar antes con "Cerrar" o Esc.
        /// </summary>
        private void StartAutoClose()
        {
            _autoCloseRemaining = AutoCloseSeconds;
            _pollStatusLabel.Text =
                $"Autenticación completada. Esta ventana se cerrará en {_autoCloseRemaining} segundos…";

            _autoCloseTimer?.Dispose();
            _autoCloseTimer = new System.Windows.Forms.Timer { Interval = 1000 };
            _autoCloseTimer.Tick += (s, e) =>
            {
                _autoCloseRemaining--;
                if (_autoCloseRemaining <= 0)
                {
                    _autoCloseTimer.Stop();
                    CloseByUser();
                    return;
                }
                _pollStatusLabel.Text =
                    $"Autenticación completada. Esta ventana se cerrará en {_autoCloseRemaining} segundos…";
            };
            _autoCloseTimer.Start();
        }

        private void CloseByUser()
        {
            _allowClose = true;
            _pollTimer?.Stop();
            _autoCloseTimer?.Stop();
            Close();
        }

        /// <summary>
        /// Obtiene un nombre legible del navegador predeterminado del usuario leyendo el
        /// ProgId de UserChoice en HKCU. Corre en el Tray (contexto de usuario), por lo que
        /// HKCU apunta al usuario correcto. Retorna "tu navegador predeterminado" si no se puede resolver.
        /// </summary>
        private static string GetDefaultBrowserName()
        {
            try
            {
                using (var key = Registry.CurrentUser.OpenSubKey(
                    @"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"))
                {
                    string progId = key?.GetValue("ProgId") as string;
                    if (string.IsNullOrWhiteSpace(progId))
                        return "tu navegador predeterminado";

                    string p = progId.ToLowerInvariant();
                    if (p.Contains("chrome")) return "Google Chrome";
                    if (p.Contains("msedge") || p.Contains("edge")) return "Microsoft Edge";
                    if (p.Contains("firefox")) return "Mozilla Firefox";
                    if (p.Contains("opera")) return "Opera";
                    if (p.Contains("brave")) return "Brave";
                    if (p.Contains("ie") || p.Contains("internetexplorer")) return "Internet Explorer";

                    // Fallback: intentar el nombre amigable del ProgId en HKCR.
                    using (var progKey = Registry.ClassesRoot.OpenSubKey(progId))
                    {
                        string friendly = progKey?.GetValue(null) as string;
                        if (!string.IsNullOrWhiteSpace(friendly))
                            return friendly;
                    }

                    return "tu navegador predeterminado";
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"CpmTokenPromptForm: no se pudo resolver el navegador predeterminado: {ex.Message}");
                return "tu navegador predeterminado";
            }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _pollTimer?.Dispose();
                _autoCloseTimer?.Dispose();
            }
            base.Dispose(disposing);
        }
    }
}
