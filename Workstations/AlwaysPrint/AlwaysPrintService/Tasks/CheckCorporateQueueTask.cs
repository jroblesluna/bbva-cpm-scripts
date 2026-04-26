using System;
using System.Linq;
using System.Management;
using System.Net;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Messages;

namespace AlwaysPrintService.Tasks
{
    /// <summary>
    /// Inspects a named Windows print queue using WMI to determine its port type,
    /// target IP, and whether it is in cloud (loopback CPM) or direct mode.
    /// </summary>
    public sealed class CheckCorporateQueueTask : IServiceTask
    {
        private const string LoopbackIp = "127.0.0.1";
        private const int    CloudPort  = 9167;

        private readonly string _queueName;
        private readonly SearchTargetsConfig _searchTargets;

        public CheckCorporateQueueTask(string queueName, SearchTargetsConfig searchTargets)
        {
            _queueName     = queueName ?? throw new ArgumentNullException(nameof(queueName));
            _searchTargets = searchTargets ?? new SearchTargetsConfig();
        }

        public ServiceTaskResult Execute()
        {
            var result = new CheckCorporateQueueResponsePayload { Exists = false };

            try
            {
                // 1. Find the printer in WMI.
                string safeQueue = EscapeWql(_queueName);
                using var printerSearch = new ManagementObjectSearcher(
                    @"\\.\root\cimv2",
                    $"SELECT Name, PortName FROM Win32_Printer WHERE Name = '{safeQueue}'");

                ManagementObject? printer = null;
                foreach (ManagementObject obj in printerSearch.Get())
                {
                    printer = obj;
                    break;
                }

                if (printer == null)
                {
                    result.Details = $"Queue '{_queueName}' not found.";
                    return ServiceTaskResult.Ok(result.Details, result);
                }

                result.Exists = true;
                string portName = printer["PortName"]?.ToString() ?? string.Empty;

                // 2. Query the TCP/IP port details.
                string safePort = EscapeWql(portName);
                using var portSearch = new ManagementObjectSearcher(
                    @"\\.\root\cimv2",
                    $"SELECT HostAddress, PortNumber, Protocol FROM Win32_TCPIPPrinterPort WHERE Name = '{safePort}'");

                ManagementObject? port = null;
                foreach (ManagementObject obj in portSearch.Get())
                {
                    port = obj;
                    break;
                }

                if (port == null)
                {
                    // Port exists but is not TCP/IP (e.g., USB, LPT).
                    result.PortType = "non-tcpip";
                    result.Details  = $"Port '{portName}' is not a TCP/IP port.";
                    return ServiceTaskResult.Ok(result.Details, result);
                }

                string ip       = port["HostAddress"]?.ToString() ?? string.Empty;
                int    portNum  = Convert.ToInt32(port["PortNumber"] ?? 9100);
                result.PortType = "TCPIP";

                // 3. Classify the target.
                if (ip == LoopbackIp && portNum == CloudPort)
                {
                    result.Cloud   = true;
                    result.Details = $"{LoopbackIp}:{CloudPort}";
                }
                else if (IsKnownTarget(ip))
                {
                    result.Cloud   = false;
                    result.Details = $"target:{ip}:{portNum}";
                }
                else
                {
                    result.Cloud   = false;
                    result.Details = $"unknown_target:{ip}:{portNum}";
                }

                return ServiceTaskResult.Ok($"Queue '{_queueName}' found. Cloud={result.Cloud}", result);
            }
            catch (Exception ex)
            {
                return ServiceTaskResult.Fail($"CheckCorporateQueueTask error: {ex.Message}", result);
            }
        }

        private bool IsKnownTarget(string ip)
        {
            // Check explicit IPs.
            if (!string.IsNullOrWhiteSpace(_searchTargets.Ips))
            {
                foreach (var known in _searchTargets.Ips.Split(','))
                {
                    if (known.Trim().Equals(ip, StringComparison.OrdinalIgnoreCase))
                        return true;
                }
            }

            // Check CIDR ranges.
            if (!string.IsNullOrWhiteSpace(_searchTargets.Ranges))
            {
                foreach (var cidr in _searchTargets.Ranges.Split(','))
                {
                    if (IsIpInCidr(ip, cidr.Trim()))
                        return true;
                }
            }

            return false;
        }

        private static bool IsIpInCidr(string ip, string cidr)
        {
            var parts = cidr.Split('/');
            if (parts.Length != 2) return false;
            if (!IPAddress.TryParse(ip, out var addr)) return false;
            if (!IPAddress.TryParse(parts[0], out var network)) return false;
            if (!int.TryParse(parts[1], out var prefix) || prefix < 0 || prefix > 32) return false;

            var ipBytes      = addr.GetAddressBytes();
            var networkBytes = network.GetAddressBytes();
            if (ipBytes.Length != 4 || networkBytes.Length != 4) return false;

            uint ipUint  = (uint)(ipBytes[0] << 24 | ipBytes[1] << 16 | ipBytes[2] << 8 | ipBytes[3]);
            uint netUint = (uint)(networkBytes[0] << 24 | networkBytes[1] << 16 | networkBytes[2] << 8 | networkBytes[3]);
            uint mask    = prefix == 0 ? 0u : ~(0xFFFFFFFFu >> prefix);

            return (ipUint & mask) == (netUint & mask);
        }

        // Prevents WQL injection via queue or port names.
        private static string EscapeWql(string value) =>
            value.Replace("\\", "\\\\").Replace("'", "\\'");
    }
}
