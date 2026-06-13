using System.ComponentModel;

namespace AlwaysPrintTray.Forms
{
    /// <summary>
    /// Modelo de un servicio Windows monitoreado en el Status Form.
    /// Implementa INotifyPropertyChanged para actualización reactiva de la UI.
    /// </summary>
    public class ServiceStatusItem : INotifyPropertyChanged
    {
        private string _displayName = string.Empty;
        private string _serviceName = string.Empty;
        private string _state = "Desconocido";
        private bool _isOperating;
        private bool _isGlobalBusy;

        /// <summary>Nombre visible en la UI (ej: "Cola de Impresión").</summary>
        public string DisplayName
        {
            get => _displayName;
            set { _displayName = value; OnPropertyChanged(nameof(DisplayName)); }
        }

        /// <summary>Nombre real del servicio Windows (ej: "Spooler").</summary>
        public string ServiceName
        {
            get => _serviceName;
            set { _serviceName = value; OnPropertyChanged(nameof(ServiceName)); }
        }

        /// <summary>Estado actual: "Running", "Stopped" o "Desconocido".</summary>
        public string State
        {
            get => _state;
            set
            {
                _state = value;
                OnPropertyChanged(nameof(State));
                OnPropertyChanged(nameof(IsActionVisible));
                OnPropertyChanged(nameof(IsActionEnabled));
            }
        }

        /// <summary>Indica si una operación sobre este servicio está en curso.</summary>
        public bool IsOperating
        {
            get => _isOperating;
            set
            {
                _isOperating = value;
                OnPropertyChanged(nameof(IsOperating));
                OnPropertyChanged(nameof(IsActionEnabled));
            }
        }

        /// <summary>
        /// Flag global: true cuando hay cualquier operación en curso en el StatusForm
        /// (inicio de servicio o ejecución de trigger OnDemand).
        /// Deshabilita todos los controles de servicio.
        /// </summary>
        public bool IsGlobalBusy
        {
            get => _isGlobalBusy;
            set
            {
                _isGlobalBusy = value;
                OnPropertyChanged(nameof(IsGlobalBusy));
                OnPropertyChanged(nameof(IsActionEnabled));
            }
        }

        /// <summary>
        /// El botón de acción solo es visible si el servicio está detenido.
        /// No se muestra opción de reiniciar (solo iniciar servicios detenidos).
        /// </summary>
        public bool IsActionVisible => State == "Stopped";

        /// <summary>
        /// Habilita el botón solo si: servicio está Stopped, no hay operación propia
        /// en curso, y no hay operación global (otro servicio o trigger ejecutándose).
        /// </summary>
        public bool IsActionEnabled => State == "Stopped" && !IsOperating && !IsGlobalBusy;

        public event PropertyChangedEventHandler? PropertyChanged;

        private void OnPropertyChanged(string propertyName)
        {
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
        }
    }
}
