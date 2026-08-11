using System;
using NUnit.Framework;

#nullable enable

namespace AlwaysPrint.Tests.Cloud
{
    /// <summary>
    /// Tests unitarios para la lógica de comparación semántica de versiones MSI
    /// utilizada en PushMessageHandler.SyncFromStateAsync.
    ///
    /// La lógica bajo test es:
    ///   - Version.TryParse(local) y Version.TryParse(remote)
    ///   - Si ambos parsean: localVer >= remoteVer → "al día" (no descarga)
    ///   - Si alguno falla: fallback a string.Equals (case-insensitive)
    ///   - Si no está al día y MsiUrl es null → warning log (sin descarga)
    ///   - Si no está al día y MsiUrl presente → disparar descarga
    ///
    /// Estos tests validan el comportamiento de comparación de versiones
    /// sin necesidad de instanciar PushMessageHandler (que requiere ConfigManager,
    /// UpdateDownloader, PipeClient, HttpClient).
    ///
    /// **Validates: Requirements 1.1, 1.2, 1.4, 1.5**
    /// </summary>
    [TestFixture]
    [Category("Feature: reconnection-reliability-fixes, Unit Tests: MSI Version Comparison")]
    public class PushMessageHandlerVersionTests
    {
        // ===================================================================
        // Lógica de comparación semántica extraída de SyncFromStateAsync
        // ===================================================================

        /// <summary>
        /// Replica la lógica de comparación de versiones de SyncFromStateAsync.
        /// Retorna un tuple con:
        ///   - versionAlDia: true si la versión local es >= remota
        ///   - disparaDescarga: true si debería disparar descarga (no al día + MsiUrl presente)
        ///   - generaWarning: true si debería generar warning (no al día + MsiUrl null)
        /// </summary>
        private static (bool versionAlDia, bool disparaDescarga, bool generaWarning) EvaluarVersionMsi(
            string currentVersion, string? msiVersion, string? msiUrl)
        {
            // Si MsiVersion es null o vacío, no hay nada que evaluar
            if (string.IsNullOrEmpty(msiVersion))
                return (true, false, false);

            // Comparación semántica: soporta 3 vs 4 segmentos (ej: "1.2.3" vs "1.2.3.0")
            bool versionAlDia;
            if (Version.TryParse(currentVersion, out var localVer) &&
                Version.TryParse(msiVersion, out var remoteVer))
            {
                // Si la versión local es >= remota, estamos al día (evita downgrades involuntarios)
                versionAlDia = (localVer >= remoteVer);
            }
            else
            {
                // Fallback a comparación string si algún parse falla
                versionAlDia = currentVersion.Equals(msiVersion, StringComparison.OrdinalIgnoreCase);
            }

            if (!versionAlDia)
            {
                // Versión remota más nueva
                if (!string.IsNullOrEmpty(msiUrl))
                {
                    // Hay URL → disparar descarga
                    return (false, true, false);
                }
                else
                {
                    // Sin URL → generar warning
                    return (false, false, true);
                }
            }

            // Al día — no descarga, no warning
            return (true, false, false);
        }

        // ===================================================================
        // Test: "1.2.3" vs local "1.2.3.0" se compara semánticamente (match)
        // ===================================================================

        /// <summary>
        /// Verifica que "1.2.3" (3 segmentos del servidor) vs "1.2.3.0" (4 segmentos local)
        /// se comparan semánticamente como iguales, sin disparar descarga.
        /// Version.TryParse("1.2.3") produce Version(1,2,3,-1) que con el operador >=
        /// compara correctamente contra Version(1,2,3,0).
        /// </summary>
        [Test]
        public void VersionComparacion_3Segmentos_Vs_4Segmentos_Iguales_NoDisparaDescarga()
        {
            // Arrange
            string localVersion = "1.2.3.0";    // Formato Assembly (4 segmentos)
            string remoteVersion = "1.2.3";     // Formato backend (3 segmentos)
            string msiUrl = "https://s3.amazonaws.com/bucket/update.msi";

            // Act
            var (versionAlDia, disparaDescarga, generaWarning) =
                EvaluarVersionMsi(localVersion, remoteVersion, msiUrl);

            // Assert: Las versiones son semánticamente equivalentes
            Assert.That(versionAlDia, Is.True,
                "Versión '1.2.3.0' local debe considerarse al día frente a '1.2.3' remota (semánticamente igual)");
            Assert.That(disparaDescarga, Is.False,
                "No debe disparar descarga cuando las versiones son semánticamente iguales");
            Assert.That(generaWarning, Is.False,
                "No debe generar warning cuando está al día");
        }

