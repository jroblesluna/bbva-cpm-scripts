using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.Windows.Forms;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintTray.Cloud;
using AlwaysPrintTray.Localization;
using AlwaysPrintTray.OnDemand;
using AlwaysPrintTray.Pipe;

namespace AlwaysPrintTray.Forms
{
    /// <summary>
    /// Formulario de estado del sistema (WinForms, UI programática sin diseñador).
    /// Muestra información general, conectividad Cloud, triggers OnDemand y servicios monitoreados.
    /// Usa posicionamiento absoluto con Y calculado dinámicamente.
    /// Timer de 5 segundos para refrescar estados de servicios y conectividad.
    /// BackgroundWorker para operaciones de pipe (sin async/await).
    /// </summary>
    public sealed class StatusForm : Form
    {
        // ── Constantes de layout ────────────────────────────────────────────────
        private const int FormWidth = 960;
        private const int LeftColX = 16;
        private const int LeftColWidth = 420;
        private const int RightColX = 460;
        private const int RightColWidth = 480;
        private const int LabelX = 16;       // Alias para compatibilidad con helpers
        private const int ValueX = 140;
        private const int RowHeight = 24;
        private const int SectionSpacing = 12;

        // ── Dependencias ────────────────────────────────────────────────────────
        private readonly PipeClient _pipe;
        private readonly Func<CloudConnectivityState?>? _connectivityStateProvider;

        // ── Controles de información general ────────────────────────────────────
        private Label _valState = null!;
        private Label _valVersion = null!;
        private Label _valHostname = null!;
        private Label _valIp = null!;
        private Label _valQueue = null!;
        private Label _valQueueStatus = null!;
        private Label _valDriver = null!;
        private Label _valConfig = null!;

        // ── Controles de conectividad Cloud ─────────────────────────────────────
        private Label _valCloudStatus = null!;
        private Label _valCloudDetails = null!;

        // ── Controles de servicios (para refresh con timer) ─────────────────────
        private readonly List<ServiceRow> _serviceRows = new List<ServiceRow>();

        // ── Controles de acciones (para estado global busy) ─────────────────────
        private readonly List<Button> _allActionButtons = new List<Button>();
        private Label _lblStatus = null!;
        private Button _btnClose = null!;

        // ── Panel de progreso inline (columna derecha) ────────────────────────
        private ListView _progressListView = null!;
        private Label _progressHeader = null!;
        private readonly List<OnDemandActionProgressPayload> _progressSteps = new List<OnDemandActionProgressPayload>();

        // ── Estado global busy ──────────────────────────────────────────────────
        private bool _isBusy;

        // ── Flag de cierre graceful ─────────────────────────────────────────────
        private bool _isClosing;

        // ── Timer para refrescar estados de servicios ───────────────────────────
        private Timer _refreshTimer = null!;

        // ── Estructura interna para fila de servicio ────────────────────────────
        private class ServiceRow
        {
            public MonitoredServiceConfig Config { get; set; } = null!;
            public Label StateLabel { get; set; } = null!;
            /// <summary>Indicador de watchdog activo para este servicio.</summary>
            public Label WatchdogLabel { get; set; } = null!;
            /// <summary>Configuración watchdog de este servicio (null si no tiene).</summary>
            public WatchdogServiceEntry? WatchdogEntry { get; set; }
        }

        /// <summary>
        /// Constructor del StatusForm.
        /// </summary>
        /// <param name="pipe">Cliente Named Pipe para comunicación con el Service.</param>
        /// <param name="connectivityStateProvider">
        /// Función que retorna el estado actual de conectividad Cloud (null si no aplica).
        /// Permite al formulario consultar el estado sin acoplarse directamente a CloudRegistration.
        /// </param>
        public StatusForm(PipeClient pipe, Func<CloudConnectivityState?>? connectivityStateProvider = null)
        {
            _pipe = pipe ?? throw new ArgumentNullException(nameof(pipe));
            _connectivityStateProvider = connectivityStateProvider;
            BuildUI();
            LoadData();
            SetupRefreshTimer();
        }

        /// <summary>
        /// Actualiza la sección de conectividad Cloud desde fuera del formulario
        /// (ej: cuando CloudRegistration emite ConnectivityStateChanged).
        /// Thread-safe: usa Invoke si se llama desde otro hilo.
        /// </summary>
        public void UpdateCloudConnectivity(CloudConnectivityState state)
        {
            if (IsDisposed) return;

            if (InvokeRequired)
            {
                BeginInvoke(new Action(() => UpdateCloudConnectivity(state)));
                return;
            }

            ApplyCloudConnectivityState(state);
        }

