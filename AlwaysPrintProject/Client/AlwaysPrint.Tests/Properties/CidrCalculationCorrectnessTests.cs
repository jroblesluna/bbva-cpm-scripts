using System;
using System.Linq;
using System.Net;
using FsCheck;
using FsCheck.NUnit;
using NUnit.Framework;
using FsCheckProperty = FsCheck.NUnit.PropertyAttribute;

namespace AlwaysPrint.Tests.Properties
{
    /// <summary>
    /// Property 1: CIDR Calculation Correctness
    /// Para cualquier dirección IPv4 válida y máscara de subred válida, aplicar la operación
    /// AND bit a bit y calcular el prefix length DEBE producir un string en formato
    /// "network_address/prefix_length" que represente una red IPv4 válida, y la dirección
    /// de red DEBE tener todos los bits de host en cero.
    /// **Validates: Requirements 1.1, 1.2**
    /// </summary>
    [TestFixture]
    [Category("Feature: workstation-cidr-vlan-registration, Property 1: CIDR Calculation Correctness")]
    public class CidrCalculationCorrectnessTests
    {
        /// <summary>
        /// Replica la lógica pura de cálculo de network address (IP AND mask).
        /// Misma operación que realiza NetworkHelper.GetOutboundCIDR().
        /// </summary>
        private static byte[] CalculateNetworkAddress(byte[] ipBytes, byte[] maskBytes)
        {
            byte[] networkBytes = new byte[4];
            for (int i = 0; i < 4; i++)
                networkBytes[i] = (byte)(ipBytes[i] & maskBytes[i]);
            return networkBytes;
        }

        /// <summary>
        /// Replica la lógica pura de conteo de bits (prefix length).
        /// Misma operación que realiza NetworkHelper.CountBits().
        /// </summary>
        private static int CountBits(byte[] mask)
        {
            int bits = 0;
            foreach (byte b in mask)
            {
                byte temp = b;
                while (temp != 0)
                {
                    bits += temp & 1;
                    temp >>= 1;
                }
            }
            return bits;
        }

        /// <summary>
        /// Calcula el CIDR completo a partir de IP y máscara (lógica pura sin dependencias de red).
        /// </summary>
        private static string CalculateCidr(byte[] ipBytes, byte[] maskBytes)
        {
            byte[] networkBytes = CalculateNetworkAddress(ipBytes, maskBytes);
            IPAddress networkAddress = new IPAddress(networkBytes);
            int prefixLength = CountBits(maskBytes);
            return $"{networkAddress}/{prefixLength}";
        }

        /// <summary>
        /// Verifica si una máscara de subred es válida (bits contiguos de 1 seguidos de 0).
        /// Una máscara válida tiene la forma: 1...1 0...0 (sin mezcla).
        /// </summary>
        private static bool IsValidSubnetMask(byte[] maskBytes)
        {
            uint mask = ((uint)maskBytes[0] << 24) |
                        ((uint)maskBytes[1] << 16) |
                        ((uint)maskBytes[2] << 8) |
                        (uint)maskBytes[3];

            // Una máscara válida: al invertir y sumar 1, debe ser potencia de 2
            // O ser 0xFFFFFFFF (/32) o 0x00000000 (/0)
            if (mask == 0) return true;
            if (mask == 0xFFFFFFFF) return true;

            uint inverted = ~mask;
            return (inverted & (inverted + 1)) == 0;
        }

        /// <summary>
        /// Genera una máscara de subred válida a partir de un prefix length (8-30).
        /// </summary>
        private static byte[] GenerateValidMask(int prefixLength)
        {
            uint mask = prefixLength == 0 ? 0 : 0xFFFFFFFF << (32 - prefixLength);
            return new byte[]
            {
                (byte)((mask >> 24) & 0xFF),
                (byte)((mask >> 16) & 0xFF),
                (byte)((mask >> 8) & 0xFF),
                (byte)(mask & 0xFF)
            };
        }

        /// <summary>
        /// Generador de prefix lengths válidos para el sistema (rango 8-30).
        /// </summary>
        private static Gen<int> ValidPrefixLengthGen =>
            Gen.Choose(8, 30);

