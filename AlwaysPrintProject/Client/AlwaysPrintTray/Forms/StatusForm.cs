using System;
using System.Collections.Generic;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintTray.Localization;
using AlwaysPrintTray.OnDemand;
using AlwaysPrintTray.Pipe;

namespace AlwaysPrintTray.Forms
{
    /// <summary>
    /// Formulario de estado del sistema (WinForms).
    /// Muestra información general, triggers OnDemand y servicios monitoreados.
    /// </summary>
    public sealed class StatusForm : Form
    {
        private readonly PipeClient _pipe;

        // Controles dinámicos
        private Label _valState = null!;
        private Label _valVersion = null!;
        private Label _valQueue = null!;
        private Label _valConfig = null!;
        private FlowLayoutPanel _triggersPanel = null!;
        private FlowLayoutPanel _servicesPanel = null!;

        public StatusForm(PipeClient pipe)
        {
            _pipe = pipe ?? throw new ArgumentNullException(nameof(pipe));
            BuildUI();
            LoadData();
        }

        private void BuildUI()
        {
            Text = LocalizationManager.Get("StatusFormTitle");
            Size = new Size(500, 520);
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            BackColor = Color.FromArgb(245, 245, 245);
            ForeColor = Color.Black;
            Font = new Font("Segoe UI", 9f);
            AutoScaleMode = AutoScaleMode.Dpi;
            KeyPreview = true;
            KeyDown += (s, e) => { if (e.KeyCode == Keys.Escape) Close(); };

            var y = 12;

            // ═══ Información General ═══
            AddSectionHeader(LocalizationManager.Get("StatusSectionGeneralInfo"), ref y);
            _valState = AddFieldRow(LocalizationManager.Get("StatusLabelState"), "...", ref y);
            _valVersion = AddFieldRow(LocalizationManager.Get("StatusLabelVersion"), "...", ref y);
            _valQueue = AddFieldRow(LocalizationManager.Get("StatusLabelActiveQueue"), "...", ref y);
            _valConfig = AddFieldRow(LocalizationManager.Get("StatusLabelConfig"), "...", ref y);

            y += 8;
            AddSeparator(ref y);

            // ═══ Acciones A Demanda ═══
            AddSectionHeader(LocalizationManager.Get("StatusSectionOnDemand"), ref y);
            _triggersPanel = new FlowLayoutPanel
            {
                Location = new Point(12, y),
                Size = new Size(420, 30),
                FlowDirection = FlowDirection.TopDown,
                AutoSize = true,
                WrapContents = false
            };
            Controls.Add(_triggersPanel);
            y += 35;

            AddSeparator(ref y);

            // ═══ Servicios ═══
            AddSectionHeader(LocalizationManager.Get("StatusSectionServices"), ref y);
            _servicesPanel = new FlowLayoutPanel
            {
                Location = new Point(12, y),
                Size = new Size(420, 30),
                FlowDirection = FlowDirection.TopDown,
                AutoSize = true,
                WrapContents = false
            };
            Controls.Add(_servicesPanel);

            // Botón Cerrar
            var btnClose = new Button
            {
                Text = LocalizationManager.Get("StatusButtonClose"),
                Size = new Size(80, 28),
                Anchor = AnchorStyles.Bottom | AnchorStyles.Right,
                DialogResult = DialogResult.Cancel
            };
            btnClose.Click += (s, e) => Close();
            Controls.Add(btnClose);

            // Posicionar botón al redimensionar/al final
            Load += (s, e) =>
            {
                btnClose.Location = new Point(ClientSize.Width - btnClose.Width - 16, ClientSize.Height - btnClose.Height - 12);
            };

            CancelButton = btnClose;
            AutoSize = true;
            AutoSizeMode = AutoSizeMode.GrowOnly;
        }