        /// <summary>
        /// Refresca la información de configuración de acciones y triggers OnDemand.
        /// Se llama externamente cuando la config se actualiza desde Cloud.
        /// Thread-safe: usa Invoke si se llama desde otro hilo.
        /// </summary>
        public void RefreshActionConfigInfo()
        {
            if (IsDisposed) return;

            if (InvokeRequired)
            {
                Invoke(new Action(RefreshActionConfigInfo));
                return;
            }

            try
            {
                // Recargar triggers OnDemand desde disco
                OnDemandConfigReader.Reload();

                // Actualizar label de configuración
                _valConfig.Text = LoadConfigName();

                // Cerrar el form para que se reconstruya con los nuevos triggers al reabrirlo
                // (la sección de botones OnDemand usa posicionamiento absoluto y no se puede
                // actualizar dinámicamente sin reconstruir todo el layout)
                Close();
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"StatusForm.RefreshActionConfigInfo: error refrescando config: {ex.Message}");
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ── Construcción de la UI ───────────────────────────────────────────────
        // ═══════════════════════════════════════════════════════════════════════

        private void BuildUI()
        {
            // Propiedades del formulario
            Text = LocalizationManager.Get("StatusFormTitle");
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = Color.FromArgb(0xF5, 0xF5, 0xF5);
            ForeColor = Color.Black;
            Font = new Font("Segoe UI", 9f);
            AutoScaleMode = AutoScaleMode.Dpi;
            KeyPreview = true;
            KeyDown += OnKeyDown;

            // ═══════════════════════════════════════════════════════════════════
            // COLUMNA IZQUIERDA: Info General + Cloud + Servicios
            // ═══════════════════════════════════════════════════════════════════
            int yL = 12;

            AddSectionHeaderAt(LocalizationManager.Get("StatusSectionGeneralInfo"), LeftColX, ref yL);
            _valState = AddFieldRowAt(LocalizationManager.Get("StatusLabelState"), "...", LeftColX, ValueX, ref yL);
            _valVersion = AddFieldRowAt(LocalizationManager.Get("StatusLabelVersion"), "...", LeftColX, ValueX, ref yL);
            _valHostname = AddFieldRowAt("Hostname:", "...", LeftColX, ValueX, ref yL);
            _valIp = AddFieldRowAt("IP:", "...", LeftColX, ValueX, ref yL);
            _valQueue = AddFieldRowAt(LocalizationManager.Get("StatusLabelActiveQueue"), "...", LeftColX, ValueX, ref yL);
            _valQueueStatus = AddFieldRowAt(LocalizationManager.Get("StatusLabelQueueStatus"), "...", LeftColX, ValueX, ref yL);
            _valDriver = AddFieldRowAt(LocalizationManager.Get("StatusLabelDriver"), "...", LeftColX, ValueX, ref yL);
            _valConfig = AddFieldRowAt(LocalizationManager.Get("StatusLabelConfig"), "...", LeftColX, ValueX, ref yL);

            yL += SectionSpacing;
            AddSeparatorAt(LeftColX, LeftColWidth, ref yL);

            // ── Conectividad Cloud ──────────────────────────────────────────────
            AddSectionHeaderAt(LocalizationManager.Get("StatusSectionCloudConnectivity"), LeftColX, ref yL);
            _valCloudStatus = AddFieldRowAt(LocalizationManager.Get("StatusLabelCloudStatus"), "...", LeftColX, ValueX, ref yL);
            {
                var lblDetails = new Label
                {
                    Text = LocalizationManager.Get("StatusLabelCloudDetails"),
                    Location = new Point(LeftColX, yL),
                    AutoSize = true,
                    ForeColor = Color.FromArgb(0x55, 0x55, 0x55)
                };
                _valCloudDetails = new Label
                {
                    Text = "",
                    Location = new Point(ValueX, yL),
                    Size = new Size(LeftColWidth - ValueX + LeftColX, 36),
                    AutoSize = false,
                    AutoEllipsis = false,
                    ForeColor = Color.FromArgb(0x66, 0x66, 0x66)
                };
                Controls.Add(lblDetails);
                Controls.Add(_valCloudDetails);
                yL += 40;
            }

            yL += SectionSpacing;
            AddSeparatorAt(LeftColX, LeftColWidth, ref yL);

            // ── Servicios ───────────────────────────────────────────────────────
            AddSectionHeaderAt(LocalizationManager.Get("StatusSectionServices"), LeftColX, ref yL);
            BuildServicesSection(ref yL);

            // ═══════════════════════════════════════════════════════════════════
            // COLUMNA DERECHA: Acciones A Demanda + Progreso
            // ═══════════════════════════════════════════════════════════════════
            int yR = 12;

            AddSectionHeaderAt(LocalizationManager.Get("StatusSectionOnDemand"), RightColX, ref yR);
            BuildTriggersSection(ref yR);

            // ── Separador vertical (línea entre columnas) ───────────────────────
            var vertSep = new Label
            {
                Location = new Point(LeftColX + LeftColWidth + 10, 12),
                Size = new Size(1, Math.Max(yL, yR) - 24),
                BorderStyle = BorderStyle.Fixed3D
            };
            Controls.Add(vertSep);

            // ═══════════════════════════════════════════════════════════════════
            // PIE: Status + Botón Cerrar
            // ═══════════════════════════════════════════════════════════════════
            int yBottom = Math.Max(yL, yR) + SectionSpacing;

            // Separador horizontal antes del pie
            AddSeparatorAt(LeftColX, FormWidth - 32, ref yBottom);

            _lblStatus = new Label
            {
                Text = "",
                Location = new Point(LeftColX, yBottom),
                AutoSize = true,
                ForeColor = Color.FromArgb(0x00, 0x66, 0xCC),
                Font = new Font("Segoe UI", 9f, FontStyle.Italic),
                Visible = false
            };
            Controls.Add(_lblStatus);

            _btnClose = new Button
            {
                Text = LocalizationManager.Get("StatusButtonClose"),
                AutoSize = true,
                Padding = new Padding(12, 2, 12, 2),
                FlatStyle = FlatStyle.Standard
            };
            _btnClose.Click += (s, e) => Close();
            Controls.Add(_btnClose);
            _btnClose.Location = new Point(FormWidth - _btnClose.PreferredSize.Width - 20, yBottom);
            CancelButton = _btnClose;

            yBottom += 36 + 12;
            ClientSize = new Size(FormWidth, yBottom);
        }

        /// <summary>Construye la sección de triggers OnDemand (columna derecha).</summary>
        private void BuildTriggersSection(ref int y)
        {
            var triggers = OnDemandConfigReader.GetOnDemandTriggers();

            if (triggers.Count == 0)
            {
                var lbl = new Label
                {
                    Text = LocalizationManager.Get("StatusNoActionsAvailable"),
                    Location = new Point(RightColX, y),
                    AutoSize = true,
                    ForeColor = Color.Gray,
                    Font = new Font("Segoe UI", 9f, FontStyle.Italic)
                };
                Controls.Add(lbl);
                y += RowHeight;
                return;
            }

            int btnX = RightColX + RightColWidth - 90;
            foreach (var trigger in triggers)
            {
                var lbl = new Label
                {
                    Text = trigger.Label,
                    Location = new Point(RightColX, y + 4),
                    AutoSize = true
                };
                Controls.Add(lbl);

                var btn = new Button
                {
                    Text = LocalizationManager.Get("StatusButtonExecute"),
                    Location = new Point(btnX, y),
                    AutoSize = true,
                    Padding = new Padding(12, 2, 12, 2),
                    Tag = trigger,
                    FlatStyle = FlatStyle.Standard
                };
                btn.Click += OnTriggerExecuteClick;
                Controls.Add(btn);
                _allActionButtons.Add(btn);

                y += 32;
            }

            y += SectionSpacing;
            AddSeparatorAt(RightColX, RightColWidth, ref y);

            // ── Panel de progreso inline (siempre visible, se llena al ejecutar) ─
            _progressHeader = new Label
            {
                Text = "Progreso",
                Location = new Point(RightColX, y),
                Size = new Size(RightColWidth, 20),
                Font = new Font("Segoe UI", 8.5f, FontStyle.Bold),
                ForeColor = Color.FromArgb(0x66, 0x66, 0x66)
            };
            Controls.Add(_progressHeader);
            y += 22;

            _progressListView = new ListView
            {
                Location = new Point(RightColX, y),
                Size = new Size(RightColWidth, 180),
                View = View.Details,
                FullRowSelect = true,
                GridLines = true,
                HeaderStyle = ColumnHeaderStyle.Nonclickable,
                Font = new Font("Consolas", 8.25f),
            };
            _progressListView.Columns.Add("", 28);
            _progressListView.Columns.Add("Acción", 130);
            _progressListView.Columns.Add("Descripción", RightColWidth - 28 - 130 - 25);
            Controls.Add(_progressListView);
            y += 184;
        }

        /// <summary>Construye la sección de servicios monitoreados (columna izquierda).</summary>
        private void BuildServicesSection(ref int y)
        {
            var services = OnDemandConfigReader.GetMonitoredServices();
            var watchdogServices = OnDemandConfigReader.GetWatchdogServices();

            int stateX = LeftColX + 260;
            int watchdogX = LeftColX + 340;

            foreach (var svc in services)
            {
                var lblName = new Label
                {
                    Text = svc.DisplayName,
                    Location = new Point(LeftColX, y + 4),
                    Size = new Size(240, 20),
                    AutoEllipsis = true
                };
                Controls.Add(lblName);

                var lblState = new Label
                {
                    Text = "...",
                    Location = new Point(stateX, y + 4),
                    AutoSize = true,
                    ForeColor = Color.FromArgb(0x66, 0x66, 0x66)
                };
                Controls.Add(lblState);

                var watchdogEntry = watchdogServices.Find(w =>
                    w.Name.Equals(svc.ServiceName, StringComparison.OrdinalIgnoreCase));

                var lblWatchdog = new Label
                {
                    Text = "",
                    Location = new Point(watchdogX, y + 4),
                    AutoSize = true,
                    Font = new Font("Segoe UI", 8f)
                };
                Controls.Add(lblWatchdog);

                _serviceRows.Add(new ServiceRow
                {
                    Config = svc,
                    StateLabel = lblState,
                    WatchdogLabel = lblWatchdog,
                    WatchdogEntry = watchdogEntry
                });

                y += 28;
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ── Carga de datos ──────────────────────────────────────────────────────
        // ═══════════════════════════════════════════════════════════════════════

        private void LoadData()
        {
            if (_isClosing) return;

            try
            {
                // Información general
                bool contingency = IsContingencyEnabled();
                _valState.Text = contingency ? "🛡️ En Contingencia" : "🛡️ Normal";
                _valState.ForeColor = contingency
                    ? Color.FromArgb(0xE6, 0x7E, 0x00)   // Naranja
                    : Color.FromArgb(0x22, 0x8B, 0x22);   // Verde
                _valVersion.Text = System.Reflection.Assembly.GetExecutingAssembly()
                    .GetName().Version?.ToString() ?? "0.0.0.0";
                _valHostname.Text = AlwaysPrint.Shared.Network.NetworkHelper.GetHostname();
                _valIp.Text = AlwaysPrint.Shared.Network.NetworkHelper.GetOutboundLocalIP();
                _valQueue.Text = LoadQueueName();
                RefreshQueueStatus();
                _valDriver.Text = LoadDriverVersion();
                _valConfig.Text = LoadConfigName();

                // Conectividad Cloud (lectura inicial)
                RefreshCloudConnectivity();

                // Estados de servicios (lectura inicial)
                RefreshServiceStates();
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"StatusForm.LoadData: {ex.Message}", AlwaysPrintLogger.EvtGenericError);
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ── Timer de refresco de servicios ──────────────────────────────────────
        // ═══════════════════════════════════════════════════════════════════════

        private void SetupRefreshTimer()
        {
            _refreshTimer = new Timer { Interval = 5000 };
            _refreshTimer.Tick += OnRefreshTimerTick;
            _refreshTimer.Start();
        }

        /// <summary>
        /// Timer callback: refresca estados de servicios y estado de contingencia.
        /// ServiceController.Status es suficientemente rápido para esto.
        /// </summary>
        private void OnRefreshTimerTick(object? sender, EventArgs e)
        {
            // No refrescar si el form está cerrándose
            if (_isClosing || IsDisposed) return;

            try
            {
                RefreshServiceStates();
                RefreshContingencyState();
                RefreshQueueStatus();
                RefreshCloudConnectivity();
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"StatusForm.RefreshTimer: {ex.Message}", AlwaysPrintLogger.EvtGenericError);
            }
        }

        /// <summary>
        /// Actualiza el estado de contingencia leyendo el semáforo del registro.
        /// </summary>
        private void RefreshContingencyState()
        {
            bool contingency = IsContingencyEnabled();
            _valState.Text = contingency ? "🛡️ En Contingencia" : "🛡️ Normal";
            _valState.ForeColor = contingency
                ? Color.FromArgb(0xE6, 0x7E, 0x00)   // Naranja
                : Color.FromArgb(0x22, 0x8B, 0x22);   // Verde
        }

        /// <summary>
        /// Lee el estado de cada servicio con ServiceController y actualiza la UI.
        /// Solo muestra el estado en gris (sin colores ni botones de inicio).
        /// </summary>
        private void RefreshServiceStates()
        {
            bool contingencyActive = IsContingencyEnabled();

            foreach (var row in _serviceRows)
            {
                string state;
                try
                {
                    using (var sc = new System.ServiceProcess.ServiceController(row.Config.ServiceName))
                    {
                        sc.Refresh();
                        state = sc.Status.ToString();
                    }
                }
                catch
                {
                    state = "NotFound";
                }

                row.StateLabel.Text = state;
                row.StateLabel.ForeColor = Color.FromArgb(0x66, 0x66, 0x66); // Siempre gris

                // Actualizar indicador de watchdog según modo actual
                if (row.WatchdogEntry == null)
                {
                    row.WatchdogLabel.Text = "";
                }
                else
                {
                    bool watchdogActive = IsWatchdogActiveForEntry(row.WatchdogEntry, contingencyActive);
                    row.WatchdogLabel.Text = watchdogActive ? "🔄 Watchdog" : "";
                    row.WatchdogLabel.ForeColor = Color.FromArgb(0x22, 0x8B, 0x22); // Verde
                }
            }
        }

        /// <summary>
        /// Determina si el watchdog está activo para una entrada según el modo operativo actual.
        /// </summary>
        private static bool IsWatchdogActiveForEntry(WatchdogServiceEntry entry, bool contingencyActive)
        {
            switch (entry.MonitorWhen?.ToLowerInvariant())
            {
                case "normal": return !contingencyActive;
                case "contingency": return contingencyActive;
                case "always":
                default: return true;
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ── Conectividad Cloud ──────────────────────────────────────────────────
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Refresca la sección de conectividad Cloud consultando al provider.
        /// </summary>
        private void RefreshCloudConnectivity()
        {
            if (_connectivityStateProvider == null)
            {
                // Sin provider: mostrar como conectado (CloudManager activo directamente)
                ApplyCloudConnectedViaManager();
                return;
            }

            var state = _connectivityStateProvider();
            if (state != null)
            {
                ApplyCloudConnectivityState(state);
            }
            else
            {
                // Provider retornó null: CloudRegistration ya no existe (registro completado),
                // CloudManager tomó el control → mostrar como conectado
                ApplyCloudConnectedViaManager();
            }
        }

        /// <summary>
        /// Muestra estado "Conectado" cuando CloudManager ya está activo
        /// (no hay CloudRegistration porque CloudEnabled=1).
        /// </summary>
        private void ApplyCloudConnectedViaManager()
        {
            _valCloudStatus.Text = LocalizationManager.Get("StatusCloudConnected");
            _valCloudStatus.ForeColor = Color.FromArgb(0x22, 0x8B, 0x22); // Verde
            _valCloudDetails.Text = LoadCloudServerUrl();
            _valCloudDetails.ForeColor = Color.FromArgb(0x66, 0x66, 0x66);
            _valCloudDetails.Visible = true;
        }

        /// <summary>
        /// Aplica un CloudConnectivityState a los controles de la sección Cloud.
        /// </summary>
        private void ApplyCloudConnectivityState(CloudConnectivityState state)
        {
            switch (state.Status)
            {
                case "Connected":
                    _valCloudStatus.Text = FormatConnectedStatus(state);
                    _valCloudStatus.ForeColor = Color.FromArgb(0x22, 0x8B, 0x22); // Verde
                    _valCloudDetails.Text = LoadCloudServerUrl();
                    _valCloudDetails.ForeColor = Color.FromArgb(0x66, 0x66, 0x66);
                    _valCloudDetails.Visible = true;
                    break;

                case "Connecting":
                    _valCloudStatus.Text = LocalizationManager.Get("StatusCloudConnecting");
                    _valCloudStatus.ForeColor = Color.FromArgb(0x00, 0x66, 0xCC); // Azul
                    _valCloudDetails.Text = "";
                    _valCloudDetails.Visible = false;
                    break;

                case "Disconnected":
                    _valCloudStatus.Text = FormatDisconnectedStatus(state);
                    _valCloudStatus.ForeColor = Color.FromArgb(0xCC, 0x33, 0x00); // Rojo
                    _valCloudDetails.Text = FormatDisconnectedDetails(state);
                    _valCloudDetails.ForeColor = Color.FromArgb(0x66, 0x66, 0x66);
                    _valCloudDetails.Visible = true;
                    break;

                default:
                    _valCloudStatus.Text = state.Status;
                    _valCloudStatus.ForeColor = Color.FromArgb(0x66, 0x66, 0x66);
                    _valCloudDetails.Text = "";
                    _valCloudDetails.Visible = false;
                    break;
            }
        }

        /// <summary>
        /// <summary>
        /// Formatea una duración en formato compacto: "Xd Xh Xm Xs" (omitiendo componentes en cero).
        /// </summary>
        private static string FormatDuration(TimeSpan dur)
        {
            if (dur.TotalDays >= 1)
                return $"{(int)dur.TotalDays}d {dur.Hours}h {dur.Minutes}m";
            if (dur.TotalHours >= 1)
                return $"{(int)dur.TotalHours}h {dur.Minutes}m {dur.Seconds}s";
            if (dur.TotalMinutes >= 1)
                return $"{(int)dur.TotalMinutes}m {dur.Seconds}s";
            return $"{dur.Seconds}s";
        }

        /// <summary>
        /// Formatea el texto principal de estado cuando está conectado.
        /// Ejemplo: "✓ Conectado (2h 15m 3s)"
        /// </summary>
        private static string FormatConnectedStatus(CloudConnectivityState state)
        {
            string text = LocalizationManager.Get("StatusCloudConnected");
            if (state.ConnectedDuration.HasValue)
            {
                text += $" ({FormatDuration(state.ConnectedDuration.Value)})";
            }
            return text;
        }

        /// <summary>
        /// Formatea el texto principal de estado cuando está desconectado.
        /// Ejemplo: "⚠ Desconectado (3 intentos, 1m 30s)"
        /// </summary>
        private static string FormatDisconnectedStatus(CloudConnectivityState state)
        {
            var parts = new List<string>();
            parts.Add(string.Format(
                LocalizationManager.Get("StatusCloudAttempts"),
                state.FailedAttempts));

            if (state.DisconnectedDuration.HasValue)
            {
                parts.Add(FormatDuration(state.DisconnectedDuration.Value));
            }

            return $"{LocalizationManager.Get("StatusCloudDisconnected")} ({string.Join(", ", parts)})";
        }

        /// <summary>
        /// Formatea los detalles del error de conectividad.
        /// Ejemplo: "Próximo reintento en 30s — timeout (10 s)"
        /// </summary>
        private static string FormatDisconnectedDetails(CloudConnectivityState state)
        {
            var parts = new List<string>();

            parts.Add(string.Format(
                LocalizationManager.Get("StatusCloudNextRetry"),
                state.CurrentRetryIntervalSeconds));

            // Extraer solo la parte relevante del error (sin la URL completa)
            if (!string.IsNullOrWhiteSpace(state.LastError))
            {
                string shortError = state.LastError;
                // Truncar si es muy largo para la UI
                if (shortError.Length > 80)
                    shortError = shortError.Substring(0, 77) + "...";
                parts.Add(shortError);
            }

            return string.Join(" — ", parts);
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ── Ejecución de trigger OnDemand ───────────────────────────────────────
        // ═══════════════════════════════════════════════════════════════════════

        private void OnTriggerExecuteClick(object? sender, EventArgs e)
        {
            var btn = sender as Button;
            if (btn == null) return;
            var trigger = btn.Tag as OnDemandTriggerInfo;
            if (trigger == null) return;

            // Confirmación del usuario
            var result = MessageBox.Show(
                this,
                trigger.Description,
                trigger.Label,
                MessageBoxButtons.OKCancel,
                MessageBoxIcon.Question);

            if (result != DialogResult.OK) return;

            // Activar estado busy global y mostrar panel de progreso
            SetBusyState(true);
            ShowProgressPanel(trigger.Label);

            // Suscribirse temporalmente a push messages para capturar progreso en tiempo real
            Action<PipeMessage> progressHandler = null!;
            progressHandler = (msg) =>
            {
                if (msg.Type != MessageType.OnDemandActionProgress) return;
                var payload = msg.GetPayload<OnDemandActionProgressPayload>();
                if (payload == null || payload.TriggerLabel != trigger.Label) return;

                // Actualizar UI desde cualquier hilo
                BeginInvoke(new Action(() => AddProgressStep(payload)));
            };
            _pipe.MessageReceived += progressHandler;

            // Ejecutar en BackgroundWorker para no bloquear UI
            var worker = new BackgroundWorker();
            worker.DoWork += (s, args) =>
            {
                if (!_pipe.IsConnected)
                {
                    args.Result = new OperationResult { Success = false, Message = "El servicio no está accesible." };
                    return;
                }

                var payload = new ExecuteOnDemandTriggerPayload { Label = trigger.Label };
                var request = PipeMessage.Create(MessageType.ExecuteOnDemandTrigger, payload);
                var response = _pipe.Send(request);

                if (response?.Type == MessageType.Ack)
                {
                    var ack = response.GetPayload<AckPayload>();
                    if (ack?.Success == true)
                        args.Result = new OperationResult { Success = true, Message = $"✓ {trigger.Label} ejecutado correctamente." };
                    else
                        args.Result = new OperationResult { Success = false, Message = $"Error: {ack?.Message ?? "desconocido"}" };
                }
                else
                {
                    var error = response?.GetPayload<ErrorPayload>();
                    args.Result = new OperationResult { Success = false, Message = $"Error: {error?.Message ?? "respuesta inesperada"}" };
                }
            };
            worker.RunWorkerCompleted += (s, args) =>
            {
                // Desuscribirse de push messages
                _pipe.MessageReceived -= progressHandler;
                SetBusyState(false);

                if (args.Error != null)
                {
                    UpdateProgressHeader(false, args.Error.Message);
                }
                else if (args.Result is OperationResult opResult)
                {
                    UpdateProgressHeader(opResult.Success, opResult.Message);
                }

                // Escribir resumen de pasos en log del Tray
                LogProgressSummary(trigger.Label);

                worker.Dispose();
            };
            worker.RunWorkerAsync();
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ── Panel de progreso inline ────────────────────────────────────────────
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Muestra el panel de progreso con el nombre del trigger que se va a ejecutar.
        /// Limpia contenido anterior.
        /// </summary>
        private void ShowProgressPanel(string triggerLabel)
        {
            _progressSteps.Clear();
            _progressListView.Items.Clear();
            _progressHeader.Text = $"⏳ Ejecutando: {triggerLabel}";
            _progressHeader.ForeColor = Color.FromArgb(0x00, 0x66, 0xCC);
        }

        /// <summary>
        /// Agrega un paso de progreso al ListView inline. Thread-safe (debe llamarse via BeginInvoke).
        /// </summary>
        private void AddProgressStep(OnDemandActionProgressPayload progress)
        {
            if (IsDisposed) return;

            // Mensaje de finalización — actualizar header
            if (progress.IsComplete)
            {
                UpdateProgressHeader(progress.OverallSuccess,
                    progress.OverallSuccess
                        ? $"✓ Completado ({progress.DurationMs}ms)"
                        : $"✗ Falló ({progress.DurationMs}ms)");
                return;
            }

            _progressSteps.Add(progress);

            string statusIcon = progress.Status switch
            {
                "running" => "⏳",
                "ok" => "✓",
                "error" => "✗",
                _ => "·"
            };

            // Si el paso está "running", buscar si ya existe para actualizarlo
            if (progress.Status != "running")
            {
                // Buscar item "running" del mismo tipo para actualizar
                for (int i = _progressListView.Items.Count - 1; i >= 0; i--)
                {
                    var item = _progressListView.Items[i];
                    if (item.SubItems[1].Text == progress.ActionType && item.SubItems[0].Text == "⏳")
                    {
                        item.SubItems[0].Text = statusIcon;
                        item.ForeColor = progress.Status == "ok" ? Color.DarkGreen : Color.DarkRed;
                        return;
                    }
                }
            }

            // Agregar nuevo item
            var newItem = new ListViewItem(statusIcon);
            newItem.SubItems.Add(progress.ActionType);
            newItem.SubItems.Add(progress.StepName);
            newItem.ForeColor = progress.Status == "running" ? Color.DarkBlue
                : progress.Status == "ok" ? Color.DarkGreen : Color.DarkRed;
            _progressListView.Items.Add(newItem);
            _progressListView.EnsureVisible(_progressListView.Items.Count - 1);
        }

        /// <summary>
        /// Actualiza el header del panel de progreso con el resultado final.
        /// </summary>
        private void UpdateProgressHeader(bool success, string message)
        {
            if (IsDisposed) return;
            _progressHeader.Text = message;
            _progressHeader.ForeColor = success
                ? Color.FromArgb(0x22, 0x8B, 0x22)   // Verde
                : Color.FromArgb(0xCC, 0x33, 0x00);   // Rojo
        }

        /// <summary>
        /// Escribe un resumen de los pasos ejecutados en el log del Tray.
        /// Solo incluye pasos con estado final (ok/error), no los intermedios (running).
        /// Formato: una línea por paso con [✓] o [✗] y la descripción.
        /// </summary>
        private void LogProgressSummary(string triggerLabel)
        {
            try
            {
                // Filtrar solo pasos con resultado final (no "running")
                var finalSteps = _progressSteps.FindAll(s => s.Status == "ok" || s.Status == "error");
                if (finalSteps.Count == 0) return;

                int okCount = finalSteps.FindAll(s => s.Status == "ok").Count;
                int errorCount = finalSteps.FindAll(s => s.Status == "error").Count;

                var lines = new System.Text.StringBuilder();
                lines.AppendLine($"OnDemand '{triggerLabel}' — {finalSteps.Count} pasos ({okCount} ok, {errorCount} error):");

                foreach (var step in finalSteps)
                {
                    string icon = step.Status == "ok" ? "✓" : "✗";
                    lines.AppendLine($"  [{icon}] {step.ActionType}: {step.StepName}");
                }

                AlwaysPrintLogger.WriteTrayInfo(lines.ToString().TrimEnd());
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"StatusForm.LogProgressSummary: error escribiendo resumen: {ex.Message}");
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ── Estado busy global ──────────────────────────────────────────────────
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Activa o desactiva el estado busy global.
        /// Deshabilita todos los botones de acción y muestra/oculta la etiqueta de estado.
        /// </summary>
        private void SetBusyState(bool busy)
        {
            _isBusy = busy;

            foreach (var btn in _allActionButtons)
                btn.Enabled = !busy;

            _btnClose.Enabled = !busy;

            _lblStatus.Text = busy ? "Ejecutando..." : "";
            _lblStatus.Visible = busy;
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ── Helpers de datos ────────────────────────────────────────────────────
        // ═══════════════════════════════════════════════════════════════════════

        private bool IsContingencyEnabled()
        {
            try
            {
                using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                    RegistryConfigManager.RegistryPath))
                {
                    var val = key?.GetValue("ContingencyEnabled");
                    return val?.ToString() == "1";
                }
            }
            catch { return false; }
        }

        private string LoadQueueName()
        {
            try
            {
                using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                    RegistryConfigManager.RegistryPath))
                {
                    return key?.GetValue("CorporateQueueName")?.ToString() ?? "N/A";
                }
            }
            catch { return "N/A"; }
        }

        /// <summary>
        /// Refresca el estado de la cola corporativa (Activa/Pausada/Offline) con color.
        /// Usa WMI Win32_Printer.PrinterState para detectar pausa (bit 0x1 = Paused).
        /// </summary>
        private void RefreshQueueStatus()
        {
            try
            {
                string queueName = LoadQueueName();
                if (queueName == "N/A")
                {
                    _valQueueStatus.Text = "N/A";
                    _valQueueStatus.ForeColor = Color.FromArgb(0x66, 0x66, 0x66);
                    return;
                }

                using (var searcher = new System.Management.ManagementObjectSearcher(
                    @"\\.\root\cimv2",
                    $"SELECT PrinterState, WorkOffline FROM Win32_Printer WHERE Name = '{queueName.Replace("'", "''")}'"))
                {
                    foreach (System.Management.ManagementObject obj in searcher.Get())
                    {
                        uint printerState = Convert.ToUInt32(obj["PrinterState"] ?? 0);
                        bool offline = Convert.ToBoolean(obj["WorkOffline"] ?? false);

                        // PrinterState bit flags: 0x1 = Paused, 0x2 = Error, 0x8 = Offline
                        bool paused = (printerState & 0x1) != 0;

                        if (paused)
                        {
                            _valQueueStatus.Text = "\u23F8 Pausada";
                            _valQueueStatus.ForeColor = Color.FromArgb(0xE6, 0x7E, 0x00); // Naranja
                        }
                        else if (offline)
                        {
                            _valQueueStatus.Text = "\u26A0 Offline";
                            _valQueueStatus.ForeColor = Color.FromArgb(0xCC, 0x33, 0x00); // Rojo
                        }
                        else
                        {
                            _valQueueStatus.Text = "\u2713 Activa";
                            _valQueueStatus.ForeColor = Color.FromArgb(0x22, 0x8B, 0x22); // Verde
                        }
                        return;
                    }
                }

                // Cola no encontrada en WMI
                _valQueueStatus.Text = "No encontrada";
                _valQueueStatus.ForeColor = Color.FromArgb(0xCC, 0x33, 0x00);
            }
            catch
            {
                _valQueueStatus.Text = "Error";
                _valQueueStatus.ForeColor = Color.FromArgb(0x66, 0x66, 0x66);
            }
        }

        /// <summary>
        /// Lee la versión del driver de la cola corporativa.
        /// Busca el valor DriverVersion directamente en el registro de drivers de impresión:
        /// HKLM\SYSTEM\CurrentControlSet\Control\Print\Environments\{arch}\Drivers\Version-3\{DriverName}
        /// </summary>
        private string LoadDriverVersion()
        {
            try
            {
                string queueName = LoadQueueName();
                if (queueName == "N/A") return "N/A";

                // 1. Obtener nombre del driver desde Win32_Printer
                string driverName;
                using (var searcher = new System.Management.ManagementObjectSearcher(
                    @"\\.\root\cimv2",
                    $"SELECT DriverName FROM Win32_Printer WHERE Name = '{queueName.Replace("'", "''")}'"))
                {
                    driverName = null;
                    foreach (System.Management.ManagementObject obj in searcher.Get())
                    {
                        driverName = obj["DriverName"]?.ToString();
                        break;
                    }
                }

                if (string.IsNullOrEmpty(driverName)) return "N/A";

                // 2. Leer DriverVersion del registro (valor REG_SZ directo)
                string[] envPaths = new[]
                {
                    $@"SYSTEM\CurrentControlSet\Control\Print\Environments\Windows x64\Drivers\Version-3\{driverName}",
                    $@"SYSTEM\CurrentControlSet\Control\Print\Environments\Windows x64\Drivers\Version-4\{driverName}",
                    $@"SYSTEM\CurrentControlSet\Control\Print\Environments\Windows NT x86\Drivers\Version-3\{driverName}"
                };

                foreach (var regPath in envPaths)
                {
                    using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(regPath))
                    {
                        if (key == null) continue;

                        string version = key.GetValue("DriverVersion")?.ToString() ?? "";
                        if (!string.IsNullOrEmpty(version))
                            return $"{driverName} ({version})";
                    }
                }

                // Sin DriverVersion en registro, retornar solo el nombre
                return driverName;
            }
            catch { return "Error"; }
        }

        private string LoadConfigName()
        {
            try
            {
                string filePath = PipeConstants.ActionConfigFilePath;
                if (!System.IO.File.Exists(filePath)) return "Sin configuración";
                var json = System.IO.File.ReadAllText(filePath);

                // Si es envelope firmado, extraer config interno
                string configJson = json;
                try
                {
                    var parsed = Newtonsoft.Json.Linq.JObject.Parse(json);
                    if (parsed["config"] != null && parsed["hash"] != null &&
                        parsed["signature"] != null && parsed["cert_version"] != null)
                    {
                        configJson = parsed["config"]!.ToString(Newtonsoft.Json.Formatting.None);
                    }
                }
                catch (Newtonsoft.Json.JsonException) { }

                var config = Newtonsoft.Json.JsonConvert.DeserializeObject<ActionConfiguration>(configJson);
                if (config == null) return "Sin configuración";
                return StatusDisplayHelper.FormatConfigDisplay(
                    string.IsNullOrWhiteSpace(config.Name) ? "Desconocida" : config.Name,
                    string.IsNullOrWhiteSpace(config.Version) ? "?" : config.Version);
            }
            catch { return "Error al leer"; }
        }

        /// <summary>
        /// Obtiene la URL del servidor Cloud desde el registro (CloudApiUrl).
        /// Retorna solo el host para mostrar en la UI.
        /// </summary>
        private string LoadCloudServerUrl()
        {
            try
            {
                using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                    RegistryConfigManager.RegistryPath))
                {
                    string? url = key?.GetValue("CloudApiUrl")?.ToString();
                    if (string.IsNullOrEmpty(url)) return "";
                    var uri = new Uri(url);
                    return uri.Host;
                }
            }
            catch { return ""; }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ── Helpers de layout ───────────────────────────────────────────────────
        // ═══════════════════════════════════════════════════════════════════════

        private void AddSectionHeaderAt(string text, int x, ref int y)
        {
            var lbl = new Label
            {
                Text = text,
                Location = new Point(x, y),
                AutoSize = true,
                Font = new Font("Segoe UI Semibold", 10f, FontStyle.Bold),
                ForeColor = Color.FromArgb(0x00, 0x66, 0xCC)
            };
            Controls.Add(lbl);
            y += 26;
        }

        private Label AddFieldRowAt(string label, string value, int x, int valueX, ref int y)
        {
            var lbl = new Label
            {
                Text = label,
                Location = new Point(x, y),
                AutoSize = true,
                ForeColor = Color.FromArgb(0x55, 0x55, 0x55)
            };
            var val = new Label
            {
                Text = value,
                Location = new Point(valueX, y),
                AutoSize = true,
                ForeColor = Color.Black
            };
            Controls.Add(lbl);
            Controls.Add(val);
            y += RowHeight;
            return val;
        }

        private void AddSeparatorAt(int x, int width, ref int y)
        {
            var sep = new Label
            {
                Location = new Point(x, y),
                Size = new Size(width, 1),
                BorderStyle = BorderStyle.Fixed3D
            };
            Controls.Add(sep);
            y += SectionSpacing;
        }

        // Helpers legacy (mantener compatibilidad con código existente que use las versiones sin "At")
        private void AddSectionHeader(string text, ref int y) => AddSectionHeaderAt(text, LeftColX, ref y);
        private Label AddFieldRow(string label, string value, ref int y) => AddFieldRowAt(label, value, LeftColX, ValueX, ref y);
        private void AddSeparator(ref int y) => AddSeparatorAt(LeftColX, LeftColWidth, ref y);

        // ═══════════════════════════════════════════════════════════════════════
        // ── Eventos del formulario ──────────────────────────────────────────────
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Escape se maneja via CancelButton → Close() → OnFormClosing (cierre graceful).
        /// No hacer nada extra aquí para evitar doble cierre.
        /// </summary>
        private void OnKeyDown(object? sender, KeyEventArgs e)
        {
            // CancelButton = _btnClose ya maneja Escape → Click → Close() → OnFormClosing
        }

        /// <summary>
        /// Cierre graceful: cancela el close actual, muestra estado "Cerrando...",
        /// detiene el timer de refresco y espera un tick para que operaciones
        /// pendientes (WMI/ServiceController) en el message pump completen.
        /// Esto evita el freeze al abrir/cerrar rápidamente.
        /// </summary>
        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            // Si ya estamos en proceso de cierre graceful, dejar que cierre
            if (_isClosing)
            {
                base.OnFormClosing(e);
                return;
            }

            // Si está busy (ejecutando acción OnDemand), no permitir cerrar
            if (_isBusy)
            {
                e.Cancel = true;
                return;
            }

            // Iniciar cierre graceful: cancelar el close actual, mostrar estado "Cerrando..."
            e.Cancel = true;
            _isClosing = true;

            // Detener el timer de refresco inmediatamente para evitar más operaciones WMI
            _refreshTimer?.Stop();

            // Mostrar estado visual de cierre
            _btnClose.Text = "Cerrando...";
            _btnClose.Enabled = false;
            Cursor = Cursors.WaitCursor;

            // Deshabilitar todos los botones de acción
            foreach (var btn in _allActionButtons)
                btn.Enabled = false;

            // Usar un timer de un solo disparo para dar tiempo a que cualquier operación
            // pendiente en el message pump complete, luego cerrar definitivamente
            var closeTimer = new Timer { Interval = 150 };
            closeTimer.Tick += (s, args) =>
            {
                closeTimer.Stop();
                closeTimer.Dispose();
                Cursor = Cursors.Default;
                Close(); // Ahora _isClosing = true, así que pasará al base.OnFormClosing
            };
            closeTimer.Start();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _refreshTimer?.Stop();
                _refreshTimer?.Dispose();
            }
            base.Dispose(disposing);
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ── Estructura interna de resultado de operación ────────────────────────
        // ═══════════════════════════════════════════════════════════════════════

        private class OperationResult
        {
            public bool Success { get; set; }
            public string Message { get; set; } = string.Empty;
        }
    }
}
