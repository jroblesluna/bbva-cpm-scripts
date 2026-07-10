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
    /// Editor de configuración con estilo corporativo AlwaysPrint.
    /// Lee valores del servicio vía Named Pipe y envía cambios de vuelta.
    /// El Tray nunca escribe HKLM directamente — el servicio persiste en registro.
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
            Shown += (_, __) => LoadCurrentConfiguration();
        }

        private void BuildUi()
        {
            Text       = "Configuración de AlwaysPrint";
            ClientSize = new Size(540, 530);
            AppTheme.ApplyFormStyle(this);

            int y = 18;
            int lw = 200, cx = 218, lx = 18;

            Label Lbl(string text)
            {
                var l = new Label
                {
                    Text      = text,
                    Location  = new Point(lx, y + 3),
                    Size      = new Size(lw, 20),
                    ForeColor = AppTheme.TextPrimary,
                    Font      = (Font)AppTheme.FontRegular.Clone()
                };
                return l;
            }

            TextBox Txt(int w = 290)
            {
                var t = new TextBox
                {
                    Location = new Point(cx, y),
                    Size     = new Size(w, 24),
                    Font     = (Font)AppTheme.FontRegular.Clone()
                };
                return t;
            }

            // Cola corporativa
            Controls.Add(Lbl("Cola corporativa:"));
            _txtQueueName = Txt();
            Controls.Add(_txtQueueName);
            y += 34;

            // IPs
            Controls.Add(Lbl("IPs de búsqueda (CSV):"));
            _txtIps = Txt();
            Controls.Add(_txtIps);
            y += 34;

            // CIDR
            Controls.Add(Lbl("Rangos CIDR (CSV):"));
            _txtRanges = Txt();
            Controls.Add(_txtRanges);
            y += 34;

            // Poll interval
            Controls.Add(Lbl("Intervalo de monitoreo (min):"));
            _numPoll = new NumericUpDown
            {
                Location = new Point(cx, y),
                Size     = new Size(80, 24),
                Minimum  = 1,
                Maximum  = 1440,
                Value    = 3,
                Font     = (Font)AppTheme.FontRegular.Clone()
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

            // ── Separador: Integración Cloud ────────────────────────────────
            Controls.Add(new Label
            {
                Text      = "─── Integración Cloud ───",
                Location  = new Point(lx, y),
                Size      = new Size(500, 20),
                ForeColor = AppTheme.TextMuted,
                Font      = (Font)AppTheme.FontSmall.Clone()
            });
            y += 26;

            // Cloud habilitado
            _chkCloudEnabled = new CheckBox
            {
                Text      = "Integración Cloud habilitada",
                Location  = new Point(cx, y),
                Size      = new Size(290, 22),
                Font      = (Font)AppTheme.FontRegular.Clone(),
                ForeColor = AppTheme.TextPrimary
            };
            Controls.Add(_chkCloudEnabled);
            y += 34;

            // URL Cloud (solo lectura — se configura por instalación/registro)
            Controls.Add(Lbl("URL del servidor Cloud (APCM):"));
            _txtCloudApiUrl = Txt();
            _txtCloudApiUrl.ReadOnly = true;
            _txtCloudApiUrl.BackColor = System.Drawing.Color.FromArgb(240, 240, 240);
            _txtCloudApiUrl.ForeColor = AppTheme.TextMuted;
            Controls.Add(_txtCloudApiUrl);
            y += 34;

            // Idioma
            Controls.Add(Lbl("Idioma (locale):"));
            _cmbCloudLocale = new ComboBox
            {
                Location      = new Point(cx, y),
                Size          = new Size(150, 24),
                DropDownStyle = ComboBoxStyle.DropDownList,
                Font          = (Font)AppTheme.FontRegular.Clone()
            };
            _cmbCloudLocale.Items.AddRange(new object[] { "Auto", "Español", "English" });
            _cmbCloudLocale.SelectedIndex = 0;
            Controls.Add(_cmbCloudLocale);
            y += 40;

            // ── Separador: Actualizaciones ──────────────────────────────────
            Controls.Add(new Label
            {
                Text      = "─── Actualizaciones ───",
                Location  = new Point(lx, y),
                Size      = new Size(500, 20),
                ForeColor = AppTheme.TextMuted,
                Font      = (Font)AppTheme.FontSmall.Clone()
            });
            y += 26;

            // Auto-actualización
            Controls.Add(Lbl("Auto-actualización:"));
            _chkAutoUpdate = new CheckBox
            {
                Text      = "Habilitar Actualizaciones Automáticas",
                Location  = new Point(cx, y),
                Size      = new Size(290, 22),
                Font      = (Font)AppTheme.FontRegular.Clone(),
                ForeColor = AppTheme.TextPrimary
            };
            Controls.Add(_chkAutoUpdate);
            y += 40;

            // Status
            _lblStatus = new Label
            {
                Location  = new Point(lx, y),
                Size      = new Size(500, 20),
                ForeColor = AppTheme.TextMuted,
                Font      = (Font)AppTheme.FontSmall.Clone()
            };
            Controls.Add(_lblStatus);
            y += 30;

            // ── Footer ──────────────────────────────────────────────────────
            var footer = new Panel
            {
                Location  = new Point(0, y),
                Size      = new Size(540, 56),
                BackColor = AppTheme.FooterBg
            };
            footer.Paint += (s, e) => AppTheme.DrawDivider(e.Graphics, 0, 0, 540);

            var btnSave = new AppButton
            {
                Text      = "Guardar",
                Location  = new Point(540 - 104 - 84 - 20, 12),
                Size      = new Size(104, 34),
                IsPrimary = true
            };
            btnSave.Click += BtnSave_Click;

            var btnCancel = new AppButton
            {
                Text         = "Cancelar",
                Location     = new Point(540 - 84 - 10, 12),
                Size         = new Size(84, 34),
                IsPrimary    = false,
                DialogResult = DialogResult.Cancel
            };

            footer.Controls.AddRange(new Control[] { btnSave, btnCancel });
            Controls.Add(footer);
            CancelButton = btnCancel;
            ClientSize   = new Size(540, y + 56);
        }

        private void LoadCurrentConfiguration()
        {
            _lblStatus.Text = "Cargando configuración...";

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
                _lblStatus.ForeColor = Color.Red;
                _lblStatus.Text = "No se pudo cargar la configuración del servicio.";
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
            _chkCloudEnabled.Checked = cfg.CloudEnabled;
            _txtCloudApiUrl.Text     = cfg.CloudApiUrl ?? string.Empty;
            _cmbCloudLocale.SelectedIndex = cfg.CloudLocale switch
            {
                "es" => 1,
                "en" => 2,
                _    => 0
            };
        }

        private void BtnSave_Click(object? sender, EventArgs e)
        {
            string cloudApiUrl = _txtCloudApiUrl.Text.Trim();
            if (!string.IsNullOrEmpty(cloudApiUrl) &&
                !Uri.IsWellFormedUriString(cloudApiUrl, UriKind.Absolute))
            {
                _lblStatus.ForeColor = Color.Red;
                _lblStatus.Text = "URL del servidor Cloud no es válida. Debe ser una URI absoluta (ej. https://...).";
                return;
            }

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
