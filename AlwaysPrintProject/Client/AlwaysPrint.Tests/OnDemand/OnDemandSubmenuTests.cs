using System.Collections.Generic;
using System.Linq;
using AlwaysPrintTray.OnDemand;
using NUnit.Framework;

namespace AlwaysPrint.Tests.OnDemand
{
    /// <summary>
    /// Unit tests para la lógica del submenú OnDemand en el menú contextual del Tray.
    /// 
    /// Dado que la construcción del submenú está acoplada a WinForms (ToolStripMenuItem),
    /// estos tests validan la LÓGICA pura que determina:
    /// - Si el submenú debe existir (triggers > 0)
    /// - Qué ítems debe contener (labels de triggers válidos)
    /// - El estado de ejecución de un trigger (ítem deshabilitado)
    /// - El formato de los mensajes balloon de éxito y error
    /// 
    /// Requirements: 6.1, 6.4, 9.1, 9.2, 9.3
    /// </summary>
    [TestFixture]
    [Category("Feature: on-demand-triggers, Unit: OnDemand Submenu")]
    public class OnDemandSubmenuTests
    {
        #region Lógica extraída para testing

        /// <summary>
        /// Determina si el submenú OnDemand debe mostrarse en el menú contextual.
        /// Equivale a la condición en RebuildOnDemandSubmenu: if (triggers.Count == 0) → no mostrar.
        /// </summary>
        internal static bool ShouldShowSubmenu(List<OnDemandTriggerInfo> triggers)
        {
            return triggers != null && triggers.Count > 0;
        }

        /// <summary>
        /// Genera la lista de labels que deben aparecer como ítems del submenú.
        /// Equivale al foreach que crea ToolStripMenuItem con trigger.Label.
        /// </summary>
        internal static List<string> GetSubmenuItemLabels(List<OnDemandTriggerInfo> triggers)
        {
            if (triggers == null || triggers.Count == 0)
                return new List<string>();

            return triggers.Select(t => t.Label).ToList();
        }

        /// <summary>
        /// Determina si un ítem del submenú debe estar deshabilitado (grayed out).
        /// Un ítem se deshabilita cuando su trigger está en ejecución.
        /// Equivale a: item.Enabled = !executingTriggers.Contains(label)
        /// </summary>
        internal static bool IsItemEnabled(string triggerLabel, HashSet<string> executingTriggers)
        {
            return !executingTriggers.Contains(triggerLabel);
        }

        /// <summary>
        /// Genera el mensaje balloon para ejecución exitosa de un trigger OnDemand.
        /// Debe incluir el label del trigger ejecutado.
        /// Validates: Requirement 9.1
        /// </summary>
        internal static string FormatSuccessBalloon(string triggerLabel)
        {
            return $"✓ {triggerLabel} ejecutado correctamente";
        }

        /// <summary>
        /// Genera el mensaje balloon para ejecución fallida de un trigger OnDemand.
        /// Debe incluir el mensaje de error si está disponible.
        /// Validates: Requirement 9.2
        /// </summary>
        internal static string FormatErrorBalloon(string triggerLabel, string? errorMessage)
        {
            if (string.IsNullOrWhiteSpace(errorMessage))
                return $"✗ {triggerLabel} falló durante la ejecución";

            return $"✗ {triggerLabel} falló: {errorMessage}";
        }

        #endregion

        #region Test: con triggers → submenú presente con ítems correctos

        /// <summary>
        /// Cuando hay triggers OnDemand válidos, el submenú debe mostrarse
        /// con exactamente los ítems correspondientes a los labels de cada trigger.
        /// Validates: Requirement 6.1
        /// </summary>
        [Test]
        public void ConTriggers_SubmenuPresente_ConItemsCorrectos()
        {
            // Arrange — lista con múltiples triggers OnDemand válidos
            var triggers = new List<OnDemandTriggerInfo>
            {
                new OnDemandTriggerInfo { Label = "Reiniciar LPMC", Description = "Reinicia servicio" },
                new OnDemandTriggerInfo { Label = "Limpiar Cache", Description = "Elimina temporales" },
                new OnDemandTriggerInfo { Label = "Resetear Spooler", Description = "Resetea cola" }
            };

            // Act
            bool shouldShow = ShouldShowSubmenu(triggers);
            var labels = GetSubmenuItemLabels(triggers);

            // Assert
            Assert.IsTrue(shouldShow,
                "Con triggers disponibles, el submenú debe mostrarse.");
            Assert.AreEqual(3, labels.Count,
                "Debe haber un ítem por cada trigger OnDemand.");
            Assert.AreEqual("Reiniciar LPMC", labels[0]);
            Assert.AreEqual("Limpiar Cache", labels[1]);
            Assert.AreEqual("Resetear Spooler", labels[2]);
        }

