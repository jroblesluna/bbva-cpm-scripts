using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Net.Http;
using System.Windows.Forms;
using AlwaysPrint.Shared.Logging;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.Forms
{
    public sealed class MyPrintersForm : Form
    {
        // ── Palette ──────────────────────────────────────────────────────────
        private static readonly Color CHeaderBg   = Color.FromArgb( 27,  46,  75);
        private static readonly Color CHeaderFg   = Color.White;
        private static readonly Color CHeaderSub  = Color.FromArgb(175, 198, 220);
        private static readonly Color CBodyBg     = Color.FromArgb(245, 247, 250);
        private static readonly Color CRowEven    = Color.White;
        private static readonly Color CRowOdd     = Color.FromArgb(248, 249, 251);
        private static readonly Color CRowSel     = Color.FromArgb(219, 234, 254);
        private static readonly Color CRowSelFg   = Color.FromArgb( 15,  40,  80);
        private static readonly Color CFavBg      = Color.FromArgb(251, 191,  36);
        private static readonly Color CFavFg      = Color.FromArgb(120,  53,  15);
        private static readonly Color CDefBg      = Color.FromArgb( 99, 102, 241);
        private static readonly Color CDefFg      = Color.White;
        private static readonly Color CActionsBg  = Color.FromArgb(236, 239, 244);
        private static readonly Color CSep        = Color.FromArgb(210, 218, 228);
        private static readonly Color CPrimary    = Color.FromArgb(  0, 120, 212);

        // ── Fields ───────────────────────────────────────────────────────────
        private readonly string     _cloudApiUrl;
        private readonly string     _workstationId;
        private readonly HttpClient _http;

        private Panel    _pnlHeader = null!;
        private Label    _lblTitle = null!;
        private Label    _lblVlan = null!;
        private ListView _listView = null!;
        private Panel    _pnlActions = null!;
        private APButton _btnFavorite = null!;
        private APButton _btnRefresh = null!;
        private APButton _btnClose = null!;
        private Panel    _pnlStatus = null!;
        private Label    _lblStatusIcon = null!;
        private Label    _lblStatus = null!;

        private List<PrinterInfo> _printers = new List<PrinterInfo>();
        private string? _favoritePrinterId;
        private string? _defaultPrinterId;

        // ── Constructor ──────────────────────────────────────────────────────
        public MyPrintersForm(string cloudApiUrl, string workstationId, HttpClient http)
        {
            _cloudApiUrl   = cloudApiUrl;
            _workstationId = workstationId;
            _http          = http;
            InitializeComponents();
            LoadPrinters();
        }

        // ── UI Construction ──────────────────────────────────────────────────
        private void InitializeComponents()
        {
            Text            = "Mis Impresoras – Contingencia";
            ClientSize      = new Size(700, 510);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox     = false;
            MinimizeBox     = false;
            StartPosition   = FormStartPosition.CenterScreen;
            ShowInTaskbar   = false;
            BackColor       = CBodyBg;
            Font            = new Font("Segoe UI", 9f);

            // ── Header ───────────────────────────────────────────────────────
            _pnlHeader = new Panel
            {
                Location  = new Point(0, 0),
                Size      = new Size(700, 75),
                BackColor = CHeaderBg
            };
            _lblTitle = new Label
            {
                Text      = "🖨  Mis Impresoras",
                ForeColor = CHeaderFg,
                Font      = new Font("Segoe UI", 14f, FontStyle.Bold),
                AutoSize  = true,
                Location  = new Point(20, 11),
                BackColor = Color.Transparent
            };
            _lblVlan = new Label
            {
                Text      = "Cargando información de red…",
                ForeColor = CHeaderSub,
                Font      = new Font("Segoe UI", 9f),
                AutoSize  = true,
                Location  = new Point(22, 44),
                BackColor = Color.Transparent
            };
            _pnlHeader.Controls.Add(_lblTitle);
            _pnlHeader.Controls.Add(_lblVlan);

            // ── ListView (1-px border wrapper) ───────────────────────────────
            _listView = new ListView
            {
                Location      = new Point(1, 1),
                Size          = new Size(668, 298),
                View          = View.Details,
                FullRowSelect  = true,
                GridLines      = false,
                MultiSelect    = false,
                OwnerDraw      = true,
                Font           = new Font("Segoe UI", 9f),
                BorderStyle    = BorderStyle.None,
                BackColor      = Color.White,
                HeaderStyle    = ColumnHeaderStyle.Nonclickable
            };
            _listView.Columns.Add("Nombre",       200);
            _listView.Columns.Add("IP : Puerto",  140);
            _listView.Columns.Add("Modelo",       130);
            _listView.Columns.Add("Ubicación",    110);
            _listView.Columns.Add("Estado",        82);
            _listView.DrawColumnHeader     += OnDrawColumnHeader;
            _listView.DrawItem             += (_, e) => e.DrawDefault = false;
            _listView.DrawSubItem          += OnDrawSubItem;
            _listView.SelectedIndexChanged += OnSelectionChanged;

            var listWrapper = new Panel
            {
                Location  = new Point(15, 90),
                Size      = new Size(670, 300),
                BackColor = CSep
            };
            listWrapper.Controls.Add(_listView);

            // ── Separator 1 ──────────────────────────────────────────────────
            var sep1 = new Panel { Location = new Point(0, 403), Size = new Size(700, 1), BackColor = CSep };

            // ── Actions panel ─────────────────────────────────────────────────
            _pnlActions = new Panel
            {
                Location  = new Point(0, 404),
                Size      = new Size(700, 48),
                BackColor = CActionsBg
            };

            _btnFavorite = new APButton
            {
                Text      = "⭐  Establecer favorita",
                Location  = new Point(16, 8),
                Size      = new Size(190, 32),
                Enabled   = false,
                BackColor = CPrimary,
                ForeColor = Color.White,
                Font      = new Font("Segoe UI", 9f, FontStyle.Bold)
            };
            _btnFavorite.Click += OnFavoriteClick;

            _btnRefresh = new APButton
            {
                Text       = "↺",
                Location   = new Point(590, 8),
                Size       = new Size(40, 32),
                BackColor  = Color.White,
                ForeColor  = Color.FromArgb(60, 75, 95),
                Font       = new Font("Segoe UI", 14f),
                ShowBorder = true
            };
            _btnRefresh.Click += (_, __) => LoadPrinters();

            _btnClose = new APButton
            {
                Text         = "Cerrar",
                Location     = new Point(640, 8),
                Size         = new Size(58, 32),
                DialogResult = DialogResult.OK,
                BackColor    = Color.White,
                ForeColor    = Color.FromArgb(60, 75, 95),
                Font         = new Font("Segoe UI", 9f),
                ShowBorder   = true
            };
            _pnlActions.Controls.AddRange(new Control[]
            {
                _btnFavorite, _btnRefresh, _btnClose
            });

            // ── Separator 2 ──────────────────────────────────────────────────
            var sep2 = new Panel { Location = new Point(0, 452), Size = new Size(700, 1), BackColor = CSep };

            // ── Status panel ─────────────────────────────────────────────────
            _pnlStatus = new Panel
            {
                Location  = new Point(0, 453),
                Size      = new Size(700, 57),
                BackColor = Color.White
            };
            _lblStatusIcon = new Label
            {
                Text      = "",
                Location  = new Point(16, 14),
                Size      = new Size(26, 26),
                Font      = new Font("Segoe UI", 12f),
                BackColor = Color.Transparent
            };
            _lblStatus = new Label
            {
                Text      = "",
                Location  = new Point(46, 10),
                Size      = new Size(640, 40),
                Font      = new Font("Segoe UI", 9f),
                ForeColor = SystemColors.GrayText,
                BackColor = Color.Transparent
            };
            _pnlStatus.Controls.Add(_lblStatusIcon);
            _pnlStatus.Controls.Add(_lblStatus);

            Controls.AddRange(new Control[]
            {
                _pnlHeader, listWrapper, sep1, _pnlActions, sep2, _pnlStatus
            });
            AcceptButton = _btnClose;
        }

        // ── Owner-draw ───────────────────────────────────────────────────────
        private void OnDrawColumnHeader(object? sender, DrawListViewColumnHeaderEventArgs e)
        {
            using var bg = new SolidBrush(Color.FromArgb(241, 244, 248));
            e.Graphics.FillRectangle(bg, e.Bounds);

            using var sep = new Pen(CSep);
            e.Graphics.DrawLine(sep,
                e.Bounds.Left,  e.Bounds.Bottom - 1,
                e.Bounds.Right, e.Bounds.Bottom - 1);

            var tr  = new RectangleF(e.Bounds.X + 10, e.Bounds.Y, e.Bounds.Width - 12, e.Bounds.Height);
            var fmt = new StringFormat { LineAlignment = StringAlignment.Center, Trimming = StringTrimming.EllipsisCharacter };
            using var fg   = new SolidBrush(Color.FromArgb(55, 70, 90));
            using var font = new Font("Segoe UI", 8.5f, FontStyle.Bold);
            e.Graphics.DrawString(e.Header?.Text ?? "", font, fg, tr, fmt);
        }

        private void OnDrawSubItem(object? sender, DrawListViewSubItemEventArgs e)
        {
            if (e.Item == null || e.SubItem == null) return;
            var printer  = e.Item.Tag as PrinterInfo;
            bool sel     = e.Item.Selected;
            bool odd     = e.ItemIndex % 2 == 1;

            var bgColor = sel ? CRowSel : (odd ? CRowOdd : CRowEven);
            using (var brush = new SolidBrush(bgColor))
                e.Graphics.FillRectangle(brush, e.Bounds);

            using (var rowSep = new Pen(Color.FromArgb(232, 236, 242)))
                e.Graphics.DrawLine(rowSep,
                    e.Bounds.Left,  e.Bounds.Bottom - 1,
                    e.Bounds.Right, e.Bounds.Bottom - 1);

            if (e.ColumnIndex == 4)
            {
                DrawBadge(e.Graphics, e.Bounds, printer);
                return;
            }

            var fgColor = sel ? CRowSelFg : Color.FromArgb(35, 45, 60);
            var fmt     = new StringFormat { LineAlignment = StringAlignment.Center, Trimming = StringTrimming.EllipsisCharacter };
            var tr      = new RectangleF(e.Bounds.X + 10, e.Bounds.Y, e.Bounds.Width - 14, e.Bounds.Height);

            using var fgBrush = new SolidBrush(fgColor);
            if (e.ColumnIndex == 0)
            {
                using var bold = new Font("Segoe UI", 9f, FontStyle.Bold);
                e.Graphics.DrawString(e.SubItem.Text, bold, fgBrush, tr, fmt);
            }
            else
            {
                using var reg = new Font("Segoe UI", 9f);
                e.Graphics.DrawString(e.SubItem.Text, reg, fgBrush, tr, fmt);
            }
        }

        private static void DrawBadge(Graphics g, Rectangle bounds, PrinterInfo? p)
        {
            if (p == null) return;
            string? label = null;
            Color bg = Color.Transparent, fg = Color.Transparent;

            if (p.IsFavorite)     { label = "⭐ Favorita"; bg = CFavBg; fg = CFavFg; }
            else if (p.IsDefault) { label = "📌 Default";  bg = CDefBg; fg = CDefFg; }
            if (label == null) return;

            using var font = new Font("Segoe UI", 7.5f, FontStyle.Bold);
            var sz  = g.MeasureString(label, font);
            int px = 8, py = 3;
            int bw  = (int)sz.Width + px * 2;
            int bh  = (int)sz.Height + py * 2;
            int bx  = bounds.X + (bounds.Width  - bw) / 2;
            int by  = bounds.Y + (bounds.Height - bh) / 2;
            var rc  = new Rectangle(bx, by, bw, bh);

            g.SmoothingMode = SmoothingMode.AntiAlias;
            using var path    = RoundedPath(rc, 8);
            using var bgBrush = new SolidBrush(bg);
            g.FillPath(bgBrush, path);
            using var fgBrush = new SolidBrush(fg);
            var fmt = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center };
            g.DrawString(label, font, fgBrush, rc, fmt);
            g.SmoothingMode = SmoothingMode.Default;
        }

        private static GraphicsPath RoundedPath(Rectangle r, int rad)
        {
            var p = new GraphicsPath();
            p.AddArc(r.X,               r.Y,                rad * 2, rad * 2, 180, 90);
            p.AddArc(r.Right - rad * 2, r.Y,                rad * 2, rad * 2, 270, 90);
            p.AddArc(r.Right - rad * 2, r.Bottom - rad * 2, rad * 2, rad * 2,   0, 90);
            p.AddArc(r.X,               r.Bottom - rad * 2, rad * 2, rad * 2,  90, 90);
            p.CloseFigure();
            return p;
        }

        // ── Data loading ─────────────────────────────────────────────────────
        private async void LoadPrinters()
        {
            try
            {
                _listView.Items.Clear();
                SetStatus("⏳", "Consultando impresoras disponibles…", SystemColors.GrayText);

                var url      = $"{_cloudApiUrl}/api/v1/devices/workstation/{_workstationId}/my-printers";
                var response = await _http.GetAsync(url);

                if (!response.IsSuccessStatusCode)
                {
                    var body = await response.Content.ReadAsStringAsync();
                    SetStatus("❌", $"Error al obtener impresoras: {response.StatusCode}", Color.Crimson);
                    AlwaysPrintLogger.WriteTrayError(
                        $"MyPrintersForm: error HTTP {response.StatusCode}. {body}");
                    return;
                }

                var json = await response.Content.ReadAsStringAsync();
                var data = JObject.Parse(json);

                _favoritePrinterId = data["favorite_printer_id"]?.ToString();
                _defaultPrinterId  = data["default_printer_id"]?.ToString();
                var vlanName = data["vlan_name"]?.ToString();
                var total    = data["total"]?.ToObject<int>() ?? 0;

                _lblVlan.Text = vlanName != null
                    ? $"VLAN: {vlanName}  ·  {total} impresora(s) disponible(s)"
                    : $"Sin VLAN asignada  ·  {total} impresora(s) de la organización";

                _printers.Clear();
                if (data["printers"] is JArray arr)
                {
                    foreach (var item in arr)
                        _printers.Add(new PrinterInfo
                        {
                            Id        = item["id"]?.ToString()             ?? "",
                            Name      = item["name"]?.ToString()           ?? "",
                            IpAddress = item["ip_address"]?.ToString()     ?? "",
                            Port      = item["port"]?.ToObject<int>()      ?? 9100,
                            Model     = item["model"]?.ToString()          ?? "",
                            Location  = item["location"]?.ToString()       ?? "",
                            IsFavorite = item["is_favorite"]?.ToObject<bool>() ?? false,
                            IsDefault  = item["is_default"]?.ToObject<bool>()  ?? false,
                        });
                }

                PopulateListView();

                if (total == 0)
                {
                    SetStatus("⚠️", "No hay impresoras configuradas para contingencia en su red.", Color.OrangeRed);
                }
                else
                {
                    var favName = _printers.Find(p => p.IsFavorite)?.Name;
                    var defName = _printers.Find(p => p.IsDefault)?.Name;
                    if (favName != null)
                        SetStatus("✅", $"Favorita: {favName} — se usará primero en contingencia.", Color.FromArgb(5, 140, 90));
                    else
                        SetStatus("ℹ️", $"Sin favorita. En contingencia se usará: {defName ?? "ninguna"} (menor IP).", SystemColors.GrayText);
                }

            }
            catch (Exception ex)
            {
                SetStatus("❌", $"Error de conexión: {ex.Message}", Color.Crimson);
                AlwaysPrintLogger.WriteTrayError(
                    $"MyPrintersForm: excepción — {ex.GetType().Name}: {ex.Message}");
            }
        }

        private void SetStatus(string icon, string text, Color color)
        {
            _lblStatusIcon.Text  = icon;
            _lblStatus.Text      = text;
            _lblStatus.ForeColor = color;
        }

        private void PopulateListView()
        {
            _listView.Items.Clear();
            foreach (var printer in _printers)
            {
                var item = new ListViewItem(new[]
                {
                    printer.Name,
                    $"{printer.IpAddress}:{printer.Port}",
                    printer.Model,
                    printer.Location,
                    ""
                });
                item.Tag = printer;
                _listView.Items.Add(item);
            }
        }

        private void OnSelectionChanged(object? sender, EventArgs e)
        {
            var sel = _listView.SelectedItems.Count > 0
                ? _listView.SelectedItems[0].Tag as PrinterInfo
                : null;

            if (sel == null)
            {
                _btnFavorite.Enabled    = false;
                _btnFavorite.Text       = "⭐  Establecer favorita";
                _btnFavorite.BackColor  = CPrimary;
                _btnFavorite.ForeColor  = Color.White;
                _btnFavorite.Font       = new Font("Segoe UI", 9f, FontStyle.Bold);
                _btnFavorite.ShowBorder = false;
            }
            else if (sel.IsFavorite)
            {
                _btnFavorite.Enabled    = true;
                _btnFavorite.Text       = "✕  Quitar favorita";
                _btnFavorite.BackColor  = Color.White;
                _btnFavorite.ForeColor  = Color.FromArgb(60, 75, 95);
                _btnFavorite.Font       = new Font("Segoe UI", 9f);
                _btnFavorite.ShowBorder = true;
            }
            else
            {
                _btnFavorite.Enabled    = true;
                _btnFavorite.Text       = "⭐  Establecer favorita";
                _btnFavorite.BackColor  = CPrimary;
                _btnFavorite.ForeColor  = Color.White;
                _btnFavorite.Font       = new Font("Segoe UI", 9f, FontStyle.Bold);
                _btnFavorite.ShowBorder = false;
            }
            _btnFavorite.Invalidate();
        }

        private async void OnFavoriteClick(object? sender, EventArgs e)
        {
            var sel = _listView.SelectedItems.Count > 0
                ? _listView.SelectedItems[0].Tag as PrinterInfo
                : null;
            if (sel == null) return;

            _btnFavorite.Enabled = false;
            try
            {
                var url = $"{_cloudApiUrl}/api/v1/devices/workstation/{_workstationId}/favorite-printer";
                StringContent content;

                if (sel.IsFavorite)
                {
                    SetStatus("⏳", "Quitando impresora favorita…", SystemColors.GrayText);
                    content = new StringContent(
                        JsonConvert.SerializeObject(new { device_id = (string?)null }),
                        System.Text.Encoding.UTF8, "application/json");
                }
                else
                {
                    SetStatus("⏳", $"Estableciendo {sel.Name} como favorita…", SystemColors.GrayText);
                    content = new StringContent(
                        JsonConvert.SerializeObject(new { device_id = sel.Id }),
                        System.Text.Encoding.UTF8, "application/json");
                }

                var response = await _http.PutAsync(url, content);
                if (response.IsSuccessStatusCode)
                {
                    AlwaysPrintLogger.WriteTrayInfo(sel.IsFavorite
                        ? "MyPrintersForm: favorita eliminada."
                        : $"MyPrintersForm: favorita → {sel.Name} ({sel.IpAddress})");
                    LoadPrinters();
                }
                else
                    SetStatus("❌", $"Error: {response.StatusCode}", Color.Crimson);
            }
            catch (Exception ex) { SetStatus("❌", $"Error: {ex.Message}", Color.Crimson); }
        }

        // ── Data model ───────────────────────────────────────────────────────
        private sealed class PrinterInfo
        {
            public string Id        { get; set; } = "";
            public string Name      { get; set; } = "";
            public string IpAddress { get; set; } = "";
            public int    Port      { get; set; } = 9100;
            public string Model     { get; set; } = "";
            public string Location  { get; set; } = "";
            public bool   IsFavorite { get; set; }
            public bool   IsDefault  { get; set; }
        }
    }

    // ── Custom button with rounded corners + hover ────────────────────────────
    internal sealed class APButton : Button
    {
        private bool _hovered;
        public bool ShowBorder { get; set; }

        public APButton()
        {
            SetStyle(
                ControlStyles.UserPaint |
                ControlStyles.AllPaintingInWmPaint |
                ControlStyles.OptimizedDoubleBuffer, true);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
        }

        protected override void OnMouseEnter(EventArgs e) { _hovered = true;  Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { _hovered = false; Invalidate(); base.OnMouseLeave(e); }

        protected override void OnPaint(PaintEventArgs e)
        {
            var g  = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;

            Color bg;
            if (!Enabled)
                bg = Color.FromArgb(218, 222, 230);
            else if (_hovered)
                bg = Color.FromArgb(
                    Math.Max(0, Math.Min(255, BackColor.R - 18)),
                    Math.Max(0, Math.Min(255, BackColor.G - 18)),
                    Math.Max(0, Math.Min(255, BackColor.B - 18)));
            else
                bg = BackColor;

            var rect = new Rectangle(0, 0, Width - 1, Height - 1);
            using var path  = RoundedPath(rect, 5);
            using var brush = new SolidBrush(bg);
            g.FillPath(brush, path);

            if (ShowBorder)
            {
                using var pen = new Pen(Color.FromArgb(180, 190, 205));
                g.DrawPath(pen, path);
            }

            var fg  = Enabled ? ForeColor : Color.FromArgb(140, 150, 165);
            var fmt = new StringFormat
            {
                Alignment     = StringAlignment.Center,
                LineAlignment = StringAlignment.Center,
                FormatFlags   = StringFormatFlags.NoWrap,
                Trimming      = StringTrimming.EllipsisCharacter
            };
            using var fgBrush = new SolidBrush(fg);
            g.DrawString(Text, Font, fgBrush, new RectangleF(0, 0, Width, Height), fmt);
        }

        private static GraphicsPath RoundedPath(Rectangle r, int rad)
        {
            var p = new GraphicsPath();
            p.AddArc(r.X,               r.Y,                rad * 2, rad * 2, 180, 90);
            p.AddArc(r.Right - rad * 2, r.Y,                rad * 2, rad * 2, 270, 90);
            p.AddArc(r.Right - rad * 2, r.Bottom - rad * 2, rad * 2, rad * 2,   0, 90);
            p.AddArc(r.X,               r.Bottom - rad * 2, rad * 2, rad * 2,  90, 90);
            p.CloseFigure();
            return p;
        }
    }
}
