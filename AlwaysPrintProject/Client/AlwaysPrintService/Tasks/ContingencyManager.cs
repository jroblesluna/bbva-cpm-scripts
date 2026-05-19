using System;
using System.Collections.Generic;
using System.Linq;
using System.Management;
using System.Net.Sockets;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintService.Tasks
{
    /// <summary>
    /// Gestiona la lógica de contingencia: redirige la cola de impresión corporativa
    /// a una impresora directa (IP:puerto) cuando CPM falla.
    /// 
    /// Prioridad de selección de impresora:
    /// 1. Impresora favorita (seleccionada por el usuario en "Mis Impresoras")
    /// 2. Impresora por defecto (menor IP en la VLAN)
    /// 3. Iteración por las demás impresoras disponibles (orden por IP ascendente)
    /// 
    /// Notifica al usuario mediante callbacks sobre el estado de la contingencia.
    /// </summary>
    public sealed class ContingencyManager
    {
        private const int TcpConnectTimeoutMs = 3000;
        private const int DefaultPrinterPort = 9100;

        private readonly string _queueName;
        private bool _contingencyActive;
        private string? _currentPrinterIp;
        private int _currentPrinterPort;

        /// <summary>Se dispara cuando la contingencia se activa exitosamente con una impresora.</summary>
        public event Action<string, string, int>? ContingencyActivated; // (printerName, ip, port)

        /// <summary>Se dispara cuando una impresora falla y se intenta la siguiente.</summary>
        public event Action<string, string>? PrinterFailed; // (printerName, errorMessage)

        /// <summary>Se dispara cuando no hay ninguna impresora disponible para contingencia.</summary>
        public event Action? NoPrintersAvailable;

        /// <summary>Se dispara cuando la contingencia se desactiva (vuelta a modo normal).</summary>
        public event Action? ContingencyDeactivated;

        public bool IsContingencyActive => _contingencyActive;
        public string? CurrentPrinterIp => _currentPrinterIp;

        public ContingencyManager(string queueName)
        {
            _queueName = queueName ?? throw new ArgumentNullException(nameof(queueName));
        }

        /// <summary>
        /// Activa la contingencia: intenta redirigir la cola a una impresora directa.
        /// Itera por la lista de impresoras en orden de prioridad hasta encontrar una accesible.
        /// </summary>
        /// <param name="printers">Lista de impresoras ordenadas por prioridad (favorita primero, luego por IP).</param>
        /// <returns>true si se logró redirigir a alguna impresora; false si ninguna está accesible.</returns>
        public bool ActivateContingency(List<ContingencyPrinter> printers)
        {
            if (printers == null || printers.Count == 0)
            {
                AlwaysPrintLogger.WriteWarning(
                    "ContingencyManager: no hay impresoras configuradas para contingencia.",
                    AlwaysPrintLogger.EvtGenericWarning);
                NoPrintersAvailable?.Invoke();
                return false;
            }

            AlwaysPrintLogger.WriteInfo(
                $"ContingencyManager: activando contingencia. {printers.Count} impresora(s) disponible(s).");

            foreach (var printer in printers)
            {
                AlwaysPrintLogger.WriteInfo(
                    $"ContingencyManager: intentando conectar a {printer.Name} ({printer.IpAddress}:{printer.Port})...");

                if (TestTcpConnection(printer.IpAddress, printer.Port))
                {
                    // Impresora accesible — redirigir la cola
                    bool redirected = RedirectQueueToIp(printer.IpAddress, printer.Port);
                    if (redirected)
                    {
                        _contingencyActive = true;
                        _currentPrinterIp = printer.IpAddress;
                        _currentPrinterPort = printer.Port;

                        AlwaysPrintLogger.WriteInfo(
                            $"ContingencyManager: contingencia activada. Cola '{_queueName}' → {printer.Name} ({printer.IpAddress}:{printer.Port}).");
                        ContingencyActivated?.Invoke(printer.Name, printer.IpAddress, printer.Port);
                        return true;
                    }
                }
                else
                {
                    string errorMsg = $"No se pudo conectar a {printer.IpAddress}:{printer.Port}";
                    AlwaysPrintLogger.WriteWarning(
                        $"ContingencyManager: {errorMsg}. Intentando siguiente impresora...",
                        AlwaysPrintLogger.EvtGenericWarning);
                    PrinterFailed?.Invoke(printer.Name, errorMsg);
                }
            }

            // Ninguna impresora accesible
            AlwaysPrintLogger.WriteError(
                "ContingencyManager: ninguna impresora accesible para contingencia.",
                AlwaysPrintLogger.EvtGenericError);
            NoPrintersAvailable?.Invoke();
            return false;
        }

        /// <summary>
        /// Desactiva la contingencia: restaura la cola al modo CPM (loopback:9167).
        /// </summary>
        public bool DeactivateContingency()
        {
            if (!_contingencyActive) return true;

            bool restored = RedirectQueueToIp("127.0.0.1", 9167);
            if (restored)
            {
                _contingencyActive = false;
                _currentPrinterIp = null;
                AlwaysPrintLogger.WriteInfo(
                    $"ContingencyManager: contingencia desactivada. Cola '{_queueName}' restaurada a CPM (127.0.0.1:9167).");
                ContingencyDeactivated?.Invoke();
            }
            else
            {
                AlwaysPrintLogger.WriteError(
                    $"ContingencyManager: error al restaurar cola '{_queueName}' a modo CPM.",
                    AlwaysPrintLogger.EvtGenericError);
            }
            return restored;
        }

        /// <summary>
        /// Prueba conectividad TCP a una IP:puerto con timeout.
        /// </summary>
        private static bool TestTcpConnection(string ip, int port)
        {
            try
            {
                using var client = new TcpClient();
                var result = client.BeginConnect(ip, port, null, null);
                bool connected = result.AsyncWaitHandle.WaitOne(TcpConnectTimeoutMs);
                if (connected)
                {
                    client.EndConnect(result);
                    return true;
                }
                return false;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// Redirige el puerto TCP/IP de la cola de impresión Windows a una nueva IP:puerto via WMI.
        /// Si el puerto no existe, lo crea. Si existe, actualiza su HostAddress y PortNumber.
        /// </summary>
        private bool RedirectQueueToIp(string targetIp, int targetPort)
        {
            try
            {
                // 1. Encontrar la cola y su puerto actual
                string safeQueue = _queueName.Replace("'", "''");
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
                    AlwaysPrintLogger.WriteError(
                        $"ContingencyManager: cola '{_queueName}' no encontrada en WMI.",
                        AlwaysPrintLogger.EvtGenericError);
                    return false;
                }

                string currentPortName = printer["PortName"]?.ToString() ?? "";

                // 2. Buscar el puerto TCP/IP existente
                string safePort = currentPortName.Replace("'", "''");
                using var portSearch = new ManagementObjectSearcher(
                    @"\\.\root\cimv2",
                    $"SELECT * FROM Win32_TCPIPPrinterPort WHERE Name = '{safePort}'");

                ManagementObject? port = null;
                foreach (ManagementObject obj in portSearch.Get())
                {
                    port = obj;
                    break;
                }

                if (port != null)
                {
                    // Actualizar el puerto existente
                    port["HostAddress"] = targetIp;
                    port["PortNumber"] = targetPort;
                    port.Put();

                    AlwaysPrintLogger.WriteInfo(
                        $"ContingencyManager: puerto '{currentPortName}' actualizado a {targetIp}:{targetPort}.");
                    return true;
                }
                else
                {
                    // El puerto no es TCP/IP — crear uno nuevo y asignarlo
                    string newPortName = $"AP_{targetIp}_{targetPort}";
                    bool created = CreateTcpIpPort(newPortName, targetIp, targetPort);
                    if (!created) return false;

                    // Asignar el nuevo puerto a la impresora
                    printer["PortName"] = newPortName;
                    printer.Put();

                    AlwaysPrintLogger.WriteInfo(
                        $"ContingencyManager: nuevo puerto '{newPortName}' creado y asignado a cola '{_queueName}'.");
                    return true;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"ContingencyManager: error WMI al redirigir cola. {ex.GetType().Name}: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
                return false;
            }
        }

        /// <summary>Crea un puerto TCP/IP de impresora via WMI.</summary>
        private static bool CreateTcpIpPort(string portName, string hostAddress, int portNumber)
        {
            try
            {
                var portClass = new ManagementClass("Win32_TCPIPPrinterPort");
                var newPort = portClass.CreateInstance();
                if (newPort == null) return false;

                newPort["Name"] = portName;
                newPort["HostAddress"] = hostAddress;
                newPort["PortNumber"] = portNumber;
                newPort["Protocol"] = 1; // RAW
                newPort["SNMPEnabled"] = false;
                newPort.Put();

                return true;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"ContingencyManager: error creando puerto TCP/IP '{portName}'. {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
                return false;
            }
        }
    }

    /// <summary>
    /// Representa una impresora candidata para contingencia, ordenada por prioridad.
    /// </summary>
    public class ContingencyPrinter
    {
        public string Id { get; set; } = "";
        public string Name { get; set; } = "";
        public string IpAddress { get; set; } = "";
        public int Port { get; set; } = 9100;
        public bool IsFavorite { get; set; }
        public bool IsDefault { get; set; }
    }
}