        private void LoadData()
        {
            try
            {
                // Información general
                _valState.Text = StatusDisplayHelper.FormatEstadoSistema(IsContingencyEnabled());
                _valVersion.Text = System.Reflection.Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "0.0.0.0";
                _valQueue.Text = LoadQueueName();
                _valConfig.Text = LoadConfigName();

                // Triggers OnDemand
                var triggers = OnDemandConfigReader.GetOnDemandTriggers();
                if (triggers.Count == 0)
                {
                    _triggersPanel.Controls.Add(new Label
                    {
                        Text = LocalizationManager.Get("StatusNoActionsAvailable"),
                        ForeColor = Color.Gray,
                        Font = new Font("Segoe UI", 9f, FontStyle.Italic),
                        AutoSize = true
                    });
                }
                else
                {
                    foreach (var trigger in triggers)
                    {
                        var panel = new FlowLayoutPanel { FlowDirection = FlowDirection.LeftToRight, AutoSize = true, WrapContents = false, Margin = new Padding(0, 2, 0, 2) };
                        panel.Controls.Add(new Label { Text = trigger.Label, AutoSize = true, Padding = new Padding(0, 4, 8, 0) });
                        var btn = new Button { Text = LocalizationManager.Get("StatusButtonExecute"), AutoSize = true, Padding = new Padding(8, 2, 8, 2), Tag = trigger };
                        btn.Click += TriggerExecuteClick;
                        panel.Controls.Add(btn);
                        _triggersPanel.Controls.Add(panel);
                    }
                }

                // Servicios monitoreados — lectura síncrona directa con ServiceController
                var services = OnDemandConfigReader.GetMonitoredServices();
                foreach (var svc in services)
                {
                    var panel = new FlowLayoutPanel { FlowDirection = FlowDirection.LeftToRight, AutoSize = true, WrapContents = false, Margin = new Padding(0, 1, 0, 1) };
                    var nameLabel = new Label { Text = svc.DisplayName, AutoSize = true, Padding = new Padding(0, 2, 12, 0), ForeColor = Color.Black, BackColor = Color.Transparent };

                    string state;
                    try
                    {
                        using var sc = new System.ServiceProcess.ServiceController(svc.ServiceName);
                        state = sc.Status.ToString();
                    }
                    catch { state = "NotFound"; }

                    var stateLabel = new Label
                    {
                        Text = state,
                        AutoSize = true,
                        ForeColor = state == "Running" ? Color.FromArgb(0x22, 0x8B, 0x22) : Color.FromArgb(0xCC, 0x00, 0x00),
                        BackColor = Color.Transparent,
                        Padding = new Padding(0, 2, 0, 0)
                    };
                    panel.Controls.Add(nameLabel);
                    panel.Controls.Add(stateLabel);
                    _servicesPanel.Controls.Add(panel);
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError($"StatusForm.LoadData: {ex.Message}", AlwaysPrintLogger.EvtGenericError);
            }
        }

        private async void TriggerExecuteClick(object? sender, EventArgs e)
        {
            var btn = sender as Button;
            if (btn == null) return;
            var trigger = btn.Tag as OnDemandTriggerInfo;
            if (trigger == null) return;

            var result = MessageBox.Show(this, trigger.Description,
                $"¿Ejecutar '{trigger.Label}'?",
                MessageBoxButtons.OKCancel, MessageBoxIcon.Question);
            if (result != DialogResult.OK) return;

            btn.Enabled = false;
            try
            {
                if (!_pipe.IsConnected)
                {
                    MessageBox.Show(this, "El servicio no está accesible.", "Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }

                var payload = new ExecuteOnDemandTriggerPayload { Label = trigger.Label };
                var request = PipeMessage.Create(MessageType.ExecuteOnDemandTrigger, payload);
                var response = await Task.Run(() => _pipe.Send(request));

                if (response?.Type == MessageType.Ack)
                {
                    var ack = response.GetPayload<AckPayload>();
                    if (ack?.Success == true)
                        MessageBox.Show(this, $"✓ {trigger.Label} ejecutado correctamente.", "Éxito", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    else
                        MessageBox.Show(this, $"Error: {ack?.Message ?? "desconocido"}", "Error", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                }
                else
                {
                    var error = response?.GetPayload<ErrorPayload>();
                    MessageBox.Show(this, $"Error: {error?.Message ?? "respuesta inesperada"}", "Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, $"Error: {ex.Message}", "Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            finally
            {
                btn.Enabled = true;
            }
        }

        // ── Helpers ──

        private bool IsContingencyEnabled()
        {
            try
            {
                using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                    RegistryConfigManager.RegistryPath);
                var val = key?.GetValue("ContingencyEnabled");
                return val?.ToString() == "1";
            }
            catch { return false; }
        }

        private string LoadQueueName()
        {
            try
            {
                using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                    RegistryConfigManager.RegistryPath);
                return key?.GetValue("CorporateQueueName")?.ToString() ?? "N/A";
            }
            catch { return "N/A"; }
        }

        private string LoadConfigName()
        {
            try
            {
                string filePath = PipeConstants.ActionConfigFilePath;
                if (!System.IO.File.Exists(filePath)) return "Sin configuración";
                var json = System.IO.File.ReadAllText(filePath);
                var config = Newtonsoft.Json.JsonConvert.DeserializeObject<ActionConfiguration>(json);
                if (config == null) return "Sin configuración";
                return StatusDisplayHelper.FormatConfigDisplay(
                    string.IsNullOrWhiteSpace(config.Name) ? "Desconocida" : config.Name,
                    string.IsNullOrWhiteSpace(config.Version) ? "?" : config.Version);
            }
            catch { return "Error al leer"; }
        }

        private void AddSectionHeader(string text, ref int y)
        {
            var lbl = new Label
            {
                Text = text,
                Location = new Point(12, y),
                AutoSize = true,
                Font = new Font("Segoe UI Semibold", 10f),
                ForeColor = Color.FromArgb(0x00, 0x66, 0xCC)
            };
            Controls.Add(lbl);
            y += 24;
        }

        private Label AddFieldRow(string label, string value, ref int y)
        {
            var lbl = new Label
            {
                Text = label,
                Location = new Point(16, y),
                AutoSize = true,
                ForeColor = Color.FromArgb(0x55, 0x55, 0x55),
                BackColor = Color.Transparent
            };
            var val = new Label
            {
                Text = value,
                Location = new Point(150, y),
                AutoSize = true,
                ForeColor = Color.Black,
                BackColor = Color.Transparent
            };
            Controls.Add(lbl);
            Controls.Add(val);
            y += 22;
            return val;
        }

        private void AddSeparator(ref int y)
        {
            var sep = new Label
            {
                Location = new Point(12, y),
                Size = new Size(420, 1),
                BorderStyle = BorderStyle.Fixed3D
            };
            Controls.Add(sep);
            y += 8;
        }
    }
}
