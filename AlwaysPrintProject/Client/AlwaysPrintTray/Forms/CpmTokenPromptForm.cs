using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Threading;
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

        private const int FormW = 560;
        private const int FormH = 420;

        // === ESTADO ===
        private readonly string _username;
        private readonly string _tokenPath;
        private readonly string _testPrintLabel;
        private readonly int _pollTimeoutSeconds;
        private readonly Func<string, bool> _triggerTestPrint;

        private bool _allowClose;
        private System.Windows.Forms.Timer _pollTimer;
        private DateTime _pollStartedUtc;

        // === CONTROLES ===
        private Panel _headerBar;
        private Label _statusIcon;
        private Label _titleLabel;
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
        /// Crea y muestra la ventana de forma MODAL en el thread actual (debe ser STA).
        /// Bloquea hasta que el usuario cierre con Salir o Esc.
        /// </summary>
        public static void ShowModal(ShowCpmTokenPromptPayload payload, Func<string, bool> triggerTestPrint)
        {
            using (var form = new CpmTokenPromptForm(payload, triggerTestPrint))
            {
                form.ShowDialog();
            }
        }

        private void BuildUi()
        {
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            TopMost = true;
            ShowInTaskbar = false;
            MaximizeBox = false;
            MinimizeBox = false;
            ControlBox = false;               // sin botón [X]
            Size = new Size(FormW, FormH);
            Text = "AlwaysPrint - Credencial de impresión";
            BackColor = AmberRedBg;
            Font = new Font("Segoe UI", 9.75f);
            KeyPreview = true;                // para capturar Esc a nivel de form

            // Barra de encabezado con acento de estado.
            _headerBar = new Panel
            {
                Dock = DockStyle.Top,
                Height = 6,
                BackColor = AmberRedAccent
            };
            Controls.Add(_headerBar);

            _statusIcon = new Label
            {
                AutoSize = false,
                Size = new Size(FormW - 40, 34),
                Location = new Point(20, 22),
                Font = new Font("Segoe UI", 15f, FontStyle.Bold),
                ForeColor = AmberRedAccent,
                Text = "⚠  Falta tu credencial de impresión"
            };
            Controls.Add(_statusIcon);

            _titleLabel = new Label
            {
                AutoSize = false,
                Size = new Size(FormW - 40, 24),
                Location = new Point(20, 60),
                Font = new Font("Segoe UI", 10f, FontStyle.Bold),
                ForeColor = Color.FromArgb(30, 41, 59),
                Text = $"Usuario: {_username}"
            };
            Controls.Add(_titleLabel);

            _bodyLabel = new Label
            {
                AutoSize = false,
                Size = new Size(FormW - 44, 190),
                Location = new Point(22, 92),
                ForeColor = Color.FromArgb(45, 55, 72),
                Font = new Font("Segoe UI", 9.75f),
                Text = BuildInstructions()
            };
            Controls.Add(_bodyLabel);

            _pollStatusLabel = new Label
            {
                AutoSize = false,
                Size = new Size(FormW - 44, 40),
                Location = new Point(22, 286),
                Font = new Font("Segoe UI", 9.75f, FontStyle.Bold),
                ForeColor = AmberRedAccent,
                Text = string.Empty
            };
            Controls.Add(_pollStatusLabel);

            _testPrintButton = new Button
            {
                Text = "Generar impresión de prueba",
                Size = new Size(260, 40),
                Location = new Point(22, FormH - 66),
                FlatStyle = FlatStyle.Flat,
                BackColor = AmberRedAccent,
                ForeColor = Color.White,
                Font = new Font("Segoe UI", 9.75f, FontStyle.Bold),
                Cursor = Cursors.Hand
            };
            _testPrintButton.FlatAppearance.BorderSize = 0;
            _testPrintButton.Click += OnTestPrintClick;
            Controls.Add(_testPrintButton);

            _exitButton = new Button
            {
                Text = "Salir",
                Size = new Size(120, 40),
                Location = new Point(FormW - 142, FormH - 66),
                FlatStyle = FlatStyle.Flat,
                BackColor = Color.FromArgb(226, 232, 240),
                ForeColor = Color.FromArgb(30, 41, 59),
                Font = new Font("Segoe UI", 9.75f, FontStyle.Bold),
                Cursor = Cursors.Hand
            };
            _exitButton.FlatAppearance.BorderSize = 0;
            _exitButton.Click += (s, e) => CloseByUser();
            Controls.Add(_exitButton);

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
            _statusIcon.ForeColor = GreenAccent;
            _statusIcon.Text = "✔  Credencial verificada";
            _bodyLabel.Text =
                "Tu credencial de impresión fue detectada correctamente.\r\n\r\n" +
                "Ya puedes enviar tus impresiones de forma segura. Puedes cerrar esta ventana.";
            _pollStatusLabel.ForeColor = GreenAccent;
            _pollStatusLabel.Text = "Autenticación completada.";
            _testPrintButton.Visible = false;

            // Resaltar el botón Salir como acción principal en estado verde.
            _exitButton.BackColor = GreenAccent;
            _exitButton.ForeColor = Color.White;
            _exitButton.Text = "Cerrar";

            AlwaysPrintLogger.WriteTrayInfo(
                $"CpmTokenPromptForm: token confirmado para '{_username}'.");
        }

        private void CloseByUser()
        {
            _allowClose = true;
            _pollTimer?.Stop();
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
                _pollTimer?.Dispose();
            base.Dispose(disposing);
        }
    }
}
