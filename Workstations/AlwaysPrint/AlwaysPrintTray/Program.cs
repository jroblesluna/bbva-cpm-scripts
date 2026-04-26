using System;
using System.Diagnostics;
using System.Threading;
using System.Windows.Forms;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray
{
    internal static class Program
    {
        // Global mutex name – unique per machine, prevents multiple Tray instances.
        private const string MutexName = "Global\\AlwaysPrintTray-SingleInstance";

        [STAThread]
        private static void Main()
        {
            EventLogWriter.EnsureSourceExists();

            // Single-instance guard using a named mutex.
            using var mutex = new Mutex(initiallyOwned: true, MutexName, out bool isNew);

            if (!isNew)
            {
                EventLogWriter.WriteWarning("AlwaysPrintTray: another instance is already running. Exiting.",
                    EventLogWriter.EvtDuplicateInstance);
                return;
            }

            try
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);

                EventLogWriter.WriteInfo("AlwaysPrintTray started.", EventLogWriter.EvtServiceStarted);
                Application.Run(new TrayApplicationContext());
            }
            catch (Exception ex)
            {
                EventLogWriter.WriteError("AlwaysPrintTray unhandled exception.", ex, EventLogWriter.EvtGenericError);
            }
            finally
            {
                EventLogWriter.WriteInfo("AlwaysPrintTray exiting.", EventLogWriter.EvtServiceStopped);
                mutex.ReleaseMutex();
            }
        }
    }
}
