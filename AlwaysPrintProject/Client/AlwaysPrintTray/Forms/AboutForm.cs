using System;
using System.Diagnostics;
using System.Drawing;
using System.Reflection;
using System.Windows.Forms;

namespace AlwaysPrintTray.Forms
{
    /// <summary>
    /// Formulario "Acerca de" con estilo corporativo AlwaysPrint.
    /// Se cierra automáticamente: 10s si es startup, 30s si es manual.
    /// </summary>
    public sealed class AboutForm : Form
    {
        private readonly Timer _autoCloseTimer;

        public AboutForm(bool isStartup = false)
        {
            var version      = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "1.0.0";
            var currentUser  = Environment.UserName;
            var processStart = Process.GetCurrentProcess().StartTime;

            Text       = "Acerca de AlwaysPrint";
            ClientSize = new Size(460, 480);
            KeyPreview = true;
            AppTheme.ApplyFormStyle(this);

            // ── Header (expandido a 210 para acomodar fila de branding) ─────
            var header = new Panel
            {
                Location  = new Point(0, 0),
                Size      = new Size(460, 210),
                BackColor = AppTheme.HeaderBg
            };
            header.Paint += (s, e) => AppTheme.DrawHeaderAccent(e.Graphics, 460, 210);

            var pic = new PictureBox
            {
                Location  = new Point((460 - 72) / 2, 18),
                Size      = new Size(72, 72),
                SizeMode  = PictureBoxSizeMode.Zoom,
                BackColor = Color.Transparent,
                Image     = LoadLogoFromResource()
            };

            var lblAppName = new Label
            {
                Text      = "AlwaysPrint",
                Font      = (Font)AppTheme.FontHeading.Clone(),
                ForeColor = AppTheme.TextOnDark,
                BackColor = Color.Transparent,
                Location  = new Point(10, 96),
                Size      = new Size(440, 42),
                TextAlign = ContentAlignment.MiddleCenter
            };

            // Fila inferior del header: versión a la izquierda, branding Robles.AI a la derecha
            var lblVersion = new Label
            {
                Text      = $"v{version}",
                Font      = new Font("Segoe UI", 10, FontStyle.Regular),
                ForeColor = Color.FromArgb(180, 220, 255),  // Azul claro legible sobre fondo oscuro
                BackColor = Color.Transparent,
                Location  = new Point(20, 140),
                Size      = new Size(200, 24),
                TextAlign = ContentAlignment.MiddleLeft
            };

            var lblAutomation = new Label
            {
                Text      = "Un producto de automatización de",
                Font      = new Font("Segoe UI", 7.5f, FontStyle.Regular),
                ForeColor = Color.FromArgb(160, 170, 180),  // Gris claro
                BackColor = Color.Transparent,
                Location  = new Point(250, 138),
                Size      = new Size(200, 16),
                TextAlign = ContentAlignment.MiddleRight
            };

            var picRobles = new PictureBox
            {
                Location  = new Point(360, 156),
                Size      = new Size(80, 32),
                SizeMode  = PictureBoxSizeMode.Zoom,
                BackColor = Color.Transparent,
                Image     = LoadRoblesLogoFromResource()
            };

            header.Controls.AddRange(new Control[] { pic, lblAppName, lblVersion, lblAutomation, picRobles });

            // ── Body ────────────────────────────────────────────────────────
            var body = new Panel
            {
                Location  = new Point(0, 210),
                Size      = new Size(460, 205),
                BackColor = AppTheme.BodyBg
            };

            var lblDesc = new Label
            {
                Text      = "Servicio de impresión corporativa",
                Font      = new Font("Segoe UI", 9, FontStyle.Italic),
                ForeColor = AppTheme.TextMuted,
                Location  = new Point(30, 16),
                AutoSize  = true
            };
            body.Controls.Add(lblDesc);
            body.Paint += (s, e) => AppTheme.DrawDivider(e.Graphics, 30, 42, 430);

            AddRow(body, "Usuario",  currentUser,                                    54);
            AddRow(body, "Iniciado", processStart.ToString("yyyy-MM-dd  HH:mm:ss"),  90);

            var lblCopyright = new Label
            {
                Text      = "© 2026 Robles.AI",
                Font      = (Font)AppTheme.FontSmall.Clone(),
                ForeColor = AppTheme.TextMuted,
                Location  = new Point(30, 134),
                Size      = new Size(400, 20),
                TextAlign = ContentAlignment.MiddleLeft
            };
            var lblLegal = new Label
            {
                Text      = "Inversiones On Line S.A.C.",
                Font      = (Font)AppTheme.FontSmall.Clone(),
                ForeColor = AppTheme.TextMuted,
                Location  = new Point(30, 158),
                Size      = new Size(400, 20),
                TextAlign = ContentAlignment.MiddleLeft
            };
            body.Controls.Add(lblCopyright);
            body.Controls.Add(lblLegal);

            // ── Footer ──────────────────────────────────────────────────────
            var footer = new Panel
            {
                Location  = new Point(0, 415),
                Size      = new Size(460, 65),
                BackColor = AppTheme.FooterBg
            };
            footer.Paint += (s, e) => AppTheme.DrawDivider(e.Graphics, 0, 0, 460);

            var btnClose = new AppButton
            {
                Text      = "Cerrar",
                Size      = new Size(104, 36),
                Location  = new Point(460 - 104 - 28, 14),
                IsPrimary = true
            };
            btnClose.Click += (s, e) => Close();

            footer.Controls.Add(btnClose);
            Controls.AddRange(new Control[] { header, body, footer });
            AcceptButton = btnClose;
            CancelButton = btnClose;

            // ── Auto-cierre: 10 segundos si es startup, 30 si es manual ─────
            _autoCloseTimer = new Timer { Interval = isStartup ? 10_000 : 30_000 };
            _autoCloseTimer.Tick += (s, e) => Close();
            _autoCloseTimer.Start();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _autoCloseTimer?.Stop();
                _autoCloseTimer?.Dispose();
            }
            base.Dispose(disposing);
        }

