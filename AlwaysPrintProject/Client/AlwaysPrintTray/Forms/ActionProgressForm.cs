using System;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;
using AlwaysPrint.Shared.Messages;

namespace AlwaysPrintTray.Forms
{
    /// <summary>
    /// Ventana modal pequeña que muestra el progreso de una ejecución OnDemand.
    /// Se cierra automáticamente 30 segundos después de completar, o al hacer click en Cerrar.
    /// Se muestra encima de otras ventanas (TopMost).
    /// </summary>
    public class ActionProgressForm : Form
    {
        private readonly ListView _listView;
        private readonly Label _statusLabel;
        private readonly Button _closeButton;
        private readonly Timer _autoCloseTimer;
        private readonly string _triggerLabel;
        private bool _isComplete;

        /// <summary>
        /// Indica si la ejecución mostrada en este form ya finalizó (exitosa o con error).
        /// Usado por TrayApplicationContext para cerrar un form completado cuando llega
        /// un nuevo trigger distinto.
        /// </summary>
        public bool IsComplete => _isComplete;

        public ActionProgressForm(string triggerLabel)
        {
            _triggerLabel = triggerLabel;

            // Configuración de la ventana
            Text = $"Ejecutando: {triggerLabel}";
            Size = new Size(500, 350);
            MinimumSize = new Size(400, 250);
            StartPosition = FormStartPosition.CenterScreen;
            TopMost = true;
            FormBorderStyle = FormBorderStyle.SizableToolWindow;
            ShowInTaskbar = false;

            // Status label en la parte superior
            _statusLabel = new Label
            {
                Text = "Ejecutando...",
                Dock = DockStyle.Top,
                Height = 28,
                TextAlign = ContentAlignment.MiddleLeft,
                Padding = new Padding(8, 4, 8, 4),
                Font = new Font(Font.FontFamily, 9f, FontStyle.Bold),
                ForeColor = Color.DarkBlue,
                BackColor = Color.FromArgb(240, 245, 255),
            };
            Controls.Add(_statusLabel);

            // ListView para los pasos
            _listView = new ListView
            {
                Dock = DockStyle.Fill,
                View = View.Details,
                FullRowSelect = true,
                GridLines = true,
                HeaderStyle = ColumnHeaderStyle.Nonclickable,
                Font = new Font("Consolas", 8.5f),
            };
            _listView.Columns.Add("Estado", 50);
            _listView.Columns.Add("Acción", 120);
            _listView.Columns.Add("Descripción", 280);
            Controls.Add(_listView);

            // Panel inferior con botón
            var bottomPanel = new Panel
            {
                Dock = DockStyle.Bottom,
                Height = 40,
                Padding = new Padding(8, 4, 8, 4),
            };

            _closeButton = new Button
            {
                Text = "Cerrar",
                Width = 80,
                Height = 30,
                Anchor = AnchorStyles.Right | AnchorStyles.Bottom,
            };
            _closeButton.Location = new Point(bottomPanel.Width - _closeButton.Width - 12, 5);
            _closeButton.Click += (_, _) => Close();
            bottomPanel.Controls.Add(_closeButton);
            Controls.Add(bottomPanel);

            // Orden correcto para DockStyle layout:
            // En WinForms, el layout de docking procesa controles desde el índice MÁS ALTO
            // hacia el más bajo. Los controles procesados primero (índices altos) reservan
            // su espacio; el último procesado (índice 0, Fill) obtiene el espacio restante.
            Controls.SetChildIndex(_listView, 0);      // Fill — procesado último, ocupa el resto
            Controls.SetChildIndex(_statusLabel, 1);   // Top — procesado segundo, reserva arriba
            Controls.SetChildIndex(bottomPanel, 2);    // Bottom — procesado primero, reserva abajo

            // Timer de auto-cierre (30s después de completar)
            _autoCloseTimer = new Timer { Interval = 30000 };
            _autoCloseTimer.Tick += (_, _) => { _autoCloseTimer.Stop(); Close(); };
        }

        /// <summary>
        /// Agrega o actualiza un paso en la lista de progreso.
        /// Thread-safe: puede llamarse desde cualquier hilo.
        /// </summary>
        public void AddProgress(OnDemandActionProgressPayload progress)
        {
            if (InvokeRequired)
            {
                BeginInvoke(new Action(() => AddProgress(progress)));
                return;
            }

            if (progress.IsComplete)
            {
                _isComplete = true;
                _statusLabel.Text = progress.OverallSuccess
                    ? $"✓ Completado ({progress.DurationMs}ms)"
                    : $"✗ Falló ({progress.DurationMs}ms)";
                _statusLabel.ForeColor = progress.OverallSuccess ? Color.DarkGreen : Color.DarkRed;
                _statusLabel.BackColor = progress.OverallSuccess
                    ? Color.FromArgb(240, 255, 240)
                    : Color.FromArgb(255, 240, 240);
                _autoCloseTimer.Start();
                return;
            }

            string statusIcon = progress.Status switch
            {
                "running" => "⏳",
                "ok" => "✓",
                "error" => "✗",
                _ => "·"
            };

            // Buscar si ya existe un item para este paso (actualizar de running → ok/error)
            ListViewItem? existing = null;
            for (int i = _listView.Items.Count - 1; i >= 0; i--)
            {
                if (_listView.Items[i].SubItems[1].Text == progress.ActionType &&
                    _listView.Items[i].SubItems[0].Text == "⏳")
                {
                    existing = _listView.Items[i];
                    break;
                }
            }

            if (existing != null && progress.Status != "running")
            {
                existing.SubItems[0].Text = statusIcon;
                existing.ForeColor = progress.Status == "ok" ? Color.DarkGreen : Color.DarkRed;
            }
            else if (progress.Status == "running")
            {
                var item = new ListViewItem(statusIcon);
                item.SubItems.Add(progress.ActionType);
                item.SubItems.Add(progress.StepName);
                item.ForeColor = Color.DarkBlue;
                _listView.Items.Add(item);
                _listView.EnsureVisible(_listView.Items.Count - 1);
            }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _autoCloseTimer?.Dispose();
            }
            base.Dispose(disposing);
        }
    }
}
