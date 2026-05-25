using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Reflection;
using System.Windows.Forms;

namespace AlwaysPrintTray.Forms
{
    public sealed class AboutForm : Form
    {
        private static readonly Color HeaderBg     = Color.FromArgb(15, 23, 42);
        private static readonly Color AccentColor  = Color.FromArgb(99, 102, 241);
        private static readonly Color BodyBg       = Color.FromArgb(248, 250, 252);
        private static readonly Color FooterBg     = Color.FromArgb(241, 245, 249);
        private static readonly Color TextColor    = Color.FromArgb(30, 41, 59);
        private static readonly Color MutedColor   = Color.FromArgb(100, 116, 139);
        private static readonly Color DividerColor = Color.FromArgb(226, 232, 240);

        public AboutForm()
        {
            var version      = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "1.0.0";
            var currentUser  = Environment.UserName;
            var processStart = Process.GetCurrentProcess().StartTime;

            Text            = "Acerca de AlwaysPrint";
            ClientSize      = new Size(460, 440);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox     = false;
            MinimizeBox     = false;
            StartPosition   = FormStartPosition.CenterScreen;
            ShowInTaskbar   = false;
            BackColor       = BodyBg;
            Font            = new Font("Segoe UI", 9);

            // ── Header ──────────────────────────────────────────────────────
            var header = new Panel
            {
                Location  = new Point(0, 0),
                Size      = new Size(460, 170),
                BackColor = HeaderBg
            };

            header.Paint += (s, e) =>
            {
                using var brush = new SolidBrush(AccentColor);
                e.Graphics.FillRectangle(brush, 0, header.Height - 3, header.Width, 3);
            };

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
                Font      = new Font("Segoe UI", 18, FontStyle.Bold),
                ForeColor = Color.White,
                BackColor = Color.Transparent,
                Location  = new Point(10, 96),
                Size      = new Size(440, 42),
                TextAlign = ContentAlignment.MiddleCenter
            };

            var lblVer = new Label
            {
                Text      = $"Versión  {version}",
                Font      = new Font("Segoe UI", 8.5f),
                ForeColor = Color.FromArgb(148, 163, 184),
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
                BackColor = BodyBg
            };

            var lblDesc = new Label
            {
                Text      = "Servicio de impresión corporativa",
                Font      = new Font("Segoe UI", 9, FontStyle.Italic),
                ForeColor = MutedColor,
                Location  = new Point(30, 16),
                AutoSize  = true
            };

            body.Controls.Add(lblDesc);

            body.Paint += (s, e) =>
            {
                using var pen = new Pen(DividerColor, 1);
                e.Graphics.DrawLine(pen, 30, 42, 430, 42);
            };

            AddRow(body, "Usuario",  currentUser,                                    54);
            AddRow(body, "Iniciado", processStart.ToString("yyyy-MM-dd  HH:mm:ss"),  90);

            var lblCopyright = new Label
            {
                Text      = "© 2026 Robles.AI",
                Font      = new Font("Segoe UI", 8.5f),
                ForeColor = MutedColor,
                Location  = new Point(30, 134),
                Size      = new Size(400, 20),
                TextAlign = ContentAlignment.MiddleLeft
            };
            var lblLegal = new Label
            {
                Text      = "Inversiones On Line S.A.C.",
                Font      = new Font("Segoe UI", 8.5f),
                ForeColor = MutedColor,
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
                BackColor = FooterBg
            };

            footer.Paint += (s, e) =>
            {
                using var pen = new Pen(DividerColor, 1);
                e.Graphics.DrawLine(pen, 0, 0, footer.Width, 0);
            };

            var btnClose = new StyledButton
            {
                Text     = "Cerrar",
                Size     = new Size(104, 36),
                Location = new Point(460 - 104 - 28, 14)
            };
            btnClose.Click += (s, e) => Close();

            footer.Controls.Add(btnClose);
            Controls.AddRange(new Control[] { header, body, footer });
            AcceptButton = btnClose;
        }

        private static void AddRow(Panel parent, string label, string value, int y)
        {
            var lblKey = new Label
            {
                Text      = label,
                Font      = new Font("Segoe UI", 9, FontStyle.Bold),
                ForeColor = MutedColor,
                Location  = new Point(30, y),
                Size      = new Size(90, 26),
                TextAlign = ContentAlignment.MiddleLeft
            };
            var lblVal = new Label
            {
                Text      = value,
                Font      = new Font("Segoe UI", 9),
                ForeColor = TextColor,
                Location  = new Point(128, y),
                Size      = new Size(302, 26),
                TextAlign = ContentAlignment.MiddleLeft
            };
            parent.Controls.Add(lblKey);
            parent.Controls.Add(lblVal);

            int capturedY = y;
            parent.Paint += (s, e) =>
            {
                using var pen = new Pen(DividerColor, 1);
                e.Graphics.DrawLine(pen, 30, capturedY + 30, 430, capturedY + 30);
            };
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

        private sealed class StyledButton : Button
        {
            private bool _hover;

            public StyledButton()
            {
                FlatStyle = FlatStyle.Flat;
                FlatAppearance.BorderSize = 0;
                Font      = new Font("Segoe UI", 9, FontStyle.Bold);
                ForeColor = Color.White;
                Cursor    = Cursors.Hand;
                UseVisualStyleBackColor = false;
            }

            protected override void OnMouseEnter(EventArgs e) { _hover = true;  Invalidate(); base.OnMouseEnter(e); }
            protected override void OnMouseLeave(EventArgs e) { _hover = false; Invalidate(); base.OnMouseLeave(e); }

            protected override void OnPaint(PaintEventArgs e)
            {
                var g = e.Graphics;
                g.SmoothingMode = SmoothingMode.AntiAlias;
                var rect = new Rectangle(0, 0, Width - 1, Height - 1);

                var bg = _hover ? Color.FromArgb(79, 70, 229) : Color.FromArgb(99, 102, 241);
                using (var brush = new SolidBrush(bg))
                using (var path  = RoundedPath(rect, 7))
                    g.FillPath(brush, path);

                TextRenderer.DrawText(g, Text, Font, rect, Color.White,
                    TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
            }

            private static GraphicsPath RoundedPath(Rectangle r, int radius)
            {
                int d    = radius * 2;
                var path = new GraphicsPath();
                path.AddArc(r.X,         r.Y,          d, d, 180, 90);
                path.AddArc(r.Right - d, r.Y,          d, d, 270, 90);
                path.AddArc(r.Right - d, r.Bottom - d, d, d, 0,   90);
                path.AddArc(r.X,         r.Bottom - d, d, d, 90,  90);
                path.CloseFigure();
                return path;
            }
        }
    }
}
