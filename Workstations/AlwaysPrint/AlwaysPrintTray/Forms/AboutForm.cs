using System;
using System.Drawing;
using System.Reflection;
using System.Windows.Forms;

namespace AlwaysPrintTray.Forms
{
    public sealed class AboutForm : Form
    {
        public AboutForm()
        {
            var version = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "1.0.0";

            Text            = "Acerca de AlwaysPrint";
            Size            = new Size(380, 200);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox     = false;
            MinimizeBox     = false;
            StartPosition   = FormStartPosition.CenterScreen;
            ShowInTaskbar   = false;

            var lblTitle = new Label
            {
                Text      = "AlwaysPrint",
                Font      = new Font("Segoe UI", 14, FontStyle.Bold),
                Location  = new Point(20, 20),
                AutoSize  = true
            };

            var lblVersion = new Label
            {
                Text     = $"Versión {version}",
                Location = new Point(20, 55),
                AutoSize = true
            };

            var lblCopyright = new Label
            {
                Text     = "© 2025 Robles.AI – Lexmark International",
                Location = new Point(20, 80),
                AutoSize = true
            };

            var lblDesc = new Label
            {
                Text      = "Servicio de impresión corporativa para BBVA.",
                Location  = new Point(20, 105),
                AutoSize  = true,
                ForeColor = SystemColors.GrayText
            };

            var btnOk = new Button
            {
                Text          = "Cerrar",
                DialogResult  = DialogResult.OK,
                Location      = new Point(280, 130),
                Size          = new Size(75, 28)
            };

            Controls.AddRange(new Control[] { lblTitle, lblVersion, lblCopyright, lblDesc, btnOk });
            AcceptButton = btnOk;
        }
    }
}
