using System;
using System.Drawing;
using System.Windows.Forms;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintTray.Pipe;
using Newtonsoft.Json;

namespace AlwaysPrintTray.Forms
{
    /// <summary>
    /// Simple configuration editor. Reads current values from the service via Named Pipe,
    /// lets the user edit them, and sends UpdateConfiguration back through the pipe.
    /// The Tray never writes HKLM directly – the service is the sole owner of registry persistence.
    /// </summary>
    public sealed class ConfigurationForm : Form
    {
        private readonly PipeClient _pipe;

        private TextBox _txtQueueName     = null!;
        private TextBox _txtIps           = null!;
        private TextBox _txtRanges        = null!;
        private NumericUpDown _numPoll    = null!;
        private TextBox _txtDomains       = null!;
        private TextBox _txtSerial        = null!;
        private Label   _lblStatus        = null!;

        public ConfigurationForm(PipeClient pipe)
        {
            _pipe = pipe ?? throw new ArgumentNullException(nameof(pipe));
            BuildUi();
            // La carga se hace en el evento Shown para no bloquear el hilo UI durante
            // la construcción del formulario (la llamada al pipe puede tardar).
            Shown += (_, __) => LoadCurrentConfiguration();
        }

        private void BuildUi()
        {
            Text            = "Configuración de AlwaysPrint";
            Size            = new Size(520, 460);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox     = false;
            MinimizeBox     = false;
            StartPosition   = FormStartPosition.CenterScreen;
            ShowInTaskbar   = false;

            int y = 16, lw = 190, cx = 210, lx = 12;

            Label Lbl(string text) => new Label { Text = text, Location = new Point(lx, y + 3), Size = new Size(lw, 20) };
            TextBox Txt(int w = 290) => new TextBox { Location = new Point(cx, y), Size = new Size(w, 22) };

            // Corporate queue name
            Controls.Add(Lbl("Cola corporativa:"));
            _txtQueueName = Txt();
            Controls.Add(_txtQueueName);
            y += 34;

            // Search IPs
            Controls.Add(Lbl("IPs de búsqueda (CSV):"));
            _txtIps = Txt();
            Controls.Add(_txtIps);
            y += 34;

            // CIDR ranges
            Controls.Add(Lbl("Rangos CIDR (CSV):"));
            _txtRanges = Txt();
            Controls.Add(_txtRanges);
            y += 34;

            // Poll interval
            Controls.Add(Lbl("Intervalo de monitoreo (min):"));
            _numPoll = new NumericUpDown
            {
                Location = new Point(cx, y),
                Size     = new Size(80, 22),
                Minimum  = 1,
                Maximum  = 1440,
                Value    = 3
            };
            Controls.Add(_numPoll);
            y += 34;

            // Bootstrap domains
            Controls.Add(Lbl("Dominios bootstrap (CSV):"));
            _txtDomains = Txt();
            Controls.Add(_txtDomains);
            y += 34;

            // License serial
            Controls.Add(Lbl("Número de serie licencia:"));
            _txtSerial = Txt();
            Controls.Add(_txtSerial);
            y += 40;

            // Status bar
            _lblStatus = new Label
            {
                Location  = new Point(lx, y),
                Size      = new Size(480, 20),
                ForeColor = SystemColors.GrayText
            };
            Controls.Add(_lblStatus);
            y += 30;

            // Buttons
            var btnSave = new Button
            {
                Text     = "Guardar",
                Location = new Point(320, y),
                Size     = new Size(80, 28)
            };
            btnSave.Click += BtnSave_Click;

            var btnCancel = new Button
            {
                Text         = "Cancelar",
                DialogResult = DialogResult.Cancel,
                Location     = new Point(410, y),
                Size         = new Size(80, 28)
            };

            Controls.AddRange(new Control[] { btnSave, btnCancel });
            CancelButton = btnCancel;
            ClientSize   = new Size(510, y + 50);
        }

        private void LoadCurrentConfiguration()
        {
            _lblStatus.Text = "Cargando configuración...";

            var response = _pipe.Send(PipeMessage.Create(MessageType.GetCurrentConfiguration));
            if (response?.Type == MessageType.Ack)
            {
                var payload = response.GetPayload<GetConfigurationResponsePayload>();
                if (payload?.Configuration != null)
                    PopulateFields(payload.Configuration);

                _lblStatus.Text = "Configuración cargada.";
            }
            else
            {
                _lblStatus.ForeColor = Color.Red;
                _lblStatus.Text = "No se pudo cargar la configuración del servicio.";
            }
        }

        private void PopulateFields(AppConfiguration cfg)
        {
            _txtQueueName.Text   = cfg.CorporateQueueName;
            _txtIps.Text         = cfg.SearchTargets?.Ips    ?? string.Empty;
            _txtRanges.Text      = cfg.SearchTargets?.Ranges ?? string.Empty;
            _numPoll.Value       = Math.Max(1, Math.Min(1440, cfg.PendingTaskPollingMinutes));
            _txtDomains.Text     = cfg.BootstrapDomains;
            _txtSerial.Text      = cfg.RoblesAiLicenseSerial;
        }

        private void BtnSave_Click(object? sender, EventArgs e)
        {
            var cfg = new AppConfiguration
            {
                CorporateQueueName      = _txtQueueName.Text.Trim(),
                PendingTaskPollingMinutes = (int)_numPoll.Value,
                BootstrapDomains        = _txtDomains.Text.Trim(),
                RoblesAiLicenseSerial   = _txtSerial.Text.Trim(),
                SearchTargets = new SearchTargetsConfig
                {
                    Ips    = _txtIps.Text.Trim(),
                    Ranges = _txtRanges.Text.Trim()
                }
            };

            var payload  = new UpdateConfigurationPayload { Configuration = cfg };
            var request  = PipeMessage.Create(MessageType.UpdateConfiguration, payload);
            var response = _pipe.Send(request);

            if (response?.Type == MessageType.Ack)
            {
                var ack = response.GetPayload<AckPayload>();
                if (ack?.Success == true)
                {
                    _lblStatus.ForeColor = Color.DarkGreen;
                    _lblStatus.Text = "Configuración guardada correctamente.";
                }
                else
                {
                    _lblStatus.ForeColor = Color.OrangeRed;
                    _lblStatus.Text = $"Error: {ack?.Message}";
                }
            }
            else
            {
                _lblStatus.ForeColor = Color.Red;
                _lblStatus.Text = "No se recibió confirmación del servicio.";
            }
        }
    }
}
