using System;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.RemoteView
{
    /// <summary>
    /// Resultado del consentimiento del usuario.
    /// </summary>
    public enum ConsentResult
    {
        /// <summary>El usuario aceptó la conexión.</summary>
        Accepted,
        /// <summary>El usuario rechazó la conexión.</summary>
        Rejected,
        /// <summary>El tiempo de espera expiró sin respuesta.</summary>
        TimedOut
    }

    /// <summary>
    /// Información de un monitor de la workstation.
    /// </summary>
    public class MonitorInfo
    {
        /// <summary>Índice del monitor (0-based).</summary>
        public int Index { get; set; }

        /// <summary>Nombre descriptivo del monitor.</summary>
        public string Name { get; set; } = string.Empty;

        /// <summary>Ancho en píxeles.</summary>
        public int Width { get; set; }

        /// <summary>Alto en píxeles.</summary>
        public int Height { get; set; }

        /// <summary>Indica si es el monitor principal.</summary>
        public bool Primary { get; set; }

        /// <summary>Posición X del monitor en el escritorio virtual.</summary>
        public int X { get; set; }

        /// <summary>Posición Y del monitor en el escritorio virtual.</summary>
        public int Y { get; set; }
    }

    /// <summary>
    /// Respuesta completa del diálogo de consentimiento.
    /// Incluye el resultado y la lista de monitores (si fue aceptado).
    /// </summary>
    public class ConsentResponse
    {
        /// <summary>Resultado del consentimiento.</summary>
        public ConsentResult Result { get; set; }

        /// <summary>Lista de monitores disponibles (solo si Result == Accepted).</summary>
        public List<MonitorInfo> Monitors { get; set; } = new List<MonitorInfo>();
    }

    /// <summary>
    /// Diálogo modal WinForms para solicitar consentimiento del usuario
    /// antes de iniciar una sesión de vista remota.
    /// Muestra el nombre del administrador, countdown de 30s, y botones Permitir/Rechazar.
    /// </summary>
    public sealed class ConsentPopup : Form
    {
        // === Constantes ===
        private const int CountdownSeconds = 30;
        private const int WarningThreshold = 10; // Segundos restantes para cambiar a rojo

        // === Controles UI ===
        private Label _lblTitle = null!;
        private Label _lblAdminName = null!;
        private Label _lblCountdown = null!;
        private Button _btnAllow = null!;
        private Button _btnReject = null!;
        private Timer _timer = null!;
        private Panel _headerPanel = null!;

        // === Estado ===
        private int _secondsRemaining;
        private ConsentResult _result = ConsentResult.TimedOut;

        /// <summary>Resultado del consentimiento tras cerrar el diálogo.</summary>
        public ConsentResult ConsentResult => _result;

        /// <summary>Lista de monitores disponibles (se llena al aceptar).</summary>
        public List<MonitorInfo> Monitors { get; private set; } = new List<MonitorInfo>();

        /// <summary>
        /// Muestra el diálogo de consentimiento y retorna la respuesta del usuario.
        /// Método estático de conveniencia para invocar desde cualquier punto.
        /// </summary>
        /// <param name="adminName">Nombre completo del administrador que solicita acceso.</param>
        /// <param name="sessionId">ID de la sesión (para logging).</param>
        /// <returns>ConsentResponse con el resultado y monitores (si fue aceptado).</returns>
        public static ConsentResponse Show(string adminName, string sessionId)
        {
            AlwaysPrintLogger.WriteTrayInfo(
                $"ConsentPopup: mostrando popup de consentimiento. admin={adminName}, session_id={sessionId}");

            ConsentResponse response;

            using (var popup = new ConsentPopup(adminName, sessionId))
            {
                popup.ShowDialog();

                response = new ConsentResponse
                {
                    Result = popup.ConsentResult,
                    Monitors = popup.Monitors
                };
            }

            AlwaysPrintLogger.WriteTrayInfo(
                $"ConsentPopup: resultado={response.Result}, monitores={response.Monitors.Count}. session_id={sessionId}");

            return response;
        }

        /// <summary>
        /// Constructor del diálogo de consentimiento.
        /// </summary>
        /// <param name="adminName">Nombre completo del administrador solicitante.</param>
        /// <param name="sessionId">ID de sesión (para logging).</param>
        private ConsentPopup(string adminName, string sessionId)
        {
            _secondsRemaining = CountdownSeconds;
            InitializeComponents(adminName);
            StartCountdown();
        }

        /// <summary>
        /// Inicializa todos los componentes visuales del formulario.
        /// </summary>
        private void InitializeComponents(string adminName)
        {
            // === Configuración del formulario ===
            this.Text = "Solicitud de Vista Remota";
            this.Size = new Size(450, 280);
            this.MinimumSize = new Size(450, 280);
            this.MaximumSize = new Size(450, 280);
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.StartPosition = FormStartPosition.CenterScreen;
            this.TopMost = true;
            this.MaximizeBox = false;
            this.MinimizeBox = false;
            this.ShowInTaskbar = true;
            this.BackColor = Color.White;
            this.Font = new Font("Segoe UI", 10F, FontStyle.Regular);

            // === Panel de cabecera (fondo azul oscuro) ===
            _headerPanel = new Panel
            {
                Dock = DockStyle.Top,
                Height = 50,
                BackColor = Color.FromArgb(30, 60, 114)
            };

            var lblHeader = new Label
            {
                Text = "\U0001F6E1 Solicitud de Monitoreo Remoto",
                ForeColor = Color.White,
                Font = new Font("Segoe UI", 12F, FontStyle.Bold),
                AutoSize = false,
                Size = new Size(430, 40),
                Location = new Point(10, 8),
                TextAlign = ContentAlignment.MiddleLeft
            };
            _headerPanel.Controls.Add(lblHeader);
            this.Controls.Add(_headerPanel);

            // === Título descriptivo ===
            _lblTitle = new Label
            {
                Text = "Un administrador solicita ver tu pantalla:",
                Location = new Point(20, 65),
                AutoSize = true,
                Font = new Font("Segoe UI", 10F, FontStyle.Regular),
                ForeColor = Color.FromArgb(60, 60, 60)
            };
            this.Controls.Add(_lblTitle);

            // === Nombre del administrador ===
            _lblAdminName = new Label
            {
                Text = adminName,
                Location = new Point(20, 92),
                AutoSize = true,
                Font = new Font("Segoe UI", 13F, FontStyle.Bold),
                ForeColor = Color.FromArgb(30, 60, 114)
            };
            this.Controls.Add(_lblAdminName);

            // === Countdown ===
            _lblCountdown = new Label
            {
                Text = $"Respuesta autom\u00e1tica en {_secondsRemaining}s: Rechazar",
                Location = new Point(20, 130),
                AutoSize = true,
                Font = new Font("Segoe UI", 10F, FontStyle.Regular),
                ForeColor = Color.FromArgb(100, 100, 100)
            };
            this.Controls.Add(_lblCountdown);

            // === Botón Permitir ===
            _btnAllow = new Button
            {
                Text = "Permitir",
                Size = new Size(130, 42),
                Location = new Point(100, 180),
                BackColor = Color.FromArgb(46, 125, 50),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat,
                Font = new Font("Segoe UI", 11F, FontStyle.Bold),
                Cursor = Cursors.Hand
            };
            _btnAllow.FlatAppearance.BorderSize = 0;
            _btnAllow.Click += BtnAllow_Click;
            this.Controls.Add(_btnAllow);

            // === Botón Rechazar ===
            _btnReject = new Button
            {
                Text = "Rechazar",
                Size = new Size(130, 42),
                Location = new Point(250, 180),
                BackColor = Color.FromArgb(198, 40, 40),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat,
                Font = new Font("Segoe UI", 11F, FontStyle.Bold),
                Cursor = Cursors.Hand
            };
            _btnReject.FlatAppearance.BorderSize = 0;
            _btnReject.Click += BtnReject_Click;
            this.Controls.Add(_btnReject);

            // Foco inicial en Rechazar (seguridad: la acción por defecto es rechazar)
            this.AcceptButton = _btnReject;
            this.ActiveControl = _btnReject;
        }

        /// <summary>
        /// Inicia el temporizador de cuenta regresiva (1 tick por segundo).
        /// </summary>
        private void StartCountdown()
        {
            _timer = new Timer
            {
                Interval = 1000 // 1 segundo
            };
            _timer.Tick += Timer_Tick;
            _timer.Start();
        }

        /// <summary>
        /// Handler del tick del timer. Actualiza countdown y auto-rechaza al llegar a 0.
        /// </summary>
        private void Timer_Tick(object? sender, EventArgs e)
        {
            _secondsRemaining--;

            if (_secondsRemaining <= 0)
            {
                // Timeout: auto-rechazo
                _timer.Stop();
                _result = ConsentResult.TimedOut;

                AlwaysPrintLogger.WriteTrayInfo(
                    "ConsentPopup: timeout alcanzado, auto-rechazando solicitud.");

                this.DialogResult = DialogResult.Cancel;
                this.Close();
                return;
            }

            // Actualizar texto del countdown
            _lblCountdown.Text = $"Respuesta autom\u00e1tica en {_secondsRemaining}s: Rechazar";

            // Cambiar a rojo/negrita cuando quedan pocos segundos
            if (_secondsRemaining <= WarningThreshold)
            {
                _lblCountdown.ForeColor = Color.FromArgb(198, 40, 40);
                _lblCountdown.Font = new Font("Segoe UI", 10F, FontStyle.Bold);
            }
        }

        /// <summary>
        /// Handler del botón Permitir. Acepta la solicitud y recopila monitores.
        /// </summary>
        private void BtnAllow_Click(object? sender, EventArgs e)
        {
            _timer.Stop();
            _result = ConsentResult.Accepted;

            // Recopilar información de monitores al aceptar
            Monitors = GetMonitorList();

            AlwaysPrintLogger.WriteTrayInfo(
                $"ConsentPopup: usuario aceptó la solicitud. Monitores detectados: {Monitors.Count}");

            this.DialogResult = DialogResult.OK;
            this.Close();
        }

        /// <summary>
        /// Handler del botón Rechazar. Rechaza la solicitud explícitamente.
        /// </summary>
        private void BtnReject_Click(object? sender, EventArgs e)
        {
            _timer.Stop();
            _result = ConsentResult.Rejected;

            AlwaysPrintLogger.WriteTrayInfo(
                "ConsentPopup: usuario rechazó la solicitud.");

            this.DialogResult = DialogResult.Cancel;
            this.Close();
        }

        /// <summary>
        /// Obtiene la lista de monitores conectados a la workstation.
        /// Delega a MonitorEnumerator que es la fuente canónica de información de monitores.
        /// </summary>
        /// <returns>Lista de MonitorInfo con los monitores disponibles.</returns>
        private static List<MonitorInfo> GetMonitorList()
        {
            return MonitorEnumerator.GetMonitors();
        }

        /// <summary>
        /// Libera recursos del timer al cerrar el formulario.
        /// </summary>
        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            _timer?.Stop();
            _timer?.Dispose();
            base.OnFormClosing(e);
        }

        /// <summary>
        /// Evita que el usuario cierre el diálogo con Alt+F4 o la X (equivale a rechazar).
        /// </summary>
        protected override void OnFormClosed(FormClosedEventArgs e)
        {
            // Si se cerró sin haber elegido explícitamente, tratar como rechazo
            if (_result != ConsentResult.Accepted)
            {
                _result = ConsentResult.Rejected;
            }
            base.OnFormClosed(e);
        }
    }
}