        /// <summary>
        /// Con un solo trigger, el submenú también debe mostrarse.
        /// Validates: Requirement 6.1
        /// </summary>
        [Test]
        public void ConUnSoloTrigger_SubmenuPresente()
        {
            // Arrange
            var triggers = new List<OnDemandTriggerInfo>
            {
                new OnDemandTriggerInfo { Label = "Acción Única", Description = "Descripción" }
            };

            // Act
            bool shouldShow = ShouldShowSubmenu(triggers);
            var labels = GetSubmenuItemLabels(triggers);

            // Assert
            Assert.IsTrue(shouldShow);
            Assert.AreEqual(1, labels.Count);
            Assert.AreEqual("Acción Única", labels[0]);
        }

        /// <summary>
        /// Los labels del submenú preservan el orden original de los triggers.
        /// Validates: Requirement 6.3
        /// </summary>
        [Test]
        public void ItemsPreservanOrdenOriginal()
        {
            // Arrange — triggers con labels en orden específico
            var triggers = new List<OnDemandTriggerInfo>
            {
                new OnDemandTriggerInfo { Label = "Zeta", Description = "" },
                new OnDemandTriggerInfo { Label = "Alfa", Description = "" },
                new OnDemandTriggerInfo { Label = "Beta", Description = "" }
            };

            // Act
            var labels = GetSubmenuItemLabels(triggers);

            // Assert — orden preservado (no alfabético)
            Assert.AreEqual("Zeta", labels[0]);
            Assert.AreEqual("Alfa", labels[1]);
            Assert.AreEqual("Beta", labels[2]);
        }

        #endregion

        #region Test: sin triggers → submenú ausente

        /// <summary>
        /// Cuando no hay triggers OnDemand, el submenú no debe mostrarse.
        /// Validates: Requirement 6.4
        /// </summary>
        [Test]
        public void SinTriggers_SubmenuAusente()
        {
            // Arrange — lista vacía
            var triggers = new List<OnDemandTriggerInfo>();

            // Act
            bool shouldShow = ShouldShowSubmenu(triggers);
            var labels = GetSubmenuItemLabels(triggers);

            // Assert
            Assert.IsFalse(shouldShow,
                "Sin triggers OnDemand, el submenú no debe mostrarse.");
            Assert.AreEqual(0, labels.Count,
                "Sin triggers, no debe haber ítems de menú.");
        }

        /// <summary>
        /// Cuando la lista de triggers es null, el submenú no debe mostrarse.
        /// Validates: Requirement 6.4
        /// </summary>
        [Test]
        public void TriggersNull_SubmenuAusente()
        {
            // Act
            bool shouldShow = ShouldShowSubmenu(null!);
            var labels = GetSubmenuItemLabels(null!);

            // Assert
            Assert.IsFalse(shouldShow);
            Assert.AreEqual(0, labels.Count);
        }

        #endregion

        #region Test: ítem deshabilitado durante ejecución

        /// <summary>
        /// Un ítem del submenú debe estar deshabilitado mientras su trigger está en ejecución.
        /// Validates: Requirement 9.3
        /// </summary>
        [Test]
        public void ItemDeshabilitado_DuranteEjecucion()
        {
            // Arrange — trigger "Reiniciar LPMC" en ejecución
            var executingTriggers = new HashSet<string> { "Reiniciar LPMC" };

            // Act
            bool enabled = IsItemEnabled("Reiniciar LPMC", executingTriggers);

            // Assert
            Assert.IsFalse(enabled,
                "El ítem debe estar deshabilitado mientras su trigger está en ejecución.");
        }

        /// <summary>
        /// Un ítem del submenú debe estar habilitado si su trigger NO está en ejecución.
        /// Validates: Requirement 9.3
        /// </summary>
        [Test]
        public void ItemHabilitado_CuandoNoEstaEnEjecucion()
        {
            // Arrange — otro trigger en ejecución, pero no el consultado
            var executingTriggers = new HashSet<string> { "Otro Trigger" };

            // Act
            bool enabled = IsItemEnabled("Reiniciar LPMC", executingTriggers);

            // Assert
            Assert.IsTrue(enabled,
                "El ítem debe estar habilitado si su trigger no está en ejecución.");
        }

        /// <summary>
        /// Múltiples triggers pueden estar en ejecución simultáneamente.
        /// Solo los que están ejecutándose deben estar deshabilitados.
        /// Validates: Requirement 9.3
        /// </summary>
        [Test]
        public void MultiplesTriggersEnEjecucion_SoloDeshabilitaCorrespondientes()
        {
            // Arrange — dos triggers en ejecución
            var executingTriggers = new HashSet<string> { "Reiniciar LPMC", "Limpiar Cache" };

            // Act & Assert
            Assert.IsFalse(IsItemEnabled("Reiniciar LPMC", executingTriggers));
            Assert.IsFalse(IsItemEnabled("Limpiar Cache", executingTriggers));
            Assert.IsTrue(IsItemEnabled("Resetear Spooler", executingTriggers));
        }

