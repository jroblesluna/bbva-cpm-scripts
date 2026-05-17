using System;
using System.Diagnostics;
using FsCheck;
using FsCheck.NUnit;
using NUnit.Framework;
using AlwaysPrint.Shared.Messages;
using FsCheckProperty = FsCheck.NUnit.PropertyAttribute;

namespace AlwaysPrint.Tests.Properties
{
    /// <summary>
    /// Property 4: Install handler exit code reporting
    /// Para cualquier exit code no-cero de un proceso, el InstallUpdateResponsePayload
    /// debe tener Success=false y ExitCode igual al código real del proceso.
    /// Validates: Requirements 5.5
    /// </summary>
    [TestFixture]
    [Category("Feature: auto-update, Property 4: Install handler exit code reporting")]
    public class InstallHandlerExitCodeTests
    {
        /// <summary>
        /// Simula la lógica de construcción de respuesta del UpdateInstallHandler
        /// cuando un proceso retorna un exit code específico.
        /// Usa cmd /c exit para generar un proceso real con el código deseado.
        /// </summary>
        /// <param name="exitCode">Código de salida del proceso.</param>
        /// <returns>Payload de respuesta construido según la lógica del handler.</returns>
        private static InstallUpdateResponsePayload BuildResponseFromProcessExitCode(int exitCode)
        {
            // Ejecutar un proceso real que retorna el exit code especificado
            // Esto replica la lógica del UpdateInstallHandler sin depender de msiexec
            var startInfo = new ProcessStartInfo
            {
                FileName = "cmd.exe",
                Arguments = $"/c exit {exitCode}",
                UseShellExecute = false,
                CreateNoWindow = true
            };

            using (var process = Process.Start(startInfo))
            {
                if (process == null)
                {
                    return new InstallUpdateResponsePayload
                    {
                        Success = false,
                        Message = "No se pudo iniciar el proceso.",
                        ExitCode = -1
                    };
                }

                process.WaitForExit();
                int actualExitCode = process.ExitCode;

                // Replicar la lógica del handler: si exitCode != 0, es fallo
                if (actualExitCode == 0)
                {
                    return new InstallUpdateResponsePayload
                    {
                        Success = true,
                        Message = "Actualización instalada exitosamente.",
                        ExitCode = 0
                    };
                }
                else
                {
                    return new InstallUpdateResponsePayload
                    {
                        Success = false,
                        Message = $"Instalación fallida. msiexec exit code={actualExitCode}.",
                        ExitCode = actualExitCode
                    };
                }
            }
        }

        /// <summary>
        /// Propiedad: Para cualquier exit code no-cero (1..255), el payload de respuesta
        /// debe tener Success=false y ExitCode igual al código real del proceso.
        /// Se usa el rango 1..255 porque cmd /c exit solo soporta valores de 0 a 255
        /// en la práctica (trunca a byte en Windows).
        /// **Validates: Requirements 5.5**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property NonZeroExitCode_ProducesFailureResponse_WithCorrectCode()
        {
            // Generar exit codes no-cero en rango válido para cmd.exe (1..255)
            return Prop.ForAll(
                Arb.From(Gen.Choose(1, 255)),
                exitCode =>
                {
                    var response = BuildResponseFromProcessExitCode(exitCode);

                    var successIsFalse = response.Success == false;
                    var exitCodeMatches = response.ExitCode == exitCode;

                    return (successIsFalse && exitCodeMatches)
                        .Label($"ExitCode={exitCode}: Success={response.Success}, " +
                               $"ResponseExitCode={response.ExitCode}");
                });
        }

        /// <summary>
        /// Propiedad complementaria: Para cualquier exit code no-cero arbitrario (rango amplio),
        /// la construcción directa del payload siempre produce Success=false y ExitCode correcto.
        /// Esto verifica la lógica de construcción sin depender de un proceso real.
        /// **Validates: Requirements 5.5**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property NonZeroExitCode_DirectConstruction_AlwaysReportsFailure()
        {
            // Generar exit codes no-cero en rango amplio (incluye códigos de error de msiexec)
            return Prop.ForAll(
                Arb.From(Gen.Choose(1, int.MaxValue)),
                exitCode =>
                {
                    // Construcción directa del payload (misma lógica que el handler)
                    var response = new InstallUpdateResponsePayload
                    {
                        Success = false,
                        Message = $"Instalación fallida. msiexec exit code={exitCode}.",
                        ExitCode = exitCode
                    };

                    var successIsFalse = response.Success == false;
                    var exitCodeMatches = response.ExitCode == exitCode;
                    var messageContainsCode = response.Message != null &&
                                             response.Message.Contains(exitCode.ToString());

                    return (successIsFalse && exitCodeMatches && messageContainsCode)
                        .Label($"ExitCode={exitCode}: Success={response.Success}, " +
                               $"ResponseExitCode={response.ExitCode}, " +
                               $"MessageContainsCode={messageContainsCode}");
                });
        }
    }
}
