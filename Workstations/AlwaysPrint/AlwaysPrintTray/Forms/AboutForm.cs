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
            Size            = new Size(450, 280);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox     = false;
            MinimizeBox     = false;
            StartPosition   = FormStartPosition.CenterScreen;
            ShowInTaskbar   = false;

            // Logo
            var picLogo = new PictureBox
            {
                Location  = new Point(20, 20),
                Size      = new Size(80, 80),
                SizeMode  = PictureBoxSizeMode.Zoom,
                Image     = LoadLogoFromResource()
            };

            var lblTitle = new Label
            {
                Text      = "AlwaysPrint",
                Font      = new Font("Segoe UI", 16, FontStyle.Bold),
                Location  = new Point(115, 30),
                AutoSize  = true
            };

            var lblVersion = new Label
            {
                Text     = $"Versión {version}",
                Location = new Point(115, 65),
                AutoSize = true,
                Font     = new Font("Segoe UI", 9)
            };

            var lblCopyright = new Label
            {
                Text     = "© 2025 Robles.AI – Lexmark International",
                Location = new Point(20, 120),
                AutoSize = true,
                Font     = new Font("Segoe UI", 9)
            };

            var lblDesc = new Label
            {
                Text      = "Servicio de impresión corporativa para BBVA.",
                Location  = new Point(20, 145),
                AutoSize  = true,
                ForeColor = SystemColors.GrayText,
                Font      = new Font("Segoe UI", 9)
            };

            var lblContact = new Label
            {
                Text      = "Contacto: antonio@robles.ai",
                Location  = new Point(20, 170),
                AutoSize  = true,
                ForeColor = SystemColors.GrayText,
                Font      = new Font("Segoe UI", 9)
            };

            var btnOk = new Button
            {
                Text          = "Cerrar",
                DialogResult  = DialogResult.OK,
                Location      = new Point(345, 205),
                Size          = new Size(80, 30)
            };

            Controls.AddRange(new Control[] { picLogo, lblTitle, lblVersion, lblCopyright, lblDesc, lblContact, btnOk });
            AcceptButton = btnOk;
        }

        private static Image? LoadLogoFromResource()
        {
            try
            {
                var assembly = Assembly.GetExecutingAssembly();
                using var stream = assembly.GetManifestResourceStream("AlwaysPrintTray.Resources.logo.ico");
                if (stream != null)
                {
                    // Cargar el icono y convertirlo a bitmap
                    using var icon = new Icon(stream);
                    return icon.ToBitmap();
                }
            }
            catch
            {
                // Si falla, no mostrar logo
            }

            return null;
        }
    }
}
