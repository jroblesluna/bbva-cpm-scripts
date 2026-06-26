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
        private const int FormWidth = 680;
        private const int LabelX = 16;
        private const int ValueX = 150;
        private const int ServiceNameWidth = 350;
        private const int StateX = 380;
        private const int ButtonX = 490;
        private const int RowHeight = 24;
        private const int SectionSpacing = 12;

        // ── Dependencias ────────────────────────────────────────────────────────
        private readonly PipeClient _pipe;
        private readonly Func<CloudConnectivityState?>? _connectivityStateProvider;

        // ── Controles de información general ────────────────────────────────────
        private Label _valState = null!;
        private Label _valVersion = null!;
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

        // ── Estado global busy ──────────────────────────────────────────────────
        private bool _isBusy;

        // ── Timer para refrescar estados de servicios ───────────────────────────
        private Timer _refreshTimer = null!;

        // ── Estructura interna para fila de servicio ────────────────────────────
        private class ServiceRow
        {
            public MonitoredServiceConfig Config { get; set; } = null!;
            public Label StateLabel { get; set; } = null!;
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

            int y = 12;

            // ── Sección A: Información General ──────────────────────────────────
            AddSectionHeader(LocalizationManager.Get("StatusSectionGeneralInfo"), ref y);
            _valState = AddFieldRow(LocalizationManager.Get("StatusLabelState"), "...", ref y);
            _valVersion = AddFieldRow(LocalizationManager.Get("StatusLabelVersion"), "...", ref y);
            _valQueue = AddFieldRow(LocalizationManager.Get("StatusLabelActiveQueue"), "...", ref y);
            _valQueueStatus = AddFieldRow(LocalizationManager.Get("StatusLabelQueueStatus"), "...", ref y);
            _valDriver = AddFieldRow(LocalizationManager.Get("StatusLabelDriver"), "...", ref y);
            _valConfig = AddFieldRow(LocalizationManager.Get("StatusLabelConfig"), "...", ref y);

            y += SectionSpacing;
            AddSeparator(ref y);

            // ── Sección A2: Conectividad Cloud ──────────────────────────────────
            AddSectionHeader(LocalizationManager.Get("StatusSectionCloudConnectivity"), ref y);
            _valCloudStatus = AddFieldRow(LocalizationManager.Get("StatusLabelCloudStatus"), "...", ref y);
            // Detalles con word-wrap (ancho fijo para que no se salga del formulario)
            {
                var lblDetails = new Label
                {
                    Text = LocalizationManager.Get("StatusLabelCloudDetails"),
                    Location = new Point(LabelX, y),
                    AutoSize = true,
                    ForeColor = Color.FromArgb(0x55, 0x55, 0x55)
                };
                _valCloudDetails = new Label
                {
                    Text = "",
                    Location = new Point(ValueX, y),
                    Size = new Size(FormWidth - ValueX - 20, 36),
                    AutoSize = false,
                    AutoEllipsis = false,
                    ForeColor = Color.FromArgb(0x66, 0x66, 0x66)
                };
                Controls.Add(lblDetails);
                Controls.Add(_valCloudDetails);
                y += 40; // Espacio extra para 2 líneas de texto
            }

            y += SectionSpacing;
            AddSeparator(ref y);

            // ── Sección B: Acciones A Demanda ───────────────────────────────────
            AddSectionHeader(LocalizationManager.Get("StatusSectionOnDemand"), ref y);
            BuildTriggersSection(ref y);

            y += SectionSpacing;
            AddSeparator(ref y);

            // ── Sección C: Servicios ────────────────────────────────────────────
            AddSectionHeader(LocalizationManager.Get("StatusSectionServices"), ref y);
            BuildServicesSection(ref y);

            y += SectionSpacing;
            AddSeparator(ref y);

            // ── Etiqueta de estado (busy) ───────────────────────────────────────
            _lblStatus = new Label
            {
                Text = "",
                Location = new Point(LabelX, y),
                AutoSize = true,
                ForeColor = Color.FromArgb(0x00, 0x66, 0xCC),
                Font = new Font("Segoe UI", 9f, FontStyle.Italic),
                Visible = false
            };
            Controls.Add(_lblStatus);

            // ── Botón Cerrar (bottom-right) ─────────────────────────────────────
            y += 28;
            _btnClose = new Button
            {
                Text = LocalizationManager.Get("StatusButtonClose"),
                AutoSize = true,
                Padding = new Padding(12, 2, 12, 2),
                FlatStyle = FlatStyle.Standard
            };
            _btnClose.Click += (s, e) => Close();
            Controls.Add(_btnClose);
            // Posicionar después de AutoSize
            _btnClose.Location = new Point(FormWidth - _btnClose.PreferredSize.Width - 20, y);
            CancelButton = _btnClose;

            // ── Calcular alto total del formulario ──────────────────────────────
            y += 36 + 24;
            ClientSize = new Size(FormWidth, y);
        }

        /// <summary>Construye la sección de triggers OnDemand.</summary>
        private void BuildTriggersSection(ref int y)
        {
            var triggers = OnDemandConfigReader.GetOnDemandTriggers();

            if (triggers.Count == 0)
            {
                var lbl = new Label
                {
                    Text = LocalizationManager.Get("StatusNoActionsAvailable"),
                    Location = new Point(LabelX, y),
                    AutoSize = true,
                    ForeColor = Color.Gray,
                    Font = new Font("Segoe UI", 9f, FontStyle.Italic)
                };
                Controls.Add(lbl);
                y += RowHeight;
                return;
            }

            foreach (var trigger in triggers)
            {
                // Etiqueta del trigger
                var lbl = new Label
                {
                    Text = trigger.Label,
                    Location = new Point(LabelX, y + 4),
                    AutoSize = true
                };
                Controls.Add(lbl);

                // Botón "Ejecutar"
                var btn = new Button
                {
                    Text = LocalizationManager.Get("StatusButtonExecute"),
                    Location = new Point(ButtonX, y),
                    AutoSize = true,
                    Padding = new Padding(12, 2, 12, 2),
                    Tag = trigger,
                    FlatStyle = FlatStyle.Standard
                };
                btn.Click += OnTriggerExecuteClick;
                Controls.Add(btn);
                _allActionButtons.Add(btn);

                y += 36;
            }
        }

        /// <summary>Construye la sección de servicios monitoreados.</summary>
        private void BuildServicesSection(ref int y)
        {
            var services = OnDemandConfigReader.GetMonitoredServices();

            foreach (var svc in services)
            {
                // Nombre del servicio (con ancho máximo para no invadir columna de estado)
                var lblName = new Label
                {
                    Text = svc.DisplayName,
                    Location = new Point(LabelX, y + 4),
                    Size = new Size(ServiceNameWidth, 24),
                    AutoEllipsis = true
                };
                Controls.Add(lblName);

                // Estado del servicio (siempre gris, solo lectura)
                var lblState = new Label
                {
                    Text = "...",
                    Location = new Point(StateX, y + 4),
                    AutoSize = true,
                    ForeColor = Color.FromArgb(0x66, 0x66, 0x66)
                };
                Controls.Add(lblState);

                _serviceRows.Add(new ServiceRow
                {
                    Config = svc,
                    StateLabel = lblState
                });

                y += 36;
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ── Carga de datos ──────────────────────────────────────────────────────
        // ═══════════════════════════════════════════════════════════════════════

        private void LoadData()
        {
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
            _valCloudDetails.Text = "";
            _valCloudDetails.Visible = false;
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
                    _valCloudDetails.Text = "";
                    _valCloudDetails.Visible = false;
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

            // Activar estado busy global
            SetBusyState(true);

            // Ejecutar en BackgroundWorker para evitar deadlocks
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
                SetBusyState(false);

                if (args.Error != null)
                {
                    MessageBox.Show(this, $"Error: {args.Error.Message}", "Error",
                        MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
                else if (args.Result is OperationResult opResult)
                {
                    var icon = opResult.Success ? MessageBoxIcon.Information : MessageBoxIcon.Warning;
                    var title = opResult.Success ? "OK" : "Error";
                    MessageBox.Show(this, opResult.Message, title, MessageBoxButtons.OK, icon);
                }

                worker.Dispose();
            };
            worker.RunWorkerAsync();
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
                var config = Newtonsoft.Json.JsonConvert.DeserializeObject<ActionConfiguration>(json);
                if (config == null) return "Sin configuración";
                return StatusDisplayHelper.FormatConfigDisplay(
                    string.IsNullOrWhiteSpace(config.Name) ? "Desconocida" : config.Name,
                    string.IsNullOrWhiteSpace(config.Version) ? "?" : config.Version);
            }
            catch { return "Error al leer"; }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ── Helpers de layout ───────────────────────────────────────────────────
        // ═══════════════════════════════════════════════════════════════════════

        private void AddSectionHeader(string text, ref int y)
        {
            var lbl = new Label
            {
                Text = text,
                Location = new Point(12, y),
                AutoSize = true,
                Font = new Font("Segoe UI Semibold", 10f, FontStyle.Bold),
                ForeColor = Color.FromArgb(0x00, 0x66, 0xCC)
            };
            Controls.Add(lbl);
            y += 26;
        }

        private Label AddFieldRow(string label, string value, ref int y)
        {
            var lbl = new Label
            {
                Text = label,
                Location = new Point(LabelX, y),
                AutoSize = true,
                ForeColor = Color.FromArgb(0x55, 0x55, 0x55)
            };
            var val = new Label
            {
                Text = value,
                Location = new Point(ValueX, y),
                AutoSize = true,
                ForeColor = Color.Black
            };
            Controls.Add(lbl);
            Controls.Add(val);
            y += RowHeight;
            return val;
        }

        private void AddSeparator(ref int y)
        {
            var sep = new Label
            {
                Location = new Point(12, y),
                Size = new Size(FormWidth - 24, 1),
                BorderStyle = BorderStyle.Fixed3D
            };
            Controls.Add(sep);
            y += SectionSpacing;
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ── Eventos del formulario ──────────────────────────────────────────────
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>Escape cierra el formulario.</summary>
        private void OnKeyDown(object? sender, KeyEventArgs e)
        {
            if (e.KeyCode == Keys.Escape)
                Close();
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