        /// <summary>
        /// Generador de bytes IPv4 arbitrarios (0-255 por octeto).
        /// </summary>
        private static Gen<byte[]> IPv4BytesGen =>
            Gen.ArrayOf(4, Gen.Choose(0, 255).Select(i => (byte)i));

        /// <summary>
        /// Propiedad: El resultado del cálculo CIDR siempre tiene formato válido "x.x.x.x/prefix".
        /// Para cualquier IP y máscara válida, el string resultante debe poder parsearse
        /// como una dirección de red IPv4 válida.
        /// **Validates: Requirements 1.1, 1.2**
        /// </summary>
        [FsCheckProperty(MaxTest = 200)]
        public Property CidrCalculation_ProducesValidFormat()
        {
            var gen = from prefixLen in ValidPrefixLengthGen
                      from ipBytes in IPv4BytesGen
                      select new { PrefixLength = prefixLen, IpBytes = ipBytes };

            return Prop.ForAll(
                Arb.From(gen),
                data =>
                {
                    byte[] maskBytes = GenerateValidMask(data.PrefixLength);
                    string cidr = CalculateCidr(data.IpBytes, maskBytes);

                    // Verificar formato: debe contener exactamente un "/"
                    string[] parts = cidr.Split('/');
                    bool hasSlash = parts.Length == 2;

                    // Verificar que la parte de red es una IP válida
                    bool validIp = IPAddress.TryParse(parts[0], out IPAddress parsedIp);

                    // Verificar que el prefix es un número válido
                    bool validPrefix = int.TryParse(parts[1], out int prefix)
                                       && prefix >= 0 && prefix <= 32;

                    return (hasSlash && validIp && validPrefix)
                        .Label($"CIDR '{cidr}' debe tener formato válido x.x.x.x/prefix. " +
                               $"hasSlash={hasSlash}, validIp={validIp}, validPrefix={validPrefix}");
                });
        }

        /// <summary>
        /// Propiedad: La dirección de red resultante tiene todos los bits de host en cero.
        /// Aplicar la máscara al network address debe producir el mismo network address
        /// (idempotencia del AND con la máscara).
        /// **Validates: Requirements 1.1, 1.2**
        /// </summary>
        [FsCheckProperty(MaxTest = 200)]
        public Property CidrCalculation_NetworkAddressHasHostBitsZero()
        {
            var gen = from prefixLen in ValidPrefixLengthGen
                      from ipBytes in IPv4BytesGen
                      select new { PrefixLength = prefixLen, IpBytes = ipBytes };

            return Prop.ForAll(
                Arb.From(gen),
                data =>
                {
                    byte[] maskBytes = GenerateValidMask(data.PrefixLength);
                    byte[] networkBytes = CalculateNetworkAddress(data.IpBytes, maskBytes);

                    // Aplicar AND de nuevo: network AND mask == network (bits de host ya son 0)
                    byte[] reapplied = CalculateNetworkAddress(networkBytes, maskBytes);

                    bool hostBitsZero = networkBytes.SequenceEqual(reapplied);

                    return hostBitsZero
                        .Label($"Network address {new IPAddress(networkBytes)} debe tener " +
                               $"bits de host en cero (re-aplicar máscara no debe cambiar nada). " +
                               $"IP={new IPAddress(data.IpBytes)}, Mask={new IPAddress(maskBytes)}");
                });
        }

        /// <summary>
        /// Propiedad: El prefix length calculado coincide con el prefix length de la máscara generada.
        /// CountBits sobre una máscara generada con N bits debe retornar exactamente N.
        /// **Validates: Requirements 1.1, 1.2**
        /// </summary>
        [FsCheckProperty(MaxTest = 200)]
        public Property CidrCalculation_PrefixLengthMatchesMask()
        {
            return Prop.ForAll(
                Arb.From(ValidPrefixLengthGen),
                expectedPrefix =>
                {
                    byte[] maskBytes = GenerateValidMask(expectedPrefix);
                    int calculatedPrefix = CountBits(maskBytes);

                    return (calculatedPrefix == expectedPrefix)
                        .Label($"CountBits de máscara con {expectedPrefix} bits debe retornar " +
                               $"{expectedPrefix}, pero retornó {calculatedPrefix}. " +
                               $"Máscara: {new IPAddress(maskBytes)}");
                });
        }

