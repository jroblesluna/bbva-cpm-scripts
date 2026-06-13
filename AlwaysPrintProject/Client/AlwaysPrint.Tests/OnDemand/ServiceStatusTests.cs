using NUnit.Framework;
using AlwaysPrintTray.Forms;

namespace AlwaysPrint.Tests.OnDemand
{
    /// <summary>
    /// Unit tests para la sección de servicios del Status Form.
    /// Valida la lógica de mapeo de estado a etiqueta de acción,
    /// el flag IsOperating y el comportamiento cuando el pipe no está disponible.
    /// Requirements: 3.2, 3.3, 3.6, 3.7
    /// </summary>
    [TestFixture]
    [Category("Feature: on-demand-triggers, Unit: ServiceStatus")]
    public class ServiceStatusTests
    {
        // ── Tests de mapeo estado → label de acción (Requirements 3.2, 3.3) ──

        /// <summary>
        /// Estado Running → label "Reiniciar".
        /// Validates: Requirement 3.2
        /// </summary>
        [Test]
        public void ActionLabel_EstadoRunning_RetornaReiniciar()
        {
            // Arrange
            var item = new ServiceStatusItem { State = "Running" };

            // Act & Assert
            Assert.AreEqual("Reiniciar", item.ActionLabel);
        }

        /// <summary>
        /// Estado Stopped → label "Iniciar".
        /// Validates: Requirement 3.3
        /// </summary>
        [Test]
        public void ActionLabel_EstadoStopped_RetornaIniciar()
        {
            // Arrange
            var item = new ServiceStatusItem { State = "Stopped" };

            // Act & Assert
            Assert.AreEqual("Iniciar", item.ActionLabel);
        }

        /// <summary>
        /// Estado Desconocido → label "Iniciar" (no es Running, cae en else).
        /// Validates: Requirement 3.3
        /// </summary>
        [Test]
        public void ActionLabel_EstadoDesconocido_RetornaIniciar()
        {
            // Arrange
            var item = new ServiceStatusItem { State = "Desconocido" };

            // Act & Assert
            Assert.AreEqual("Iniciar", item.ActionLabel);
        }

        // ── Tests de IsOperating deshabilita control (Requirement 3.6) ──

        /// <summary>
        /// IsOperating = true deshabilita el control (IsActionEnabled = false)
        /// incluso si el estado es Running.
        /// Validates: Requirement 3.6
        /// </summary>
        [Test]
        public void IsActionEnabled_IsOperatingTrue_RetornaFalse()
        {
            // Arrange
            var item = new ServiceStatusItem
            {
                State = "Running",
                IsOperating = true
            };

            // Act & Assert
            Assert.IsFalse(item.IsActionEnabled);
        }

        /// <summary>
        /// IsOperating = false con estado Running → control habilitado.
        /// Validates: Requirement 3.6
        /// </summary>
        [Test]
        public void IsActionEnabled_IsOperatingFalseEstadoRunning_RetornaTrue()
        {
            // Arrange
            var item = new ServiceStatusItem
            {
                State = "Running",
                IsOperating = false
            };

            // Act & Assert
            Assert.IsTrue(item.IsActionEnabled);
        }

        /// <summary>
        /// IsOperating = false con estado Stopped → control habilitado.
        /// Validates: Requirement 3.6
        /// </summary>
        [Test]
        public void IsActionEnabled_IsOperatingFalseEstadoStopped_RetornaTrue()
        {
            // Arrange
            var item = new ServiceStatusItem
            {
                State = "Stopped",
                IsOperating = false
            };

            // Act & Assert
            Assert.IsTrue(item.IsActionEnabled);
        }

        // ── Tests de pipe no disponible → "Estado desconocido" (Requirement 3.7) ──

        /// <summary>
        /// Estado "Desconocido" (pipe no disponible) → control deshabilitado.
        /// Validates: Requirement 3.7
        /// </summary>
        [Test]
        public void IsActionEnabled_EstadoDesconocido_RetornaFalse()
        {
            // Arrange
            var item = new ServiceStatusItem { State = "Desconocido" };

            // Act & Assert
            Assert.IsFalse(item.IsActionEnabled);
        }

        /// <summary>
        /// Estado por defecto del ServiceStatusItem es "Desconocido" y control deshabilitado.
        /// Validates: Requirement 3.7
        /// </summary>
        [Test]
        public void ServiceStatusItem_EstadoInicial_EsDesconocidoYDeshabilitado()
        {
            // Arrange & Act
            var item = new ServiceStatusItem();

            // Assert
            Assert.AreEqual("Desconocido", item.State);
            Assert.IsFalse(item.IsActionEnabled);
        }

        /// <summary>
        /// Estado "Desconocido" con IsOperating=true → control sigue deshabilitado.
        /// Validates: Requirements 3.6, 3.7
        /// </summary>
        [Test]
        public void IsActionEnabled_EstadoDesconocidoEIsOperating_RetornaFalse()
        {
            // Arrange
            var item = new ServiceStatusItem
            {
                State = "Desconocido",
                IsOperating = true
            };

            // Act & Assert
            Assert.IsFalse(item.IsActionEnabled);
        }
    }
}
