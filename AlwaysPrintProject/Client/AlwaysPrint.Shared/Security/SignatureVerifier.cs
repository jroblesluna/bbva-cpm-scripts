using System;
using System.IO;
using System.Net.Http;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Threading.Tasks;
using AlwaysPrint.Shared.Logging;
using Microsoft.Win32;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AlwaysPrint.Shared.Security
{
    /// <summary>
    /// Verificador de firma digital ECDSA para configuraciones de AlwaysPrint.
    /// Valida la integridad y autenticidad de los archivos .alwaysconfig firmados
    /// descargados desde la Cloud.
    /// </summary>
    public static class SignatureVerifier
    {
        /// <summary>Ruta del registro para la versión del certificado.</summary>
#if ENV_DEV
        private const string RegistryPath = @"SOFTWARE\Robles.AI\AlwaysPrint-DEV";
#else
        private const string RegistryPath = @"SOFTWARE\Robles.AI\AlwaysPrint";
#endif

        private const string CertVersionValueName = "CertVersion";

        // ═══════════════════════════════════════════════════════════════════════
        // HELPERS DE LOGGING CON SOURCE CONFIGURABLE
        // ═══════════════════════════════════════════════════════════════════════

        private static void LogInfo(string message, bool traySource)
        {
            if (traySource)
                AlwaysPrintLogger.WriteTrayInfo(message);
            else
                AlwaysPrintLogger.WriteInfo(message);
        }

        private static void LogWarning(string message, bool traySource, int eventId = AlwaysPrintLogger.EvtGenericWarning)
        {
            if (traySource)
                AlwaysPrintLogger.WriteTrayWarning(message, eventId);
            else
                AlwaysPrintLogger.WriteWarning(message, eventId);
        }

        private static void LogError(string message, bool traySource, int eventId = AlwaysPrintLogger.EvtGenericError)
        {
            if (traySource)
                AlwaysPrintLogger.WriteTrayError(message, eventId);
            else
                AlwaysPrintLogger.WriteError(message, eventId);
        }

        private static void LogError(string message, Exception ex, bool traySource, int eventId = AlwaysPrintLogger.EvtGenericError)
        {
            if (traySource)
                AlwaysPrintLogger.WriteTrayError(message, ex, eventId);
            else
                AlwaysPrintLogger.WriteError(message, ex, eventId);
        }

        // ═══════════════════════════════════════════════════════════════════════
        // VERIFICACIÓN DE CONFIGURACIÓN FIRMADA
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Verifica la firma ECDSA de un JSON envolvente firmado.
        /// Parsea el JSON, valida el hash SHA256 del config, y verifica la firma ECDSA
        /// usando el certificado público proporcionado.
        /// </summary>
        /// <param name="signedJson">JSON envolvente con estructura: {"config":{...},"hash":"...","signature":"...","cert_version":N}</param>
        /// <param name="certPath">Ruta al archivo .cer del certificado público.</param>
        /// <param name="configJson">Si la verificación es exitosa, contiene el JSON serializado del config.</param>
        /// <param name="traySource">Si true, los logs se atribuyen al proceso Tray [APP]; si false, al Service [SVC].</param>
        /// <returns>true si hash y firma son válidos, false en caso contrario.</returns>
        public static bool VerifyConfig(string signedJson, string certPath, out string configJson, bool traySource = false)
        {
            configJson = null!;

            try
            {
                // 1. Parsear el JSON envolvente
                JObject envelope = JObject.Parse(signedJson);

                JToken? configToken = envelope["config"];
                string? hashHex = envelope["hash"]?.ToString();
                string? signatureBase64 = envelope["signature"]?.ToString();

                if (configToken == null || string.IsNullOrEmpty(hashHex) || string.IsNullOrEmpty(signatureBase64))
                {
                    LogError(
                        "SignatureVerifier: JSON envolvente inválido — faltan campos requeridos (config, hash, signature).",
                        traySource, AlwaysPrintLogger.EvtGenericError);
                    return false;
                }

                // 2. Verificar integridad: SHA256 del config serializado debe coincidir con hash declarado.
                // El backend normaliza el config con json.dumps(separators=(',',':')) antes de hashear,
                // que produce output idéntico a Newtonsoft configToken.ToString(Formatting.None).
                string serializedConfig = configToken.ToString(Formatting.None);
                byte[] configBytes = Encoding.UTF8.GetBytes(serializedConfig);
                byte[] computedHashBytes;

                using (var sha256 = SHA256.Create())
                {
                    computedHashBytes = sha256.ComputeHash(configBytes);
                }

                string computedHashHex = BitConverter.ToString(computedHashBytes).Replace("-", "").ToLowerInvariant();

                if (!computedHashHex.Equals(hashHex, StringComparison.OrdinalIgnoreCase))
                {
                    LogError(
                        $"SignatureVerifier: hash SHA256 del config no coincide. " +
                        $"Declarado: {hashHex.Substring(0, Math.Min(16, hashHex.Length))}..., " +
                        $"Calculado: {computedHashHex.Substring(0, 16)}... " +
                        "El contenido fue modificado en disco.",
                        traySource, AlwaysPrintLogger.EvtGenericError);
                    return false;
                }

                // hashBytes para verificación de firma (ya tenemos computedHashBytes que coincide)
                byte[] hashBytes = computedHashBytes;

                // 3. Cargar certificado X.509 y obtener clave pública ECDSA
                // (sabemos que hash corresponde al config — ahora verificamos autenticidad)
                if (!File.Exists(certPath))
                {
                    LogError(
                        $"SignatureVerifier: certificado no encontrado en {certPath}",
                        traySource, AlwaysPrintLogger.EvtGenericError);
                    return false;
                }

                using (var cert = new X509Certificate2(certPath))
                using (ECDsa ecDsa = cert.GetECDsaPublicKey())
                {
                    if (ecDsa == null)
                    {
                        LogError(
                            "SignatureVerifier: el certificado no contiene una clave pública ECDSA.",
                            traySource, AlwaysPrintLogger.EvtGenericError);
                        return false;
                    }

                    // 4. Verificar firma ECDSA del hash (integridad ya confirmada en paso 2)
                    // El backend Python firma con: private_key.sign(hash_bytes, ec.ECDSA(hashes.SHA256()))
                    // Esto significa que hash_bytes (32 bytes) son hasheados OTRA VEZ con SHA256 antes de firmar.
                    // En .NET, VerifyData(data, signature, HashAlgorithmName.SHA256) hace exactamente eso:
                    // hashea 'data' con SHA256 y luego verifica la firma ECDSA.
                    byte[] signatureBytes = Convert.FromBase64String(signatureBase64);

                    // Convertir de formato DER (Python cryptography) a IEEE P1363 (.NET Framework 4.8)
                    byte[] p1363Signature = ConvertDerToIeeeP1363(signatureBytes);

                    bool isValid = ecDsa.VerifyData(
                        hashBytes,
                        p1363Signature,
                        HashAlgorithmName.SHA256);

                    if (!isValid)
                    {
                        LogError(
                            "SignatureVerifier: firma ECDSA inválida — la configuración fue alterada o el certificado no corresponde.",
                            traySource, AlwaysPrintLogger.EvtGenericError);
                        return false;
                    }
                }

                // 5. Firma válida — extraer config como string para el ActionEngine
                configJson = configToken.ToString(Formatting.None);
                LogInfo(
                    "SignatureVerifier: verificación de firma ECDSA exitosa.", traySource);
                return true;
            }
            catch (JsonException ex)
            {
                LogError(
                    $"SignatureVerifier: error parseando JSON envolvente: {ex.Message}", ex,
                    traySource, AlwaysPrintLogger.EvtGenericError);
                return false;
            }
            catch (CryptographicException ex)
            {
                LogError(
                    $"SignatureVerifier: error criptográfico durante verificación: {ex.Message}", ex,
                    traySource, AlwaysPrintLogger.EvtGenericError);
                return false;
            }
            catch (Exception ex)
            {
                LogError(
                    $"SignatureVerifier: error inesperado durante verificación: {ex.Message}", ex,
                    traySource, AlwaysPrintLogger.EvtGenericError);
                return false;
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // DESCARGA DE CERTIFICADO
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Descarga el certificado público desde una URL y lo guarda en la ruta local especificada.
        /// Crea el directorio destino si no existe.
        /// </summary>
        /// <param name="certUrl">URL pública del certificado .cer en S3.</param>
        /// <param name="localPath">Ruta local donde guardar el certificado (ej: C:\ProgramData\AlwaysPrint\config\org.cer).</param>
        /// <param name="traySource">Si true, los logs se atribuyen al proceso Tray [APP]; si false, al Service [SVC].</param>
        /// <returns>true si la descarga y escritura fueron exitosas, false en caso contrario.</returns>
        public static async Task<bool> DownloadCertAsync(string certUrl, string localPath, bool traySource = false)
        {
            try
            {
                LogInfo(
                    $"SignatureVerifier: descargando certificado desde {certUrl}", traySource);

                using (var httpClient = new HttpClient())
                {
                    httpClient.Timeout = TimeSpan.FromSeconds(30);

                    byte[] certBytes = await httpClient.GetByteArrayAsync(certUrl);

                    if (certBytes == null || certBytes.Length == 0)
                    {
                        LogError(
                            "SignatureVerifier: certificado descargado está vacío.",
                            traySource, AlwaysPrintLogger.EvtGenericError);
                        return false;
                    }

                    // Crear directorio si no existe
                    string directory = Path.GetDirectoryName(localPath);
                    if (!string.IsNullOrEmpty(directory) && !Directory.Exists(directory))
                    {
                        Directory.CreateDirectory(directory);
                    }

                    // Guardar certificado en disco
                    File.WriteAllBytes(localPath, certBytes);

                    LogInfo(
                        $"SignatureVerifier: certificado guardado exitosamente en {localPath} ({certBytes.Length} bytes)", traySource);
                    return true;
                }
            }
            catch (HttpRequestException ex)
            {
                LogError(
                    $"SignatureVerifier: error HTTP descargando certificado: {ex.Message}", ex,
                    traySource, AlwaysPrintLogger.EvtGenericError);
                return false;
            }
            catch (IOException ex)
            {
                LogError(
                    $"SignatureVerifier: error de I/O guardando certificado: {ex.Message}", ex,
                    traySource, AlwaysPrintLogger.EvtGenericError);
                return false;
            }
            catch (Exception ex)
            {
                LogError(
                    $"SignatureVerifier: error inesperado descargando certificado: {ex.Message}", ex,
                    traySource, AlwaysPrintLogger.EvtGenericError);
                return false;
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // GESTIÓN DE VERSIÓN DE CERTIFICADO EN REGISTRO
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Lee la versión del certificado almacenada localmente en el registro de Windows.
        /// Retorna 0 si el valor no existe o no se puede leer.
        /// </summary>
        /// <param name="traySource">Si true, los logs se atribuyen al proceso Tray [APP]; si false, al Service [SVC].</param>
        /// <returns>Versión del certificado local (0 si no se encuentra).</returns>
        public static int GetLocalCertVersion(bool traySource = false)
        {
            try
            {
                using (var key = Registry.LocalMachine.OpenSubKey(RegistryPath, writable: false))
                {
                    if (key == null) return 0;

                    var rawValue = key.GetValue(CertVersionValueName);
                    if (rawValue == null) return 0;

                    return Convert.ToInt32(rawValue);
                }
            }
            catch (Exception ex)
            {
                LogWarning(
                    $"SignatureVerifier: error leyendo CertVersion del registro, retornando 0. {ex.Message}",
                    traySource, AlwaysPrintLogger.EvtGenericWarning);
                return 0;
            }
        }

        /// <summary>
        /// Escribe la versión del certificado en el registro de Windows.
        /// Crea la clave de registro si no existe.
        /// Requiere privilegios de administrador (servicio LocalSystem).
        /// </summary>
        /// <param name="version">Número de versión del certificado a persistir.</param>
        public static void SetLocalCertVersion(int version)
        {
            try
            {
                using (var key = Registry.LocalMachine.CreateSubKey(RegistryPath, writable: true))
                {
                    if (key == null)
                    {
                        AlwaysPrintLogger.WriteError(
                            "SignatureVerifier: no se pudo crear/abrir la clave de registro para CertVersion.",
                            AlwaysPrintLogger.EvtGenericError);
                        return;
                    }

                    key.SetValue(CertVersionValueName, version, RegistryValueKind.DWord);

                    AlwaysPrintLogger.WriteInfo(
                        $"SignatureVerifier: CertVersion actualizado a {version} en registro.");
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"SignatureVerifier: error escribiendo CertVersion en registro: {ex.Message}", ex,
                    AlwaysPrintLogger.EvtGenericError);
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // CONVERSIÓN DE FORMATO DE FIRMA DER → IEEE P1363
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Convierte una firma ECDSA de formato DER (ASN.1) a formato IEEE P1363 (r || s).
        /// Python cryptography produce firmas en DER; .NET Framework 4.8 espera IEEE P1363.
        /// Para P-256, el resultado es siempre 64 bytes (32 bytes r + 32 bytes s).
        /// </summary>
        /// <param name="derSignature">Firma en formato DER/ASN.1 (variable length, ~70-72 bytes para P-256).</param>
        /// <param name="keySize">Tamaño del componente en bytes (32 para P-256).</param>
        /// <returns>Firma en formato IEEE P1363 (64 bytes fijos para P-256).</returns>
        private static byte[] ConvertDerToIeeeP1363(byte[] derSignature, int keySize = 32)
        {
            // DER format: SEQUENCE { INTEGER r, INTEGER s }
            // 30 <len> 02 <rLen> <r> 02 <sLen> <s>

            int offset = 0;

            // Verificar SEQUENCE tag (0x30)
            if (derSignature[offset++] != 0x30)
                throw new CryptographicException("Firma DER inválida: falta tag SEQUENCE");

            // Skip sequence length (puede ser 1 o 2 bytes en long form)
            int seqLen = derSignature[offset++];
            if (seqLen > 0x80)
                offset += (seqLen - 0x80); // Long form length

            // Parse INTEGER r
            if (derSignature[offset++] != 0x02)
                throw new CryptographicException("Firma DER inválida: falta tag INTEGER para r");
            int rLen = derSignature[offset++];
            byte[] rBytes = new byte[rLen];
            Array.Copy(derSignature, offset, rBytes, 0, rLen);
            offset += rLen;

            // Parse INTEGER s
            if (derSignature[offset++] != 0x02)
                throw new CryptographicException("Firma DER inválida: falta tag INTEGER para s");
            int sLen = derSignature[offset++];
            byte[] sBytes = new byte[sLen];
            Array.Copy(derSignature, offset, sBytes, 0, sLen);

            // Convertir a formato P1363 de tamaño fijo (strip leading zeros, pad a keySize)
            byte[] result = new byte[keySize * 2];

            // Copiar r (alineado a la derecha, strip leading zero de ASN.1 integer positivo)
            int rStart = (rBytes.Length > keySize) ? rBytes.Length - keySize : 0;
            int rCopyLen = Math.Min(rBytes.Length, keySize);
            int rDestOffset = keySize - rCopyLen;
            Array.Copy(rBytes, rStart, result, rDestOffset, rCopyLen);

            // Copiar s (alineado a la derecha, strip leading zero de ASN.1 integer positivo)
            int sStart = (sBytes.Length > keySize) ? sBytes.Length - keySize : 0;
            int sCopyLen = Math.Min(sBytes.Length, keySize);
            int sDestOffset = keySize + (keySize - sCopyLen);
            Array.Copy(sBytes, sStart, result, sDestOffset, sCopyLen);

            return result;
        }
    }
}
