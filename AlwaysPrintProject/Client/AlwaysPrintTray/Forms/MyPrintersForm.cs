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
        // ── Fields ───────────────────────────────────────────────────────────
        private readonly string     _cloudApiUrl;
        private readonly string     _workstationId;
        private readonly HttpClient _http;

        private Panel    _pnlHeader = null!;
        private Label    _lblTitle = null!;
        private Label    _lblVlan = null!;
        private ListView _listView = null!;
        private Panel    _pnlActions = null!;
        private AppButton _btnFavorite = null!;
        private AppButton _btnRefresh = null!;
        private AppButton _btnClose = null!;
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
            Text       = "Mis Impresoras – Contingencia";
            ClientSize = new Size(700, 510);
            AppTheme.ApplyFormStyle(this);

            // ── Header ───────────────────────────────────────────────────────
            _pnlHeader = new Panel
            {
                Location  = new Point(0, 0),
                Size      = new Size(700, 75),
                BackColor = AppTheme.HeaderBg
            };
            _pnlHeader.Paint += (s, e) => AppTheme.DrawHeaderAccent(e.Graphics, 700, 75);

            _lblTitle = new Label
            {
                Text      = "🖨  Mis Impresoras",
                ForeColor = AppTheme.TextOnDark,
                Font      = AppTheme.FontTitle,
                AutoSize  = true,
                Location  = new Point(20, 11),
                BackColor = Color.Transparent
            };
            _lblVlan = new Label
            {
                Text      = "Cargando información de red…",
                ForeColor = AppTheme.TextSubtitle,
                Font      = AppTheme.FontRegular,
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
                Font           = AppTheme.FontRegular,
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
                BackColor = AppTheme.Border
            };
            listWrapper.Controls.Add(_listView);

            // ── Separator 1 ──────────────────────────────────────────────────
            var sep1 = new Panel { Location = new Point(0, 403), Size = new Size(700, 1), BackColor = AppTheme.Divider };

            // ── Actions panel ─────────────────────────────────────────────────
            _pnlActions = new Panel
            {
                Location  = new Point(0, 404),
                Size      = new Size(700, 48),
                BackColor = AppTheme.FooterBg
            };

            _btnFavorite = new AppButton
            {
                Text      = "⭐  Establecer favorita",
                Location  = new Point(16, 8),
                Size      = new Size(190, 32),
                Enabled   = false,
                IsPrimary = true
            };
            _btnFavorite.Click += OnFavoriteClick;

            _btnRefresh = new AppButton
            {
                Text      = "↺",
                Location  = new Point(590, 8),
                Size      = new Size(40, 32),
                IsPrimary = false,
                Font      = new Font("Segoe UI", 14f)
            };
            _btnRefresh.Click += (_, __) => LoadPrinters();

            _btnClose = new AppButton
            {
                Text         = "Cerrar",
                Location     = new Point(640, 8),
                Size         = new Size(58, 32),
                IsPrimary    = false,
                DialogResult = DialogResult.OK
            };
            _pnlActions.Controls.AddRange(new Control[]
            {
                _btnFavorite, _btnRefresh, _btnClose
            });

            // ── Separator 2 ──────────────────────────────────────────────────
            var sep2 = new Panel { Location = new Point(0, 452), Size = new Size(700, 1), BackColor = AppTheme.Divider };

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
                Font      = AppTheme.FontRegular,
                ForeColor = AppTheme.TextMuted,
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
            using var bg = new SolidBrush(AppTheme.FooterBg);
            e.Graphics.FillRectangle(bg, e.Bounds);

            using var sep = new Pen(AppTheme.Divider);
            e.Graphics.DrawLine(sep,
                e.Bounds.Left,  e.Bounds.Bottom - 1,
                e.Bounds.Right, e.Bounds.Bottom - 1);

            var tr  = new RectangleF(e.Bounds.X + 10, e.Bounds.Y, e.Bounds.Width - 12, e.Bounds.Height);
            var fmt = new StringFormat { LineAlignment = StringAlignment.Center, Trimming = StringTrimming.EllipsisCharacter };
            using var fg   = new SolidBrush(AppTheme.TextMuted);
            using var font = new Font("Segoe UI", 8.5f, FontStyle.Bold);
            e.Graphics.DrawString(e.Header?.Text ?? "", font, fg, tr, fmt);
        }

        private void OnDrawSubItem(object? sender, DrawListViewSubItemEventArgs e)
        {
            if (e.Item == null || e.SubItem == null) return;
            var printer  = e.Item.Tag as PrinterInfo;
            bool sel     = e.Item.Selected;
            bool odd     = e.ItemIndex % 2 == 1;

            var bgColor = sel ? AppTheme.RowSelected : (odd ? AppTheme.RowOdd : AppTheme.RowEven);
            using (var brush = new SolidBrush(bgColor))
                e.Graphics.FillRectangle(brush, e.Bounds);

            using (var rowSep = new Pen(AppTheme.Divider))
                e.Graphics.DrawLine(rowSep,
                    e.Bounds.Left,  e.Bounds.Bottom - 1,
                    e.Bounds.Right, e.Bounds.Bottom - 1);

            if (e.ColumnIndex == 4)
            {
                DrawBadge(e.Graphics, e.Bounds, printer);
                return;
            }

            var fgColor = sel ? AppTheme.RowSelectedText : AppTheme.TextPrimary;
            var fmt     = new StringFormat { LineAlignment = StringAlignment.Center, Trimming = StringTrimming.EllipsisCharacter };
            var tr      = new RectangleF(e.Bounds.X + 10, e.Bounds.Y, e.Bounds.Width - 14, e.Bounds.Height);

            using var fgBrush = new SolidBrush(fgColor);
            if (e.ColumnIndex == 0)
            {
                using var bold = AppTheme.FontBold;
                e.Graphics.DrawString(e.SubItem.Text, bold, fgBrush, tr, fmt);
            }
            else
            {
                using var reg = AppTheme.FontRegular;
                e.Graphics.DrawString(e.SubItem.Text, reg, fgBrush, tr, fmt);
            }
        }

        private static void DrawBadge(Graphics g, Rectangle bounds, PrinterInfo? p)
        {
            if (p == null) return;
            string? label = null;
            Color bg = Color.Transparent, fg = Color.Transparent;

            if (p.IsFavorite)     { label = "⭐ Favorita"; bg = AppTheme.BadgeFavBg; fg = AppTheme.BadgeFavFg; }
            else if (p.IsDefault) { label = "📌 Default";  bg = AppTheme.BadgeDefBg; fg = AppTheme.BadgeDefFg; }
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
            using var path    = AppTheme.RoundedPath(rc, 8);
            using var bgBrush = new SolidBrush(bg);
            g.FillPath(bgBrush, path);
            using var fgBrush = new SolidBrush(fg);
            var fmt = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center };
            g.DrawString(label, font, fgBrush, rc, fmt);
            g.SmoothingMode = SmoothingMode.Default;
        }

        private static GraphicsPath RoundedPath(Rectangle r, int rad) => AppTheme.RoundedPath(r, rad);

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
                _btnFavorite.Enabled   = false;
                _btnFavorite.Text      = "⭐  Establecer favorita";
                _btnFavorite.IsPrimary = true;
            }
            else if (sel.IsFavorite)
            {
                _btnFavorite.Enabled   = true;
                _btnFavorite.Text      = "✕  Quitar favorita";
                _btnFavorite.IsPrimary = false;
            }
            else
            {
                _btnFavorite.Enabled   = true;
                _btnFavorite.Text      = "⭐  Establecer favorita";
                _btnFavorite.IsPrimary = true;
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
}
