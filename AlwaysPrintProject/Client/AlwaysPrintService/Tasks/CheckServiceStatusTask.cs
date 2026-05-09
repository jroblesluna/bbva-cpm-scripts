using System;
using System.Management;
using System.ServiceProcess;
using AlwaysPrint.Shared.Messages;

namespace AlwaysPrintService.Tasks
{
    /// <summary>
    /// Queries a Windows service status, binary path, and approximate start time via WMI.
    /// ServiceController alone does not expose the binary path or start time; WMI Win32_Service does.
    /// </summary>
    public sealed class CheckServiceStatusTask : IServiceTask
    {
        private readonly string _serviceName;

        public CheckServiceStatusTask(string serviceName)
        {
            _serviceName = serviceName ?? throw new ArgumentNullException(nameof(serviceName));
        }

        public ServiceTaskResult Execute()
        {
            var result = new CheckServiceStatusResponsePayload
            {
                ServiceName = _serviceName,
                State       = "NotFound"
            };

            try
            {
                // Basic state check via ServiceController.
                using var sc = new ServiceController(_serviceName);
                result.State = sc.Status.ToString();
            }
            catch (InvalidOperationException)
            {
                result.State = "NotFound";
                return ServiceTaskResult.Ok($"Service '{_serviceName}' not found.", result);
            }

            // Enrich with binary path and approximate start time from WMI.
            try
            {
                string safeName = EscapeWql(_serviceName);
                using var search = new ManagementObjectSearcher(
                    @"\\.\root\cimv2",
                    $"SELECT PathName, ProcessId FROM Win32_Service WHERE Name = '{safeName}'");

                foreach (ManagementObject obj in search.Get())
                {
                    result.BinaryPath = obj["PathName"]?.ToString();

                    // Resolve process start time from Win32_Process if the service is running.
                    var pidObj = obj["ProcessId"];
                    if (pidObj != null)
                    {
                        uint pid = Convert.ToUInt32(pidObj);
                        if (pid > 0)
                            result.StartTime = GetProcessStartTime(pid);
                    }
                    break;
                }
            }
            catch { /* WMI enrichment is best-effort; status is already known. */ }

            return ServiceTaskResult.Ok($"Service '{_serviceName}' state={result.State}", result);
        }

        private static string? GetProcessStartTime(uint pid)
        {
            try
            {
                using var search = new ManagementObjectSearcher(
                    @"\\.\root\cimv2",
                    $"SELECT CreationDate FROM Win32_Process WHERE ProcessId = {pid}");

                foreach (ManagementObject obj in search.Get())
                {
                    var raw = obj["CreationDate"]?.ToString();
                    if (!string.IsNullOrWhiteSpace(raw))
                    {
                        // WMI datetime format: yyyymmddHHmmss.ffffff+zzz
                        var dt = ManagementDateTimeConverter.ToDateTime(raw);
                        return dt.ToLocalTime().ToString("o");
                    }
                }
            }
            catch { /* ignore */ }
            return null;
        }

        private static string EscapeWql(string value) =>
            value.Replace("\\", "\\\\").Replace("'", "\\'");
    }
}
