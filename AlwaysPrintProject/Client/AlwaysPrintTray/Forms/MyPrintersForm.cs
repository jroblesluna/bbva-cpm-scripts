using System;
using System.Collections.Generic;
using System.Drawing;
using System.Net.Http;
using System.Windows.Forms;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.Forms
{
    /// <summary>
    /// Formulario "Mis Impresoras" que muestra las impresoras disponibles en la misma VLAN
    /// y permite al usuario seleccionar una impresora favorita para contingencia.
    /// 
    /// Prioridad de contingencia:
    /// 1. Impresora favorita (seleccionada por el usuario)
    /// 2. Impresora por defecto (menor IP en la VLAN)
    /// 3. Iteración por las demás impresoras disponibles
    /// </summary>
    public sealed class MyPrintersForm : Form
    {
        private readonly string _cloudApiUrl;
        private readonly string _workstationId;
        private readonly HttpClient _http;

        private ListView _listView;
        private Button _btnSetFavorite;
        private Button _btnRemoveFavorite;
        private Button _btnRefresh;
        private Button _btnClose;
        private Label _lblStatus;
        private Label _lblVlan;

        private List<PrinterInfo> _printers = new List<PrinterInfo>();
        private string? _favoritePrinterId;
        private string? _defaultPrinterId;

        public MyPrintersForm(string cloudApiUrl, string workstationId, HttpClient http)
        {
            _cloudApiUrl = cloudApiUrl;
            _workstationId = workstationId;
            _http = http;

            InitializeComponents();
            LoadPrinters();
        }

        private void InitializeComponents()
        {
            Text = "Mis Impresoras - Contingencia";
            Size = new Size(650, 480);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            ShowInTaskbar = false;

            // Etiqueta de VLAN
            _lblVlan = new Label
            {
                Text = "Cargando información de red...",
                Location = new Point(15, 15),
                Size = new Size(600, 20),
                Font = new Font("Segoe UI", 9, FontStyle.Bold)
            };

            // ListView de impresoras
            _listView = new ListView
            {
                Location = new Point(15, 45),
                Size = new Size(600, 280),
                View = View.Details,
                FullRowSelect = true,
                GridLines = true,
                MultiSelect = false,
                Font = new Font("Segoe UI", 9)
            };
            _listView.Columns.Add("Nombre", 180);
            _listView.Columns.Add("IP:Puerto", 130);
            _listView.Columns.Add("Modelo", 120);
            _listView.Columns.Add("Ubicación", 100);
            _listView.Columns.Add("Estado", 60);
            _listView.SelectedIndexChanged += OnSelectionChanged;

            // Botones
            _btnSetFavorite = new Button
            {
                Text = "⭐ Establecer como Favorita",
                Location = new Point(15, 340),
                Size = new Size(200, 32),
                Enabled = false,
                Font = new Font("Segoe UI", 9)
            };
            _btnSetFavorite.Click += OnSetFavorite;

            _btnRemoveFavorite = new Button
            {
                Text = "Quitar Favorita",
                Location = new Point(225, 340),
                Size = new Size(140, 32),
                Enabled = false,
                Font = new Font("Segoe UI", 9)
            };
            _btnRemoveFavorite.Click += OnRemoveFavorite;

            _btnRefresh = new Button
            {
                Text = "🔄 Actualizar",
                Location = new Point(450, 340),
                Size = new Size(100, 32),
                Font = new Font("Segoe UI", 9)
            };
            _btnRefresh.Click += (_, __) => LoadPrinters();

            _btnClose = new Button
            {
                Text = "Cerrar",
                Location = new Point(555, 340),
                Size = new Size(60, 32),
                DialogResult = DialogResult.OK,
                Font = new Font("Segoe UI", 9)
            };

            // Etiqueta de estado
            _lblStatus = new Label
            {
                Text = "",
                Location = new Point(15, 385),
                Size = new Size(600, 50),
                Font = new Font("Segoe UI", 8),
                ForeColor = SystemColors.GrayText
            };

            Controls.AddRange(new Control[]
            {
                _lblVlan, _listView, _btnSetFavorite, _btnRemoveFavorite,
                _btnRefresh, _btnClose, _lblStatus
            });
            AcceptButton = _btnClose;
        }

        private async void LoadPrinters()
        {
            try
            {
                _listView.Items.Clear();
                _lblStatus.Text = "Consultando impresoras disponibles...";
                _lblStatus.ForeColor = SystemColors.GrayText;

                var url = $"{_cloudApiUrl}/api/v1/devices/workstation/{_workstationId}/my-printers";
                var response = await _http.GetAsync(url);

                if (!response.IsSuccessStatusCode)
                {
                    var errorBody = await response.Content.ReadAsStringAsync();
                    _lblStatus.Text = $"Error al obtener impresoras: {response.StatusCode}";
                    _lblStatus.ForeColor = Color.Red;
                    AlwaysPrintLogger.WriteTrayError(
                        $"MyPrintersForm: error HTTP {response.StatusCode} al obtener impresoras. {errorBody}");
                    return;
                }

                var json = await response.Content.ReadAsStringAsync();
                var data = JObject.Parse(json);

                _favoritePrinterId = data["favorite_printer_id"]?.ToString();
                _defaultPrinterId = data["default_printer_id"]?.ToString();
                var vlanName = data["vlan_name"]?.ToString();
                var total = data["total"]?.ToObject<int>() ?? 0;

                _lblVlan.Text = vlanName != null
                    ? $"VLAN: {vlanName} — {total} impresora(s) disponible(s)"
                    : $"Sin VLAN asignada — {total} impresora(s) de la organización";

                _printers.Clear();
                var printersArray = data["printers"] as JArray;
                if (printersArray != null)
                {
                    foreach (var p in printersArray)
                    {
                        _printers.Add(new PrinterInfo
                        {
                            Id = p["id"]?.ToString() ?? "",
                            Name = p["name"]?.ToString() ?? "",
                            IpAddress = p["ip_address"]?.ToString() ?? "",
                            Port = p["port"]?.ToObject<int>() ?? 9100,
                            Model = p["model"]?.ToString() ?? "",
                            Location = p["location"]?.ToString() ?? "",
                            IsFavorite = p["is_favorite"]?.ToObject<bool>() ?? false,
                            IsDefault = p["is_default"]?.ToObject<bool>() ?? false,
                        });
                    }
                }

                PopulateListView();

                if (total == 0)
                {
                    _lblStatus.Text = "⚠️ No hay impresoras configuradas para contingencia en su red.";
                    _lblStatus.ForeColor = Color.OrangeRed;
                }
                else
                {
                    var favName = _printers.Find(p => p.IsFavorite)?.Name;
                    var defName = _printers.Find(p => p.IsDefault)?.Name;
                    _lblStatus.Text = favName != null
                        ? $"✅ Impresora favorita: {favName}\nEn contingencia se usará esta impresora primero."
                        : $"ℹ️ Sin favorita. En contingencia se usará: {defName ?? "ninguna"} (menor IP).";
                    _lblStatus.ForeColor = favName != null ? Color.DarkGreen : SystemColors.GrayText;
                }

                _btnRemoveFavorite.Enabled = _favoritePrinterId != null;
            }
            catch (Exception ex)
            {
                _lblStatus.Text = $"Error de conexión: {ex.Message}";
                _lblStatus.ForeColor = Color.Red;
                AlwaysPrintLogger.WriteTrayError(
                    $"MyPrintersForm: excepción al cargar impresoras — {ex.GetType().Name}: {ex.Message}");
            }
        }

        private void PopulateListView()
        {
            _listView.Items.Clear();
            foreach (var printer in _printers)
            {
                string status = "";
                if (printer.IsFavorite) status = "⭐ Fav";
                else if (printer.IsDefault) status = "📌 Def";

                var item = new ListViewItem(new[]
                {
                    printer.Name,
                    $"{printer.IpAddress}:{printer.Port}",
                    printer.Model,
                    printer.Location,
                    status
                });

                if (printer.IsFavorite)
                    item.BackColor = Color.LightGoldenrodYellow;
                else if (printer.IsDefault)
                    item.BackColor = Color.AliceBlue;

                item.Tag = printer;
                _listView.Items.Add(item);
            }
        }

        private void OnSelectionChanged(object? sender, EventArgs e)
        {
            bool hasSelection = _listView.SelectedItems.Count > 0;
            if (hasSelection)
            {
                var selected = _listView.SelectedItems[0].Tag as PrinterInfo;
                _btnSetFavorite.Enabled = selected != null && !selected.IsFavorite;
            }
            else
            {
                _btnSetFavorite.Enabled = false;
            }
        }

        private async void OnSetFavorite(object? sender, EventArgs e)
        {
            if (_listView.SelectedItems.Count == 0) return;
            var selected = _listView.SelectedItems[0].Tag as PrinterInfo;
            if (selected == null) return;

            try
            {
                _btnSetFavorite.Enabled = false;
                _lblStatus.Text = $"Estableciendo {selected.Name} como favorita...";

                var url = $"{_cloudApiUrl}/api/v1/devices/workstation/{_workstationId}/favorite-printer";
                var content = new StringContent(
                    JsonConvert.SerializeObject(new { device_id = selected.Id }),
                    System.Text.Encoding.UTF8, "application/json");

                var response = await _http.PutAsync(url, content);
                if (response.IsSuccessStatusCode)
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"MyPrintersForm: impresora favorita establecida — {selected.Name} ({selected.IpAddress})");
                    LoadPrinters();
                }
                else
                {
                    _lblStatus.Text = $"Error al establecer favorita: {response.StatusCode}";
                    _lblStatus.ForeColor = Color.Red;
                }
            }
            catch (Exception ex)
            {
                _lblStatus.Text = $"Error: {ex.Message}";
                _lblStatus.ForeColor = Color.Red;
            }
        }

        private async void OnRemoveFavorite(object? sender, EventArgs e)
        {
            try
            {
                _btnRemoveFavorite.Enabled = false;
                _lblStatus.Text = "Quitando impresora favorita...";

                var url = $"{_cloudApiUrl}/api/v1/devices/workstation/{_workstationId}/favorite-printer";
                var content = new StringContent(
                    JsonConvert.SerializeObject(new { device_id = (string?)null }),
                    System.Text.Encoding.UTF8, "application/json");

                var response = await _http.PutAsync(url, content);
                if (response.IsSuccessStatusCode)
                {
                    AlwaysPrintLogger.WriteTrayInfo("MyPrintersForm: impresora favorita eliminada.");
                    LoadPrinters();
                }
                else
                {
                    _lblStatus.Text = $"Error al quitar favorita: {response.StatusCode}";
                    _lblStatus.ForeColor = Color.Red;
                }
            }
            catch (Exception ex)
            {
                _lblStatus.Text = $"Error: {ex.Message}";
                _lblStatus.ForeColor = Color.Red;
            }
        }

        /// <summary>Información de una impresora disponible.</summary>
        private class PrinterInfo
        {
            public string Id { get; set; } = "";
            public string Name { get; set; } = "";
            public string IpAddress { get; set; } = "";
            public int Port { get; set; } = 9100;
            public string Model { get; set; } = "";
            public string Location { get; set; } = "";
            public bool IsFavorite { get; set; }
            public bool IsDefault { get; set; }
        }
    }
}
