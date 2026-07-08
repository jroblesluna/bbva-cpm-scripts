using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Windows.Forms;
using AlwaysPrintTray.Cloud;
using AlwaysPrintTray.Connectivity;

namespace AlwaysPrintTray.Forms
{
    /// <summary>
    /// Formulario de reporte detallado de conectividad.
    /// Muestra una tabla (DataGridView) con los resultados de cada URL verificada,
    /// un header con información de resumen (proxy, totales) y un botón "Cerrar".
    /// Se abre como modal desde el ConnectivityNotificationForm.
    /// </summary>
    public sealed class ConnectivityReportForm : Form
    {
        // === CONSTANTES DE LAYOUT ===
        private const int FormW = 750;
        private const int FormH = 450;
        private const int HeaderHeight = 80;
        private const int FooterHeight = 50;
        private const int Pad = 12;

        // === CAMPOS ===
        private readonly List<UrlCheckResult> _results;
        private readonly int _percent;

        /// <summary>
        /// Crea el formulario de reporte de conectividad.
        /// </summary>
        /// <param name="results">Lista de resultados individuales por URL.</param>
        /// <param name="percent">Porcentaje de URLs exitosas (0-100).</param>
        public ConnectivityReportForm(List<UrlCheckResult> results, int percent)
        {
            _results = results ?? new List<UrlCheckResult>();
            _percent = percent;

            // === Configuración del Form ===
            Text = $"Reporte de Conectividad \u2014 {DateTime.Now:yyyy-MM-dd HH:mm:ss}";
            ClientSize = new Size(FormW, FormH);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            ShowInTaskbar = true;
            BackColor = AppTheme.BodyBg;
            Font = (Font)AppTheme.FontRegular.Clone();

            // === Construir UI ===
            ConstruirHeader();
            ConstruirDataGridView();
            ConstruirFooter();
        }

        // =====================================================================
        // HEADER — información de resumen (proxy, totales)
        // =====================================================================

        /// <summary>
        /// Construye el panel superior con información de proxy y totales.
        /// </summary>
        private void ConstruirHeader()
        {
            var pnlHeader = new Panel
            {
                Dock = DockStyle.Top,
                Height = HeaderHeight,
                BackColor = AppTheme.HeaderBg,
                Padding = new Padding(Pad, 8, Pad, 8)
            };
            pnlHeader.Paint += PintarHeader;
            Controls.Add(pnlHeader);

            // === Línea 1: información de proxy ===
            string proxyText = DetectarProxyTexto();
            var lblProxy = new Label
            {
                Text = proxyText,
                Font = (Font)AppTheme.FontRegular.Clone(),
                ForeColor = AppTheme.TextOnDark,
                Location = new Point(Pad, 12),
                Size = new Size(FormW - Pad * 2, 20),
                BackColor = Color.Transparent
            };
            pnlHeader.Controls.Add(lblProxy);

            // === Línea 2: totales de URLs ===
            int total = _results.Count;
            int exitosas = _results.Count(r => r.Success);
            int fallidas = total - exitosas;

            var lblTotales = new Label
            {
                Text = $"URLs verificadas: {total}  |  Exitosas: {exitosas}  |  Fallidas: {fallidas}",
                Font = (Font)AppTheme.FontBold.Clone(),
                ForeColor = AppTheme.TextSubtitle,
                Location = new Point(Pad, 38),
                Size = new Size(FormW - Pad * 2, 20),
                BackColor = Color.Transparent
            };
            pnlHeader.Controls.Add(lblTotales);
        }

        /// <summary>
        /// Pinta la barra de acento inferior del header.
        /// </summary>
        private void PintarHeader(object sender, PaintEventArgs e)
        {
            var panel = (Panel)sender;
            AppTheme.DrawHeaderAccent(e.Graphics, panel.Width, panel.Height);
        }

        // =====================================================================
        // DATAGRIDVIEW — tabla de resultados
        // =====================================================================

