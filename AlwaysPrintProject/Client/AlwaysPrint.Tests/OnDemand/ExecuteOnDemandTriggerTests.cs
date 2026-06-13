using System.Collections.Generic;
using NUnit.Framework;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrintService.Actions;
using Newtonsoft.Json;

namespace AlwaysPrint.Tests.OnDemand
{
    /// <summary>
    /// Unit tests para ActionEngine.ExecuteOnDemandTrigger.
    /// Valida búsqueda por label exacto, manejo de errores, y deduplicación.
    /// Requirements: 8.1, 8.2, 8.4, 8.5
    /// </summary>
    [TestFixture]
    [Category("Feature: on-demand-triggers, Unit: ExecuteOnDemandTrigger")]
    public class ExecuteOnDemandTriggerTests
    {
        private ActionEngine _engine = null!;

        [SetUp]
        public void SetUp()
        {
            _engine = new ActionEngine();
        }

        /// <summary>
        /// Helper: carga una configuración JSON en el engine para testing.
        /// </summary>
        private void LoadConfig(ActionConfiguration config)
        {
            var json = JsonConvert.SerializeObject(config);
            _engine.LoadConfigurationFromString(json);
        }

        /// <summary>
        /// Crea una configuración con triggers OnDemand usando acciones vacías
        /// para evitar efectos secundarios en tests unitarios.
        /// </summary>
        private ActionConfiguration CreateConfigWithOnDemandTriggers(
            params (string label, string description)[] triggers)
        {
            var config = new ActionConfiguration
            {
                Name = "TestConfig",
                Version = "1.0",
                Triggers = new List<TriggerConfig>()
            };

            foreach (var (label, description) in triggers)
            {
                config.Triggers.Add(new TriggerConfig
                {
                    Event = "OnDemand",
                    Label = label,
                    Description = description,
                    Actions = new List<ActionConfig>() // acciones vacías = ejecución exitosa
                });
            }

            return config;
        }

        // ═══════════════════════════════════════════════════════════════════════
        // TEST: Label existente ejecuta acciones correctas
        // Validates: Requirement 8.1
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Cuando se ejecuta un trigger con un label que existe en la configuración,
        /// el método retorna success=true y un mensaje indicando ejecución correcta.
        /// </summary>
        [Test]
        public void ExecuteOnDemandTrigger_LabelExistente_RetornaExito()
        {
            // Arrange — config con un trigger OnDemand válido (acciones vacías = éxito)
            var config = CreateConfigWithOnDemandTriggers(
                ("Reiniciar LPMC", "Reinicia el servicio LPMC"));
            LoadConfig(config);

            // Act
            var (success, message) = _engine.ExecuteOnDemandTrigger("Reiniciar LPMC");

            // Assert
            Assert.IsTrue(success,
                "Un trigger con label existente y acciones vacías debe retornar success=true.");
            Assert.That(message, Does.Contain("Reiniciar LPMC"),
                "El mensaje de éxito debe contener el label del trigger ejecutado.");
            Assert.That(message, Does.Contain("ejecutado correctamente"),
                "El mensaje debe indicar ejecución correcta.");
        }

        /// <summary>
        /// Verifica que la búsqueda por label es case-sensitive (comparación Ordinal).
        /// "reiniciar lpmc" NO debe encontrar "Reiniciar LPMC".
        /// </summary>
        [Test]
        public void ExecuteOnDemandTrigger_LabelCaseSensitive_NoEncuentraSiDifiere()
        {
            // Arrange
            var config = CreateConfigWithOnDemandTriggers(
                ("Reiniciar LPMC", "Reinicia el servicio LPMC"));
            LoadConfig(config);

            // Act — buscar con case diferente
            var (success, message) = _engine.ExecuteOnDemandTrigger("reiniciar lpmc");

            // Assert — no debe encontrarlo (comparación Ordinal)
            Assert.IsFalse(success,
                "La búsqueda por label debe ser case-sensitive (Ordinal).");
            Assert.That(message, Does.Contain("no encontrado"),
                "El mensaje debe indicar que no se encontró el trigger.");
        }

