using System.ComponentModel;

namespace AlwaysPrintTray.Forms
{
    /// <summary>
    /// Modelo de un trigger OnDemand disponible para ejecución en el Status Form.
    /// Implementa INotifyPropertyChanged para actualización reactiva de la UI.
    /// </summary>
    public class OnDemandTriggerItem : INotifyPropertyChanged
    {
        private string _label = string.Empty;
        private string _description = string.Empty;
        private bool _isExecuting;
        private bool _isGlobalBusy;

        /// <summary>Etiqueta visible del trigger (identificador único).</summary>
        public string Label
        {
            get => _label;
            set { _label = value; OnPropertyChanged(nameof(Label)); }
        }

        /// <summary>Descripción que se muestra en el diálogo de confirmación.</summary>
        public string Description
        {
            get => _description;
            set { _description = value; OnPropertyChanged(nameof(Description)); }
        }

        /// <summary>Indica si este trigger está en ejecución.</summary>
        public bool IsExecuting
        {
            get => _isExecuting;
            set
            {
                _isExecuting = value;
                OnPropertyChanged(nameof(IsExecuting));
                OnPropertyChanged(nameof(IsActionEnabled));
            }
        }

        /// <summary>
        /// Flag global: true cuando hay cualquier operación en curso en el StatusForm.
        /// Deshabilita el botón de ejecución de este trigger.
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

        /// <summary>Habilita el botón solo si no está ejecutándose y no hay operación global.</summary>
        public bool IsActionEnabled => !IsExecuting && !IsGlobalBusy;

        public event PropertyChangedEventHandler? PropertyChanged;

        private void OnPropertyChanged(string propertyName)
        {
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
        }
    }
}
