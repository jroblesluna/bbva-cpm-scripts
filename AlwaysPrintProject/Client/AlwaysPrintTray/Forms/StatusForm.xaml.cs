using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Reflection;
using System.Threading.Tasks;
using System.Windows;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintTray.Localization;
using AlwaysPrintTray.OnDemand;
using AlwaysPrintTray.Pipe;
using Microsoft.Win32;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.Forms
{
    /// <summary>
    /// Formulario de estado del sistema AlwaysPrint (WPF).
    /// Muestra información general, estado de servicios y triggers OnDemand disponibles.
    /// Diseñado como no modal con control de instancia única (singleton).
    /// </summary>
    public partial class StatusForm : Window, INotifyPropertyChanged
    {
        private readonly PipeClient _pipe;

        // ── Campos de respaldo para propiedades con notificación ──

        private string _estadoSistema = "Normal";
        private string _versionApp = string.Empty;
        private string _colaActiva = string.Empty;
        private string _configActiva = string.Empty;

        public StatusForm(PipeClient pipe)
        {
            _pipe = pipe ?? throw new ArgumentNullException(nameof(pipe));

            Servicios = new ObservableCollection<ServiceStatusItem>();
            TriggersOnDemand = new ObservableCollection<OnDemandTriggerItem>();

            InitializeComponent();
            DataContext = this;
            Title = LocalizationManager.Get("StatusFormTitle");

            // Cargar información general al abrir el formulario
            LoadGeneralInfo();

            // Cargar estado de servicios monitoreados
            _ = LoadServiciosAsync();

            // Cargar triggers OnDemand disponibles
            LoadTriggersOnDemand();

            // Timer para refrescar estado de servicios cada 5 segundos
            _refreshTimer = new System.Windows.Threading.DispatcherTimer
            {
                Interval = TimeSpan.FromSeconds(5)
            };
            _refreshTimer.Tick += async (s, e) => await RefreshServiciosEstadoAsync();
            _refreshTimer.Start();

            // Detener timer al cerrar la ventana
            Closed += (s, e) => _refreshTimer.Stop();
        }

        private readonly System.Windows.Threading.DispatcherTimer _refreshTimer;

        // ── Propiedades de localización para bindings XAML ──

        public string LblSectionGeneralInfo => LocalizationManager.Get("StatusSectionGeneralInfo");
        public string LblState => LocalizationManager.Get("StatusLabelState");
        public string LblVersion => LocalizationManager.Get("StatusLabelVersion");
        public string LblActiveQueue => LocalizationManager.Get("StatusLabelActiveQueue");
        public string LblConfig => LocalizationManager.Get("StatusLabelConfig");
        public string LblSectionOnDemand => LocalizationManager.Get("StatusSectionOnDemand");
        public string LblNoActions => LocalizationManager.Get("StatusNoActionsAvailable");
        public string LblExecute => LocalizationManager.Get("StatusButtonExecute");
        public string LblSectionServices => LocalizationManager.Get("StatusSectionServices");
        public string LblStartService => LocalizationManager.Get("StatusButtonStartService");
        public string LblClose => LocalizationManager.Get("StatusButtonClose");

        // ── Carga de información general ──

        /// <summary>
        /// Carga la información general del sistema: estado de contingencia,
        /// versión del ensamblado, cola activa gestionada y configuración activa.
        /// </summary>
        internal void LoadGeneralInfo()
        {
            EstadoSistema = LoadEstadoSistema();
            VersionApp = LoadVersionApp();
            ColaActiva = LoadColaActiva();
            ConfigActiva = LoadConfigActiva();
        }

        /// <summary>
        /// Lee el valor ContingencyEnabled del registro para determinar el estado del sistema.
        /// </summary>
        private static string LoadEstadoSistema()
        {
            try
            {
                using (var key = Registry.LocalMachine.OpenSubKey(
                    RegistryConfigManager.RegistryPath, writable: false))
                {
                    if (key == null)
                        return StatusDisplayHelper.FormatEstadoSistema(false);

                    int contingencyEnabled = Convert.ToInt32(key.GetValue("ContingencyEnabled", 0));
                    return StatusDisplayHelper.FormatEstadoSistema(contingencyEnabled == 1);
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"StatusForm.LoadEstadoSistema: error leyendo ContingencyEnabled del registro: {ex.Message}");
                return StatusDisplayHelper.FormatEstadoSistema(false);
            }
        }

        /// <summary>
        /// Obtiene la versión del ensamblado actual de AlwaysPrintTray.
        /// </summary>
        private static string LoadVersionApp()
        {
            return Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "0.0.0.0";
        }

        /// <summary>
        /// Determina la cola activa gestionada según el modo de operación:
        /// - CPM (sin remote_queue_path en resources.json): muestra solo el nombre de cola.
        /// - LPM (con remote_queue_path en resources.json): muestra nombre + ruta remota.
        /// </summary>
        private static string LoadColaActiva()
        {
            try
            {
                // Leer nombre de la cola corporativa desde registro
                var registry = new RegistryConfigManager();
                var appConfig = registry.Load();
                string queueName = appConfig.CorporateQueueName;

                // Verificar si existe resources.json con remote_queue_path (modo LPM)
                string resourcesPath = PipeConstants.ResourcesFilePath;
                string? remoteQueuePath = null;

                if (File.Exists(resourcesPath))
                {
                    string json = File.ReadAllText(resourcesPath);
                    var obj = JObject.Parse(json);
                    remoteQueuePath = obj["remote_queue_path"]?.ToString();
                }

                return StatusDisplayHelper.FormatColaActiva(queueName, remoteQueuePath);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"StatusForm.LoadColaActiva: error determinando cola activa: {ex.Message}");
                return "Desconocida";
            }
        }

        /// <summary>
        /// Lee la configuración activa y genera el texto de display con formato "{Name} v{Version}".
        /// </summary>
        private static string LoadConfigActiva()
        {
            try
            {
                string configPath = PipeConstants.ActionConfigFilePath;
                if (!File.Exists(configPath))
                    return "Sin configuración";

                string json = File.ReadAllText(configPath);
                var config = Newtonsoft.Json.JsonConvert.DeserializeObject<ActionConfiguration>(json);

                if (config == null)
                    return "Sin configuración";

                string name = !string.IsNullOrWhiteSpace(config.Name) ? config.Name : "Desconocida";
                string version = !string.IsNullOrWhiteSpace(config.Version) ? config.Version : "?";

                return StatusDisplayHelper.FormatConfigDisplay(name, version);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"StatusForm.LoadConfigActiva: error leyendo configuración activa: {ex.Message}");
                return "Error al leer";
            }
        }

        // ── Carga de estado de servicios ──

        /// <summary>
        /// Carga la colección de servicios monitoreados desde la configuración activa
        /// y consulta su estado real vía Named Pipe (CheckServiceStatus).
        /// Si el pipe no está disponible, todos se muestran con estado "Desconocido".
        /// </summary>
        internal async Task LoadServiciosAsync()
        {
            Servicios.Clear();

            // Leer servicios desde la configuración activa (no hardcodeados)
            var monitoredServices = OnDemandConfigReader.GetMonitoredServices();

            if (monitoredServices.Count == 0)
                return;

            // Crear los ítems de servicio con estado inicial "Desconocido"
            var items = new List<ServiceStatusItem>();
            foreach (var svc in monitoredServices)
            {
                items.Add(new ServiceStatusItem
                {
                    DisplayName = svc.DisplayName,
                    ServiceName = svc.ServiceName,
                    State = "Desconocido"
                });
            }

            // Agregar a la colección observable para que la UI los muestre
            foreach (var item in items)
                Servicios.Add(item);

            // Verificar si el pipe está disponible
            if (!_pipe.IsConnected)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    "StatusForm.LoadServiciosAsync: pipe no disponible, servicios en estado desconocido.");
                return;
            }

            // Consultar estado real de cada servicio vía pipe
            foreach (var item in items)
            {
                await Task.Run(() =>
                {
                    try
                    {
                        var request = PipeMessage.Create(
                            MessageType.CheckServiceStatus,
                            new CheckServiceStatusPayload { ServiceName = item.ServiceName });

                        var response = _pipe.Send(request);

                        if (response == null)
                        {
                            AlwaysPrintLogger.WriteTrayWarning(
                                $"StatusForm.LoadServiciosAsync: sin respuesta para servicio '{item.ServiceName}'.");
                            return;
                        }

                        var payload = response.GetPayload<CheckServiceStatusResponsePayload>();
                        if (payload != null && !string.IsNullOrWhiteSpace(payload.State))
                        {
                            // Actualizar estado en el hilo de UI
                            Dispatcher.Invoke(() => item.State = payload.State);
                        }
                    }
                    catch (Exception ex)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"StatusForm.LoadServiciosAsync: error consultando servicio '{item.ServiceName}': {ex.Message}");
                    }
                });
            }
        }

        /// <summary>
        /// Refresca el estado de los servicios ya cargados sin reconstruir la colección.
        /// Se ejecuta periódicamente por el DispatcherTimer para reflejar cambios en tiempo real.
        /// </summary>
        private async Task RefreshServiciosEstadoAsync()
        {
            if (!_pipe.IsConnected || Servicios.Count == 0)
                return;

            foreach (var item in Servicios)
            {
                if (item.IsOperating) continue; // No actualizar servicios en operación

                await Task.Run(() =>
                {
                    try
                    {
                        var request = PipeMessage.Create(
                            MessageType.CheckServiceStatus,
                            new CheckServiceStatusPayload { ServiceName = item.ServiceName });

                        var response = _pipe.Send(request);
                        var payload = response?.GetPayload<CheckServiceStatusResponsePayload>();

                        if (payload != null && !string.IsNullOrWhiteSpace(payload.State))
                        {
                            Dispatcher.Invoke(() => item.State = payload.State);
                        }
                    }
                    catch { /* Ignorar errores individuales en refresh periódico */ }
                });
            }
        }

        // ── Carga de triggers OnDemand ──

        /// <summary>
        /// Carga los triggers OnDemand desde la configuración activa.
        /// Popula la colección TriggersOnDemand y controla la visibilidad
        /// del mensaje "No hay acciones disponibles".
        /// </summary>
        internal void LoadTriggersOnDemand()
        {
            var triggers = OnDemandConfigReader.GetOnDemandTriggers();
            PopulateTriggersCollection(triggers);
        }

        /// <summary>
        /// Actualiza dinámicamente la lista de triggers OnDemand en el formulario.
        /// Llamado externamente cuando la configuración activa cambia (ActionConfigChanged).
        /// Si un trigger que estaba en ejecución fue eliminado de la nueva configuración,
        /// se preserva en la lista hasta que su ejecución finalice (Req 10.4).
        /// </summary>
        /// <param name="triggers">Nueva lista de triggers OnDemand disponibles.</param>
        public void RefreshOnDemandTriggers(List<OnDemandTriggerInfo> triggers)
        {
            if (triggers == null)
                triggers = new List<OnDemandTriggerInfo>();

            // Identificar triggers que están en ejecución y fueron eliminados de la nueva config
            var executingLabels = new HashSet<string>();
            var executingItems = new List<OnDemandTriggerItem>();

            foreach (var item in TriggersOnDemand)
            {
                if (item.IsExecuting)
                {
                    bool stillExists = triggers.Exists(t => t.Label == item.Label);
                    if (!stillExists)
                    {
                        // Preservar trigger en ejecución que fue eliminado
                        executingItems.Add(item);
                        executingLabels.Add(item.Label);
                        AlwaysPrintLogger.WriteTrayInfo(
                            $"RefreshOnDemandTriggers: preservando trigger '{item.Label}' en ejecución " +
                            "(eliminado de nueva config, se removerá al finalizar).");
                    }
                }
            }

            // Reconstruir la colección: nueva config + triggers en ejecución eliminados
            TriggersOnDemand.Clear();

            foreach (var trigger in triggers)
            {
                TriggersOnDemand.Add(new OnDemandTriggerItem
                {
                    Label = trigger.Label,
                    Description = trigger.Description
                });
            }

            // Agregar al final los triggers en ejecución que fueron eliminados
            foreach (var item in executingItems)
            {
                TriggersOnDemand.Add(item);
            }

            // Mostrar u ocultar el mensaje según si hay triggers disponibles
            UpdateNoTriggersMessageVisibility();
        }

        /// <summary>
        /// Actualiza el campo "Configuración" releyendo el archivo de configuración activa.
        /// Llamado externamente cuando la configuración activa cambia (ActionConfigChanged).
        /// </summary>
        public void RefreshConfigActiva()
        {
            ConfigActiva = LoadConfigActiva();
        }

        /// <summary>
        /// Popula la colección observable de triggers y actualiza la visibilidad
        /// del mensaje de "no hay acciones disponibles".
        /// </summary>
        private void PopulateTriggersCollection(List<OnDemandTriggerInfo> triggers)
        {
            TriggersOnDemand.Clear();

            foreach (var trigger in triggers)
            {
                TriggersOnDemand.Add(new OnDemandTriggerItem
                {
                    Label = trigger.Label,
                    Description = trigger.Description
                });
            }

            // Mostrar u ocultar el mensaje según si hay triggers disponibles
            UpdateNoTriggersMessageVisibility();
        }

        /// <summary>
        /// Actualiza la visibilidad del TextBlock NoTriggersMessage.
        /// Visible cuando no hay triggers; colapsado cuando hay al menos uno.
        /// </summary>
        private void UpdateNoTriggersMessageVisibility()
        {
            if (NoTriggersMessage != null)
            {
                NoTriggersMessage.Visibility = TriggersOnDemand.Count == 0
                    ? Visibility.Visible
                    : Visibility.Collapsed;
            }

            if (TriggersListControl != null)
            {
                TriggersListControl.Visibility = TriggersOnDemand.Count > 0
                    ? Visibility.Visible
                    : Visibility.Collapsed;
            }
        }

        // ── Información General ──

        /// <summary>Estado actual del sistema: "Normal" o "En Contingencia".</summary>
        public string EstadoSistema
        {
            get => _estadoSistema;
            set { _estadoSistema = value; OnPropertyChanged(nameof(EstadoSistema)); }
        }

        /// <summary>Versión del ensamblado de AlwaysPrint.</summary>
        public string VersionApp
        {
            get => _versionApp;
            set { _versionApp = value; OnPropertyChanged(nameof(VersionApp)); }
        }

        /// <summary>Cola de impresión activa gestionada por AlwaysPrint.</summary>
        public string ColaActiva
        {
            get => _colaActiva;
            set { _colaActiva = value; OnPropertyChanged(nameof(ColaActiva)); }
        }

        /// <summary>Nombre y versión de la configuración activa (ej: "CPM_Compliant v5.2").</summary>
        public string ConfigActiva
        {
            get => _configActiva;
            set { _configActiva = value; OnPropertyChanged(nameof(ConfigActiva)); }
        }

        // ── Servicios ──

        /// <summary>Colección observable de servicios monitoreados con su estado actual.</summary>
        public ObservableCollection<ServiceStatusItem> Servicios { get; }

        // ── OnDemand Triggers ──

        /// <summary>Colección observable de triggers OnDemand disponibles para ejecución.</summary>
        public ObservableCollection<OnDemandTriggerItem> TriggersOnDemand { get; }

        // ── Control global de operaciones ──

        /// <summary>
        /// Establece el flag global de ocupado: cuando hay cualquier operación en curso
        /// (inicio de servicio o ejecución de trigger), deshabilita todos los controles
        /// de servicios y triggers para prevenir operaciones concurrentes.
        /// </summary>
        private void SetGlobalBusy(bool busy)
        {
            foreach (var svc in Servicios)
                svc.IsGlobalBusy = busy;

            foreach (var trigger in TriggersOnDemand)
                trigger.IsGlobalBusy = busy;
        }

        // ── Eventos de UI ──

        /// <summary>Manejador de clic en botón de acción de servicio (solo Iniciar).</summary>
        private async void ServiceAction_Click(object sender, RoutedEventArgs e)
        {
            var button = sender as System.Windows.Controls.Button;
            if (button == null) return;

            var service = button.Tag as ServiceStatusItem;
            if (service == null) return;

            // Solo permite iniciar servicios detenidos
            string action = "Start";

            AlwaysPrintLogger.WriteTrayInfo(
                $"ServiceAction_Click: usuario solicitó '{action}' para servicio '{service.ServiceName}'.");

            // Activar flag global: deshabilita todos los controles de servicios y triggers
            SetGlobalBusy(true);
            service.IsOperating = true;

            try
            {
                // Verificar disponibilidad del pipe
                if (!_pipe.IsConnected)
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"ServiceAction_Click: pipe no disponible al intentar '{action}' en '{service.ServiceName}'.");
                    service.State = "Desconocido";
                    return;
                }

                // Construir y enviar mensaje al Service
                var payload = new ServiceActionPayload
                {
                    ServiceName = service.ServiceName,
                    Action = action
                };
                var request = PipeMessage.Create(MessageType.ServiceAction, payload);

                var response = await Task.Run(() => _pipe.Send(request));

                if (response == null)
                {
                    // Pipe se desconectó durante la comunicación
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"ServiceAction_Click: sin respuesta del Service para '{action}' en '{service.ServiceName}'.");
                    service.State = "Desconocido";
                    return;
                }

                if (response.Type == MessageType.ServiceActionResponse)
                {
                    var responsePayload = response.GetPayload<ServiceActionResponsePayload>();
                    if (responsePayload != null && responsePayload.Success)
                    {
                        AlwaysPrintLogger.WriteTrayInfo(
                            $"ServiceAction_Click: '{action}' en '{service.ServiceName}' exitoso. Nuevo estado: {responsePayload.NewState}.");
                        service.State = responsePayload.NewState;
                    }
                    else
                    {
                        var errorMsg = responsePayload?.Message ?? "Error desconocido";
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"ServiceAction_Click: '{action}' en '{service.ServiceName}' falló. Mensaje: {errorMsg}");
                        // Actualizar estado si se proporcionó uno nuevo
                        if (responsePayload != null && !string.IsNullOrWhiteSpace(responsePayload.NewState))
                            service.State = responsePayload.NewState;
                    }
                }
                else if (response.Type == MessageType.Error)
                {
                    var error = response.GetPayload<ErrorPayload>();
                    var errorMsg = error?.Message ?? "Error desconocido";
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"ServiceAction_Click: Service retornó error para '{action}' en '{service.ServiceName}'. " +
                        $"Código: {error?.Code}, Mensaje: {errorMsg}");
                }
                else
                {
                    AlwaysPrintLogger.WriteTrayWarning(
                        $"ServiceAction_Click: respuesta inesperada tipo '{response.Type}' para '{action}' en '{service.ServiceName}'.");
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"ServiceAction_Click: excepción al ejecutar '{action}' en '{service.ServiceName}': {ex.Message}");
            }
            finally
            {
                // Rehabilitar control tras respuesta (éxito o error)
                service.IsOperating = false;
                SetGlobalBusy(false);
            }
        }

        /// <summary>Manejador de clic en botón de ejecución de trigger OnDemand.</summary>
        private async void TriggerExecute_Click(object sender, RoutedEventArgs e)
        {
            var button = sender as System.Windows.Controls.Button;
            if (button == null) return;

            var trigger = button.Tag as OnDemandTriggerItem;
            if (trigger == null) return;

            // Mostrar diálogo de confirmación con la descripción del trigger
            var resultado = MessageBox.Show(
                trigger.Description,
                $"¿Ejecutar '{trigger.Label}'?",
                MessageBoxButton.OKCancel,
                MessageBoxImage.Question);

            // Si el usuario cancela, no hacer nada
            if (resultado != MessageBoxResult.OK)
                return;

            AlwaysPrintLogger.WriteTrayInfo(
                $"TriggerExecute_Click: usuario confirmó ejecución de trigger '{trigger.Label}'.");

            // Deshabilitar ítem durante ejecución para prevenir clics duplicados
            trigger.IsExecuting = true;
            SetGlobalBusy(true);

            try
            {
                // Verificar disponibilidad del pipe
                if (!_pipe.IsConnected)
                {
                    AlwaysPrintLogger.WriteTrayError(
                        $"TriggerExecute_Click: pipe no disponible al intentar ejecutar '{trigger.Label}'.",
                        AlwaysPrintLogger.EvtGenericError);
                    MessageBox.Show(
                        "El servicio no está accesible. Verifique que AlwaysPrintService esté en ejecución.",
                        "Error",
                        MessageBoxButton.OK,
                        MessageBoxImage.Error);
                    return;
                }

                // Construir y enviar mensaje al Service
                var payload = new ExecuteOnDemandTriggerPayload { Label = trigger.Label };
                var request = PipeMessage.Create(MessageType.ExecuteOnDemandTrigger, payload);

                var response = await Task.Run(() => _pipe.Send(request));

                if (response == null)
                {
                    // Pipe se desconectó durante la comunicación
                    AlwaysPrintLogger.WriteTrayError(
                        $"TriggerExecute_Click: no se recibió respuesta del Service para '{trigger.Label}'.",
                        AlwaysPrintLogger.EvtGenericError);
                    MessageBox.Show(
                        "No se recibió respuesta del servicio. La conexión se perdió.",
                        "Error",
                        MessageBoxButton.OK,
                        MessageBoxImage.Error);
                    return;
                }

                if (response.Type == MessageType.Ack)
                {
                    var ack = response.GetPayload<AckPayload>();
                    if (ack?.Success == true)
                    {
                        AlwaysPrintLogger.WriteTrayInfo(
                            $"TriggerExecute_Click: trigger '{trigger.Label}' ejecutado exitosamente.");
                        MessageBox.Show(
                            $"✓ {trigger.Label} ejecutado correctamente.",
                            "Ejecución exitosa",
                            MessageBoxButton.OK,
                            MessageBoxImage.Information);
                    }
                    else
                    {
                        // Ack con success=false
                        var errorMsg = ack?.Message ?? "Error desconocido";
                        AlwaysPrintLogger.WriteTrayError(
                            $"TriggerExecute_Click: trigger '{trigger.Label}' falló. Mensaje: {errorMsg}",
                            AlwaysPrintLogger.EvtGenericError);
                        MessageBox.Show(
                            $"Error ejecutando '{trigger.Label}': {errorMsg}",
                            "Error de ejecución",
                            MessageBoxButton.OK,
                            MessageBoxImage.Warning);
                    }
                }
                else if (response.Type == MessageType.Error)
                {
                    var error = response.GetPayload<ErrorPayload>();
                    var errorMsg = error?.Message ?? "Error desconocido";
                    AlwaysPrintLogger.WriteTrayError(
                        $"TriggerExecute_Click: Service retornó error para '{trigger.Label}'. " +
                        $"Código: {error?.Code}, Mensaje: {errorMsg}",
                        AlwaysPrintLogger.EvtGenericError);
                    MessageBox.Show(
                        $"Error ejecutando '{trigger.Label}': {errorMsg}",
                        "Error del servicio",
                        MessageBoxButton.OK,
                        MessageBoxImage.Error);
                }
                else
                {
                    // Tipo de respuesta inesperado
                    AlwaysPrintLogger.WriteTrayError(
                        $"TriggerExecute_Click: respuesta inesperada tipo '{response.Type}' para '{trigger.Label}'.",
                        AlwaysPrintLogger.EvtGenericError);
                    MessageBox.Show(
                        $"Error ejecutando '{trigger.Label}': respuesta inesperada del servicio.",
                        "Error",
                        MessageBoxButton.OK,
                        MessageBoxImage.Error);
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"TriggerExecute_Click: excepción al ejecutar '{trigger.Label}': {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
                MessageBox.Show(
                    $"Error ejecutando '{trigger.Label}': {ex.Message}",
                    "Error",
                    MessageBoxButton.OK,
                    MessageBoxImage.Error);
            }
            finally
            {
                // Rehabilitar ítem tras respuesta (éxito o error)
                trigger.IsExecuting = false;
                SetGlobalBusy(false);
            }
        }

        /// <summary>Manejador de clic en botón Cerrar.</summary>
        private void CloseButton_Click(object sender, RoutedEventArgs e)
        {
            Close();
        }

        // ── INotifyPropertyChanged ──

        public event PropertyChangedEventHandler? PropertyChanged;

        private void OnPropertyChanged(string propertyName)
        {
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
        }
    }
}
