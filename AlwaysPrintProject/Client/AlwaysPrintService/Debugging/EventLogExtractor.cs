using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintService.Debugging
{
    /// <summary>
    /// Extrae entradas del Event Log de Windows entre dos timestamps.
    /// Genera texto formateado por cada grupo de eventos.
    /// Formato por entrada: [Timestamp] [Level] [Source] Message
    /// </summary>
    public class EventLogExtractor
    {
        /// <summary>
        /// Extrae eventos de los grupos especificados entre startTime y endTime.
        /// Cada grupo se retorna como texto separado.
        /// </summary>
        /// <param name="eventLogGroups">Nombres de los logs: "System", "Application", "Security"</param>
        /// <param name="startTime">Inicio del período (UTC).</param>
        /// <param name="endTime">Fin del período (UTC).</param>
        /// <returns>Diccionario de nombre_grupo → texto formateado de eventos.</returns>
        public Dictionary<string, string> ExtractEvents(
            string[] eventLogGroups,
            DateTime startTime,
            DateTime endTime)
        {
            var result = new Dictionary<string, string>();

            foreach (var group in eventLogGroups)
            {
                try
                {
                    string content = ExtractFromLog(group, startTime, endTime);
                    result[group] = content;
                }
                catch (System.Security.SecurityException)
                {
                    result[group] = $"[Error: Sin permisos para leer el log '{group}'. " +
                                    $"Se requiere ejecutar como LocalSystem o administrador.]";
                    AlwaysPrintLogger.WriteWarning(
                        $"EventLogExtractor: Sin permisos para leer '{group}'.");
                }
                catch (Exception ex)
                {
                    result[group] = $"[Error leyendo log '{group}': {ex.Message}]";
                    AlwaysPrintLogger.WriteError(
                        $"EventLogExtractor: Error en '{group}': {ex.Message}");
                }
            }

            return result;
        }

        private string ExtractFromLog(string logName, DateTime startTime, DateTime endTime)
        {
            var sb = new StringBuilder();
            int entryCount = 0;

            // Convertir a hora local (EventLog usa hora local internamente)
            DateTime localStart = startTime.ToLocalTime();
            DateTime localEnd = endTime.ToLocalTime();

            sb.AppendLine($"=== Windows Event Log: {logName} ===");
            sb.AppendLine($"=== Período: {startTime:yyyy-MM-dd HH:mm:ss} - {endTime:yyyy-MM-dd HH:mm:ss} UTC ===");

            using (var eventLog = new EventLog(logName))
            {
                // EventLog.Entries puede ser grande, iterar desde el final para eficiencia
                var entries = eventLog.Entries;
                for (int i = entries.Count - 1; i >= 0; i--)
                {
                    try
                    {
                        var entry = entries[i];

                        // Si la entrada es anterior al inicio, dejar de buscar
                        // (las entradas están ordenadas cronológicamente)
                        if (entry.TimeGenerated < localStart)
                            break;

                        // Solo incluir entradas dentro del rango
                        if (entry.TimeGenerated >= localStart && entry.TimeGenerated <= localEnd)
                        {
                            entryCount++;
                            string level = GetLevelString(entry.EntryType);
                            string message = TruncateMessage(entry.Message, 500);

                            sb.AppendLine();
                            sb.AppendLine($"[{entry.TimeGenerated:yyyy-MM-dd HH:mm:ss}] [{level}] [{entry.Source}]");
                            sb.AppendLine(message);
                        }
                    }
                    catch
                    {
                        // Ignorar entradas individuales con errores de lectura
                        continue;
                    }
                }
            }

            // Insertar total de entradas después del header
            sb.Insert(
                sb.ToString().IndexOf("===", sb.ToString().IndexOf("===") + 1) + 3 +
                    Environment.NewLine.Length,
                $"=== Total entradas: {entryCount} ===" + Environment.NewLine);

            if (entryCount == 0)
            {
                sb.AppendLine();
                sb.AppendLine("[Sin eventos en el período especificado]");
            }

            return sb.ToString();
        }

        private string GetLevelString(EventLogEntryType entryType)
        {
            return entryType switch
            {
                EventLogEntryType.Error => "Error",
                EventLogEntryType.Warning => "Warning",
                EventLogEntryType.Information => "Information",
                EventLogEntryType.SuccessAudit => "Audit Success",
                EventLogEntryType.FailureAudit => "Audit Failure",
                _ => "Unknown"
            };
        }

        private string TruncateMessage(string? message, int maxLength)
        {
            if (string.IsNullOrEmpty(message)) return "(sin mensaje)";
            if (message.Length <= maxLength) return message;
            return message.Substring(0, maxLength) + "... [truncado]";
        }
    }
}
