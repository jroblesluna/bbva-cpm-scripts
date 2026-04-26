using System;
using System.ServiceProcess;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintService
{
    internal static class Program
    {
        [STAThread]
        private static void Main(string[] args)
        {
            EventLogWriter.EnsureSourceExists();

            // /console flag allows running outside the SCM for debugging.
            if (args.Length > 0 && args[0].Equals("/console", StringComparison.OrdinalIgnoreCase))
            {
                Console.WriteLine("AlwaysPrintService running in console mode. Press Enter to stop.");
                var svc = new AlwaysPrintWindowsService();
                svc.TestStartFromConsole();
                Console.ReadLine();
                svc.TestStopFromConsole();
            }
            else
            {
                ServiceBase.Run(new AlwaysPrintWindowsService());
            }
        }
    }
}
