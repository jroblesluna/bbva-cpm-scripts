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
                OnPropertyChanged(nameof(ActionLabel));
                OnPropertyChanged(nameof(IsActionEnabled));
            }
        }

        /// <summary>Indica si una operación de Start/Restart está en curso.</summary>
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

        /// <summary>Texto del botón de acción: "Reiniciar" si Running, "Iniciar" si Stopped.</summary>
        public string ActionLabel => State == "Running" ? "Reiniciar" : "Iniciar";

        /// <summary>Habilita el botón de acción solo si no hay operación en curso y el estado es conocido.</summary>
        public bool IsActionEnabled => !IsOperating && State != "Desconocido";

        public event PropertyChangedEventHandler? PropertyChanged;

        private void OnPropertyChanged(string propertyName)
        {
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
        }
    }
}
