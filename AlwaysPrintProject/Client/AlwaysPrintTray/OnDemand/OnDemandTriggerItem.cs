using System.ComponentModel;

namespace AlwaysPrintTray.Forms
{
    public class OnDemandTriggerItem : INotifyPropertyChanged
    {
        private string _label = string.Empty;
        private string _description = string.Empty;
        private bool _isExecuting;

        public string Label
        {
            get => _label;
            set { _label = value; OnPropertyChanged(nameof(Label)); }
        }

        public string Description
        {
            get => _description;
            set { _description = value; OnPropertyChanged(nameof(Description)); }
        }

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

        public bool IsActionEnabled => !IsExecuting;

        public event PropertyChangedEventHandler? PropertyChanged;

        private void OnPropertyChanged(string propertyName)
        {
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
        }
    }
}
