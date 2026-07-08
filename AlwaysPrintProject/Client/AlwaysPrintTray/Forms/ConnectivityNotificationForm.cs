using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintTray.Connectivity;

namespace AlwaysPrintTray.Forms
{
    /// <summary>
    /// Formulario de notificación tipo toast para mostrar resultados del check de conectividad.
    /// Se muestra en la esquina inferior derecha de la pantalla (sobre la barra de tareas).
    /// Singleton: solo una instancia visible a la vez.
    /// </summary>
    public sealed class ConnectivityNotificationForm : Form
    {
        // === COLORES DE SEVERIDAD ===
        private static readonly Color GreenBg = ColorTranslator.FromHtml("#E8F5E9");
        private static readonly Color YellowBg = ColorTranslator.FromHtml("#FFF3E0");
        private static readonly Color RedBg = ColorTranslator.FromHtml("#FFEBEE");

        private static readonly Color GreenIcon = Color.FromArgb(76, 175, 80);
        private static readonly Color YellowIcon = Color.FromArgb(255, 152, 0);
        private static readonly Color RedIcon = Color.FromArgb(244, 67, 54);

        // === CONSTANTES DE LAYOUT ===
        private const int FormWidth = 380;
        private const int FormHeight = 100;
        private const int FadeStepMs = 20;
        private const double FadeIncrement = 0.067; // ~15 pasos en 300ms (20ms * 15 = 300ms)

        // === SINGLETON (thread-safe para thread STA dedicado) ===
        private static ConnectivityNotificationForm _current;
        private static readonly object _lock = new object();

        /// <summary>
        /// Instancia activa del formulario de notificación. Null si no hay ninguna visible.
        /// Thread-safe: la notificación se ejecuta en un thread STA dedicado.
        /// </summary>
        public static ConnectivityNotificationForm Current
        {
            get { lock (_lock) return _current; }
            private set { lock (_lock) _current = value; }
        }

        // === CAMPOS INTERNOS ===
        private readonly Timer _autoCloseTimer;
        private readonly Timer _fadeInTimer;
        private readonly List<UrlCheckResult> _results;
        private readonly int _percent;
        private readonly Severity _severity;
        private readonly int _criticalFails;

        /// <summary>Nivel de severidad de la notificación.</summary>
        private enum Severity
        {
            Green,
            Yellow,
            Red
        }

        /// <summary>
        /// Constructor privado. Usar <see cref="ShowResult"/> para crear y mostrar.
        /// </summary>
        private ConnectivityNotificationForm(
            List<UrlCheckResult> results, int percent, ConnectivityCheckPayload payload,
            int criticalFails, int criticalTotal, bool serverUrlFailed)
        {
            _results = results;
            _percent = percent;
            _criticalFails = criticalFails;
            _severity = DeterminarSeveridad(criticalFails, serverUrlFailed);

            // === Configuración del Form ===
            FormBorderStyle = FormBorderStyle.None;
            TopMost = true;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.Manual;
            Size = new Size(FormWidth, FormHeight);
            BackColor = ObtenerColorFondo(_severity);
            Opacity = 0; // Inicia invisible para el fade-in

            // Posicionar en esquina inferior derecha (sobre barra de tareas)
            PosicionarEnEsquina();

            // === Construir controles de UI ===
            ConstruirUI(payload);

            // === Timer de fade-in (300ms total) ===
            _fadeInTimer = new Timer { Interval = FadeStepMs };
            _fadeInTimer.Tick += OnFadeInTick;

            // === Timer de auto-cierre (solo amarillo) ===
            _autoCloseTimer = new Timer();
            if (_severity == Severity.Yellow)
            {
                _autoCloseTimer.Interval = payload.NotificationYellowTimeoutSeconds * 1000;
                _autoCloseTimer.Tick += (s, e) => Close();
            }
            // Rojo: sin auto-cierre (persistente)
        }

