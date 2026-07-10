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
            var version = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "1.0.0";

            Text       = "Acerca de AlwaysPrint";
            ClientSize = new Size(460, 420);
            KeyPreview = true;
            AppTheme.ApplyFormStyle(this);

            // ── Header (fondo oscuro, logo + nombre + versión centrados) ─────
            var header = new Panel
            {
                Location  = new Point(0, 0),
                Size      = new Size(460, 160),
                BackColor = AppTheme.HeaderBg
            };
            header.Paint += (s, e) => AppTheme.DrawHeaderAccent(e.Graphics, 460, 160);

            var pic = new PictureBox
            {
                Location  = new Point((460 - 64) / 2, 20),
                Size      = new Size(64, 64),
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
                Location  = new Point(10, 88),
                Size      = new Size(440, 34),
                TextAlign = ContentAlignment.MiddleCenter
            };

            var lblVersion = new Label
            {
                Text      = $"v{version}",
                Font      = new Font("Segoe UI", 10, FontStyle.Regular),
                ForeColor = Color.FromArgb(180, 220, 255),
                BackColor = Color.Transparent,
                Location  = new Point(10, 122),
                Size      = new Size(440, 24),
                TextAlign = ContentAlignment.MiddleCenter
            };

            header.Controls.AddRange(new Control[] { pic, lblAppName, lblVersion });

            // ── Body ────────────────────────────────────────────────────────
            var body = new Panel
            {
                Location  = new Point(0, 160),
                Size      = new Size(460, 200),
                BackColor = AppTheme.BodyBg
            };

            // Primera fila: descripción a la izquierda, branding Robles.AI a la derecha
            var lblDesc = new Label
            {
                Text      = "Servicio de impresión\ncorporativa",
                Font      = new Font("Segoe UI", 9, FontStyle.Italic),
                ForeColor = AppTheme.TextMuted,
                Location  = new Point(30, 16),
                Size      = new Size(200, 36),
                TextAlign = ContentAlignment.TopLeft
            };

            var lblAutomation = new Label
            {
                Text      = "Un producto de automatización de",
                Font      = new Font("Segoe UI", 7.5f, FontStyle.Regular),
                ForeColor = AppTheme.TextMuted,
                BackColor = Color.Transparent,
                Location  = new Point(260, 14),
                Size      = new Size(180, 16),
                TextAlign = ContentAlignment.MiddleRight
            };

            var picRobles = new PictureBox
            {
                Location  = new Point(350, 32),
                Size      = new Size(80, 28),
                SizeMode  = PictureBoxSizeMode.Zoom,
                BackColor = Color.Transparent,
                Image     = LoadRoblesLogoFromResource()
            };

            body.Controls.Add(lblDesc);
            body.Controls.Add(lblAutomation);
            body.Controls.Add(picRobles);

            // Separador
            body.Paint += (s, e) => AppTheme.DrawDivider(e.Graphics, 30, 68, 430);

            // Copyright
            var lblCopyright = new Label
            {
                Text      = "\u00a9 2026 INVERSIONES ON LINE S.A.C.",
                Font      = new Font("Segoe UI", 9f, FontStyle.Bold),
                ForeColor = AppTheme.TextPrimary,
                Location  = new Point(30, 78),
                Size      = new Size(400, 22),
                TextAlign = ContentAlignment.MiddleLeft
            };
            body.Controls.Add(lblCopyright);

            // Web (clickable link)
            var lblWeb = new LinkLabel
            {
                Text      = "\ud83c\udf10  www.sistemas.com.pe",
                Font      = (Font)AppTheme.FontRegular.Clone(),
                ForeColor = AppTheme.Accent,
                LinkColor = AppTheme.Accent,
                ActiveLinkColor = AppTheme.AccentHover,
                Location  = new Point(30, 108),
                Size      = new Size(300, 22),
                TextAlign = ContentAlignment.MiddleLeft
            };
            lblWeb.LinkClicked += (s, e) =>
            {
                try { Process.Start(new ProcessStartInfo("https://www.sistemas.com.pe") { UseShellExecute = true }); }
                catch { }
            };
            body.Controls.Add(lblWeb);

            // Email con botón copiar
            var lblEmail = new Label
            {
                Text      = "\u2709  info@iol.pe",
                Font      = (Font)AppTheme.FontRegular.Clone(),
                ForeColor = AppTheme.TextPrimary,
                Location  = new Point(30, 136),
                Size      = new Size(300, 22),
                TextAlign = ContentAlignment.MiddleLeft
            };
            body.Controls.Add(lblEmail);

            var btnCopyEmail = new Button
            {
                Text      = "\ud83d\udccb",
                Font      = new Font("Segoe UI", 8f),
                Size      = new Size(28, 22),
                Location  = new Point(180, 136),
                FlatStyle = FlatStyle.Flat,
                Cursor    = Cursors.Hand
            };
            btnCopyEmail.FlatAppearance.BorderSize = 0;
            btnCopyEmail.Click += (s, e) =>
            {
                Clipboard.SetText("info@iol.pe");
                btnCopyEmail.Text = "\u2713";
                var resetTimer = new Timer { Interval = 1500 };
                resetTimer.Tick += (_, __) => { btnCopyEmail.Text = "\ud83d\udccb"; resetTimer.Stop(); resetTimer.Dispose(); };
                resetTimer.Start();
            };
            body.Controls.Add(btnCopyEmail);

            // Teléfono con botón copiar
            var lblPhone = new Label
            {
                Text      = "\ud83d\udcde  +1(408)590-0153",
                Font      = (Font)AppTheme.FontRegular.Clone(),
                ForeColor = AppTheme.TextPrimary,
                Location  = new Point(30, 164),
                Size      = new Size(300, 22),
                TextAlign = ContentAlignment.MiddleLeft
            };
            body.Controls.Add(lblPhone);

            var btnCopyPhone = new Button
            {
                Text      = "\ud83d\udccb",
                Font      = new Font("Segoe UI", 8f),
                Size      = new Size(28, 22),
                Location  = new Point(200, 164),
                FlatStyle = FlatStyle.Flat,
                Cursor    = Cursors.Hand
            };
            btnCopyPhone.FlatAppearance.BorderSize = 0;
            btnCopyPhone.Click += (s, e) =>
            {
                Clipboard.SetText("+14085900153");
                btnCopyPhone.Text = "\u2713";
                var resetTimer = new Timer { Interval = 1500 };
                resetTimer.Tick += (_, __) => { btnCopyPhone.Text = "\ud83d\udccb"; resetTimer.Stop(); resetTimer.Dispose(); };
                resetTimer.Start();
            };
            body.Controls.Add(btnCopyPhone);

            // ── Footer ──────────────────────────────────────────────────────
            var footer = new Panel
            {
                Location  = new Point(0, 360),
                Size      = new Size(460, 60),
                BackColor = AppTheme.FooterBg
            };
            footer.Paint += (s, e) => AppTheme.DrawDivider(e.Graphics, 0, 0, 460);

            var btnClose = new AppButton
            {
                Text      = "Cerrar",
                Size      = new Size(104, 36),
                Location  = new Point(460 - 104 - 28, 12),
                IsPrimary = true
            };
            btnClose.Click += (s, e) => Close();

            footer.Controls.Add(btnClose);
            Controls.AddRange(new Control[] { header, body, footer });
            AcceptButton = btnClose;
            CancelButton = btnClose;

            // ── Auto-cierre: 10 segundos si es startup, 30 si es manual ──────
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
