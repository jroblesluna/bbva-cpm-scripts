using System;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Threading.Tasks;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Network;

namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Descarga el MSI de actualización de forma asíncrona y no bloqueante.
    /// Guarda el archivo en %TEMP%\AlwaysPrint\Updates\ y verifica su integridad por tamaño.
    /// </summary>
    public class UpdateDownloader
    {
        private readonly string _cloudApiUrl;
        private readonly HttpClient _httpClient;

        /// <summary>Directorio temporal donde se guardan las actualizaciones descargadas.</summary>
        private static readonly string UpdatesDir =
            Path.Combine(Path.GetTempPath(), "AlwaysPrint", "Updates");

        /// <summary>Nombre del archivo MSI descargado.</summary>
        private const string MsiFileName = "AlwaysPrint_update.msi";

        /// <summary>
        /// Crea una nueva instancia de UpdateDownloader.
        /// </summary>
        /// <param name="cloudApiUrl">URL base de la API Cloud (ej: https://alwaysprint.apps.iol.pe).</param>
        public UpdateDownloader(string cloudApiUrl)
        {
            _cloudApiUrl = cloudApiUrl ?? throw new ArgumentNullException(nameof(cloudApiUrl));

            // Crear HttpClient que sigue redirects automáticamente (comportamiento por defecto)
            // Timeout generoso para descargas de archivos grandes
            _httpClient = new HttpClient
            {
                Timeout = TimeSpan.FromMinutes(10)
            };
        }

        /// <summary>
        /// [DEPRECADO] Descarga el MSI desde el endpoint HTTP /api/v1/updates/download.
        /// 
        /// Con push-based distribution, la descarga de MSI se realiza directamente desde
        /// presigned URLs de S3 provistas por MSI_Push_Message o Registration_Enrichment,
        /// usando DownloadFromUrlAsync(). El endpoint HTTP solo se usa como fallback
        /// cuando la presigned URL ha expirado (HTTP 403).
        /// 
        /// Este método será eliminado cuando se complete la migración a push-based distribution.
        /// </summary>
        /// <param name="expectedSize">Tamaño esperado del archivo en bytes (reportado por el backend).</param>
        /// <returns>Ruta completa del MSI descargado si la verificación es exitosa; null si falla.</returns>
        [Obsolete("Usar DownloadFromUrlAsync con presigned URL de S3 (push-based). " +
                   "Este método se mantiene como fallback cuando la presigned URL expira.")]
        public async Task<string?> DownloadAsync(long expectedSize)
        {
            var stopwatch = Stopwatch.StartNew();
            string filePath = Path.Combine(UpdatesDir, MsiFileName);

            try
            {
                // 1. Crear directorio de descargas si no existe
                if (!Directory.Exists(UpdatesDir))
                {
                    Directory.CreateDirectory(UpdatesDir);
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"UpdateDownloader: directorio de actualizaciones creado en '{UpdatesDir}'.");
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"UpdateDownloader: iniciando descarga del MSI. Tamaño esperado: {(expectedSize > 0 ? $"{expectedSize} bytes" : "desconocido")}.");

                // 2. Llamar al endpoint de descarga (sigue redirect a presigned URL automáticamente)
                string downloadUrl = $"{_cloudApiUrl.TrimEnd('/')}/api/v1/updates/download";

                var request = new HttpRequestMessage(HttpMethod.Get, downloadUrl);
                // Headers de identificación para diagnóstico de IPs pendientes
                request.Headers.Add("X-Workstation-Hostname", Environment.MachineName);
                request.Headers.Add("X-Workstation-User", Environment.UserName);
                request.Headers.Add("X-Workstation-IP-Private", NetworkHelper.GetOutboundLocalIP());

                using (var response = await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead))
                {
                    response.EnsureSuccessStatusCode();

                    // 3. Guardar el contenido como archivo MSI
                    using (var contentStream = await response.Content.ReadAsStreamAsync())
                    using (var fileStream = new FileStream(filePath, FileMode.Create, FileAccess.Write, FileShare.None, 81920, useAsync: true))
                    {
                        await contentStream.CopyToAsync(fileStream);
                    }
                }

                stopwatch.Stop();

                // 4. Verificar integridad: comparar tamaño real vs esperado
                var fileInfo = new FileInfo(filePath);
                long actualSize = fileInfo.Length;

                if (actualSize != expectedSize)
                {
                    // Diagnóstico: leer primeros bytes del archivo para identificar respuesta de proxy/error
                    string snippet = "";
                    try
                    {
                        byte[] head = new byte[Math.Min(1024, (int)actualSize)];
                        using (var fs = System.IO.File.OpenRead(filePath))
                            fs.Read(head, 0, head.Length);
                        snippet = System.Text.Encoding.UTF8.GetString(head).Replace("\r", "").Replace("\n", " ");
                    }
                    catch { snippet = "(no se pudo leer)"; }

                    // Verificación de integridad fallida: eliminar archivo parcial
                    AlwaysPrintLogger.WriteTrayError(
                        $"UpdateDownloader: integridad de MSI fallida. " +
                        $"Esperado: {expectedSize} bytes, actual: {actualSize} bytes. " +
                        $"Primeros bytes: [{snippet}]. Archivo parcial eliminado.");

                    DeleteFileSafe(filePath);
                    return null;
                }

                // 5. Descarga exitosa: loggear con tamaño y duración
                AlwaysPrintLogger.WriteTrayInfo(
                    $"UpdateDownloader: descarga completada exitosamente. " +
                    $"Archivo: '{filePath}', tamaño: {actualSize} bytes, " +
                    $"duración: {stopwatch.Elapsed.TotalSeconds:F1} segundos.");

                return filePath;
            }
            catch (HttpRequestException ex)
            {
                // Error de red (DNS, conexión rechazada, timeout de conexión, etc.)
                stopwatch.Stop();
                AlwaysPrintLogger.WriteTrayError(
                    $"UpdateDownloader: descarga de actualización interrumpida por error de red: {ex.Message}. " +
                    $"Archivo parcial eliminado.");

                DeleteFileSafe(filePath);
                return null;
            }
            catch (TaskCanceledException ex)
            {
                // Timeout del HttpClient
                stopwatch.Stop();
                AlwaysPrintLogger.WriteTrayError(
                    $"UpdateDownloader: descarga de actualización excedió el timeout: {ex.Message}. " +
                    $"Archivo parcial eliminado.");

                DeleteFileSafe(filePath);
                return null;
            }
            catch (IOException ex)
            {
                // Error de I/O (disco lleno, permisos, etc.)
                stopwatch.Stop();
                AlwaysPrintLogger.WriteTrayError(
                    $"UpdateDownloader: error de I/O al guardar MSI: {ex.Message}. " +
                    $"Archivo parcial eliminado.");

                DeleteFileSafe(filePath);
                return null;
            }
            catch (Exception ex)
            {
                // Error inesperado
                stopwatch.Stop();
                AlwaysPrintLogger.WriteTrayError(
                    $"UpdateDownloader: error inesperado durante la descarga: {ex.Message}. " +
                    $"Archivo parcial eliminado.");

                DeleteFileSafe(filePath);
                return null;
            }
        }

        /// <summary>
        /// Descarga el MSI directamente desde una presigned URL de S3 (flujo zero-query).
        /// Verifica la integridad del archivo comparando el tamaño descargado vs esperado.
        /// Si la presigned URL ha expirado (HTTP 403), retorna null para activar fallback al flujo legacy.
        /// </summary>
        /// <param name="downloadUrl">Presigned URL de S3 para descarga directa.</param>
        /// <param name="expectedSize">Tamaño esperado del archivo en bytes.</param>
        /// <param name="version">Versión del MSI a descargar.</param>
        /// <returns>Ruta completa del MSI descargado si la verificación es exitosa; null si falla.</returns>
        public async Task<string?> DownloadFromUrlAsync(string downloadUrl, long expectedSize, string version)
        {
            var stopwatch = Stopwatch.StartNew();
            string filePath = Path.Combine(UpdatesDir, MsiFileName);

            try
            {
                // Crear directorio si no existe
                if (!Directory.Exists(UpdatesDir))
                {
                    Directory.CreateDirectory(UpdatesDir);
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"UpdateDownloader: directorio de actualizaciones creado en '{UpdatesDir}'.");
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"UpdateDownloader: iniciando descarga directa zero-query. " +
                    $"Versión: {version}, tamaño esperado: {(expectedSize > 0 ? $"{expectedSize} bytes" : "desconocido")}, URL: [presigned]");

                using (var response = await _httpClient.GetAsync(downloadUrl, HttpCompletionOption.ResponseHeadersRead))
                {
                    // Verificar si la URL presigned ha expirado (S3 retorna 403)
                    if (response.StatusCode == System.Net.HttpStatusCode.Forbidden)
                    {
                        stopwatch.Stop();
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"UpdateDownloader: presigned URL expirada (HTTP 403). " +
                            $"Versión: {version}. Se activará fallback al flujo legacy.");
                        return null;
                    }

                    response.EnsureSuccessStatusCode();

                    // Guardar contenido como archivo MSI
                    using (var contentStream = await response.Content.ReadAsStreamAsync())
                    using (var fileStream = new FileStream(filePath, FileMode.Create, FileAccess.Write, FileShare.None, 81920, useAsync: true))
                    {
                        await contentStream.CopyToAsync(fileStream);
                    }
                }

                stopwatch.Stop();

                // Verificar integridad por tamaño
                var fileInfo = new FileInfo(filePath);
                long actualSize = fileInfo.Length;

                if (expectedSize > 0 && actualSize != expectedSize)
                {
                    // Diagnóstico: leer primeros bytes para identificar respuesta de proxy/error
                    string snippet = "";
                    try
                    {
                        byte[] head = new byte[Math.Min(1024, (int)actualSize)];
                        using (var fs = System.IO.File.OpenRead(filePath))
                            fs.Read(head, 0, head.Length);
                        snippet = System.Text.Encoding.UTF8.GetString(head).Replace("\r", "").Replace("\n", " ");
                    }
                    catch { snippet = "(no se pudo leer)"; }

                    AlwaysPrintLogger.WriteTrayError(
                        $"UpdateDownloader: integridad de MSI fallida (zero-query). " +
                        $"Esperado: {expectedSize} bytes, actual: {actualSize} bytes. " +
                        $"Versión: {version}. Primeros bytes: [{snippet}]. Archivo parcial eliminado.");
                    DeleteFileSafe(filePath);
                    return null;
                }

                AlwaysPrintLogger.WriteTrayInfo(
                    $"UpdateDownloader: descarga directa zero-query completada. " +
                    $"Versión: {version}, tamaño: {actualSize} bytes, " +
                    $"duración: {stopwatch.Elapsed.TotalSeconds:F1} segundos.");

                return filePath;
            }
            catch (HttpRequestException ex)
            {
                stopwatch.Stop();
                AlwaysPrintLogger.WriteTrayError(
                    $"UpdateDownloader: error de red en descarga zero-query: {ex.Message}. " +
                    $"Versión: {version}. Archivo parcial eliminado.");
                DeleteFileSafe(filePath);
                return null;
            }
            catch (TaskCanceledException ex)
            {
                stopwatch.Stop();
                AlwaysPrintLogger.WriteTrayError(
                    $"UpdateDownloader: timeout en descarga zero-query: {ex.Message}. " +
                    $"Versión: {version}. Archivo parcial eliminado.");
                DeleteFileSafe(filePath);
                return null;
            }
            catch (IOException ex)
            {
                stopwatch.Stop();
                AlwaysPrintLogger.WriteTrayError(
                    $"UpdateDownloader: error de I/O en descarga zero-query: {ex.Message}. " +
                    $"Versión: {version}. Archivo parcial eliminado.");
                DeleteFileSafe(filePath);
                return null;
            }
            catch (Exception ex)
            {
                stopwatch.Stop();
                AlwaysPrintLogger.WriteTrayError(
                    $"UpdateDownloader: error inesperado en descarga zero-query: {ex.Message}. " +
                    $"Versión: {version}. Archivo parcial eliminado.");
                DeleteFileSafe(filePath);
                return null;
            }
        }

        /// <summary>
        /// Elimina archivos antiguos o parciales del directorio de actualizaciones.
        /// Útil para limpiar descargas previas que ya no son necesarias.
        /// </summary>
        public void Cleanup()
        {
            try
            {
                if (!Directory.Exists(UpdatesDir))
                {
                    return;
                }

                var files = Directory.GetFiles(UpdatesDir);
                int deletedCount = 0;

                foreach (var file in files)
                {
                    try
                    {
                        File.Delete(file);
                        deletedCount++;
                    }
                    catch (Exception ex)
                    {
                        AlwaysPrintLogger.WriteTrayWarning(
                            $"UpdateDownloader: no se pudo eliminar archivo antiguo '{Path.GetFileName(file)}': {ex.Message}");
                    }
                }

                if (deletedCount > 0)
                {
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"UpdateDownloader: limpieza completada. {deletedCount} archivo(s) eliminado(s) de '{UpdatesDir}'.");
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"UpdateDownloader: error durante limpieza del directorio de actualizaciones: {ex.Message}");
            }
        }

        /// <summary>
        /// Elimina un archivo de forma segura, sin lanzar excepciones si falla.
        /// </summary>
        /// <param name="filePath">Ruta del archivo a eliminar.</param>
        private static void DeleteFileSafe(string filePath)
        {
            try
            {
                if (File.Exists(filePath))
                {
                    File.Delete(filePath);
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"UpdateDownloader: no se pudo eliminar archivo parcial '{filePath}': {ex.Message}");
            }
        }
    }
}
