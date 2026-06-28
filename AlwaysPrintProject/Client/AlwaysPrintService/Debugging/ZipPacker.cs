using System;
using System.IO;
using System.IO.Compression;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintService.Debugging
{
    /// <summary>
    /// Comprime la carpeta completa de debugging a un ZIP y elimina los originales.
    /// El ZIP permanece en la misma carpeta para upload posterior.
    /// </summary>
    public class ZipPacker
    {
        /// <summary>
        /// Comprime todos los archivos de la carpeta en un ZIP.
        /// Elimina los archivos originales después de comprimir exitosamente.
        /// </summary>
        /// <param name="folderPath">Ruta de la carpeta de debugging.</param>
        /// <param name="debuggingId">ID para nombrar el ZIP.</param>
        /// <returns>Ruta al ZIP creado, o null si falla.</returns>
        public string? PackFolder(string folderPath, string debuggingId)
        {
            if (!Directory.Exists(folderPath))
            {
                AlwaysPrintLogger.WriteWarning(
                    $"ZipPacker: Carpeta no existe: {folderPath}");
                return null;
            }

            string zipFileName = $"debug_{debuggingId}.zip";
            string zipPath = Path.Combine(folderPath, zipFileName);

            try
            {
                // Si ya existe un ZIP previo, eliminarlo
                if (File.Exists(zipPath))
                {
                    File.Delete(zipPath);
                }

                // Crear ZIP con todos los archivos (excepto el propio ZIP)
                using (var zipStream = new FileStream(zipPath, FileMode.Create))
                using (var archive = new ZipArchive(zipStream, ZipArchiveMode.Create))
                {
                    var files = Directory.GetFiles(folderPath);
                    foreach (var filePath in files)
                    {
                        string fileName = Path.GetFileName(filePath);
                        // No incluir el ZIP a sí mismo
                        if (fileName.Equals(zipFileName, StringComparison.OrdinalIgnoreCase))
                            continue;

                        var entry = archive.CreateEntry(fileName, CompressionLevel.Optimal);
                        using (var entryStream = entry.Open())
                        using (var fileStream = File.OpenRead(filePath))
                        {
                            fileStream.CopyTo(entryStream);
                        }
                    }
                }

                AlwaysPrintLogger.WriteInfo(
                    $"ZipPacker: ZIP creado exitosamente: {zipPath} " +
                    $"({new FileInfo(zipPath).Length} bytes)");

                // Eliminar archivos originales (mantener solo el ZIP)
                DeleteOriginalFiles(folderPath, zipFileName);

                return zipPath;
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"ZipPacker: Error creando ZIP para {debuggingId}: {ex.Message}");

                // Intentar limpiar ZIP parcial
                try { if (File.Exists(zipPath)) File.Delete(zipPath); }
                catch { /* Ignorar */ }

                return null;
            }
        }

        /// <summary>
        /// Elimina todos los archivos originales excepto el ZIP.
        /// </summary>
        private void DeleteOriginalFiles(string folderPath, string zipFileName)
        {
            int deleted = 0;
            int errors = 0;

            foreach (var filePath in Directory.GetFiles(folderPath))
            {
                string fileName = Path.GetFileName(filePath);
                if (fileName.Equals(zipFileName, StringComparison.OrdinalIgnoreCase))
                    continue;

                try
                {
                    File.Delete(filePath);
                    deleted++;
                }
                catch (Exception ex)
                {
                    errors++;
                    AlwaysPrintLogger.WriteWarning(
                        $"ZipPacker: No se pudo eliminar '{fileName}': {ex.Message}");
                }
            }

            AlwaysPrintLogger.WriteInfo(
                $"ZipPacker: Archivos originales eliminados: {deleted}, errores: {errors}");
        }
    }
}
