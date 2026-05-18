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

        // === CAMPOS CLOUD ===
        private CheckBox _chkCloudEnabled = null!;
        private TextBox  _txtCloudApiUrl  = null!;
        private ComboBox _cmbCloudLocale  = null!;

        // === AUTO-ACTUALIZACIÓN ===
        private CheckBox _chkAutoUpdate   = null!;

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

            // === SECCIÓN INTEGRACIÓN CLOUD ===

            // Separador visual
            Controls.Add(new Label
            {
                Text      = "─── Integración Cloud ───",
                Location  = new Point(lx, y),
                Size      = new Size(480, 20),
                ForeColor = SystemColors.GrayText
            });
            y += 26;

            // Checkbox: Cloud habilitado
            _chkCloudEnabled = new CheckBox
            {
                Text     = "Integración Cloud habilitada",
                Location = new Point(cx, y),
                Size     = new Size(290, 22)
            };
            Controls.Add(new Label { Text = string.Empty, Location = new Point(lx, y + 3), Size = new Size(lw, 20) });
            Controls.Add(_chkCloudEnabled);
            y += 34;

            // URL del servidor Cloud
            Controls.Add(Lbl("URL del servidor Cloud (APCM):"));
            _txtCloudApiUrl = Txt();
            Controls.Add(_txtCloudApiUrl);
            y += 34;

            // Idioma (locale)
            Controls.Add(Lbl("Idioma (locale):"));
            _cmbCloudLocale = new ComboBox
            {
                Location      = new Point(cx, y),
                Size          = new Size(150, 22),
                DropDownStyle = ComboBoxStyle.DropDownList
            };
            _cmbCloudLocale.Items.AddRange(new object[] { "Auto", "Español", "English" });
            _cmbCloudLocale.SelectedIndex = 0;
            Controls.Add(_cmbCloudLocale);
            y += 40;

            // === SECCIÓN AUTO-ACTUALIZACIÓN ===

            // Separador visual
            Controls.Add(new Label
            {
                Text      = "─── Actualizaciones ───",
                Location  = new Point(lx, y),
                Size      = new Size(480, 20),
                ForeColor = SystemColors.GrayText
            });
            y += 26;

            // Checkbox: Habilitar Actualizaciones Automáticas
            _chkAutoUpdate = new CheckBox
            {
                Text     = "Habilitar Actualizaciones Automáticas",
                Location = new Point(cx, y),
                Size     = new Size(290, 22)
            };
            Controls.Add(new Label { Text = "Auto-actualización:", Location = new Point(lx, y + 3), Size = new Size(lw, 20) });
            Controls.Add(_chkAutoUpdate);
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

            // Cargar flag de auto-actualización directamente del registro
            // (es independiente de AppConfiguration y no requiere privilegios elevados para lectura)
            var registry = new RegistryConfigManager();
            _chkAutoUpdate.Checked = registry.LoadAutoUpdateEnabled();

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
                // Si el pipe falla o devuelve null, mostrar error y dejar controles en estado default
                _lblStatus.ForeColor = Color.Red;
                _lblStatus.Text = "No se pudo cargar la configuración del servicio.";

                // Dejar controles Cloud en estado default explícitamente
                _chkCloudEnabled.Checked  = false;
                _txtCloudApiUrl.Text      = string.Empty;
                _cmbCloudLocale.SelectedIndex = 0;
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

            // === CAMPOS CLOUD ===
            _chkCloudEnabled.Checked = cfg.CloudEnabled;
            _txtCloudApiUrl.Text     = cfg.CloudApiUrl ?? string.Empty;

            // Seleccionar el item del ComboBox según el valor de CloudLocale
            _cmbCloudLocale.SelectedIndex = cfg.CloudLocale switch
            {
                "es" => 1,
                "en" => 2,
                _    => 0   // "" o cualquier otro valor → "Auto"
            };
        }

        private void BtnSave_Click(object? sender, EventArgs e)
        {
            // Validar URL Cloud si no está vacía
            string cloudApiUrl = _txtCloudApiUrl.Text.Trim();
            if (!string.IsNullOrEmpty(cloudApiUrl) &&
                !Uri.IsWellFormedUriString(cloudApiUrl, UriKind.Absolute))
            {
                _lblStatus.ForeColor = Color.Red;
                _lblStatus.Text = "URL del servidor Cloud no es válida. Debe ser una URI absoluta (ej. https://...).";
                return;
            }

            // Mapear el índice del ComboBox al valor de locale
            string cloudLocale = _cmbCloudLocale.SelectedIndex switch
            {
                1 => "es",
                2 => "en",
                _ => string.Empty
            };

            var cfg = new AppConfiguration
            {
                CorporateQueueName        = _txtQueueName.Text.Trim(),
                PendingTaskPollingMinutes = (int)_numPoll.Value,
                BootstrapDomains          = _txtDomains.Text.Trim(),
                RoblesAiLicenseSerial     = _txtSerial.Text.Trim(),
                SearchTargets = new SearchTargetsConfig
                {
                    Ips    = _txtIps.Text.Trim(),
                    Ranges = _txtRanges.Text.Trim()
                },
                // === CAMPOS CLOUD ===
                CloudEnabled = _chkCloudEnabled.Checked,
                CloudApiUrl  = cloudApiUrl,
                CloudLocale  = cloudLocale
            };

            var payload  = new UpdateConfigurationPayload
            {
                Configuration = cfg,
                AutoUpdateEnabled = _chkAutoUpdate.Checked
            };
            var request  = PipeMessage.Create(MessageType.UpdateConfiguration, payload);
            var response = _pipe.Send(request);

            if (response?.Type == MessageType.Ack)
            {
                var ack = response.GetPayload<AckPayload>();
                if (ack?.Success == true)
                {
                    DialogResult = DialogResult.OK;
                    Close();
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
