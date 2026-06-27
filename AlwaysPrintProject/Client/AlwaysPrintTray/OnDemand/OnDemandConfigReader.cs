using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AlwaysPrintTray.OnDemand
{
    /// <summary>
    /// Lee triggers OnDemand desde el archivo de configuración activa.
    /// Filtra solo triggers con event="OnDemand" y label no vacío.
    /// </summary>
    public static class OnDemandConfigReader
    {
        private static List<OnDemandTriggerInfo> _cachedTriggers = new List<OnDemandTriggerInfo>();

        /// <summary>
        /// Lee y retorna los triggers OnDemand válidos de la configuración activa.
        /// Retorna lista vacía si el archivo no existe o no es parseable.
        /// </summary>
        public static List<OnDemandTriggerInfo> GetOnDemandTriggers()
        {
            if (_cachedTriggers.Count > 0)
                return _cachedTriggers;

            _cachedTriggers = ReadTriggersFromFile(PipeConstants.ActionConfigFilePath);
            return _cachedTriggers;
        }

        /// <summary>
        /// Lee y retorna los triggers OnDemand válidos desde una ruta específica.
        /// Permite testeo con archivos temporales.
        /// </summary>
        public static List<OnDemandTriggerInfo> GetOnDemandTriggers(string filePath)
        {
            return ReadTriggersFromFile(filePath);
        }

        /// <summary>
        /// Recarga la configuración. Llamado al recibir ActionConfigChanged.
        /// </summary>
        public static List<OnDemandTriggerInfo> Reload()
        {
            _cachedTriggers = ReadTriggersFromFile(PipeConstants.ActionConfigFilePath);
            return _cachedTriggers;
        }

        /// <summary>
        /// Lee la lista de servicios monitoreados desde la configuración activa.
        /// Retorna lista vacía si no hay servicios configurados.
        /// </summary>
        public static List<MonitoredServiceConfig> GetMonitoredServices()
        {
            return GetMonitoredServices(PipeConstants.ActionConfigFilePath);
        }

        /// <summary>
        /// Lee la lista de servicios monitoreados desde una ruta específica.
        /// </summary>
        public static List<MonitoredServiceConfig> GetMonitoredServices(string filePath)
        {
            if (!File.Exists(filePath))
                return new List<MonitoredServiceConfig>();

            try
            {
                string json = File.ReadAllText(filePath);
                string configJson = ExtractConfigJson(json);
                var config = JsonConvert.DeserializeObject<ActionConfiguration>(configJson);

                if (config?.MonitoredServices == null)
                    return new List<MonitoredServiceConfig>();

                return config.MonitoredServices
                    .Where(s => !string.IsNullOrWhiteSpace(s.ServiceName))
                    .ToList();
            }
            catch (Exception)
            {
                return new List<MonitoredServiceConfig>();
            }
        }

        /// <summary>
        /// Lee el archivo de configuración y extrae los triggers OnDemand válidos.
        /// </summary>
        private static List<OnDemandTriggerInfo> ReadTriggersFromFile(string filePath)
        {

            if (!File.Exists(filePath))
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"OnDemandConfigReader: archivo de configuración no encontrado en '{filePath}'. " +
                    "No se cargarán triggers OnDemand.");
                return new List<OnDemandTriggerInfo>();
            }

            try
            {
                string json = File.ReadAllText(filePath);
                string configJson = ExtractConfigJson(json);
                var config = JsonConvert.DeserializeObject<ActionConfiguration>(configJson);

                if (config?.Triggers == null)
                    return new List<OnDemandTriggerInfo>();

                // Filtrar triggers OnDemand con label no vacío, preservando orden original
                return config.Triggers
                    .Where(t => t.Event.Equals(TriggerEvents.OnDemand, StringComparison.OrdinalIgnoreCase)
                             && !string.IsNullOrWhiteSpace(t.Label))
                    .Select(t => new OnDemandTriggerInfo
                    {
                        Label = t.Label!,
                        Description = t.Description ?? string.Empty
                    })
                    .ToList();
            }
            catch (JsonException ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"OnDemandConfigReader: error al parsear JSON de configuración en '{filePath}': {ex.Message}");
                return new List<OnDemandTriggerInfo>();
            }
            catch (IOException ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"OnDemandConfigReader: error al leer archivo de configuración en '{filePath}': {ex.Message}");
                return new List<OnDemandTriggerInfo>();
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayWarning(
                    $"OnDemandConfigReader: error inesperado al cargar configuración: {ex.Message}");
                return new List<OnDemandTriggerInfo>();
            }
        }

        /// <summary>
        /// Extrae el JSON del config interno de un archivo.
        /// Si es un envelope firmado (tiene campos config/hash/signature/cert_version),
        /// retorna solo la porción "config" serializada.
        /// Si es formato legacy, retorna el contenido tal cual.
        /// </summary>
        private static string ExtractConfigJson(string fileContent)
        {
            try
            {
                var parsed = JObject.Parse(fileContent);

                // Detectar si es envelope firmado
                if (parsed["config"] != null && parsed["hash"] != null &&
                    parsed["signature"] != null && parsed["cert_version"] != null)
                {
                    // Es envelope — extraer config interno
                    return parsed["config"]!.ToString(Formatting.None);
                }
            }
            catch (JsonException)
            {
                // No es JSON válido — retornar tal cual (fallará en deserialización)
            }

            // No es envelope — retornar contenido original
            return fileContent;
        }
    }
}
