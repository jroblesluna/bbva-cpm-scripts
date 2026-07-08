using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;
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

        // === SINGLETON ===
        private static ConnectivityNotificationForm _current;

        /// <summary>
        /// Instancia activa del formulario de notificación. Null si no hay ninguna visible.
        /// </summary>
        public static ConnectivityNotificationForm Current
        {
            get => _current;
            private set => _current = value;
        }

        // === CAMPOS INTERNOS ===
        private readonly Timer _autoCloseTimer;
        private readonly Timer _fadeInTimer;
        private readonly List<UrlCheckResult> _results;
        private readonly int _percent;
        private readonly Severity _severity;

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
            List<UrlCheckResult> results, int percent, ConnectivityCheckPayload payload)
        {
            _results = results;
            _percent = percent;
            _severity = DeterminarSeveridad(percent);

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

            // === Timer de auto-cierre (solo verde y amarillo) ===
            _autoCloseTimer = new Timer();
            if (_severity == Severity.Green)
            {
                _autoCloseTimer.Interval = payload.NotificationGreenTimeoutSeconds * 1000;
                _autoCloseTimer.Tick += (s, e) => Close();
            }
            else if (_severity == Severity.Yellow)
            {
                _autoCloseTimer.Interval = payload.NotificationYellowTimeoutSeconds * 1000;
                _autoCloseTimer.Tick += (s, e) => Close();
            }
            // Rojo: sin auto-cierre
        }

        /// <summary>
        /// Muestra el resultado del check de conectividad al usuario.
        /// Debe invocarse desde el UI thread.
        /// Gestiona el singleton: cierra la notificación previa si existe.
        /// </summary>
        /// <param name="results">Lista de resultados por URL.</param>
        /// <param name="percent">Porcentaje de URLs accesibles (0-100).</param>
        /// <param name="payload">Payload original con parámetros de timeouts de notificación.</param>
        public static void ShowResult(
            List<UrlCheckResult> results, int percent, ConnectivityCheckPayload payload)
        {
            // Cerrar notificación previa si existe
            if (Current != null && !Current.IsDisposed)
            {
                try { Current.Close(); } catch { /* ignorar si ya fue cerrado */ }
            }
            Current = null;

            // Crear y mostrar nueva notificación
            var form = new ConnectivityNotificationForm(results, percent, payload);
            Current = form;
            form.Show();
            form.BringToFront();  // Forzar visibilidad sobre diálogos modales (ej: StatusForm con ShowDialog)
            form.Activate();      // Dar foco al formulario para asegurar que se renderiza correctamente
            form._fadeInTimer.Start();

            // Iniciar auto-cierre después del fade-in (si aplica)
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
                Text = ObtenerTexto(_severity, _percent),
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
                        // Dibuja el checkmark
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
                        // Signo de exclamación
                        g.FillRectangle(brush, 18, 14, 4, 10);
                        g.FillEllipse(brush, 18, 27, 4, 4);
                    }
                    break;

                case Severity.Red:
                    // Icono de impresora en rojo (simplificado como X en círculo)
                    using (var pen = new Pen(RedIcon, 3f))
                    {
                        g.DrawEllipse(pen, rect);
                        // X dentro del círculo
                        g.DrawLine(pen, 13, 13, 27, 27);
                        g.DrawLine(pen, 27, 13, 13, 27);
                    }
                    break;
            }
        }

        /// <summary>
        /// Handler del tick del timer de fade-in.
        /// Incrementa la opacidad gradualmente.
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
        /// Handler del botón "Ver Reporte". Abre el formulario de reporte detallado (no modal).
        /// </summary>
        private void OnVerReporteClick(object sender, EventArgs e)
        {
            try
            {
                var reportForm = new ConnectivityReportForm(_results, _percent);
                reportForm.Show(); // No modal para evitar bloquear la UI
            }
            catch
            {
                // Si ConnectivityReportForm falla por alguna razón, ignorar
            }
        }

        /// <summary>
        /// Determina la severidad según el porcentaje de éxito.
        /// </summary>
        private static Severity DeterminarSeveridad(int percent)
        {
            if (percent == 100) return Severity.Green;
            if (percent > 0) return Severity.Yellow;
            return Severity.Red;
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
        /// Obtiene el texto de la notificación según la severidad y porcentaje.
        /// </summary>
        private static string ObtenerTexto(Severity severity, int percent)
        {
            switch (severity)
            {
                case Severity.Green:
                    return "Conectividad: Todo OK 100%";
                case Severity.Yellow:
                    int fallidas = 100 - percent;
                    return $"Conectividad: {fallidas}% fallidas";
                case Severity.Red:
                    return "Sin acceso a Internet \u2014 Requiere autenticaci\u00f3n en ZScaler";
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
            // Borde sutil alrededor del form
            using var pen = new Pen(Color.FromArgb(60, Color.Black), 1);
            e.Graphics.DrawRectangle(pen, 0, 0, Width - 1, Height - 1);
        }

        /// <summary>
        /// Al cerrar, limpiar la referencia singleton y detener timers.
        /// </summary>
        protected override void OnFormClosed(FormClosedEventArgs e)
        {
            if (Current == this)
                Current = null;

            base.OnFormClosed(e);
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
