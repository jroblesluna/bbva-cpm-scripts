using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace AlwaysPrintTray.Forms
{
    /// <summary>
    /// Paleta de colores y componentes reutilizables para la imagen corporativa AlwaysPrint.
    /// Todos los formularios del Tray deben usar estos colores y el botón AppButton.
    /// </summary>
    internal static class AppTheme
    {
        // === PALETA CORPORATIVA ===

        /// <summary>Fondo de header oscuro (slate-900).</summary>
        public static readonly Color HeaderBg = Color.FromArgb(15, 23, 42);

        /// <summary>Color de acento principal (indigo-500).</summary>
        public static readonly Color Accent = Color.FromArgb(99, 102, 241);

        /// <summary>Acento hover (indigo-600).</summary>
        public static readonly Color AccentHover = Color.FromArgb(79, 70, 229);

        /// <summary>Fondo de body claro (slate-50).</summary>
        public static readonly Color BodyBg = Color.FromArgb(248, 250, 252);

        /// <summary>Fondo de footer/actions (slate-100).</summary>
        public static readonly Color FooterBg = Color.FromArgb(241, 245, 249);

        /// <summary>Texto principal oscuro (slate-800).</summary>
        public static readonly Color TextPrimary = Color.FromArgb(30, 41, 59);

        /// <summary>Texto secundario/muted (slate-500).</summary>
        public static readonly Color TextMuted = Color.FromArgb(100, 116, 139);

        /// <summary>Texto sobre fondo oscuro.</summary>
        public static readonly Color TextOnDark = Color.White;

        /// <summary>Texto subtitle sobre header (slate-400).</summary>
        public static readonly Color TextSubtitle = Color.FromArgb(148, 163, 184);

        /// <summary>Divisor/separador (slate-200).</summary>
        public static readonly Color Divider = Color.FromArgb(226, 232, 240);

        /// <summary>Borde de inputs y paneles (slate-300).</summary>
        public static readonly Color Border = Color.FromArgb(203, 213, 225);

        /// <summary>Fondo de filas alternas pares.</summary>
        public static readonly Color RowEven = Color.White;

        /// <summary>Fondo de filas alternas impares.</summary>
        public static readonly Color RowOdd = Color.FromArgb(248, 249, 251);

        /// <summary>Fondo de fila seleccionada (blue-100).</summary>
        public static readonly Color RowSelected = Color.FromArgb(219, 234, 254);

        /// <summary>Texto en fila seleccionada.</summary>
        public static readonly Color RowSelectedText = Color.FromArgb(15, 40, 80);

        /// <summary>Badge favorita (amber-300).</summary>
        public static readonly Color BadgeFavBg = Color.FromArgb(251, 191, 36);
        public static readonly Color BadgeFavFg = Color.FromArgb(120, 53, 15);

        /// <summary>Badge default (indigo-500).</summary>
        public static readonly Color BadgeDefBg = Accent;
        public static readonly Color BadgeDefFg = Color.White;

        /// <summary>Fondo de botón deshabilitado.</summary>
        public static readonly Color DisabledBg = Color.FromArgb(218, 222, 230);
        public static readonly Color DisabledFg = Color.FromArgb(140, 150, 165);

        // === FUENTES ===

        public static readonly Font FontRegular = new Font("Segoe UI", 9f);
        public static readonly Font FontBold = new Font("Segoe UI", 9f, FontStyle.Bold);
        public static readonly Font FontSmall = new Font("Segoe UI", 8.5f);
        public static readonly Font FontTitle = new Font("Segoe UI", 14f, FontStyle.Bold);
        public static readonly Font FontHeading = new Font("Segoe UI", 18f, FontStyle.Bold);

        // === UTILIDADES ===

        /// <summary>
        /// Crea un GraphicsPath con esquinas redondeadas.
        /// </summary>
        public static GraphicsPath RoundedPath(Rectangle r, int radius)
        {
            int d = radius * 2;
            var path = new GraphicsPath();
            path.AddArc(r.X, r.Y, d, d, 180, 90);
            path.AddArc(r.Right - d, r.Y, d, d, 270, 90);
            path.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
            path.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
            path.CloseFigure();
            return path;
        }

        /// <summary>
        /// Aplica estilos base corporativos a un Form (fuente, fondo, borde).
        /// </summary>
        public static void ApplyFormStyle(Form form)
        {
            form.Font            = FontRegular;
            form.BackColor       = BodyBg;
            form.FormBorderStyle = FormBorderStyle.FixedDialog;
            form.MaximizeBox     = false;
            form.MinimizeBox     = false;
            form.StartPosition   = FormStartPosition.CenterScreen;
            form.ShowInTaskbar   = false;
        }

        /// <summary>
        /// Pinta una línea divisora horizontal en el handler Paint de un Panel.
        /// </summary>
        public static void DrawDivider(Graphics g, int x1, int y, int x2)
        {
            using var pen = new Pen(Divider, 1);
            g.DrawLine(pen, x1, y, x2, y);
        }

        /// <summary>
        /// Pinta la barra de acento inferior en un header panel.
        /// </summary>
        public static void DrawHeaderAccent(Graphics g, int width, int headerHeight)
        {
            using var brush = new SolidBrush(Accent);
            g.FillRectangle(brush, 0, headerHeight - 3, width, 3);
        }
    }

    // =========================================================================
    // BOTÓN CORPORATIVO REUTILIZABLE
    // =========================================================================

    /// <summary>
    /// Botón con estilo corporativo AlwaysPrint: fondo redondeado, hover, sin esquinas negras.
    /// Soporta modo primario (fondo accent) y secundario (fondo blanco con borde).
    /// </summary>
    internal sealed class AppButton : Button
    {
        private bool _hovered;

        /// <summary>Si es true, se dibuja un borde alrededor del botón (modo secundario).</summary>
        public bool ShowBorder { get; set; }

        /// <summary>Si es true, usa el color de acento como fondo (modo primario). Por defecto true.</summary>
        public bool IsPrimary { get; set; } = true;

        public AppButton()
        {
            SetStyle(
                ControlStyles.UserPaint |
                ControlStyles.AllPaintingInWmPaint |
                ControlStyles.OptimizedDoubleBuffer, true);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            Font = AppTheme.FontBold;
            ForeColor = Color.White;
            Cursor = Cursors.Hand;
        }

        protected override void OnMouseEnter(EventArgs e) { _hovered = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { _hovered = false; Invalidate(); base.OnMouseLeave(e); }

        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            var rect = new Rectangle(0, 0, Width - 1, Height - 1);

            // Limpiar fondo con color del padre para evitar esquinas negras
            var parentBg = Parent?.BackColor ?? AppTheme.BodyBg;
            using (var clearBrush = new SolidBrush(parentBg))
                g.FillRectangle(clearBrush, ClientRectangle);

            // Determinar color de fondo según estado
            Color bg;
            if (!Enabled)
            {
                bg = AppTheme.DisabledBg;
            }
            else if (IsPrimary)
            {
                bg = _hovered ? AppTheme.AccentHover : AppTheme.Accent;
            }
            else
            {
                bg = _hovered
                    ? Color.FromArgb(241, 245, 249)
                    : Color.White;
            }

            using (var brush = new SolidBrush(bg))
            using (var path = AppTheme.RoundedPath(rect, 6))
                g.FillPath(brush, path);

            // Borde si es secundario o ShowBorder
            if (ShowBorder || !IsPrimary)
            {
                using var pen = new Pen(AppTheme.Border);
                using var path = AppTheme.RoundedPath(rect, 6);
                g.DrawPath(pen, path);
            }

            // Texto
            var fg = !Enabled ? AppTheme.DisabledFg
                   : IsPrimary ? Color.White
                   : AppTheme.TextPrimary;

            TextRenderer.DrawText(g, Text, Font, rect, fg,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
        }
    }
}
