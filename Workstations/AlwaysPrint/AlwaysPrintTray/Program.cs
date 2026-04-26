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
                EventLogWriter.WriteTrayWarning("AlwaysPrintTray: another instance is already running. Exiting.",
                    EventLogWriter.EvtDuplicateInstance);
                return;
            }

            try
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);

                EventLogWriter.WriteTrayInfo("AlwaysPrintTray started.", EventLogWriter.EvtServiceStarted);
                Application.Run(new TrayApplicationContext());
            }
            catch (Exception ex)
            {
                EventLogWriter.WriteTrayError("AlwaysPrintTray unhandled exception.", ex, EventLogWriter.EvtGenericError);
            }
            finally
            {
                EventLogWriter.WriteTrayInfo("AlwaysPrintTray exiting.", EventLogWriter.EvtServiceStopped);
                mutex.ReleaseMutex();
            }
        }
    }
}
