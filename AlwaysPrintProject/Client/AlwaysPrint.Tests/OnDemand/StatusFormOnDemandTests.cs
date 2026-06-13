using System.Collections.Generic;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintTray.Forms;
using AlwaysPrintTray.OnDemand;
using NUnit.Framework;

namespace AlwaysPrint.Tests.OnDemand
{
    /// <summary>
    /// Unit tests para la lógica de ejecución OnDemand desde el Status Form.
    /// 
    /// Dado que StatusForm es WPF (difícil de instanciar en tests unitarios),
    /// estos tests validan la LÓGICA pura que gobierna:
    /// - Confirmación: construye y enviaría el PipeMessage correcto
    /// - Cancelación: no produce ningún envío
    /// - IsExecuting: deshabilita el ítem (IsActionEnabled = false)
    /// - Sin triggers: debe indicar mensaje vacío
    /// 
    /// Requirements: 4.3, 4.4, 4.5, 4.7
    /// </summary>
    [TestFixture]
    [Category("Feature: on-demand-triggers, Unit: StatusForm OnDemand")]
    public class StatusFormOnDemandTests
    {
        #region Lógica extraída para testing

        /// <summary>
        /// Simula la decisión de ejecución en el Status Form:
        /// si el usuario confirma, se construye el PipeMessage; si cancela, retorna null.
        /// Equivale a la lógica en ExecuteOnDemandTriggerAsync del StatusForm.
        /// </summary>
        internal static PipeMessage? BuildExecutionMessage(string triggerLabel, bool userConfirmed)
        {
            if (!userConfirmed)
                return null;

            var payload = new ExecuteOnDemandTriggerPayload { Label = triggerLabel };
            return PipeMessage.Create(MessageType.ExecuteOnDemandTrigger, payload);
        }

        /// <summary>
        /// Determina si debe mostrarse el mensaje "No hay acciones disponibles"
        /// en la sección OnDemand del Status Form.
        /// Validates: Requirement 4.7
        /// </summary>
        internal static bool ShouldShowNoTriggersMessage(List<OnDemandTriggerInfo> triggers)
        {
            return triggers == null || triggers.Count == 0;
        }

        #endregion

        // ═══════════════════════════════════════════════════════════════════════
        // TEST: Confirmar ejecuta envío de pipe message
        // Validates: Requirement 4.3
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Cuando el usuario confirma la ejecución de un trigger OnDemand,
        /// se construye un PipeMessage de tipo ExecuteOnDemandTrigger con el label correcto.
        /// </summary>
        [Test]
        public void Confirmar_ConstruyePipeMessage_ConTipoYLabelCorrectos()
        {
            // Arrange
            string label = "Reiniciar LPMC";
            bool userConfirmed = true;

            // Act
            var message = BuildExecutionMessage(label, userConfirmed);

            // Assert
            Assert.IsNotNull(message,
                "Al confirmar, debe generarse un PipeMessage.");
            Assert.AreEqual(MessageType.ExecuteOnDemandTrigger, message!.Type,
                "El tipo de mensaje debe ser ExecuteOnDemandTrigger.");

            var payload = message.GetPayload<ExecuteOnDemandTriggerPayload>();
            Assert.IsNotNull(payload,
                "El mensaje debe contener un payload ExecuteOnDemandTriggerPayload.");
            Assert.AreEqual("Reiniciar LPMC", payload!.Label,
                "El payload debe contener el label del trigger seleccionado.");
        }

        /// <summary>
        /// El PipeMessage generado al confirmar contiene un ID único y timestamp.
        /// </summary>
        [Test]
        public void Confirmar_PipeMessage_TieneIdYTimestamp()
        {
            // Act
            var message = BuildExecutionMessage("Limpiar Cache", userConfirmed: true);

            // Assert
            Assert.IsNotNull(message);
            Assert.IsNotNull(message!.Id,
                "El mensaje debe tener un ID único.");
            Assert.IsNotEmpty(message.Id,
                "El ID no debe estar vacío.");
            Assert.That(message.Timestamp, Is.Not.EqualTo(default(System.DateTime)),
                "El timestamp debe estar establecido.");
        }

