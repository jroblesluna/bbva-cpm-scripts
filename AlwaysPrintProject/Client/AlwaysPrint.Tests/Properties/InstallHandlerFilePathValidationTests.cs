using System;
using System.IO;
using FsCheck;
using FsCheck.NUnit;
using NUnit.Framework;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintService.Tasks;
using FsCheckProperty = FsCheck.NUnit.PropertyAttribute;

namespace AlwaysPrint.Tests.Properties
{
    /// <summary>
    /// Property 3: Install handler file path validation
    /// Verifica que el handler retorna failure si y solo si el archivo no existe en el path.
    /// Validates: Requirements 5.2, 5.4
    /// </summary>
    [TestFixture]
    [Category("Feature: auto-update, Property 3: Install handler file path validation")]
    public class InstallHandlerFilePathValidationTests
    {
        /// <summary>
        /// Generador de paths que garantizan NO existir en el sistema de archivos.
        /// Usa GUIDs aleatorios como nombres de archivo en el directorio temporal.
        /// </summary>
        private static Arbitrary<string> NonExistentPathArbitrary()
        {
            var gen = from guid in Arb.Generate<Guid>()
                      from ext in Gen.Elements(".msi", ".tmp", ".exe", ".dat")
                      select Path.Combine(
                          Path.GetTempPath(),
                          "AlwaysPrint_Test_NonExistent",
                          $"{guid}{ext}");

            return Arb.From(gen);
        }

        /// <summary>
        /// Propiedad: Para cualquier path que NO existe en el sistema de archivos,
        /// UpdateInstallHandler.Execute() retorna Success=false con un mensaje de error significativo.
        /// **Validates: Requirements 5.2, 5.4**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property NonExistentPath_ReturnsFailure()
        {
            return Prop.ForAll(
                NonExistentPathArbitrary(),
                path =>
                {
                    // Precondición: el path no debe existir (los GUIDs lo garantizan)
                    if (File.Exists(path))
                        return true.Label("Path existe inesperadamente, se omite iteración");

                    var handler = new UpdateInstallHandler();
                    var result = handler.Execute(path);

                    // Verificar que retorna failure
                    var successIsFalse = !result.Success;
                    var hasErrorMessage = !string.IsNullOrEmpty(result.Message);
                    var exitCodeIsNegative = result.ExitCode == -1;

                    return (successIsFalse && hasErrorMessage && exitCodeIsNegative)
                        .Label($"Path='{path}': Success={result.Success}, " +
                               $"Message='{result.Message}', ExitCode={result.ExitCode}");
                });
        }

        /// <summary>
        /// Propiedad: Para cualquier archivo que SÍ existe en el path,
        /// UpdateInstallHandler.Execute() NO retorna el error de "archivo no encontrado".
        /// (msiexec fallará porque no es un MSI válido, pero ese es un error diferente)
        /// **Validates: Requirements 5.2, 5.4**
        /// </summary>
        [FsCheckProperty(MaxTest = 10)]
        public Property ExistingPath_DoesNotReturnFileNotFoundError()
        {
            // Generador que crea archivos temporales reales
            var gen = Arb.Generate<Guid>()
                .Select(g =>
                {
                    var dir = Path.Combine(Path.GetTempPath(), "AlwaysPrint_Test_Existing");
                    Directory.CreateDirectory(dir);
                    var filePath = Path.Combine(dir, $"{g}.msi");
                    // Crear archivo vacío para que exista
                    File.WriteAllBytes(filePath, new byte[] { 0x00 });
                    return filePath;
                });

            return Prop.ForAll(
                Arb.From(gen),
                path =>
                {
                    try
                    {
                        var handler = new UpdateInstallHandler();
                        var result = handler.Execute(path);

                        // El archivo existe, así que NO debe retornar error de "archivo no encontrado"
                        // msiexec fallará (no es un MSI válido), pero el mensaje será diferente
                        var notFileNotFoundError = result.Message == null ||
                            !result.Message.Contains("archivo no encontrado");

                        return notFileNotFoundError
                            .Label($"Path='{path}': Success={result.Success}, " +
                                   $"Message='{result.Message}' - No debe ser error de archivo no encontrado");
                    }
                    finally
                    {
                        // Limpiar archivo temporal
                        try { File.Delete(path); } catch { /* ignorar */ }
                    }
                });
        }

        /// <summary>
        /// Limpieza de directorios temporales creados durante los tests.
        /// </summary>
        [OneTimeTearDown]
        public void Cleanup()
        {
            try
            {
                var nonExistentDir = Path.Combine(Path.GetTempPath(), "AlwaysPrint_Test_NonExistent");
                if (Directory.Exists(nonExistentDir))
                    Directory.Delete(nonExistentDir, true);
            }
            catch { /* ignorar errores de limpieza */ }

            try
            {
                var existingDir = Path.Combine(Path.GetTempPath(), "AlwaysPrint_Test_Existing");
                if (Directory.Exists(existingDir))
                    Directory.Delete(existingDir, true);
            }
            catch { /* ignorar errores de limpieza */ }
        }
    }
}