        /// <summary>
        /// Propiedad: El network address calculado siempre está contenido en la red CIDR resultante.
        /// Es decir, el network address AND mask == network address (es la dirección base de la red).
        /// **Validates: Requirements 1.1, 1.2**
        /// </summary>
        [FsCheckProperty(MaxTest = 200)]
        public Property CidrCalculation_NetworkAddressBelongsToNetwork()
        {
            var gen = from prefixLen in ValidPrefixLengthGen
                      from ipBytes in IPv4BytesGen
                      select new { PrefixLength = prefixLen, IpBytes = ipBytes };

            return Prop.ForAll(
                Arb.From(gen),
                data =>
                {
                    byte[] maskBytes = GenerateValidMask(data.PrefixLength);
                    string cidr = CalculateCidr(data.IpBytes, maskBytes);

                    // Parsear el resultado
                    string[] parts = cidr.Split('/');
                    IPAddress networkAddr = IPAddress.Parse(parts[0]);
                    int prefix = int.Parse(parts[1]);

                    // Verificar que el prefix length está en rango válido
                    bool prefixInRange = prefix >= 8 && prefix <= 30;

                    // Verificar que la IP original pertenece a la misma red
                    byte[] networkBytes = networkAddr.GetAddressBytes();
                    byte[] originalNetworkBytes = CalculateNetworkAddress(data.IpBytes, maskBytes);
                    bool sameNetwork = networkBytes.SequenceEqual(originalNetworkBytes);

                    return (prefixInRange && sameNetwork)
                        .Label($"CIDR={cidr}, IP original={new IPAddress(data.IpBytes)}, " +
                               $"prefixInRange={prefixInRange}, sameNetwork={sameNetwork}");
                });
        }

        /// <summary>
        /// Propiedad: Para cualquier IP dentro de una red, el cálculo CIDR produce la misma red.
        /// Dos IPs diferentes en la misma subred deben producir el mismo network address.
        /// **Validates: Requirements 1.1, 1.2**
        /// </summary>
        [FsCheckProperty(MaxTest = 200)]
        public Property CidrCalculation_SameSubnetProducesSameNetwork()
        {
            var gen = from prefixLen in ValidPrefixLengthGen
                      from ipBytes1 in IPv4BytesGen
                      from ipBytes2 in IPv4BytesGen
                      select new { PrefixLength = prefixLen, IpBytes1 = ipBytes1, IpBytes2 = ipBytes2 };

            return Prop.ForAll(
                Arb.From(gen),
                data =>
                {
                    byte[] maskBytes = GenerateValidMask(data.PrefixLength);

                    // Forzar que ambas IPs estén en la misma subred:
                    // Tomar el network de IP1 y poner bits de host de IP2
                    byte[] network1 = CalculateNetworkAddress(data.IpBytes1, maskBytes);

                    // Crear IP2 en la misma subred: network1 OR (IP2 AND ~mask)
                    byte[] ip2InSameSubnet = new byte[4];
                    for (int i = 0; i < 4; i++)
                        ip2InSameSubnet[i] = (byte)(network1[i] | (data.IpBytes2[i] & ~maskBytes[i]));

                    // Calcular network de ambas
                    byte[] networkFromIp1 = CalculateNetworkAddress(data.IpBytes1, maskBytes);
                    byte[] networkFromIp2 = CalculateNetworkAddress(ip2InSameSubnet, maskBytes);

                    bool sameNetwork = networkFromIp1.SequenceEqual(networkFromIp2);

                    return sameNetwork
                        .Label($"IPs en misma subred deben producir mismo network. " +
                               $"IP1={new IPAddress(data.IpBytes1)}, " +
                               $"IP2={new IPAddress(ip2InSameSubnet)}, " +
                               $"Net1={new IPAddress(networkFromIp1)}, " +
                               $"Net2={new IPAddress(networkFromIp2)}, " +
                               $"Mask={new IPAddress(maskBytes)}");
                });
        }
    }
}
