using System;
using System.Linq;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrint.Shared.Network
{
    /// <summary>
    /// Helper para obtener información de red de la workstation.
    /// Detecta la IP privada de la interfaz física (Ethernet/WiFi) que se usa
    /// para conectarse a Internet, ignorando interfaces virtuales.
    /// </summary>
    public static class NetworkHelper
    {
        /// <summary>
        /// Obtiene la IP privada de la interfaz de red que se usa para conectarse a Internet.
        /// 
        /// Estrategia:
        /// 1. Crea un socket UDP hacia un servidor público (no envía datos reales)
        /// 2. El sistema operativo selecciona automáticamente la interfaz correcta
        /// 3. Obtiene la IP local del socket (la IP que se usaría para salir a Internet)
        /// 
        /// Esta técnica es más confiable que enumerar interfaces porque:
        /// - Ignora automáticamente interfaces virtuales inactivas
        /// - Respeta las tablas de ruteo del sistema operativo
        /// - Detecta la interfaz que realmente se usa para tráfico saliente
        /// </summary>
        /// <returns>IP privada de la interfaz principal, o "unknown" si no se puede detectar</returns>
        public static string GetOutboundLocalIP()
        {
            try
            {
                // Crear un socket UDP hacia un servidor público
                // No se envían datos reales, solo se usa para que el SO seleccione la interfaz
                using (Socket socket = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, 0))
                {
                    // Conectar a un servidor DNS público (Google DNS)
                    // El puerto y el servidor no importan, solo necesitamos que el SO
                    // determine qué interfaz usaría para llegar a Internet
                    socket.Connect("8.8.8.8", 80);
                    
                    IPEndPoint? endPoint = socket.LocalEndPoint as IPEndPoint;
                    if (endPoint != null)
                    {
                        string localIP = endPoint.Address.ToString();
                        AlwaysPrintLogger.WriteTrayInfo(
                            $"NetworkHelper: IP local detectada (interfaz saliente): {localIP}");
                        return localIP;
                    }
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"NetworkHelper: error al detectar IP local con socket: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
            }

            // Fallback: intentar con NetworkInterface (menos confiable)
            try
            {
                return GetOutboundLocalIPFromInterfaces();
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"NetworkHelper: error al detectar IP local con NetworkInterface: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
            }

            return "unknown";
        }

        /// <summary>
        /// Método alternativo: enumera interfaces de red y selecciona la mejor.
        /// Menos confiable que GetOutboundLocalIP() porque puede seleccionar
        /// una interfaz virtual si está activa.
        /// </summary>
        private static string GetOutboundLocalIPFromInterfaces()
        {
            var interfaces = NetworkInterface.GetAllNetworkInterfaces()
                .Where(ni => 
                    ni.OperationalStatus == OperationalStatus.Up &&
                    ni.NetworkInterfaceType != NetworkInterfaceType.Loopback &&
                    ni.NetworkInterfaceType != NetworkInterfaceType.Tunnel)
                .OrderBy(ni => GetInterfacePriority(ni))
                .ToList();

            foreach (var ni in interfaces)
            {
                var ipProps = ni.GetIPProperties();
                var unicastAddresses = ipProps.UnicastAddresses
                    .Where(addr => 
                        addr.Address.AddressFamily == AddressFamily.InterNetwork &&
                        !IPAddress.IsLoopback(addr.Address))
                    .ToList();

                if (unicastAddresses.Any())
                {
                    string ip = unicastAddresses.First().Address.ToString();
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"NetworkHelper: IP local detectada (interfaz {ni.Name}): {ip}");
                    return ip;
                }
            }

            return "unknown";
        }

        /// <summary>
        /// Asigna prioridad a las interfaces de red.
        /// Menor número = mayor prioridad.
        /// 
        /// Prioridad:
        /// 1. Ethernet (cableada)
        /// 2. WiFi (inalámbrica)
        /// 3. Otras interfaces físicas
        /// 4. Interfaces virtuales (menor prioridad)
        /// </summary>
        private static int GetInterfacePriority(NetworkInterface ni)
        {
            // Ethernet tiene máxima prioridad
            if (ni.NetworkInterfaceType == NetworkInterfaceType.Ethernet ||
                ni.NetworkInterfaceType == NetworkInterfaceType.Ethernet3Megabit ||
                ni.NetworkInterfaceType == NetworkInterfaceType.FastEthernetT ||
                ni.NetworkInterfaceType == NetworkInterfaceType.FastEthernetFx ||
                ni.NetworkInterfaceType == NetworkInterfaceType.GigabitEthernet)
            {
                // Pero si el nombre sugiere que es virtual, bajar prioridad
                if (IsVirtualInterface(ni))
                    return 100;
                return 1;
            }

            // WiFi tiene segunda prioridad
            if (ni.NetworkInterfaceType == NetworkInterfaceType.Wireless80211)
            {
                if (IsVirtualInterface(ni))
                    return 101;
                return 2;
            }

            // Otras interfaces físicas
            if (!IsVirtualInterface(ni))
                return 50;

            // Interfaces virtuales tienen menor prioridad
            return 200;
        }

        /// <summary>
        /// Detecta si una interfaz es virtual basándose en su nombre y descripción.
        /// </summary>
        private static bool IsVirtualInterface(NetworkInterface ni)
        {
            string name = ni.Name.ToLowerInvariant();
            string desc = ni.Description.ToLowerInvariant();

            // Patrones comunes de interfaces virtuales
            string[] virtualPatterns = new[]
            {
                "virtual", "vmware", "vbox", "virtualbox", "hyper-v", "hyperv",
                "vethernet", "vnic", "tap", "tun", "docker", "wsl", "vpn",
                "loopback", "pseudo", "teredo", "isatap", "6to4"
            };

            return virtualPatterns.Any(pattern => 
                name.Contains(pattern) || desc.Contains(pattern));
        }

        /// <summary>
        /// Obtiene el hostname de la workstation.
        /// </summary>
        public static string GetHostname()
        {
            try
            {
                return Dns.GetHostName();
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"NetworkHelper: error al obtener hostname: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
                return "unknown";
            }
        }

        /// <summary>
        /// Obtiene información completa de la workstation para enviar al backend.
        /// </summary>
        public static (string LocalIP, string Hostname) GetWorkstationInfo()
        {
            string localIP = GetOutboundLocalIP();
            string hostname = GetHostname();

            AlwaysPrintLogger.WriteTrayInfo(
                $"NetworkHelper: Workstation info - IP: {localIP}, Hostname: {hostname}");

            return (localIP, hostname);
        }
    }
}