        /// <summary>
        /// Muestra el resultado del check de conectividad al usuario.
        /// Gestiona el singleton: cierra la notificación previa si existe (thread-safe).
        /// Se invoca desde el thread STA dedicado de la notificación.
        /// NOTA: No se llama cuando criticalFails == 0 (verde = sin notificación).
        /// </summary>
        /// <param name="results">Lista de resultados por URL.</param>
        /// <param name="percent">Porcentaje de URLs accesibles (0-100).</param>
        /// <param name="payload">Payload original con parámetros de timeouts de notificación.</param>
        /// <param name="criticalFails">Número de URLs críticas con fallo de transporte.</param>
        /// <param name="criticalTotal">Total de URLs críticas verificadas.</param>
        /// <param name="serverUrlFailed">true si la primera URL (SERVER_URL) falló.</param>
        public static void ShowResult(
            List<UrlCheckResult> results, int percent, ConnectivityCheckPayload payload,
            int criticalFails = 0, int criticalTotal = 0, bool serverUrlFailed = false)
        {
            // Cerrar notificación previa si existe (thread-safe)
            var prev = Current;
            if (prev != null && !prev.IsDisposed)
            {
                try
                {
                    if (prev.InvokeRequired)
                        prev.Invoke(new Action(() => prev.Close()));
                    else
                        prev.Close();
                }
                catch { /* ignorar si ya fue cerrado */ }
            }
            Current = null;

            // Crear y mostrar nueva notificación (ya estamos en el thread STA correcto)
            var form = new ConnectivityNotificationForm(results, percent, payload,
                criticalFails, criticalTotal, serverUrlFailed);
            Current = form;
            form.Show();
            form.BringToFront();
            form.Activate();
            form._fadeInTimer.Start();

            AlwaysPrintLogger.WriteTrayInfo(
                $"ConnectivityNotificationForm: mostrada ({(form._severity == Severity.Yellow ? "amarilla" : "roja")}, " +
                $"críticos fallidos={criticalFails}/{criticalTotal}).",
                AlwaysPrintLogger.EvtConnectivitySummary);

            if (form._severity != Severity.Red)
            {
                form._autoCloseTimer.Start();
            }
        }

        // === MÉTODOS PRIVADOS ===

        /// <summary>
        /// Posiciona el formulario en la esquina inferior derecha del área de trabajo.
        /// </summary>
        private void PosicionarEnEsquina()
        {
            var workArea = Screen.PrimaryScreen.WorkingArea;
            int x = workArea.Right - FormWidth - 12;
            int y = workArea.Bottom - FormHeight - 12;
            Location = new Point(x, y);
        }

        /// <summary>
        /// Construye todos los controles de la interfaz de usuario.
        /// </summary>
        private void ConstruirUI(ConnectivityCheckPayload payload)
        {
            // === Panel de icono (izquierda) ===
            var pnlIcono = new Panel
            {
                Location = new Point(12, 12),
                Size = new Size(40, 40),
                BackColor = Color.Transparent
            };
            pnlIcono.Paint += PintarIcono;
            Controls.Add(pnlIcono);

            // === Label con texto del resultado ===
            var lblTexto = new Label
            {
                Text = ObtenerTexto(_severity, _criticalFails),
                Font = new Font("Segoe UI", 10f, FontStyle.Bold),
                ForeColor = AppTheme.TextPrimary,
                Location = new Point(60, 16),
                Size = new Size(FormWidth - 72, 28),
                TextAlign = ContentAlignment.MiddleLeft
            };
            Controls.Add(lblTexto);

            // === Botón "Ver Reporte" ===
            var btnReporte = new AppButton
            {
                Text = "Ver Reporte",
                Size = new Size(100, 30),
                Location = new Point(60, FormHeight - 44),
                IsPrimary = false,
                ShowBorder = true
            };
            btnReporte.Click += OnVerReporteClick;
            Controls.Add(btnReporte);

            // === Botón "OK" / "Entendido" ===
            var btnAck = new AppButton
            {
                Text = _severity == Severity.Red ? "Entendido" : "OK",
                Size = new Size(_severity == Severity.Red ? 100 : 70, 30),
                Location = new Point(FormWidth - (_severity == Severity.Red ? 112 : 82), FormHeight - 44),
                IsPrimary = true
            };
            btnAck.Click += (s, e) => Close();
            Controls.Add(btnAck);
        }