        /// <summary>
        /// Construye el DataGridView con los resultados de conectividad.
        /// Columnas: URL, Estado (✓/✗), Latencia, Intentos, Error.
        /// </summary>
        private void ConstruirDataGridView()
        {
            var dgv = new DataGridView
            {
                Location = new Point(Pad, HeaderHeight + Pad),
                Size = new Size(FormW - Pad * 2, FormH - HeaderHeight - FooterHeight - Pad * 2),
                Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Bottom,
                ReadOnly = true,
                AllowUserToAddRows = false,
                AllowUserToDeleteRows = false,
                AllowUserToResizeRows = false,
                RowHeadersVisible = false,
                SelectionMode = DataGridViewSelectionMode.FullRowSelect,
                MultiSelect = false,
                BorderStyle = BorderStyle.FixedSingle,
                BackgroundColor = Color.White,
                GridColor = AppTheme.Divider,
                CellBorderStyle = DataGridViewCellBorderStyle.SingleHorizontal,
                AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.None,
                ScrollBars = ScrollBars.Vertical,
                EnableHeadersVisualStyles = false
            };

            // === Estilo general de celdas ===
            dgv.DefaultCellStyle.Font = (Font)AppTheme.FontRegular.Clone();
            dgv.DefaultCellStyle.ForeColor = AppTheme.TextPrimary;
            dgv.DefaultCellStyle.BackColor = AppTheme.RowEven;
            dgv.DefaultCellStyle.SelectionBackColor = AppTheme.RowEven;
            dgv.DefaultCellStyle.SelectionForeColor = AppTheme.TextPrimary;
            dgv.DefaultCellStyle.Padding = new Padding(4, 2, 4, 2);

            // === Filas alternas para legibilidad ===
            dgv.AlternatingRowsDefaultCellStyle.BackColor = AppTheme.RowOdd;
            dgv.AlternatingRowsDefaultCellStyle.SelectionBackColor = AppTheme.RowOdd;
            dgv.AlternatingRowsDefaultCellStyle.SelectionForeColor = AppTheme.TextPrimary;

            // === Estilo de encabezados de columna ===
            dgv.ColumnHeadersDefaultCellStyle.Font = (Font)AppTheme.FontBold.Clone();
            dgv.ColumnHeadersDefaultCellStyle.BackColor = AppTheme.FooterBg;
            dgv.ColumnHeadersDefaultCellStyle.ForeColor = AppTheme.TextPrimary;
            dgv.ColumnHeadersDefaultCellStyle.SelectionBackColor = AppTheme.FooterBg;
            dgv.ColumnHeadersDefaultCellStyle.SelectionForeColor = AppTheme.TextPrimary;
            dgv.ColumnHeadersDefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleLeft;
            dgv.ColumnHeadersHeight = 30;
            dgv.ColumnHeadersHeightSizeMode = DataGridViewColumnHeadersHeightSizeMode.DisableResizing;

            // === Definir columnas ===
            dgv.Columns.Add(CrearColumna("URL", "URL", 310));
            dgv.Columns.Add(CrearColumna("Estado", "Estado", 60, DataGridViewContentAlignment.MiddleCenter));
            dgv.Columns.Add(CrearColumna("Latencia", "Latencia", 90, DataGridViewContentAlignment.MiddleRight));
            dgv.Columns.Add(CrearColumna("Intentos", "Intentos", 70, DataGridViewContentAlignment.MiddleCenter));
            dgv.Columns.Add(CrearColumna("Error", "Error", 180));

            // === Llenar filas con datos ===
            foreach (var r in _results)
            {
                string estado = r.Success ? "\u2713" : "\u2717";
                string latencia = r.Success
                    ? $"{r.LatencyMs} ms"
                    : (r.Error != null && r.Error.Contains("Timeout") ? "Timeout" : $"{r.LatencyMs} ms");
                string error = r.Error ?? "";

                int rowIdx = dgv.Rows.Add(r.Url, estado, latencia, r.Attempts.ToString(), error);

                // Colorear la celda de estado según éxito/fallo
                var estadoCell = dgv.Rows[rowIdx].Cells["Estado"];
                if (r.Success)
                {
                    estadoCell.Style.ForeColor = Color.FromArgb(76, 175, 80); // verde
                    estadoCell.Style.SelectionForeColor = Color.FromArgb(76, 175, 80);
                    estadoCell.Style.Font = new Font("Segoe UI", 11f, FontStyle.Bold);
                }
                else
                {
                    estadoCell.Style.ForeColor = Color.FromArgb(244, 67, 54); // rojo
                    estadoCell.Style.SelectionForeColor = Color.FromArgb(244, 67, 54);
                    estadoCell.Style.Font = new Font("Segoe UI", 11f, FontStyle.Bold);
                }
            }

            Controls.Add(dgv);
        }