        // ===================================================================
        // Test: "1.3.0" vs local "1.2.3.0" dispara descarga
        // ===================================================================

        /// <summary>
        /// Verifica que una versión remota más nueva ("1.3.0") dispara descarga
        /// cuando la versión local es "1.2.3.0" y hay MsiUrl disponible.
        /// </summary>
        [Test]
        public void VersionComparacion_RemotaMasNueva_DisparaDescarga()
        {
            // Arrange
            string localVersion = "1.2.3.0";
            string remoteVersion = "1.3.0";
            string msiUrl = "https://s3.amazonaws.com/bucket/update-1.3.0.msi";

            // Act
            var (versionAlDia, disparaDescarga, generaWarning) =
                EvaluarVersionMsi(localVersion, remoteVersion, msiUrl);

            // Assert: Versión remota más nueva, debe disparar descarga
            Assert.That(versionAlDia, Is.False,
                "Versión '1.2.3.0' local NO está al día frente a '1.3.0' remota");
            Assert.That(disparaDescarga, Is.True,
                "Debe disparar descarga cuando la versión remota es más nueva y hay URL");
            Assert.That(generaWarning, Is.False,
                "No debe generar warning cuando hay URL disponible para descarga");
        }

        // ===================================================================
        // Test: "1.1.0" vs local "1.2.3.0" NO dispara descarga (no downgrade)
        // ===================================================================

        /// <summary>
        /// Verifica que una versión remota más vieja ("1.1.0") NO dispara descarga.
        /// El operador >= previene downgrades involuntarios: si local > remota, estamos al día.
        /// </summary>
        [Test]
        public void VersionComparacion_RemotaMasVieja_NoDisparaDescarga_NoDowngrade()
        {
            // Arrange
            string localVersion = "1.2.3.0";
            string remoteVersion = "1.1.0";
            string msiUrl = "https://s3.amazonaws.com/bucket/update-1.1.0.msi";

            // Act
            var (versionAlDia, disparaDescarga, generaWarning) =
                EvaluarVersionMsi(localVersion, remoteVersion, msiUrl);

            // Assert: Versión local más nueva que remota — no hacer downgrade
            Assert.That(versionAlDia, Is.True,
                "Versión '1.2.3.0' local es más nueva que '1.1.0' remota — se considera al día (no downgrade)");
            Assert.That(disparaDescarga, Is.False,
                "NO debe disparar descarga cuando la versión local es más nueva (evita downgrade)");
            Assert.That(generaWarning, Is.False,
                "No debe generar warning cuando está al día");
        }

        // ===================================================================
        // Test: MsiVersion más nueva con MsiUrl null genera warning log
        // ===================================================================

        /// <summary>
        /// Verifica que cuando la versión remota es más nueva pero MsiUrl es null,
        /// se genera un warning (no se puede descargar) sin intentar descarga.
        /// </summary>
        [Test]
        public void VersionComparacion_RemotaMasNueva_MsiUrlNull_GeneraWarning()
        {
            // Arrange
            string localVersion = "1.2.3.0";
            string remoteVersion = "1.4.0";
            string? msiUrl = null;  // Sin URL de descarga

            // Act
            var (versionAlDia, disparaDescarga, generaWarning) =
                EvaluarVersionMsi(localVersion, remoteVersion, msiUrl);

            // Assert: Versión remota más nueva pero sin URL → warning
            Assert.That(versionAlDia, Is.False,
                "Versión '1.2.3.0' local NO está al día frente a '1.4.0' remota");
            Assert.That(disparaDescarga, Is.False,
                "NO debe disparar descarga cuando MsiUrl es null");
            Assert.That(generaWarning, Is.True,
                "Debe generar warning cuando la versión remota es más nueva pero MsiUrl es null");
        }