        private static void AddRow(Panel parent, string label, string value, int y)
        {
            parent.Controls.Add(new Label
            {
                Text      = label,
                Font      = (Font)AppTheme.FontBold.Clone(),
                ForeColor = AppTheme.TextMuted,
                Location  = new Point(30, y),
                Size      = new Size(90, 26),
                TextAlign = ContentAlignment.MiddleLeft
            });
            parent.Controls.Add(new Label
            {
                Text      = value,
                Font      = (Font)AppTheme.FontRegular.Clone(),
                ForeColor = AppTheme.TextPrimary,
                Location  = new Point(128, y),
                Size      = new Size(302, 26),
                TextAlign = ContentAlignment.MiddleLeft
            });

            int capturedY = y;
            parent.Paint += (s, e) => AppTheme.DrawDivider(e.Graphics, 30, capturedY + 30, 430);
        }

        private static Image? LoadLogoFromResource()
        {
            try
            {
                var assembly = Assembly.GetExecutingAssembly();
                using var stream = assembly.GetManifestResourceStream("AlwaysPrintTray.Resources.logo.png");
                if (stream != null) return Image.FromStream(stream);

                using var icoStream = assembly.GetManifestResourceStream("AlwaysPrintTray.Resources.logo.ico");
                if (icoStream != null)
                {
                    using var icon = new Icon(icoStream, 256, 256);
                    return icon.ToBitmap();
                }
            }
            catch { }
            return null;
        }

        /// <summary>
        /// Carga el logo de Robles.AI desde recurso embebido.
        /// </summary>
        private static Image? LoadRoblesLogoFromResource()
        {
            try
            {
                var assembly = Assembly.GetExecutingAssembly();
                using var stream = assembly.GetManifestResourceStream("AlwaysPrintTray.Resources.robles_logo.png");
                if (stream != null) return Image.FromStream(stream);
            }
            catch { }
            return null;
        }
    }
}