        /// <summary>
        /// Crea una columna de texto para el DataGridView.
        /// </summary>
        private static DataGridViewTextBoxColumn CrearColumna(
            string name, string headerText, int width,
            DataGridViewContentAlignment alignment = DataGridViewContentAlignment.MiddleLeft)
        {
            return new DataGridViewTextBoxColumn
            {
                Name = name,
                HeaderText = headerText,
                Width = width,
                SortMode = DataGridViewColumnSortMode.NotSortable,
                DefaultCellStyle = new DataGridViewCellStyle { Alignment = alignment }
            };
        }

        // =====================================================================
        // FOOTER — botón "Cerrar"
        // =====================================================================

        /// <summary>
        /// Construye el panel inferior con el botón "Cerrar".
        /// </summary>
        private void ConstruirFooter()
        {
            var pnlFooter = new Panel
            {
                Dock = DockStyle.Bottom,
                Height = FooterHeight,
                BackColor = AppTheme.FooterBg,
                Padding = new Padding(Pad)
            };
            // Línea divisora superior del footer
            pnlFooter.Paint += (s, e) =>
            {
                AppTheme.DrawDivider(e.Graphics, 0, 0, pnlFooter.Width);
            };

            var btnCerrar = new AppButton
            {
                Text = "Cerrar",
                Size = new Size(100, 32),
                IsPrimary = true
            };
            // Posicionar a la derecha
            btnCerrar.Location = new Point(
                FormW - Pad * 2 - btnCerrar.Width,
                (FooterHeight - btnCerrar.Height) / 2);
            btnCerrar.Click += (s, e) => Close();
            pnlFooter.Controls.Add(btnCerrar);

            Controls.Add(pnlFooter);
        }

        // =====================================================================
        // UTILIDADES
        // =====================================================================

        /// <summary>
        /// Detecta el proxy del sistema y retorna un texto descriptivo para el header.
        /// Usa ProxyHelper.GetSystemProxyUri() con la primera URL de los resultados.
        /// </summary>
        private string DetectarProxyTexto()
        {
            try
            {
                // Usar la primera URL de resultados como target para detectar proxy
                Uri targetUri = null;
                if (_results.Count > 0 && !string.IsNullOrEmpty(_results[0].Url))
                {
                    var url = _results[0].Url;
                    if (!url.StartsWith("http", StringComparison.OrdinalIgnoreCase))
                        url = "https://" + url;
                    targetUri = new Uri(url);
                }
                else
                {
                    targetUri = new Uri("https://cloud.lexmark.com");
                }

                var proxyUri = ProxyHelper.GetSystemProxyUri(targetUri);
                if (proxyUri != null)
                {
                    return $"Proxy: {proxyUri.Host}:{proxyUri.Port} (detectado)";
                }
                return "Proxy: no detectado (conexi\u00f3n directa)";
            }
            catch
            {
                return "Proxy: no se pudo detectar";
            }
        }
    }
}