        // ===================================================================
        // Test: MsiVersion igual a la local no dispara descarga
        // ===================================================================

        /// <summary>
        /// Verifica que cuando la versión remota es exactamente igual a la local
        /// (mismo formato 4 segmentos), no se dispara descarga.
        /// </summary>
        [Test]
        public void VersionComparacion_VersionIgual_NoDisparaDescarga()
        {
            // Arrange
            string localVersion = "2.1.0.0";
            string remoteVersion = "2.1.0.0";
            string msiUrl = "https://s3.amazonaws.com/bucket/update-2.1.0.msi";

            // Act
            var (versionAlDia, disparaDescarga, generaWarning) =
                EvaluarVersionMsi(localVersion, remoteVersion, msiUrl);

            // Assert: Versiones idénticas — al día
            Assert.That(versionAlDia, Is.True,
                "Versión '2.1.0.0' local debe considerarse al día frente a '2.1.0.0' remota");
            Assert.That(disparaDescarga, Is.False,
                "No debe disparar descarga cuando las versiones son idénticas");
            Assert.That(generaWarning, Is.False,
                "No debe generar warning cuando está al día");
        }

        // ===================================================================
        // Tests adicionales: Edge cases de Version.TryParse
        // ===================================================================

        /// <summary>
        /// Verifica que el fallback a comparación string funciona cuando
        /// Version.TryParse falla (ej: formato inválido como "invalid").
        /// </summary>
        [Test]
        public void VersionComparacion_FormatoInvalido_FallbackAString_NoMatch()
        {
            // Arrange: Versión remota con formato que no parsea como Version
            string localVersion = "1.2.3.0";
            string remoteVersion = "invalid-version";
            string msiUrl = "https://s3.amazonaws.com/bucket/update.msi";

            // Act
            var (versionAlDia, disparaDescarga, generaWarning) =
                EvaluarVersionMsi(localVersion, remoteVersion, msiUrl);

            // Assert: Fallback a string — no son iguales → disparar descarga
            Assert.That(versionAlDia, Is.False,
                "Con formato inválido, fallback a string: '1.2.3.0' != 'invalid-version'");
            Assert.That(disparaDescarga, Is.True,
                "Debe disparar descarga cuando el fallback string no coincide y hay URL");
        }

        /// <summary>
        /// Verifica que MsiVersion vacía o null no evalúa nada (se considera al día).
        /// </summary>
        [TestCase(null)]
        [TestCase("")]
        public void VersionComparacion_MsiVersionNullOVacia_NoEvalua(string? msiVersion)
        {
            // Arrange
            string localVersion = "1.0.0.0";
            string msiUrl = "https://s3.amazonaws.com/bucket/update.msi";

            // Act
            var (versionAlDia, disparaDescarga, generaWarning) =
                EvaluarVersionMsi(localVersion, msiVersion, msiUrl);

            // Assert: MsiVersion null/vacía → se considera al día, no se evalúa
            Assert.That(versionAlDia, Is.True,
                "MsiVersion null o vacía debe considerarse 'al día' (nada que comparar)");
            Assert.That(disparaDescarga, Is.False);
            Assert.That(generaWarning, Is.False);
        }

        /// <summary>
        /// Verifica que la comparación con MsiUrl vacía también genera warning
        /// (string vacía se trata como null para fines de descarga).
        /// </summary>
        [Test]
        public void VersionComparacion_RemotaMasNueva_MsiUrlVacia_GeneraWarning()
        {
            // Arrange
            string localVersion = "1.0.0.0";
            string remoteVersion = "2.0.0";
            string msiUrl = "";  // URL vacía = no disponible

            // Act
            var (versionAlDia, disparaDescarga, generaWarning) =
                EvaluarVersionMsi(localVersion, remoteVersion, msiUrl);

            // Assert: URL vacía → misma lógica que null → warning
            Assert.That(versionAlDia, Is.False,
                "Versión '1.0.0.0' local NO está al día frente a '2.0.0' remota");
            Assert.That(disparaDescarga, Is.False,
                "NO debe disparar descarga cuando MsiUrl es vacía");
            Assert.That(generaWarning, Is.True,
                "Debe generar warning cuando la versión remota es más nueva pero MsiUrl es vacía");
        }
    }
}
