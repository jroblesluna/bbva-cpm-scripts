using System;
using System.Diagnostics;
using System.Net;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
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

        // AUMID para notificaciones toast en Windows 10/11 (mismo para dev y prod)
        private const string AppUserModelId = "Robles.AI.AlwaysPrint";

        [DllImport("shell32.dll", SetLastError = true)]
        private static extern void SetCurrentProcessExplicitAppUserModelID(
            [MarshalAs(UnmanagedType.LPWStr)] string AppID);

        [STAThread]
        private static void Main()
        {
            // Registrar AUMID antes de cualquier UI para que las notificaciones toast
            // muestren el nombre correcto de la aplicación.
            SetCurrentProcessExplicitAppUserModelID(AppUserModelId);

            // Forzar TLS 1.2 para todas las conexiones (requerido por WebSocket4Net en .NET 4.8)
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;

            AlwaysPrintLogger.EnsureSourceExists();

            // Protección: si el Tray fue lanzado como SYSTEM (session 0), salir inmediatamente.
            // Esto puede ocurrir si CreateProcessAsUser falla silenciosamente o si el proceso
            // se hereda del contexto del Service en lugar de la sesión interactiva del usuario.
            var currentIdentity = WindowsIdentity.GetCurrent();
            if (currentIdentity.IsSystem ||
                currentIdentity.User?.Value == "S-1-5-18") // NT AUTHORITY\SYSTEM
            {
                AlwaysPrintLogger.WriteTrayError(
                    "AlwaysPrintTray: detectado ejecución como SYSTEM (session 0). " +
                    "El Tray debe ejecutarse en la sesión interactiva del usuario. Saliendo.",
                    AlwaysPrintLogger.EvtGenericError);
                return;
            }

            // Single-instance guard using a named mutex.
            // Se configura MutexSecurity para permitir acceso a todos los usuarios,
            // evitando UnauthorizedAccessException cuando el Service (LocalSystem) lanza el Tray
            // en la sesión de un usuario con privilegios limitados.
            var mutexSecurity = new MutexSecurity();
            mutexSecurity.AddAccessRule(new MutexAccessRule(
                new SecurityIdentifier(WellKnownSidType.WorldSid, null),
                MutexRights.FullControl,
                AccessControlType.Allow));

            bool isNew;
            using var mutex = new Mutex(initiallyOwned: false, MutexName, out isNew, mutexSecurity);

            // Intentar adquirir ownership del mutex.
            // Se usa un timeout de 10 segundos para manejar la race condition durante
            // actualizaciones: el MSI mata la instancia vieja pero el Mutex tarda un
            // instante en liberarse. Sin timeout, la nueva instancia se cierra prematuramente.
            try
            {
                isNew = mutex.WaitOne(TimeSpan.FromSeconds(10));
            }
            catch (AbandonedMutexException)
            {
                // El mutex fue abandonado por otra instancia que crasheó o fue matada — lo tomamos
                isNew = true;
            }

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
