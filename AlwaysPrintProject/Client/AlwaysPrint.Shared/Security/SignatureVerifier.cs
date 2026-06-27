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
        /// <returns>true si hash y firma son válidos, false en caso contrario.</returns>
        public static bool VerifyConfig(string signedJson, string certPath, out string configJson)
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
                    AlwaysPrintLogger.WriteError(
                        "SignatureVerifier: JSON envolvente inválido — faltan campos requeridos (config, hash, signature).",
                        AlwaysPrintLogger.EvtGenericError);
                    return false;
                }

                // 2. Serializar el config a JSON compacto (sin whitespace)
                string serializedConfig = configToken.ToString(Formatting.None);

                // 3. Calcular SHA256 del config serializado y comparar con el campo "hash"
                byte[] configBytes = Encoding.UTF8.GetBytes(serializedConfig);
                byte[] computedHashBytes;

                using (var sha256 = SHA256.Create())
                {
                    computedHashBytes = sha256.ComputeHash(configBytes);
                }

                string computedHashHex = BitConverter.ToString(computedHashBytes)
                    .Replace("-", "")
                    .ToLowerInvariant();

                if (!computedHashHex.Equals(hashHex, StringComparison.OrdinalIgnoreCase))
                {
                    AlwaysPrintLogger.WriteError(
                        $"SignatureVerifier: hash SHA256 no coincide. Esperado: {hashHex}, Calculado: {computedHashHex}",
                        AlwaysPrintLogger.EvtGenericError);
                    return false;
                }

                // 4. Cargar certificado X.509 y obtener clave pública ECDSA
                if (!File.Exists(certPath))
                {
                    AlwaysPrintLogger.WriteError(
                        $"SignatureVerifier: certificado no encontrado en {certPath}",
                        AlwaysPrintLogger.EvtGenericError);
                    return false;
                }

                using (var cert = new X509Certificate2(certPath))
                using (ECDsa ecDsa = cert.GetECDsaPublicKey())
                {
                    if (ecDsa == null)
                    {
                        AlwaysPrintLogger.WriteError(
                            "SignatureVerifier: el certificado no contiene una clave pública ECDSA.",
                            AlwaysPrintLogger.EvtGenericError);
                        return false;
                    }

                    // 5. Verificar firma ECDSA
                    // El backend Python firma con: private_key.sign(hash_bytes, ec.ECDSA(hashes.SHA256()))
                    // Esto significa que hash_bytes (32 bytes) son hasheados OTRA VEZ con SHA256 antes de firmar.
                    // En .NET, VerifyData(data, signature, HashAlgorithmName.SHA256) hace exactamente eso:
                    // hashea 'data' con SHA256 y luego verifica la firma ECDSA.
                    byte[] signatureBytes = Convert.FromBase64String(signatureBase64);

                    bool isValid = ecDsa.VerifyData(
                        computedHashBytes,
                        signatureBytes,
                        HashAlgorithmName.SHA256);

                    if (!isValid)
                    {
                        AlwaysPrintLogger.WriteError(
                            "SignatureVerifier: firma ECDSA inválida — la configuración pudo haber sido alterada.",
                            AlwaysPrintLogger.EvtGenericError);
                        return false;
                    }
                }

                // 6. Verificación exitosa
                configJson = serializedConfig;
                AlwaysPrintLogger.WriteInfo(
                    "SignatureVerifier: verificación de firma ECDSA exitosa.");
                return true;
            }
            catch (JsonException ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"SignatureVerifier: error parseando JSON envolvente: {ex.Message}", ex,
                    AlwaysPrintLogger.EvtGenericError);
                return false;
            }
            catch (CryptographicException ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"SignatureVerifier: error criptográfico durante verificación: {ex.Message}", ex,
                    AlwaysPrintLogger.EvtGenericError);
                return false;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"SignatureVerifier: error inesperado durante verificación: {ex.Message}", ex,
                    AlwaysPrintLogger.EvtGenericError);
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
        /// <returns>true si la descarga y escritura fueron exitosas, false en caso contrario.</returns>
        public static async Task<bool> DownloadCertAsync(string certUrl, string localPath)
        {
            try
            {
                AlwaysPrintLogger.WriteInfo(
                    $"SignatureVerifier: descargando certificado desde {certUrl}");

                using (var httpClient = new HttpClient())
                {
                    httpClient.Timeout = TimeSpan.FromSeconds(30);

                    byte[] certBytes = await httpClient.GetByteArrayAsync(certUrl);

                    if (certBytes == null || certBytes.Length == 0)
                    {
                        AlwaysPrintLogger.WriteError(
                            "SignatureVerifier: certificado descargado está vacío.",
                            AlwaysPrintLogger.EvtGenericError);
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

                    AlwaysPrintLogger.WriteInfo(
                        $"SignatureVerifier: certificado guardado exitosamente en {localPath} ({certBytes.Length} bytes)");
                    return true;
                }
            }
            catch (HttpRequestException ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"SignatureVerifier: error HTTP descargando certificado: {ex.Message}", ex,
                    AlwaysPrintLogger.EvtGenericError);
                return false;
            }
            catch (IOException ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"SignatureVerifier: error de I/O guardando certificado: {ex.Message}", ex,
                    AlwaysPrintLogger.EvtGenericError);
                return false;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"SignatureVerifier: error inesperado descargando certificado: {ex.Message}", ex,
                    AlwaysPrintLogger.EvtGenericError);
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
        /// <returns>Versión del certificado local (0 si no se encuentra).</returns>
        public static int GetLocalCertVersion()
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
                AlwaysPrintLogger.WriteWarning(
                    $"SignatureVerifier: error leyendo CertVersion del registro, retornando 0. {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
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
    }
}