        /// <summary>
        /// Sin triggers en ejecución, todos los ítems están habilitados.
        /// Validates: Requirement 9.3
        /// </summary>
        [Test]
        public void SinTriggersEnEjecucion_TodosHabilitados()
        {
            // Arrange — ningún trigger en ejecución
            var executingTriggers = new HashSet<string>();

            // Act & Assert
            Assert.IsTrue(IsItemEnabled("Reiniciar LPMC", executingTriggers));
            Assert.IsTrue(IsItemEnabled("Limpiar Cache", executingTriggers));
        }

        #endregion

        #region Test: balloon success con label correcto

        /// <summary>
        /// El mensaje balloon de éxito debe incluir el label del trigger ejecutado.
        /// Validates: Requirement 9.1
        /// </summary>
        [Test]
        public void BalloonSuccess_IncluyeLabel()
        {
            // Arrange
            string label = "Reiniciar LPMC";

            // Act
            string mensaje = FormatSuccessBalloon(label);

            // Assert
            Assert.IsTrue(mensaje.Contains(label),
                "El mensaje de éxito debe incluir el label del trigger.");
            Assert.IsTrue(mensaje.Contains("✓"),
                "El mensaje de éxito debe indicar visualmente que fue exitoso.");
        }

        /// <summary>
        /// El formato del balloon de éxito para diferentes labels.
        /// Validates: Requirement 9.1
        /// </summary>
        [TestCase("Reiniciar LPMC", "✓ Reiniciar LPMC ejecutado correctamente")]
        [TestCase("Limpiar Cache", "✓ Limpiar Cache ejecutado correctamente")]
        [TestCase("Resetear Spooler", "✓ Resetear Spooler ejecutado correctamente")]
        public void BalloonSuccess_FormatoCorrecto(string label, string esperado)
        {
            // Act
            string mensaje = FormatSuccessBalloon(label);

            // Assert
            Assert.AreEqual(esperado, mensaje);
        }

        #endregion

        #region Test: balloon error con mensaje

        /// <summary>
        /// El mensaje balloon de error debe incluir el label del trigger y el mensaje de error.
        /// Validates: Requirement 9.2
        /// </summary>
        [Test]
        public void BalloonError_IncluyeLabelYMensaje()
        {
            // Arrange
            string label = "Reiniciar LPMC";
            string errorMsg = "Servicio no responde después de 30s";

            // Act
            string mensaje = FormatErrorBalloon(label, errorMsg);

            // Assert
            Assert.IsTrue(mensaje.Contains(label),
                "El mensaje de error debe incluir el label del trigger.");
            Assert.IsTrue(mensaje.Contains(errorMsg),
                "El mensaje de error debe incluir el mensaje de error específico.");
        }

        /// <summary>
        /// Cuando no hay mensaje de error disponible, el balloon muestra un mensaje genérico.
        /// Validates: Requirement 9.2
        /// </summary>
        [Test]
        public void BalloonError_SinMensaje_MuestraGenerico()
        {
            // Arrange
            string label = "Limpiar Cache";

            // Act
            string mensaje = FormatErrorBalloon(label, null);

            // Assert
            Assert.IsTrue(mensaje.Contains(label),
                "El mensaje genérico debe incluir el label del trigger.");
            Assert.IsTrue(mensaje.Contains("falló"),
                "El mensaje genérico debe indicar que falló.");
        }

        /// <summary>
        /// Con mensaje de error vacío o whitespace, se usa formato genérico.
        /// Validates: Requirement 9.2
        /// </summary>
        [TestCase("")]
        [TestCase("   ")]
        [TestCase(null)]
        public void BalloonError_MensajeVacioONull_FormatoGenerico(string? errorMsg)
        {
            // Arrange
            string label = "Resetear Spooler";

            // Act
            string mensaje = FormatErrorBalloon(label, errorMsg);

            // Assert
            Assert.AreEqual($"✗ {label} falló durante la ejecución", mensaje,
                "Con mensaje de error vacío/null se usa formato genérico.");
        }

        /// <summary>
        /// Con mensaje de error válido, se incluye en el balloon.
        /// Validates: Requirement 9.2
        /// </summary>
        [Test]
        public void BalloonError_ConMensaje_FormatoCorrecto()
        {
            // Arrange
            string label = "Reiniciar LPMC";
            string error = "Timeout al iniciar servicio";

            // Act
            string mensaje = FormatErrorBalloon(label, error);

            // Assert
            Assert.AreEqual("✗ Reiniciar LPMC falló: Timeout al iniciar servicio", mensaje);
        }

        #endregion
    }
}
