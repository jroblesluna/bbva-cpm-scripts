using NUnit.Framework;
using AlwaysPrintTray.OnDemand;

namespace AlwaysPrint.Tests.OnDemand
{
    /// <summary>
    /// Unit tests para la lógica de información general del Status Form.
    /// Valida el formateo de estado del sistema y cola activa gestionada.
    /// Requirements: 2.1, 2.3, 2.4
    /// </summary>
    [TestFixture]
    [Category("Feature: on-demand-triggers, Unit: StatusFormGeneralInfo")]
    public class StatusFormGeneralInfoTests
    {
        // ── Tests de estado del sistema (Requirement 2.1) ──

        /// <summary>
        /// ContingencyEnabled = false → muestra "Normal".
        /// Validates: Requirement 2.1
        /// </summary>
        [Test]
        public void FormatEstadoSistema_ContingencyDesactivada_RetornaNormal()
        {
            // Act
            var resultado = StatusDisplayHelper.FormatEstadoSistema(contingencyEnabled: false);

            // Assert
            Assert.AreEqual("Normal", resultado);
        }

        /// <summary>
        /// ContingencyEnabled = true → muestra "En Contingencia".
        /// Validates: Requirement 2.1
        /// </summary>
        [Test]
        public void FormatEstadoSistema_ContingencyActivada_RetornaEnContingencia()
        {
            // Act
            var resultado = StatusDisplayHelper.FormatEstadoSistema(contingencyEnabled: true);

            // Assert
            Assert.AreEqual("En Contingencia", resultado);
        }

        // ── Tests de cola activa modo CPM (Requirement 2.3) ──

        /// <summary>
        /// Modo CPM (sin remote_queue_path): muestra solo el nombre de la cola.
        /// Validates: Requirement 2.3
        /// </summary>
        [Test]
        public void FormatColaActiva_ModoCpm_SinRemotePath_RetornaSoloNombre()
        {
            // Arrange
            string queueName = "LexmarkBBVA";

            // Act
            var resultado = StatusDisplayHelper.FormatColaActiva(queueName, remoteQueuePath: null);

            // Assert
            Assert.AreEqual("LexmarkBBVA", resultado);
        }

        /// <summary>
        /// Modo CPM con remote_queue_path vacío: se trata como CPM (solo nombre).
        /// Validates: Requirement 2.3
        /// </summary>
        [Test]
        public void FormatColaActiva_ModoCpm_RemotePathVacio_RetornaSoloNombre()
        {
            // Arrange
            string queueName = "LexmarkBBVA";

            // Act
            var resultado = StatusDisplayHelper.FormatColaActiva(queueName, remoteQueuePath: "");

            // Assert
            Assert.AreEqual("LexmarkBBVA", resultado);
        }

        /// <summary>
        /// Modo CPM con remote_queue_path solo whitespace: se trata como CPM (solo nombre).
        /// Validates: Requirement 2.3
        /// </summary>
        [Test]
        public void FormatColaActiva_ModoCpm_RemotePathWhitespace_RetornaSoloNombre()
        {
            // Arrange
            string queueName = "LexmarkBBVA";

            // Act
            var resultado = StatusDisplayHelper.FormatColaActiva(queueName, remoteQueuePath: "   ");

            // Assert
            Assert.AreEqual("LexmarkBBVA", resultado);
        }

        // ── Tests de cola activa modo LPM (Requirement 2.4) ──

        /// <summary>
        /// Modo LPM (con remote_queue_path): muestra nombre + ruta remota entre paréntesis.
        /// Validates: Requirement 2.4
        /// </summary>
        [Test]
        public void FormatColaActiva_ModoLpm_ConRemotePath_RetornaNombreYRuta()
        {
            // Arrange
            string queueName = "LexmarkBBVA";
            string remotePath = @"\\server\share";

            // Act
            var resultado = StatusDisplayHelper.FormatColaActiva(queueName, remotePath);

            // Assert
            Assert.AreEqual(@"LexmarkBBVA (\\server\share)", resultado);
        }

        /// <summary>
        /// Modo LPM con ruta remota compleja (múltiples niveles): formato correcto.
        /// Validates: Requirement 2.4
        /// </summary>
        [Test]
        public void FormatColaActiva_ModoLpm_RutaCompleja_RetornaFormatoCorrecto()
        {
            // Arrange
            string queueName = "LexmarkBBVA";
            string remotePath = @"\\printserver.corp.bbva\lexmark_queue";

            // Act
            var resultado = StatusDisplayHelper.FormatColaActiva(queueName, remotePath);

            // Assert
            Assert.AreEqual(@"LexmarkBBVA (\\printserver.corp.bbva\lexmark_queue)", resultado);
        }
    }
}