        /// <summary>
        /// Cuando hay múltiples triggers OnDemand, se ejecuta exactamente el solicitado.
        /// </summary>
        [Test]
        public void ExecuteOnDemandTrigger_MultiplesTriggersOnDemand_EjecutaElSolicitado()
        {
            // Arrange — config con varios triggers OnDemand
            var config = CreateConfigWithOnDemandTriggers(
                ("Reiniciar LPMC", "Reinicia el servicio LPMC"),
                ("Limpiar Cache", "Limpia archivos temporales"),
                ("Reiniciar Spooler", "Reinicia el servicio de impresión"));
            LoadConfig(config);

            // Act
            var (success, message) = _engine.ExecuteOnDemandTrigger("Limpiar Cache");

            // Assert
            Assert.IsTrue(success,
                "Debe ejecutar exitosamente el trigger con label 'Limpiar Cache'.");
            Assert.That(message, Does.Contain("Limpiar Cache"),
                "El mensaje debe referenciar el label ejecutado.");
        }

        // ═══════════════════════════════════════════════════════════════════════
        // TEST: Label inexistente retorna error
        // Validates: Requirement 8.2
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Cuando se solicita un label que no existe en ningún trigger OnDemand,
        /// el método retorna success=false con mensaje de error indicando que no fue encontrado.
        /// </summary>
        [Test]
        public void ExecuteOnDemandTrigger_LabelInexistente_RetornaError()
        {
            // Arrange — config con triggers pero sin el label buscado
            var config = CreateConfigWithOnDemandTriggers(
                ("Reiniciar LPMC", "Reinicia el servicio LPMC"),
                ("Limpiar Cache", "Limpia archivos temporales"));
            LoadConfig(config);

            // Act
            var (success, message) = _engine.ExecuteOnDemandTrigger("Trigger Inexistente");

            // Assert
            Assert.IsFalse(success,
                "Un label inexistente debe retornar success=false.");
            Assert.That(message, Does.Contain("no encontrado"),
                "El mensaje debe indicar que el trigger no fue encontrado.");
            Assert.That(message, Does.Contain("Trigger Inexistente"),
                "El mensaje de error debe incluir el label buscado.");
        }

        /// <summary>
        /// Cuando la configuración no tiene ningún trigger OnDemand, un label cualquiera
        /// retorna error de no encontrado.
        /// </summary>
        [Test]
        public void ExecuteOnDemandTrigger_SinTriggersOnDemand_RetornaError()
        {
            // Arrange — config con triggers de otro tipo pero sin OnDemand
            var config = new ActionConfiguration
            {
                Name = "TestConfig",
                Version = "1.0",
                Triggers = new List<TriggerConfig>
                {
                    new TriggerConfig
                    {
                        Event = "OnTrayLaunched",
                        Label = "Reiniciar LPMC", // mismo label pero evento diferente
                        Description = "Trigger de tray",
                        Actions = new List<ActionConfig>()
                    }
                }
            };
            LoadConfig(config);

            // Act
            var (success, message) = _engine.ExecuteOnDemandTrigger("Reiniciar LPMC");

            // Assert — no debe encontrarlo porque el evento no es OnDemand
            Assert.IsFalse(success,
                "Un label que existe solo en triggers no-OnDemand no debe ejecutarse.");
            Assert.That(message, Does.Contain("no encontrado"),
                "El mensaje debe indicar que el trigger OnDemand no fue encontrado.");
        }