        /// <summary>
        /// El payload del PipeMessage es serializable y contiene exactamente el label esperado.
        /// </summary>
        [Test]
        public void Confirmar_PayloadSerializable_ConLabelExacto()
        {
            // Arrange
            string label = "Resetear Spooler";

            // Act
            var message = BuildExecutionMessage(label, userConfirmed: true);
            var serialized = message!.Serialize();
            var deserialized = PipeMessage.Deserialize(serialized);
            var payload = deserialized!.GetPayload<ExecuteOnDemandTriggerPayload>();

            // Assert
            Assert.AreEqual(label, payload!.Label,
                "Tras serialización round-trip, el label debe preservarse exactamente.");
        }

        /// <summary>
        /// Diferentes labels producen mensajes con payloads distintos.
        /// </summary>
        [TestCase("Reiniciar LPMC")]
        [TestCase("Limpiar Cache Impresión")]
        [TestCase("Resetear Spooler")]
        public void Confirmar_DiferentesLabels_GeneranPayloadCorrecto(string label)
        {
            // Act
            var message = BuildExecutionMessage(label, userConfirmed: true);
            var payload = message!.GetPayload<ExecuteOnDemandTriggerPayload>();

            // Assert
            Assert.AreEqual(label, payload!.Label);
        }

        // ═══════════════════════════════════════════════════════════════════════
        // TEST: Cancelar no envía nada
        // Validates: Requirement 4.4
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Cuando el usuario cancela en el diálogo de confirmación,
        /// no se produce ningún PipeMessage (retorna null = sin acción).
        /// </summary>
        [Test]
        public void Cancelar_NoGeneraMensaje()
        {
            // Arrange
            string label = "Reiniciar LPMC";
            bool userConfirmed = false;

            // Act
            var message = BuildExecutionMessage(label, userConfirmed);

            // Assert
            Assert.IsNull(message,
                "Al cancelar, no debe generarse ningún PipeMessage.");
        }

        /// <summary>
        /// Cancelar no genera mensaje sin importar qué trigger se seleccionó.
        /// </summary>
        [TestCase("Reiniciar LPMC")]
        [TestCase("Limpiar Cache")]
        [TestCase("Resetear Spooler")]
        public void Cancelar_NingunTrigger_GeneraMensaje(string label)
        {
            // Act
            var message = BuildExecutionMessage(label, userConfirmed: false);

            // Assert
            Assert.IsNull(message,
                $"Cancelar para '{label}' no debe generar mensaje.");
        }

        // ═══════════════════════════════════════════════════════════════════════
        // TEST: IsExecuting deshabilita ítem
        // Validates: Requirement 4.5
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Cuando IsExecuting = true, la propiedad IsActionEnabled es false
        /// (el botón de ejecución se deshabilita).
        /// </summary>
        [Test]
        public void IsExecuting_True_IsActionEnabled_False()
        {
            // Arrange
            var item = new OnDemandTriggerItem
            {
                Label = "Reiniciar LPMC",
                Description = "Reinicia el servicio LPMC"
            };

            // Act
            item.IsExecuting = true;

            // Assert
            Assert.IsFalse(item.IsActionEnabled,
                "IsExecuting=true debe producir IsActionEnabled=false (botón deshabilitado).");
        }

        /// <summary>
        /// Cuando IsExecuting = false, la propiedad IsActionEnabled es true
        /// (el botón de ejecución está habilitado).
        /// </summary>
        [Test]
        public void IsExecuting_False_IsActionEnabled_True()
        {
            // Arrange
            var item = new OnDemandTriggerItem
            {
                Label = "Reiniciar LPMC",
                Description = "Reinicia el servicio LPMC"
            };

            // Act
            item.IsExecuting = false;

            // Assert
            Assert.IsTrue(item.IsActionEnabled,
                "IsExecuting=false debe producir IsActionEnabled=true (botón habilitado).");
        }

        /// <summary>
        /// Un ítem recién creado (sin modificar IsExecuting) tiene IsActionEnabled = true.
        /// </summary>
        [Test]
        public void ItemNuevo_IsActionEnabled_True_PorDefecto()
        {
            // Arrange & Act
            var item = new OnDemandTriggerItem
            {
                Label = "Acción",
                Description = "Descripción"
            };

            // Assert
            Assert.IsFalse(item.IsExecuting,
                "Un ítem nuevo debe tener IsExecuting=false por defecto.");
            Assert.IsTrue(item.IsActionEnabled,
                "Un ítem nuevo debe tener IsActionEnabled=true por defecto.");
        }

