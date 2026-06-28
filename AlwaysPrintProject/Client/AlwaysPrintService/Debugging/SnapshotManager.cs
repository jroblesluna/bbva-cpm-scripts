using System;
using System.Collections.Generic;
using System.ServiceProcess;
using AlwaysPrint.Shared.Logging;
using Microsoft.Win32;
using Newtonsoft.Json;

namespace AlwaysPrintService.Debugging
{
    /// <summary>
    /// Captura snapshots de servicios Windows y registro.
    /// Genera archivos JSON estructurados para comparación inicial vs final.
    /// </summary>
    public class SnapshotManager
    {
        /// <summary>
        /// Captura el estado de todos los servicios monitoreados.
        /// Retorna JSON con: captured_at, services: [{service_name, display_name, status, start_type}]
        /// </summary>
        public string CaptureServicesSnapshot(string[] serviceNames)
        {
            var result = new ServicesSnapshot
            {
                CapturedAt = DateTime.UtcNow,
                Services = new List<ServiceInfo>()
            };

            foreach (var serviceName in serviceNames)
            {
                try
                {
                    using (var sc = new ServiceController(serviceName))
                    {
                        result.Services.Add(new ServiceInfo
                        {
                            ServiceName = sc.ServiceName,
                            DisplayName = sc.DisplayName,
                            Status = sc.Status.ToString(),
                            StartType = sc.StartType.ToString()
                        });
                    }
                }
                catch (InvalidOperationException)
                {
                    // Servicio no encontrado
                    result.Services.Add(new ServiceInfo
                    {
                        ServiceName = serviceName,
                        DisplayName = "(no encontrado)",
                        Status = "NotFound",
                        StartType = "N/A"
                    });
                    AlwaysPrintLogger.WriteWarning(
                        $"SnapshotManager: Servicio '{serviceName}' no encontrado.");
                }
                catch (Exception ex)
                {
                    result.Services.Add(new ServiceInfo
                    {
                        ServiceName = serviceName,
                        DisplayName = "(error)",
                        Status = $"Error: {ex.Message}",
                        StartType = "N/A"
                    });
                    AlwaysPrintLogger.WriteError(
                        $"SnapshotManager: Error capturando servicio '{serviceName}': {ex.Message}");
                }
            }

            return JsonConvert.SerializeObject(result, Formatting.Indented);
        }

        /// <summary>
        /// Captura los valores (claves) de cada llave de registro (single level, no recursivo).
        /// Retorna JSON con: captured_at, keys: [{key_path, values: [{name, type, data}]}]
        /// </summary>
        public string CaptureRegistrySnapshot(string[] registryKeys)
        {
            var result = new RegistrySnapshot
            {
                CapturedAt = DateTime.UtcNow,
                Keys = new List<RegistryKeyInfo>()
            };

            foreach (var keyPath in registryKeys)
            {
                var keyInfo = new RegistryKeyInfo
                {
                    KeyPath = keyPath,
                    Values = new List<RegistryValueInfo>()
                };

                try
                {
                    using (var regKey = OpenRegistryKey(keyPath))
                    {
                        if (regKey == null)
                        {
                            keyInfo.Values.Add(new RegistryValueInfo
                            {
                                Name = "(error)",
                                Type = "N/A",
                                Data = "Llave no encontrada o sin permisos"
                            });
                            AlwaysPrintLogger.WriteWarning(
                                $"SnapshotManager: Llave de registro no encontrada: {keyPath}");
                        }
                        else
                        {
                            foreach (var valueName in regKey.GetValueNames())
                            {
                                try
                                {
                                    var valueKind = regKey.GetValueKind(valueName);
                                    var data = regKey.GetValue(valueName);

                                    keyInfo.Values.Add(new RegistryValueInfo
                                    {
                                        Name = string.IsNullOrEmpty(valueName) ? "(Default)" : valueName,
                                        Type = valueKind.ToString(),
                                        Data = data?.ToString() ?? "(null)"
                                    });
                                }
                                catch (Exception ex)
                                {
                                    keyInfo.Values.Add(new RegistryValueInfo
                                    {
                                        Name = valueName,
                                        Type = "Error",
                                        Data = ex.Message
                                    });
                                }
                            }
                        }
                    }
                }
                catch (Exception ex)
                {
                    keyInfo.Values.Add(new RegistryValueInfo
                    {
                        Name = "(error)",
                        Type = "N/A",
                        Data = $"Error accediendo llave: {ex.Message}"
                    });
                    AlwaysPrintLogger.WriteError(
                        $"SnapshotManager: Error accediendo registro '{keyPath}': {ex.Message}");
                }

                result.Keys.Add(keyInfo);
            }

            return JsonConvert.SerializeObject(result, Formatting.Indented);
        }

        /// <summary>
        /// Abre una llave de registro a partir del path completo (ej: HKLM\SOFTWARE\Lexmark).
        /// </summary>
        private RegistryKey? OpenRegistryKey(string fullPath)
        {
            // Parsear root key y subpath
            string[] parts = fullPath.Split(new[] { '\\' }, 2);
            if (parts.Length < 2) return null;

            string rootName = parts[0].ToUpper();
            string subPath = parts[1];

            RegistryKey? root = rootName switch
            {
                "HKLM" => Registry.LocalMachine,
                "HKEY_LOCAL_MACHINE" => Registry.LocalMachine,
                "HKCU" => Registry.CurrentUser,
                "HKEY_CURRENT_USER" => Registry.CurrentUser,
                "HKCR" => Registry.ClassesRoot,
                "HKEY_CLASSES_ROOT" => Registry.ClassesRoot,
                "HKU" => Registry.Users,
                "HKEY_USERS" => Registry.Users,
                "HKCC" => Registry.CurrentConfig,
                "HKEY_CURRENT_CONFIG" => Registry.CurrentConfig,
                _ => null
            };

            return root?.OpenSubKey(subPath, writable: false);
        }

        // ═══════════════════════════════════════════════════════════════════════
        // CLASES DE DATOS PARA SERIALIZACIÓN JSON
        // ═══════════════════════════════════════════════════════════════════════

        private class ServicesSnapshot
        {
            [JsonProperty("captured_at")]
            public DateTime CapturedAt { get; set; }

            [JsonProperty("services")]
            public List<ServiceInfo> Services { get; set; } = new List<ServiceInfo>();
        }

        private class ServiceInfo
        {
            [JsonProperty("service_name")]
            public string ServiceName { get; set; } = "";

            [JsonProperty("display_name")]
            public string DisplayName { get; set; } = "";

            [JsonProperty("status")]
            public string Status { get; set; } = "";

            [JsonProperty("start_type")]
            public string StartType { get; set; } = "";
        }

        private class RegistrySnapshot
        {
            [JsonProperty("captured_at")]
            public DateTime CapturedAt { get; set; }

            [JsonProperty("keys")]
            public List<RegistryKeyInfo> Keys { get; set; } = new List<RegistryKeyInfo>();
        }

        private class RegistryKeyInfo
        {
            [JsonProperty("key_path")]
            public string KeyPath { get; set; } = "";

            [JsonProperty("values")]
            public List<RegistryValueInfo> Values { get; set; } = new List<RegistryValueInfo>();
        }

        private class RegistryValueInfo
        {
            [JsonProperty("name")]
            public string Name { get; set; } = "";

            [JsonProperty("type")]
            public string Type { get; set; } = "";

            [JsonProperty("data")]
            public object? Data { get; set; }
        }
    }
}
