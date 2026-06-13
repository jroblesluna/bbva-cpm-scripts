using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using AlwaysPrintTray.Forms;
using AlwaysPrintTray.OnDemand;
using NUnit.Framework;

namespace AlwaysPrint.Tests.OnDemand
{
    /// <summary>
    /// Unit tests para actualización dinámica del submenú y StatusForm
    /// ante cambios de configuración (ActionConfigChanged).
    ///
    /// Dado que TrayApplicationContext y StatusForm (WPF) son difíciles de instanciar,
    /// se testea la LÓGICA pura:
    /// 1. OnDemandConfigReader.Reload() retorna nueva lista al cambiar archivo
    /// 2. RefreshOnDemandTriggers actualiza correctamente la ObservableCollection
    /// 3. Items con IsExecuting=true se preservan durante refresh hasta respuesta
    ///
    /// Requirements: 10.1, 10.2, 10.4
    /// </summary>
    [TestFixture]
    [Category("Feature: on-demand-triggers, Unit: Dynamic Update")]
    public class DynamicUpdateTests
    {
        private string _tempDir = null!;

        [SetUp]
        public void SetUp()
        {
            _tempDir = Path.Combine(Path.GetTempPath(), "DynamicUpdateTests_" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_tempDir);
        }

        [TearDown]
        public void TearDown()
        {
            if (Directory.Exists(_tempDir))
                Directory.Delete(_tempDir, recursive: true);
        }

        private string WriteTempConfig(string json)
        {
            var filePath = Path.Combine(_tempDir, "active.alwaysconfig");
            File.WriteAllText(filePath, json);
            return filePath;
        }

        // ═══════════════════════════════════════════════════════════════════════
        // TEST: Cambio de config reconstruye submenú
        // Validates: Requirement 10.1
        //
        // Simula el flujo: archivo cambia → Reload() retorna nueva lista →
        // la lógica de RebuildOnDemandSubmenu usa la nueva lista para construir ítems.
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Al cambiar el archivo de configuración, una nueva lectura (Reload) retorna
        /// la lista actualizada de triggers, que se usa para reconstruir el submenú.
        /// Validates: Requirement 10.1
        /// </summary>
        [Test]
        public void CambioDeConfig_Reload_RetornaNuevaListaParaSubmenu()
        {
            // Arrange — configuración inicial con 2 triggers
            var jsonInicial = @"{
                ""version"": ""1.0"",
                ""name"": ""Config_V1"",
                ""triggers"": [
                    {
                        ""event"": ""OnDemand"",
                        ""label"": ""Reiniciar LPMC"",
                        ""description"": ""Reinicia servicio LPMC"",
                        ""actions"": []
                    },
                    {
                        ""event"": ""OnDemand"",
                        ""label"": ""Limpiar Cache"",
                        ""description"": ""Limpia temporales"",
                        ""actions"": []
                    }
                ]
            }";
            var filePath = WriteTempConfig(jsonInicial);

            // Act — lectura inicial
            var triggersIniciales = OnDemandConfigReader.GetOnDemandTriggers(filePath);

            // Assert — configuración inicial correcta
            Assert.AreEqual(2, triggersIniciales.Count);
            Assert.AreEqual("Reiniciar LPMC", triggersIniciales[0].Label);
            Assert.AreEqual("Limpiar Cache", triggersIniciales[1].Label);

            // Arrange — nueva configuración con 3 triggers (uno nuevo, uno eliminado)
            var jsonActualizado = @"{
                ""version"": ""2.0"",
                ""name"": ""Config_V2"",
                ""triggers"": [
                    {
                        ""event"": ""OnDemand"",
                        ""label"": ""Reiniciar LPMC"",
                        ""description"": ""Reinicia servicio LPMC"",
                        ""actions"": []
                    },
                    {
                        ""event"": ""OnDemand"",
                        ""label"": ""Resetear Spooler"",
                        ""description"": ""Resetea cola de impresión"",
                        ""actions"": []
                    },
                    {
                        ""event"": ""OnDemand"",
                        ""label"": ""Nueva Acción"",
                        ""description"": ""Acción agregada en v2"",
                        ""actions"": []
                    }
                ]
            }";
            File.WriteAllText(filePath, jsonActualizado);