        // ═══════════════════════════════════════════════════════════════════════
        // TEST: Labels duplicados ejecuta primero y loguea warning
        // Validates: Requirement 8.5
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Cuando existen múltiples triggers OnDemand con el mismo label,
        /// se ejecuta el primero encontrado en el array (retorna éxito).
        /// El warning se registra en el log (efecto secundario no verificable sin mock).
        /// </summary>
        [Test]
        public void ExecuteOnDemandTrigger_LabelsDuplicados_EjecutaPrimeroConExito()
        {
            // Arrange — config con dos triggers que comparten el mismo label
            var config = new ActionConfiguration
            {
                Name = "TestConfig",
                Version = "1.0",
                Triggers = new List<TriggerConfig>
                {
                    new TriggerConfig
                    {
                        Event = "OnDemand",
                        Label = "Reiniciar LPMC",
                        Description = "Primera versión del trigger",
                        Actions = new List<ActionConfig>() // acciones vacías = éxito
                    },
                    new TriggerConfig
                    {
                        Event = "OnDemand",
                        Label = "Reiniciar LPMC",
                        Description = "Segunda versión (duplicada)",
                        Actions = new List<ActionConfig>() // también éxito, pero no debería ejecutarse
                    }
                }
            };
            LoadConfig(config);

            // Act
            var (success, message) = _engine.ExecuteOnDemandTrigger("Reiniciar LPMC");

            // Assert — debe ejecutar exitosamente (el primero encontrado)
            Assert.IsTrue(success,
                "Con labels duplicados, debe ejecutar el primer trigger exitosamente.");
            Assert.That(message, Does.Contain("Reiniciar LPMC"),
                "El mensaje debe referenciar el label ejecutado.");
            Assert.That(message, Does.Contain("ejecutado correctamente"),
                "Aun con duplicados, la ejecución del primero debe ser exitosa.");
            // Nota: el warning se loguea en AlwaysPrintLogger.WriteWarning pero no es
            // verificable en unit test sin inyección de dependencias del logger.
        }

        /// <summary>
        /// Verifica que con labels duplicados, es el PRIMER trigger en el array
        /// el que se ejecuta (preserva orden del JSON original).
        /// Usamos una acción inválida en el segundo para confirmar que no se ejecuta.
        /// </summary>
        [Test]
        public void ExecuteOnDemandTrigger_LabelsDuplicados_PrimeroEnArrayGana()
        {
            // Arrange — primer trigger con acciones vacías (éxito),
            // segundo con acción de tipo desconocido que fallaría
            var config = new ActionConfiguration
            {
                Name = "TestConfig",
                Version = "1.0",
                Triggers = new List<TriggerConfig>
                {
                    new TriggerConfig
                    {
                        Event = "OnDemand",
                        Label = "MiAccion",
                        Description = "Primero — acciones vacías (exitoso)",
                        Actions = new List<ActionConfig>() // vacío = success
                    },
                    new TriggerConfig
                    {
                        Event = "OnDemand",
                        Label = "MiAccion",
                        Description = "Segundo — tiene acción inválida (fallaría)",
                        Actions = new List<ActionConfig>
                        {
                            new ActionConfig
                            {
                                Type = "TipoInvalido_NoExiste",
                                Description = "Acción que fallaría si se ejecuta"
                            }
                        }
                    }
                }
            };
            LoadConfig(config);

            // Act
            var (success, message) = _engine.ExecuteOnDemandTrigger("MiAccion");

            // Assert — el primero (vacío) debe ejecutarse con éxito
            Assert.IsTrue(success,
                "Se debe ejecutar el primer trigger (acciones vacías = éxito), no el segundo.");
        }

        // ═══════════════════════════════════════════════════════════════════════
        // TEST: Config no cargada retorna error
        // Validates: Requirement 8.4
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Cuando no se ha cargado configuración (config == null),
        /// el método retorna success=false con mensaje indicando ausencia de configuración.
        /// </summary>
        [Test]
        public void ExecuteOnDemandTrigger_ConfigNoCargada_RetornaError()
        {
            // Arrange — engine recién creado sin LoadConfiguration
            // (_config es null internamente)

            // Act
            var (success, message) = _engine.ExecuteOnDemandTrigger("Cualquier Label");

            // Assert
            Assert.IsFalse(success,
                "Sin configuración cargada, debe retornar success=false.");
            Assert.That(message, Does.Contain("No hay configuración cargada"),
                "El mensaje debe indicar que no hay configuración cargada.");
        }

        /// <summary>
        /// Incluso con un label vacío, si no hay config cargada,
        /// el error de "config no cargada" tiene prioridad.
        /// </summary>
        [Test]
        public void ExecuteOnDemandTrigger_ConfigNoCargada_PrioridadSobreOtrosErrores()
        {
            // Arrange — sin configuración cargada

            // Act
            var (success, message) = _engine.ExecuteOnDemandTrigger("");

            // Assert — el error de config no cargada tiene prioridad
            Assert.IsFalse(success);
            Assert.That(message, Does.Contain("No hay configuración cargada"),
                "El error 'config no cargada' debe tener prioridad sobre cualquier validación de label.");
        }
    }
}
