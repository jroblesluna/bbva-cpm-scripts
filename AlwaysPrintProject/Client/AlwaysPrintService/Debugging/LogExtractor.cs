using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintService.Debugging
{
    /// <summary>
    /// Extrae líneas de log desde una posición conocida hasta el final del archivo.
    /// Maneja tanto archivos individuales como patrones glob.
    /// </summary>
    public class LogExtractor
    {
        /// <summary>
        /// Cuenta las líneas totales de cada archivo de log en el momento de inicio.
        /// Si es un patrón glob, resuelve y retorna conteos por archivo.
        /// </summary>
        /// <param name="logPaths">Rutas absolutas o patrones glob.</param>
        /// <returns>Diccionario de ruta_archivo → total_líneas.</returns>
        public Dictionary<string, long> GetInitialLineCounts(string[] logPaths)
        {
            var counts = new Dictionary<string, long>();

            foreach (var pathOrPattern in logPaths)
            {
                try
                {
                    var resolvedPaths = ResolveGlob(pathOrPattern);
                    foreach (var filePath in resolvedPaths)
                    {
                        if (File.Exists(filePath))
                        {
                            long lineCount = CountLines(filePath);
                            counts[filePath] = lineCount;
                        }
                        else
                        {
                            AlwaysPrintLogger.WriteWarning(
                                $"LogExtractor: Archivo no encontrado: {filePath}");
                        }
                    }

                    if (resolvedPaths.Count == 0)
                    {
                        AlwaysPrintLogger.WriteWarning(
                            $"LogExtractor: Patrón no resolvió a ningún archivo: {pathOrPattern}");
                    }
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteError(
                        $"LogExtractor: Error contando líneas de '{pathOrPattern}': {ex.Message}");
                }
            }

            return counts;
        }

        /// <summary>
        /// Extrae líneas nuevas (desde initialLineCount hasta EOF) de cada log.
        /// Retorna diccionario de nombre_sanitizado → contenido extraído.
        /// </summary>
        public Dictionary<string, string> ExtractNewLines(Dictionary<string, long> initialCounts)
        {
            var result = new Dictionary<string, string>();

            foreach (var kvp in initialCounts)
            {
                string filePath = kvp.Key;
                long startLine = kvp.Value;

                try
                {
                    if (!File.Exists(filePath))
                    {
                        result[SanitizeFilename(filePath)] = "[Archivo no encontrado al finalizar]";
                        continue;
                    }

                    // Leer con FileShare.ReadWrite para acceder aunque otro proceso escriba
                    string[] lines;
                    using (var fs = new FileStream(filePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                    using (var reader = new StreamReader(fs))
                    {
                        lines = reader.ReadToEnd().Split(new[] { "\r\n", "\n" }, StringSplitOptions.None);
                    }

                    if (lines.Length > startLine)
                    {
                        var newLines = lines.Skip((int)startLine).ToArray();
                        result[SanitizeFilename(filePath)] = string.Join(Environment.NewLine, newLines);
                    }
                    else
                    {
                        result[SanitizeFilename(filePath)] = "[Sin líneas nuevas durante el debugging]";
                    }
                }
                catch (Exception ex)
                {
                    result[SanitizeFilename(filePath)] = $"[Error extrayendo: {ex.Message}]";
                    AlwaysPrintLogger.WriteError(
                        $"LogExtractor: Error extrayendo de '{filePath}': {ex.Message}");
                }
            }

            return result;
        }

        /// <summary>
        /// Obtiene la cantidad de líneas actual del log de AlwaysPrint del día.
        /// </summary>
        public long GetAlwaysPrintCurrentLineCount()
        {
            try
            {
                string logPath = GetAlwaysPrintLogPath();
                if (string.IsNullOrEmpty(logPath) || !File.Exists(logPath))
                    return 0;

                return CountLines(logPath);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"LogExtractor: Error contando líneas del log AlwaysPrint: {ex.Message}");
                return 0;
            }
        }

        /// <summary>
        /// Extrae el log de AlwaysPrint del día actual desde la línea indicada.
        /// </summary>
        public string ExtractAlwaysPrintLog(long fromLine)
        {
            try
            {
                string logPath = GetAlwaysPrintLogPath();
                if (string.IsNullOrEmpty(logPath) || !File.Exists(logPath))
                    return "[Log de AlwaysPrint no encontrado]";

                string[] lines;
                using (var fs = new FileStream(logPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                using (var reader = new StreamReader(fs))
                {
                    lines = reader.ReadToEnd().Split(new[] { "\r\n", "\n" }, StringSplitOptions.None);
                }

                if (lines.Length > fromLine)
                {
                    var newLines = lines.Skip((int)fromLine).ToArray();
                    return string.Join(Environment.NewLine, newLines);
                }

                return "[Sin líneas nuevas en el log de AlwaysPrint]";
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"LogExtractor: Error extrayendo log AlwaysPrint: {ex.Message}");
                return $"[Error extrayendo log: {ex.Message}]";
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // MÉTODOS PRIVADOS
        // ═══════════════════════════════════════════════════════════════════════

        private string GetAlwaysPrintLogPath()
        {
            // El log de AlwaysPrint se guarda en ProgramData\AlwaysPrint\logs
            // con formato: AlwaysPrint_YYYYMMDD.log (mismo path que AlwaysPrintLogger)
            string logDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                "AlwaysPrint", "logs");
            string today = DateTime.Now.ToString("yyyyMMdd");
            return Path.Combine(logDir, $"AlwaysPrint_{today}.log");
        }

        private long CountLines(string filePath)
        {
            long count = 0;
            // Abrir con FileShare.ReadWrite para leer aunque otro proceso escriba
            using (var fs = new FileStream(filePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            using (var reader = new StreamReader(fs))
            {
                while (reader.ReadLine() != null)
                    count++;
            }
            return count;
        }

        /// <summary>
        /// Resuelve un patrón glob a la lista de archivos que coinciden.
        /// Soporta: * (cualquier caracter excepto separador), ? (un caracter).
        /// </summary>
        private List<string> ResolveGlob(string pathOrPattern)
        {
            var result = new List<string>();

            // Si no contiene wildcards, es una ruta directa
            if (!pathOrPattern.Contains("*") && !pathOrPattern.Contains("?"))
            {
                result.Add(pathOrPattern);
                return result;
            }

            // Separar directorio base y patrón de archivo
            string? directory = Path.GetDirectoryName(pathOrPattern);
            string pattern = Path.GetFileName(pathOrPattern);

            if (string.IsNullOrEmpty(directory) || !Directory.Exists(directory))
                return result;

            try
            {
                var files = Directory.GetFiles(directory, pattern, SearchOption.TopDirectoryOnly);
                result.AddRange(files);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"LogExtractor: Error resolviendo glob '{pathOrPattern}': {ex.Message}");
            }

            return result;
        }

        /// <summary>
        /// Sanitiza un path de archivo para usarlo como nombre de archivo.
        /// Reemplaza caracteres no válidos por underscore.
        /// </summary>
        private string SanitizeFilename(string filePath)
        {
            string name = Path.GetFileNameWithoutExtension(filePath);
            // Reemplazar caracteres no válidos
            foreach (char c in Path.GetInvalidFileNameChars())
            {
                name = name.Replace(c, '_');
            }
            // Limitar longitud
            if (name.Length > 50) name = name.Substring(0, 50);
            return name;
        }
    }
}
