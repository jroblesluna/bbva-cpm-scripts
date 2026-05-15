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
        /// 1. Busca la interfaz con gateway predeterminado configurado (la que sale a Internet)
        /// 2. Si falla, intenta con socket UDP hacia un servidor público
        /// 3. Si falla, enumera interfaces y las prioriza
        /// 
        /// Esta técnica prioriza la interfaz con gateway porque:
        /// - Es la que realmente se usa para tráfico saliente a Internet
        /// - Funciona correctamente incluso con proxies corporativos
        /// - Ignora automáticamente interfaces virtuales sin gateway
        /// </summary>
        /// <returns>IP privada de la interfaz principal, o "unknown" si no se puede detectar</returns>
        public static string GetOutboundLocalIP()
        {
            // Estrategia 1: Buscar interfaz con gateway predeterminado
            try
            {
                string? ipWithGateway = GetIPFromInterfaceWithGateway();
                if (!string.IsNullOrEmpty(ipWithGateway) && ipWithGateway != "unknown")
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"NetworkHelper: IP local detectada (interfaz con gateway): {ipWithGateway}");
                    return ipWithGateway;
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"NetworkHelper: error al detectar IP con gateway: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
            }

            // Estrategia 2: Usar socket UDP (puede fallar con proxies)
            try
            {
                // Crear un socket UDP hacia un servidor público
                // No se envían datos reales, solo se usa para que el SO seleccione la interfaz
                using (Socket socket = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, 0))
                {
                    // Conectar a un servidor DNS público (Google DNS)
                    socket.Connect("8.8.8.8", 80);
                    
                    IPEndPoint? endPoint = socket.LocalEndPoint as IPEndPoint;
                    if (endPoint != null)
                    {
                        string localIP = endPoint.Address.ToString();
                        
                        // Verificar que no sea una interfaz virtual
                        if (!IsVirtualIP(localIP))
                        {
                            AlwaysPrintLogger.WriteTrayInfo(
                                $"NetworkHelper: IP local detectada (socket): {localIP}");
                            return localIP;
                        }
                        else
                        {
                            AlwaysPrintLogger.WriteTrayInfo(
                                $"NetworkHelper: socket retornó IP virtual ({localIP}), usando fallback");
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"NetworkHelper: error al detectar IP local con socket: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
            }

            // Estrategia 3: Fallback - enumerar interfaces
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
        /// Obtiene la IP de la interfaz que tiene un gateway predeterminado configurado.
        /// Esta es la interfaz que realmente se usa para salir a Internet.
        /// </summary>
        private static string? GetIPFromInterfaceWithGateway()
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
                
                // Verificar si tiene gateway configurado
                var gateways = ipProps.GatewayAddresses
                    .Where(g => g.Address.AddressFamily == AddressFamily.InterNetwork)
                    .ToList();

                if (!gateways.Any())
                    continue; // Sin gateway, no es la interfaz principal

                // Obtener la IP de esta interfaz
                var unicastAddresses = ipProps.UnicastAddresses
                    .Where(addr => 
                        addr.Address.AddressFamily == AddressFamily.InterNetwork &&
                        !IPAddress.IsLoopback(addr.Address))
                    .ToList();

                if (unicastAddresses.Any())
                {
                    string ip = unicastAddresses.First().Address.ToString();
                    string gateway = gateways.First().Address.ToString();
                    
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"NetworkHelper: interfaz con gateway encontrada - {ni.Name}: IP={ip}, Gateway={gateway}");
                    
                    return ip;
                }
            }

            return null;
        }

        /// <summary>
        /// Verifica si una IP pertenece a una interfaz virtual basándose en su rango.
        /// </summary>
        private static bool IsVirtualIP(string ip)
        {
            // Rangos comunes de interfaces virtuales
            // VMware: 192.168.x.1 (típicamente .23.1, .189.1, etc.)
            // VirtualBox: 192.168.56.x
            // Docker: 172.17.x.x, 172.18.x.x
            // Hyper-V: 172.x.x.x
            
            if (ip.StartsWith("192.168.23.") || 
                ip.StartsWith("192.168.189.") ||
                ip.StartsWith("192.168.56.") ||
                ip.StartsWith("172.17.") ||
                ip.StartsWith("172.18."))
            {
                return true;
            }

            return false;
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