        /// <summary>
        /// Pinta el icono de severidad en el panel.
        /// </summary>
        private void PintarIcono(object sender, PaintEventArgs e)
        {
            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            var rect = new Rectangle(4, 4, 32, 32);

            switch (_severity)
            {
                case Severity.Green:
                    // Checkmark verde dentro de un círculo
                    using (var pen = new Pen(GreenIcon, 3f))
                    {
                        g.DrawEllipse(pen, rect);
                        g.DrawLine(pen, 12, 20, 17, 26);
                        g.DrawLine(pen, 17, 26, 28, 14);
                    }
                    break;

                case Severity.Yellow:
                    // Triángulo de advertencia naranja
                    using (var pen = new Pen(YellowIcon, 2.5f))
                    using (var brush = new SolidBrush(YellowIcon))
                    {
                        var triangle = new Point[]
                        {
                            new Point(20, 6),
                            new Point(4, 34),
                            new Point(36, 34)
                        };
                        g.DrawPolygon(pen, triangle);
                        g.FillRectangle(brush, 18, 14, 4, 10);
                        g.FillEllipse(brush, 18, 27, 4, 4);
                    }
                    break;

                case Severity.Red:
                    // X en círculo rojo
                    using (var pen = new Pen(RedIcon, 3f))
                    {
                        g.DrawEllipse(pen, rect);
                        g.DrawLine(pen, 13, 13, 27, 27);
                        g.DrawLine(pen, 27, 13, 13, 27);
                    }
                    break;
            }
        }

        /// <summary>
        /// Handler del tick del timer de fade-in.
        /// </summary>
        private void OnFadeInTick(object sender, EventArgs e)
        {
            if (Opacity >= 1.0)
            {
                Opacity = 1.0;
                _fadeInTimer.Stop();
                return;
            }
            Opacity = Math.Min(1.0, Opacity + FadeIncrement);
        }

        /// <summary>
        /// Handler del botón "Ver Reporte". Abre el formulario de reporte detallado.
        /// </summary>
        private void OnVerReporteClick(object sender, EventArgs e)
        {
            try
            {
                var reportForm = new ConnectivityReportForm(_results, _percent);
                reportForm.ShowDialog(this);
            }
            catch { }
        }

        /// <summary>
        /// Determina la severidad según fallos críticos.
        /// Verde: 0 fallos críticos (no debería llegar aquí — no se muestra notificación).
        /// Amarillo: 1-2 fallos críticos.
        /// Rojo: 3+ fallos críticos O SERVER_URL falla.
        /// </summary>
        private static Severity DeterminarSeveridad(int criticalFails, bool serverUrlFailed)
        {
            if (criticalFails == 0) return Severity.Green;
            if (criticalFails >= 3 || serverUrlFailed) return Severity.Red;
            return Severity.Yellow;
        }

        /// <summary>
        /// Obtiene el color de fondo según la severidad.
        /// </summary>
        private static Color ObtenerColorFondo(Severity severity)
        {
            switch (severity)
            {
                case Severity.Green: return GreenBg;
                case Severity.Yellow: return YellowBg;
                case Severity.Red: return RedBg;
                default: return GreenBg;
            }
        }

        /// <summary>
        /// Obtiene el texto de la notificación según la severidad y fallos críticos.
        /// </summary>
        private static string ObtenerTexto(Severity severity, int criticalFails)
        {
            switch (severity)
            {
                case Severity.Green:
                    return "Conectividad: Todo OK 100%";
                case Severity.Yellow:
                    return $"Conectividad: {criticalFails} servicio(s) cr\u00edtico(s) inaccesible(s)";
                case Severity.Red:
                    return "Sin acceso a servicios cr\u00edticos de impresi\u00f3n";
                default:
                    return string.Empty;
            }
        }

        /// <summary>
        /// Sobrescribe el pintado para agregar borde sutil.
        /// </summary>
        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            using var pen = new Pen(Color.FromArgb(60, Color.Black), 1);
            e.Graphics.DrawRectangle(pen, 0, 0, Width - 1, Height - 1);
        }

        /// <summary>
        /// Al cerrar, limpiar la referencia singleton, detener timers y
        /// terminar el message loop del thread STA dedicado.
        /// </summary>
        protected override void OnFormClosed(FormClosedEventArgs e)
        {
            if (Current == this)
                Current = null;

            AlwaysPrintLogger.WriteTrayInfo(
                "ConnectivityNotificationForm: cerrada.",
                AlwaysPrintLogger.EvtConnectivitySummary);

            base.OnFormClosed(e);

            // Terminar el message loop del thread dedicado de notificación
            Application.ExitThread();
        }

        /// <summary>
        /// Libera recursos de timers.
        /// </summary>
        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _fadeInTimer?.Stop();
                _fadeInTimer?.Dispose();
                _autoCloseTimer?.Stop();
                _autoCloseTimer?.Dispose();
            }
            base.Dispose(disposing);
        }
    }
}
