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

        // Nombre del mensaje Win32 registrado para comunicación entre instancias.
        // Cuando se detecta una segunda instancia, se envía este broadcast para que
        // la primera instancia muestre el formulario de estado.
        private const string BroadcastMessageName = "AlwaysPrintTray_ShowStatus";

        // AUMID para notificaciones toast en Windows 10/11 (mismo para dev y prod)
        private const string AppUserModelId = "AlwaysPrintTray";

        // Win32 interop: registrar mensaje personalizado por nombre
        [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        private static extern uint RegisterWindowMessage(string lpString);

        // Win32 interop: enviar mensaje a una o más ventanas
        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);

        // Handle especial para enviar mensaje a todas las ventanas top-level
        private static readonly IntPtr HWND_BROADCAST = new IntPtr(0xFFFF);

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

            // Registrar mensaje Win32 personalizado (ambas instancias usan el mismo nombre).
            // Si la segunda instancia detecta que el mutex está tomado, envía este broadcast
            // para que la primera instancia muestre el formulario de estado.
            uint showStatusMsgId = RegisterWindowMessage(BroadcastMessageName);

            bool isNew;
            using var mutex = new Mutex(initiallyOwned: false, MutexName, out isNew, mutexSecurity);

            // Intentar adquirir ownership del mutex.
            // Timeout corto (1s) para respuesta rápida al doble-click.
            // Si falla, se asume que hay otra instancia corriendo (caso normal).
            // El timeout de 10s anterior era para updates MSI, pero eso se maneja mejor
            // con retry: intentar 1s, si falla verificar si es post-update (servicio
            // recién mató la instancia vieja), si sí reintentar con timeout largo.
            try
            {
                isNew = mutex.WaitOne(TimeSpan.FromSeconds(1));
            }
            catch (AbandonedMutexException)
            {
                // El mutex fue abandonado por otra instancia que crasheó o fue matada — lo tomamos
                isNew = true;
            }

            if (!isNew)
            {
                // Segunda instancia detectada: enviar broadcast ShowStatus y salir.
                // La primera instancia recibirá este mensaje en su WndProc y mostrará
                // el formulario de estado.
                AlwaysPrintLogger.WriteTrayInfo(
                    "Segunda instancia detectada. Enviando broadcast ShowStatus.");
                PostMessage(HWND_BROADCAST, showStatusMsgId, IntPtr.Zero, IntPtr.Zero);
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
                Application.Run(new TrayApplicationContext(showStatusMsgId));
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