        /// <summary>
        /// Transición IsExecuting false → true → false rehabilita el ítem correctamente.
        /// Simula el ciclo completo de ejecución de un trigger.
        /// </summary>
        [Test]
        public void IsExecuting_CicloCompleto_RehabilitaItem()
        {
            // Arrange
            var item = new OnDemandTriggerItem
            {
                Label = "Limpiar Cache",
                Description = "Limpia archivos temporales"
            };

            // Assert — estado inicial
            Assert.IsTrue(item.IsActionEnabled, "Inicial: habilitado.");

            // Act — comienza ejecución
            item.IsExecuting = true;
            Assert.IsFalse(item.IsActionEnabled, "Durante ejecución: deshabilitado.");

            // Act — finaliza ejecución
            item.IsExecuting = false;
            Assert.IsTrue(item.IsActionEnabled, "Tras ejecución: rehabilitado.");
        }

        /// <summary>
        /// Cambiar IsExecuting notifica PropertyChanged para IsActionEnabled.
        /// Esto es esencial para que el DataBinding WPF actualice la UI.
        /// </summary>
        [Test]
        public void IsExecuting_NotificaPropertyChanged_ParaIsActionEnabled()
        {
            // Arrange
            var item = new OnDemandTriggerItem
            {
                Label = "Reiniciar LPMC",
                Description = "Reinicia servicio"
            };
            var propertyNames = new List<string>();
            item.PropertyChanged += (sender, e) => propertyNames.Add(e.PropertyName!);

            // Act
            item.IsExecuting = true;

            // Assert — debe notificar tanto IsExecuting como IsActionEnabled
            Assert.Contains("IsExecuting", propertyNames,
                "Debe notificar cambio de IsExecuting.");
            Assert.Contains("IsActionEnabled", propertyNames,
                "Debe notificar cambio de IsActionEnabled para actualizar UI.");
        }

        // ═══════════════════════════════════════════════════════════════════════
        // TEST: Sin triggers muestra mensaje vacío
        // Validates: Requirement 4.7
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Cuando no hay triggers OnDemand configurados, se debe mostrar el mensaje
        /// "No hay acciones disponibles" en la sección.
        /// </summary>
        [Test]
        public void SinTriggers_MuestraMensajeVacio()
        {
            // Arrange — lista vacía
            var triggers = new List<OnDemandTriggerInfo>();

            // Act
            bool shouldShowMessage = ShouldShowNoTriggersMessage(triggers);

            // Assert
            Assert.IsTrue(shouldShowMessage,
                "Sin triggers, debe mostrarse el mensaje 'No hay acciones disponibles'.");
        }

        /// <summary>
        /// Cuando la lista de triggers es null, se muestra el mensaje vacío.
        /// </summary>
        [Test]
        public void TriggersNull_MuestraMensajeVacio()
        {
            // Act
            bool shouldShowMessage = ShouldShowNoTriggersMessage(null!);

            // Assert
            Assert.IsTrue(shouldShowMessage,
                "Con triggers null, debe mostrarse el mensaje de vacío.");
        }

        /// <summary>
        /// Cuando hay al menos un trigger OnDemand, NO se muestra el mensaje vacío.
        /// </summary>
        [Test]
        public void ConTriggers_NoMuestraMensajeVacio()
        {
            // Arrange
            var triggers = new List<OnDemandTriggerInfo>
            {
                new OnDemandTriggerInfo { Label = "Reiniciar LPMC", Description = "Reinicia servicio" }
            };

            // Act
            bool shouldShowMessage = ShouldShowNoTriggersMessage(triggers);

            // Assert
            Assert.IsFalse(shouldShowMessage,
                "Con triggers disponibles, NO debe mostrarse el mensaje de vacío.");
        }

        /// <summary>
        /// Con múltiples triggers, no se muestra el mensaje vacío.
        /// </summary>
        [Test]
        public void MultiplesTriggers_NoMuestraMensajeVacio()
        {
            // Arrange
            var triggers = new List<OnDemandTriggerInfo>
            {
                new OnDemandTriggerInfo { Label = "Reiniciar LPMC", Description = "Reinicia" },
                new OnDemandTriggerInfo { Label = "Limpiar Cache", Description = "Limpia" },
                new OnDemandTriggerInfo { Label = "Resetear Spooler", Description = "Resetea" }
            };

            // Act
            bool shouldShowMessage = ShouldShowNoTriggersMessage(triggers);

            // Assert
            Assert.IsFalse(shouldShowMessage,
                "Con múltiples triggers, NO debe mostrarse el mensaje de vacío.");
        }
    }
}
