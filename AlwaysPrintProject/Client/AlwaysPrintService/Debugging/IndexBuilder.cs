using System;
using System.Collections.Generic;
using System.IO;
using AlwaysPrint.Shared.Logging;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintService.Debugging
{
    /// <summary>
    /// Construye y actualiza el archivo index.json que describe
    /// el contenido completo de la carpeta de debugging.
    /// </summary>
    public class IndexBuilder
    {
        private IndexData _index = new IndexData();

        /// <summary>Crea el index inicial con metadata de la sesión.</summary>
        public void CreateIndex(
            string debuggingId,
            string profileName,
            DateTime startTime,
            int durationSeconds,
            JObject profile)
        {
            _index = new IndexData
            {
                DebuggingId = debuggingId,
                ProfileName = profileName,
                StartTime = startTime.ToString("yyyy-MM-ddTHH:mm:ss.fffZ"),
                DurationSeconds = durationSeconds,
                Targets = new IndexTargets
                {
                    ExternalLogs = profile["external_logs"]?.ToObject<List<string>>() ?? new List<string>(),
                    EventlogGroups = profile["eventlog_groups"]?.ToObject<List<string>>() ?? new List<string>(),
                    RegistryKeys = profile["registry_keys"]?.ToObject<List<string>>() ?? new List<string>(),
                    MonitoredServices = profile["monitored_services"]?.ToObject<List<string>>() ?? new List<string>()
                },
                Files = new List<IndexFileRef>(),
                Errors = new List<IndexError>()
            };
        }

        /// <summary>Agrega una referencia de archivo al índice.</summary>
        public void AddFileReference(string filename, string description, long sizeBytes)
        {
            _index.Files.Add(new IndexFileRef
            {
                Filename = filename,
                Description = description,
                SizeBytes = sizeBytes
            });
        }

        /// <summary>Agrega un error al array de errores.</summary>
        public void AddError(string target, string errorMessage)
        {
            _index.Errors.Add(new IndexError
            {
                Target = target,
                Error = errorMessage
            });
            AlwaysPrintLogger.WriteWarning(
                $"IndexBuilder: Error registrado para '{target}': {errorMessage}");
        }

        /// <summary>Finaliza el índice con end_time y conteos totales.</summary>
        public void Finalize(DateTime endTime)
        {
            _index.EndTime = endTime.ToString("yyyy-MM-ddTHH:mm:ss.fffZ");
            _index.TotalFiles = _index.Files.Count;

            long totalSize = 0;
            foreach (var file in _index.Files)
            {
                totalSize += file.SizeBytes;
            }
            _index.TotalSizeBytes = totalSize;
        }

        /// <summary>Serializa y guarda el index.json en la carpeta.</summary>
        public void Save(string folderPath)
        {
            try
            {
                string json = JsonConvert.SerializeObject(_index, Formatting.Indented);
                string indexPath = Path.Combine(folderPath, "index.json");
                File.WriteAllText(indexPath, json);
                AlwaysPrintLogger.WriteInfo(
                    $"IndexBuilder: index.json guardado ({_index.TotalFiles} archivos, " +
                    $"{_index.TotalSizeBytes} bytes total)");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"IndexBuilder: Error guardando index.json: {ex.Message}");
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // CLASES DE DATOS PARA SERIALIZACIÓN JSON
        // ═══════════════════════════════════════════════════════════════════════

        private class IndexData
        {
            [JsonProperty("debugging_id")]
            public string DebuggingId { get; set; } = "";

            [JsonProperty("profile_name")]
            public string ProfileName { get; set; } = "";

            [JsonProperty("start_time")]
            public string StartTime { get; set; } = "";

            [JsonProperty("end_time")]
            public string? EndTime { get; set; }

            [JsonProperty("duration_seconds")]
            public int DurationSeconds { get; set; }

            [JsonProperty("targets")]
            public IndexTargets Targets { get; set; } = new IndexTargets();

            [JsonProperty("files")]
            public List<IndexFileRef> Files { get; set; } = new List<IndexFileRef>();

            [JsonProperty("total_files")]
            public int TotalFiles { get; set; }

            [JsonProperty("total_size_bytes")]
            public long TotalSizeBytes { get; set; }

            [JsonProperty("errors")]
            public List<IndexError> Errors { get; set; } = new List<IndexError>();
        }

        private class IndexTargets
        {
            [JsonProperty("external_logs")]
            public List<string> ExternalLogs { get; set; } = new List<string>();

            [JsonProperty("eventlog_groups")]
            public List<string> EventlogGroups { get; set; } = new List<string>();

            [JsonProperty("registry_keys")]
            public List<string> RegistryKeys { get; set; } = new List<string>();

            [JsonProperty("monitored_services")]
            public List<string> MonitoredServices { get; set; } = new List<string>();
        }

        private class IndexFileRef
        {
            [JsonProperty("filename")]
            public string Filename { get; set; } = "";

            [JsonProperty("description")]
            public string Description { get; set; } = "";

            [JsonProperty("size_bytes")]
            public long SizeBytes { get; set; }
        }

        private class IndexError
        {
            [JsonProperty("target")]
            public string Target { get; set; } = "";

            [JsonProperty("error")]
            public string Error { get; set; } = "";
        }
    }
}