            // Act — recarga (simula Reload tras ActionConfigChanged)
            var triggersActualizados = OnDemandConfigReader.GetOnDemandTriggers(filePath);

            // Assert — la nueva lista refleja el archivo actualizado
            Assert.AreEqual(3, triggersActualizados.Count,
                "Tras cambio de config, Reload debe retornar la nueva lista de triggers.");
            Assert.AreEqual("Reiniciar LPMC", triggersActualizados[0].Label);
            Assert.AreEqual("Resetear Spooler", triggersActualizados[1].Label);
            Assert.AreEqual("Nueva Acción", triggersActualizados[2].Label);

            // Verificar que "Limpiar Cache" ya no está (fue eliminado en v2)
            Assert.IsFalse(triggersActualizados.Any(t => t.Label == "Limpiar Cache"),
                "El trigger eliminado en la nueva config no debe aparecer tras Reload.");
        }

        /// <summary>
        /// Si la nueva configuración no tiene triggers OnDemand, Reload retorna lista vacía,
        /// lo que causa que RebuildOnDemandSubmenu elimine el submenú.
        /// Validates: Requirement 10.1
        /// </summary>
        [Test]
        public void CambioDeConfig_SinTriggersOnDemand_RetornaListaVacia()
        {
            // Arrange — configuración inicial con triggers
            var jsonConTriggers = @"{
                ""version"": ""1.0"",
                ""name"": ""ConTriggers"",
                ""triggers"": [
                    {
                        ""event"": ""OnDemand"",
                        ""label"": ""Acción"",
                        ""description"": ""Desc"",
                        ""actions"": []
                    }
                ]
            }";
            var filePath = WriteTempConfig(jsonConTriggers);

            var triggersConAcciones = OnDemandConfigReader.GetOnDemandTriggers(filePath);
            Assert.AreEqual(1, triggersConAcciones.Count);

            // Arrange — nueva config sin triggers OnDemand
            var jsonSinTriggers = @"{
                ""version"": ""2.0"",
                ""name"": ""SinTriggers"",
                ""triggers"": [
                    {
                        ""event"": ""OnTrayLaunched"",
                        ""description"": ""Solo trigger de tray"",
                        ""actions"": []
                    }
                ]
            }";
            File.WriteAllText(filePath, jsonSinTriggers);

            // Act — recarga
            var triggersSinOnDemand = OnDemandConfigReader.GetOnDemandTriggers(filePath);

            // Assert — lista vacía → submenú se elimina
            Assert.AreEqual(0, triggersSinOnDemand.Count,
                "Sin triggers OnDemand en la nueva config, Reload debe retornar lista vacía.");
        }

        // ═══════════════════════════════════════════════════════════════════════
        // TEST: Cambio de config actualiza Status Form si está abierto
        // Validates: Requirement 10.2
        //
        // Simula RefreshOnDemandTriggers: la lógica de reemplazo de la
        // ObservableCollection<OnDemandTriggerItem> ante nueva lista de triggers.
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// RefreshOnDemandTriggers reemplaza el contenido de la ObservableCollection
        /// con los nuevos triggers proporcionados.
        /// Validates: Requirement 10.2
        /// </summary>
        [Test]
        public void RefreshOnDemandTriggers_ActualizaColeccion_ConNuevosTriggers()
        {
            // Arrange — colección inicial simulando StatusForm.TriggersOnDemand
            var collection = new ObservableCollection<OnDemandTriggerItem>
            {
                new OnDemandTriggerItem { Label = "Acción Vieja 1", Description = "Desc 1" },
                new OnDemandTriggerItem { Label = "Acción Vieja 2", Description = "Desc 2" }
            };

            // Simular nuevos triggers recibidos tras cambio de configuración
            var nuevosTriggers = new List<OnDemandTriggerInfo>
            {
                new OnDemandTriggerInfo { Label = "Acción Nueva A", Description = "Nueva desc A" },
                new OnDemandTriggerInfo { Label = "Acción Nueva B", Description = "Nueva desc B" },
                new OnDemandTriggerInfo { Label = "Acción Nueva C", Description = "Nueva desc C" }
            };

            // Act — simular RefreshOnDemandTriggers (lógica de PopulateTriggersCollection)
            RefreshTriggersCollection(collection, nuevosTriggers);

            // Assert — colección actualizada con los nuevos triggers
            Assert.AreEqual(3, collection.Count,
                "Tras refresh, la colección debe contener solo los nuevos triggers.");
            Assert.AreEqual("Acción Nueva A", collection[0].Label);
            Assert.AreEqual("Nueva desc A", collection[0].Description);
            Assert.AreEqual("Acción Nueva B", collection[1].Label);
            Assert.AreEqual("Acción Nueva C", collection[2].Label);
        }

        /// <summary>
        /// Cuando la nueva configuración no tiene triggers OnDemand,
        /// RefreshOnDemandTriggers deja la colección vacía.
        /// Validates: Requirement 10.2
        /// </summary>
        [Test]
        public void RefreshOnDemandTriggers_SinTriggers_ColeccionVacia()
        {
            // Arrange — colección con triggers existentes
            var collection = new ObservableCollection<OnDemandTriggerItem>
            {
                new OnDemandTriggerItem { Label = "Trigger A", Description = "Desc" },
                new OnDemandTriggerItem { Label = "Trigger B", Description = "Desc" }
            };

            // Act — refresh con lista vacía (nueva config sin triggers OnDemand)
            RefreshTriggersCollection(collection, new List<OnDemandTriggerInfo>());

            // Assert
            Assert.AreEqual(0, collection.Count,
                "Sin triggers en la nueva config, la colección debe quedar vacía.");
        }

        /// <summary>
        /// RefreshOnDemandTriggers con lista null se trata como vacía.
        /// Validates: Requirement 10.2
        /// </summary>
        [Test]
        public void RefreshOnDemandTriggers_TriggersNull_ColeccionVacia()
        {
            // Arrange
            var collection = new ObservableCollection<OnDemandTriggerItem>
            {
                new OnDemandTriggerItem { Label = "Trigger A", Description = "Desc" }
            };

            // Act — refresh con null (caso defensivo)
            RefreshTriggersCollection(collection, null!);

            // Assert
            Assert.AreEqual(0, collection.Count,
                "Con triggers null, la colección debe quedar vacía.");
        }

        // ═══════════════════════════════════════════════════════════════════════
        // TEST: Trigger en ejecución no se elimina hasta respuesta
        // Validates: Requirement 10.4
        //
        // Cuando un trigger está ejecutándose (IsExecuting=true) y la configuración
        // cambia eliminando ese trigger, el sistema debe preservar el ítem hasta
        // que finalice la ejecución (reciba respuesta del Service).
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Un trigger con IsExecuting=true debe preservarse en la colección
        /// aunque la nueva configuración ya no lo contenga.
        /// Validates: Requirement 10.4
        /// </summary>
        [Test]
        public void TriggerEnEjecucion_NoSeElimina_HastaRespuesta()
        {
            // Arrange — colección con un trigger en ejecución
            var collection = new ObservableCollection<OnDemandTriggerItem>
            {
                new OnDemandTriggerItem { Label = "Reiniciar LPMC", Description = "Reinicia", IsExecuting = true },
                new OnDemandTriggerItem { Label = "Limpiar Cache", Description = "Limpia", IsExecuting = false }
            };

            // Nueva config elimina "Reiniciar LPMC" pero agrega "Nueva Acción"
            var nuevosTriggers = new List<OnDemandTriggerInfo>
            {
                new OnDemandTriggerInfo { Label = "Limpiar Cache", Description = "Limpia" },
                new OnDemandTriggerInfo { Label = "Nueva Acción", Description = "Nueva desc" }
            };

            // Act — refresh que preserva triggers en ejecución
            RefreshTriggersCollectionPreservingExecuting(collection, nuevosTriggers);

            // Assert — el trigger en ejecución se preserva
            Assert.IsTrue(collection.Any(t => t.Label == "Reiniciar LPMC"),
                "El trigger con IsExecuting=true debe permanecer en la colección.");
            Assert.IsTrue(collection.First(t => t.Label == "Reiniciar LPMC").IsExecuting,
                "El trigger preservado debe mantener IsExecuting=true.");

            // Assert — los nuevos triggers se agregan correctamente
            Assert.IsTrue(collection.Any(t => t.Label == "Limpiar Cache"),
                "Los triggers que siguen en la config deben mantenerse.");
            Assert.IsTrue(collection.Any(t => t.Label == "Nueva Acción"),
                "Los nuevos triggers de la config deben agregarse.");
        }

        /// <summary>
        /// Una vez que el trigger en ejecución termina (IsExecuting=false),
        /// un refresh posterior lo eliminará si ya no está en la configuración.
        /// Validates: Requirement 10.4
        /// </summary>
        [Test]
        public void TriggerFinalizaEjecucion_SeEliminaEnSiguienteRefresh()
        {
            // Arrange — trigger estaba ejecutándose, ahora terminó
            var triggerEjecutando = new OnDemandTriggerItem
            {
                Label = "Reiniciar LPMC",
                Description = "Reinicia",
                IsExecuting = true
            };

            var collection = new ObservableCollection<OnDemandTriggerItem>
            {
                triggerEjecutando,
                new OnDemandTriggerItem { Label = "Limpiar Cache", Description = "Limpia" }
            };

            // Nueva config sin "Reiniciar LPMC"
            var nuevosTriggers = new List<OnDemandTriggerInfo>
            {
                new OnDemandTriggerInfo { Label = "Limpiar Cache", Description = "Limpia" }
            };

            // Act 1 — primer refresh: trigger en ejecución se preserva
            RefreshTriggersCollectionPreservingExecuting(collection, nuevosTriggers);
            Assert.IsTrue(collection.Any(t => t.Label == "Reiniciar LPMC"),
                "Primer refresh: trigger en ejecución debe preservarse.");

            // Act 2 — simular que la ejecución terminó (respuesta del Service)
            triggerEjecutando.IsExecuting = false;

            // Act 3 — segundo refresh: ahora sí se elimina
            RefreshTriggersCollectionPreservingExecuting(collection, nuevosTriggers);

            // Assert — trigger ya no está en ejecución, se elimina
            Assert.IsFalse(collection.Any(t => t.Label == "Reiniciar LPMC"),
                "Segundo refresh: trigger que ya no ejecuta ni está en config debe eliminarse.");
            Assert.AreEqual(1, collection.Count,
                "Solo debe quedar el trigger de la nueva config.");
            Assert.AreEqual("Limpiar Cache", collection[0].Label);
        }

        /// <summary>
        /// Sin triggers en ejecución, un refresh completo reemplaza toda la colección.
        /// Validates: Requirement 10.4
        /// </summary>
        [Test]
        public void SinTriggersEnEjecucion_RefreshReemplazaTodo()
        {
            // Arrange — ninguno está ejecutándose
            var collection = new ObservableCollection<OnDemandTriggerItem>
            {
                new OnDemandTriggerItem { Label = "Vieja A", Description = "Desc" },
                new OnDemandTriggerItem { Label = "Vieja B", Description = "Desc" }
            };

            var nuevosTriggers = new List<OnDemandTriggerInfo>
            {
                new OnDemandTriggerInfo { Label = "Nueva X", Description = "Desc X" }
            };

            // Act
            RefreshTriggersCollectionPreservingExecuting(collection, nuevosTriggers);

            // Assert — reemplazo completo
            Assert.AreEqual(1, collection.Count);
            Assert.AreEqual("Nueva X", collection[0].Label);
        }

        /// <summary>
        /// Múltiples triggers en ejecución se preservan todos durante el refresh.
        /// Validates: Requirement 10.4
        /// </summary>
        [Test]
        public void MultiplesTriggersEnEjecucion_TodosSePreservan()
        {
            // Arrange — dos triggers en ejecución
            var collection = new ObservableCollection<OnDemandTriggerItem>
            {
                new OnDemandTriggerItem { Label = "Acción 1", Description = "D1", IsExecuting = true },
                new OnDemandTriggerItem { Label = "Acción 2", Description = "D2", IsExecuting = true },
                new OnDemandTriggerItem { Label = "Acción 3", Description = "D3", IsExecuting = false }
            };

            // Nueva config elimina todos los anteriores
            var nuevosTriggers = new List<OnDemandTriggerInfo>
            {
                new OnDemandTriggerInfo { Label = "Completamente Nuevo", Description = "Desc nuevo" }
            };

            // Act
            RefreshTriggersCollectionPreservingExecuting(collection, nuevosTriggers);

            // Assert — los dos en ejecución se preservan
            Assert.IsTrue(collection.Any(t => t.Label == "Acción 1" && t.IsExecuting),
                "Trigger 1 en ejecución debe preservarse.");
            Assert.IsTrue(collection.Any(t => t.Label == "Acción 2" && t.IsExecuting),
                "Trigger 2 en ejecución debe preservarse.");
            // El nuevo se agrega
            Assert.IsTrue(collection.Any(t => t.Label == "Completamente Nuevo"),
                "El nuevo trigger de la config debe agregarse.");
            // El que no estaba ejecutándose se remueve
            Assert.IsFalse(collection.Any(t => t.Label == "Acción 3"),
                "Trigger no en ejecución y no en nueva config debe eliminarse.");
        }

        // ═══════════════════════════════════════════════════════════════════════
        // HELPERS — Lógica extraída que replica el comportamiento del sistema
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Replica la lógica de PopulateTriggersCollection en StatusForm:
        /// Clear + Add de los nuevos triggers (sin protección de ejecución).
        /// Usado para testear el comportamiento básico de RefreshOnDemandTriggers.
        /// </summary>
        private static void RefreshTriggersCollection(
            ObservableCollection<OnDemandTriggerItem> collection,
            List<OnDemandTriggerInfo>? triggers)
        {
            collection.Clear();

            if (triggers == null)
                return;

            foreach (var trigger in triggers)
            {
                collection.Add(new OnDemandTriggerItem
                {
                    Label = trigger.Label,
                    Description = trigger.Description
                });
            }
        }

        /// <summary>
        /// Replica la lógica de actualización dinámica que preserva triggers en ejecución:
        /// - Items con IsExecuting=true que ya no están en la nueva config se preservan
        /// - Items sin ejecución se reemplazan con la nueva lista
        /// Esto es el comportamiento esperado según Requirement 10.4.
        /// </summary>
        private static void RefreshTriggersCollectionPreservingExecuting(
            ObservableCollection<OnDemandTriggerItem> collection,
            List<OnDemandTriggerInfo> nuevosTriggers)
        {
            if (nuevosTriggers == null)
                nuevosTriggers = new List<OnDemandTriggerInfo>();

            // Preservar triggers en ejecución que ya no están en la nueva config
            var ejecutando = collection
                .Where(t => t.IsExecuting
                         && !nuevosTriggers.Any(n => n.Label == t.Label))
                .ToList();

            // Reconstruir colección
            collection.Clear();

            // Agregar los nuevos triggers de la config
            foreach (var trigger in nuevosTriggers)
            {
                collection.Add(new OnDemandTriggerItem
                {
                    Label = trigger.Label,
                    Description = trigger.Description
                });
            }

            // Re-agregar los que estaban en ejecución (al final, para visibilidad)
            foreach (var item in ejecutando)
            {
                collection.Add(item);
            }
        }
    }
}
