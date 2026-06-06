using System;
using System.Diagnostics;
using System.Drawing;
using System.Reflection;
using System.Windows.Forms;

namespace AlwaysPrintTray.Forms
{
    /// <summary>
    /// Formulario "Acerca de" con estilo corporativo AlwaysPrint.
    /// Se cierra automáticamente a los 30 segundos.
    /// </summary>
    public sealed class AboutForm : Form
    {
        private readonly Timer _autoCloseTimer;

        public AboutForm()
        {
            var version      = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "1.0.0";
            var currentUser  = Environment.UserName;
            var processStart = Process.GetCurrentProcess().StartTime;

            Text       = "Acerca de AlwaysPrint";
            ClientSize = new Size(460, 440);
            KeyPreview = true;
            AppTheme.ApplyFormStyle(this);

            // ── Header ──────────────────────────────────────────────────────
            var header = new Panel
            {
                Location  = new Point(0, 0),
                Size      = new Size(460, 170),
                BackColor = AppTheme.HeaderBg
            };
            header.Paint += (s, e) => AppTheme.DrawHeaderAccent(e.Graphics, 460, 170);

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
                Font      = AppTheme.FontHeading,
                ForeColor = AppTheme.TextOnDark,
                BackColor = Color.Transparent,
                Location  = new Point(10, 96),
                Size      = new Size(440, 42),
                TextAlign = ContentAlignment.MiddleCenter
            };

            var lblVer = new Label
            {
                Text      = $"Versión  {version}",
                Font      = AppTheme.FontSmall,
                ForeColor = AppTheme.TextSubtitle,
                BackColor = Color.Transparent,
                Location  = new Point(10, 138),
                Size      = new Size(440, 24),
                TextAlign = ContentAlignment.MiddleCenter
            };

            header.Controls.AddRange(new Control[] { pic, lblAppName, lblVer });

            // ── Body ────────────────────────────────────────────────────────
            var body = new Panel
            {
                Location  = new Point(0, 170),
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
                Font      = AppTheme.FontSmall,
                ForeColor = AppTheme.TextMuted,
                Location  = new Point(30, 134),
                Size      = new Size(400, 20),
                TextAlign = ContentAlignment.MiddleLeft
            };
            var lblLegal = new Label
            {
                Text      = "Inversiones On Line S.A.C.",
                Font      = AppTheme.FontSmall,
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
                Location  = new Point(0, 375),
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

            // ── Auto-cierre a los 30 segundos ───────────────────────────────
            _autoCloseTimer = new Timer { Interval = 30_000 };
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
                Font      = AppTheme.FontBold,
                ForeColor = AppTheme.TextMuted,
                Location  = new Point(30, y),
                Size      = new Size(90, 26),
                TextAlign = ContentAlignment.MiddleLeft
            });
            parent.Controls.Add(new Label
            {
                Text      = value,
                Font      = AppTheme.FontRegular,
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
    }
}
