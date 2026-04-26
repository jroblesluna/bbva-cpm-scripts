using System;
using System.Diagnostics;
using System.Linq;
using Microsoft.Deployment.WindowsInstaller;
using Microsoft.Win32;

namespace AlwaysPrint.CustomActions
{
    public class CustomActions
    {
        [CustomAction]
        public static ActionResult UninstallPreviousVersion(Session session)
        {
            session.Log("Begin UninstallPreviousVersion");

            try
            {
                // Solo ejecutar si estamos en modo desinstalación (REMOVE=ALL)
                string remove = session["REMOVE"];
                if (string.IsNullOrEmpty(remove) || !remove.Equals("ALL", StringComparison.OrdinalIgnoreCase))
                {
                    session.Log("Not in uninstall mode, skipping");
                    return ActionResult.Success;
                }

                // Buscar AlwaysPrint instalado en el registro
                string productCode = FindInstalledProductCode(session);
                
                if (string.IsNullOrEmpty(productCode))
                {
                    session.Log("No previous version found");
                    return ActionResult.Success;
                }

                session.Log($"Found installed product: {productCode}");

                // Desinstalar usando msiexec
                var startInfo = new ProcessStartInfo
                {
                    FileName = "msiexec.exe",
                    Arguments = $"/x {productCode} /qn",
                    UseShellExecute = false,
                    CreateNoWindow = true
                };

                session.Log($"Executing: msiexec.exe {startInfo.Arguments}");

                using (var process = Process.Start(startInfo))
                {
                    process?.WaitForExit();
                    int exitCode = process?.ExitCode ?? -1;
                    session.Log($"Uninstall exit code: {exitCode}");

                    if (exitCode == 0 || exitCode == 1605) // 1605 = product not found (OK)
                    {
                        return ActionResult.Success;
                    }
                }

                return ActionResult.Success; // No fallar la instalación si la desinstalación falla
            }
            catch (Exception ex)
            {
                session.Log($"Error in UninstallPreviousVersion: {ex.Message}");
                return ActionResult.Success; // No fallar la instalación
            }
        }

        private static string FindInstalledProductCode(Session session)
        {
            try
            {
                // Buscar en HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall
                using (var uninstallKey = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"))
                {
                    if (uninstallKey != null)
                    {
                        foreach (var subKeyName in uninstallKey.GetSubKeyNames())
                        {
                            using (var subKey = uninstallKey.OpenSubKey(subKeyName))
                            {
                                var displayName = subKey?.GetValue("DisplayName") as string;
                                if (displayName != null && displayName.Equals("AlwaysPrint", StringComparison.OrdinalIgnoreCase))
                                {
                                    session.Log($"Found in Uninstall: {subKeyName}");
                                    return subKeyName;
                                }
                            }
                        }
                    }
                }

                // Buscar en WOW6432Node (32-bit en 64-bit)
                using (var uninstallKey = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"))
                {
                    if (uninstallKey != null)
                    {
                        foreach (var subKeyName in uninstallKey.GetSubKeyNames())
                        {
                            using (var subKey = uninstallKey.OpenSubKey(subKeyName))
                            {
                                var displayName = subKey?.GetValue("DisplayName") as string;
                                if (displayName != null && displayName.Equals("AlwaysPrint", StringComparison.OrdinalIgnoreCase))
                                {
                                    session.Log($"Found in WOW6432Node: {subKeyName}");
                                    return subKeyName;
                                }
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                session.Log($"Error searching registry: {ex.Message}");
            }

            return null;
        }
    }
}
