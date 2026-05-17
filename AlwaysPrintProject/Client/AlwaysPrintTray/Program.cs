using System;
using System.Diagnostics;
using System.Net;
using System.Threading;
using System.Windows.Forms;
using AlwaysPrint.Shared.Logging;
using AlwaysPrintTray.Localization;

namespace AlwaysPrintTray
{
    internal static class Program
    {
        // Global mutex name – unique per machine, prevents multiple Tray instances.
        private const string MutexName = "Global\\AlwaysPrintTray-SingleInstance";

        [STAThread]
        private static void Main()
        {
            // Forzar TLS 1.2 para todas las conexiones (requerido por WebSocket4Net en .NET 4.8)
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;

            AlwaysPrintLogger.EnsureSourceExists();

            // Single-instance guard using a named mutex.
            using var mutex = new Mutex(initiallyOwned: true, MutexName, out bool isNew);

            if (!isNew)
            {
                AlwaysPrintLogger.WriteTrayWarning("AlwaysPrintTray: another instance is already running. Exiting.",
                    AlwaysPrintLogger.EvtDuplicateInstance);
                return;
            }

            try
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);

                // Inicializar el sistema de localización antes de construir el contexto del Tray
                LocalizationManager.Initialize();

                // Configurar headers HTTP con información de la workstation
                Bootstrap.DomainHealthChecker.ConfigureWorkstationHeaders();

                AlwaysPrintLogger.WriteTrayInfo($"AlwaysPrintTray started. Versión: {System.Reflection.Assembly.GetExecutingAssembly().GetName().Version}", AlwaysPrintLogger.EvtServiceStarted);
                Application.Run(new TrayApplicationContext());
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError("AlwaysPrintTray unhandled exception.", ex, AlwaysPrintLogger.EvtGenericError);
            }
            finally
            {
                AlwaysPrintLogger.WriteTrayInfo("AlwaysPrintTray exiting.", AlwaysPrintLogger.EvtServiceStopped);
                mutex.ReleaseMutex();
            }
        }
    }
}
