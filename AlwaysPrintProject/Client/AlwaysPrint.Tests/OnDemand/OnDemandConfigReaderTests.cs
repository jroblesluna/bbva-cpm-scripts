using System;
using System.Collections.Generic;
using System.IO;
using NUnit.Framework;
using AlwaysPrintTray.OnDemand;

namespace AlwaysPrint.Tests.OnDemand
{
    /// <summary>
    /// Unit tests para OnDemandConfigReader.
    /// Valida manejo de errores (archivo inexistente, JSON inválido)
    /// y filtrado correcto de triggers OnDemand.
    /// Requirements: 11.3, 11.4, 5.5
    /// </summary>
    [TestFixture]
    [Category("Feature: on-demand-triggers, Unit: OnDemandConfigReader")]
    public class OnDemandConfigReaderTests
    {
        private string _tempDir = null!;

        [SetUp]
        public void SetUp()
        {
            _tempDir = Path.Combine(Path.GetTempPath(), "OnDemandConfigReaderTests_" + Guid.NewGuid().ToString("N"));
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
            var filePath = Path.Combine(_tempDir, "test.alwaysconfig");
            File.WriteAllText(filePath, json);
            return filePath;
        }

        /// <summary>
        /// Archivo inexistente retorna lista vacía.
        /// Validates: Requirement 11.3
        /// </summary>
        [Test]
        public void GetOnDemandTriggers_ArchivoInexistente_RetornaListaVacia()
        {
            // Arrange
            var rutaInexistente = Path.Combine(_tempDir, "no_existe.alwaysconfig");

            // Act
            var resultado = OnDemandConfigReader.GetOnDemandTriggers(rutaInexistente);

            // Assert
            Assert.IsNotNull(resultado);
            Assert.AreEqual(0, resultado.Count);
        }

        /// <summary>
        /// JSON inválido retorna lista vacía.
        /// Validates: Requirement 11.3
        /// </summary>
        [Test]
        public void GetOnDemandTriggers_JsonInvalido_RetornaListaVacia()
        {
            // Arrange
            var filePath = WriteTempConfig("{ esto no es json válido !!!");

            // Act
            var resultado = OnDemandConfigReader.GetOnDemandTriggers(filePath);

            // Assert
            Assert.IsNotNull(resultado);
            Assert.AreEqual(0, resultado.Count);
        }

        /// <summary>
        /// Triggers sin campo label se omiten del resultado.
        /// Validates: Requirement 11.4, 5.5
        /// </summary>
        [Test]
        public void GetOnDemandTriggers_TriggersSinLabel_SeOmiten()
        {
            // Arrange — trigger OnDemand sin campo label (null)
            var json = @"{
                ""version"": ""1.0"",
                ""name"": ""Test"",
                ""triggers"": [
                    {
                        ""event"": ""OnDemand"",
                        ""description"": ""Trigger sin label"",
                        ""actions"": []
                    }
                ]
            }";
            var filePath = WriteTempConfig(json);

            // Act
            var resultado = OnDemandConfigReader.GetOnDemandTriggers(filePath);

            // Assert
            Assert.IsNotNull(resultado);
            Assert.AreEqual(0, resultado.Count);
        }

        /// <summary>
        /// Triggers con label vacío o whitespace se omiten del resultado.
        /// Validates: Requirement 11.4, 5.5
        /// </summary>
        [TestCase("")]
        [TestCase("   ")]
        [TestCase("\t")]
        [TestCase("\n")]
        public void GetOnDemandTriggers_LabelVacioOWhitespace_SeOmiten(string labelVacio)
        {
            // Arrange
            var json = $@"{{
                ""version"": ""1.0"",
                ""name"": ""Test"",
                ""triggers"": [
                    {{
                        ""event"": ""OnDemand"",
                        ""label"": ""{EscapeJsonString(labelVacio)}"",
                        ""description"": ""Trigger con label vacío"",
                        ""actions"": []
                    }}
                ]
            }}";
            var filePath = WriteTempConfig(json);

            // Act
            var resultado = OnDemandConfigReader.GetOnDemandTriggers(filePath);

            // Assert
            Assert.IsNotNull(resultado);
            Assert.AreEqual(0, resultado.Count);
        }

        /// <summary>
        /// Solo triggers con event="OnDemand" se incluyen; otros eventos se excluyen.
        /// Validates: Requirement 11.4
        /// </summary>
        [Test]
        public void GetOnDemandTriggers_SoloTriggersOnDemand_OtrosEventosExcluidos()
        {
            // Arrange — mezcla de eventos, solo los OnDemand con label válido deben incluirse
            var json = @"{
                ""version"": ""2.0"",
                ""name"": ""MixedConfig"",
                ""triggers"": [
                    {
                        ""event"": ""OnTrayLaunched"",
                        ""label"": ""Este no debería aparecer"",
                        ""description"": ""Trigger de tray"",
                        ""actions"": []
                    },
                    {
                        ""event"": ""OnDemand"",
                        ""label"": ""Reiniciar LPMC"",
                        ""description"": ""Reinicia el servicio LPMC"",
                        ""actions"": []
                    },
                    {
                        ""event"": ""OnConfigChange"",
                        ""label"": ""Tampoco aparece"",
                        ""description"": ""Trigger de config"",
                        ""actions"": []
                    },
                    {
                        ""event"": ""OnDemand"",
                        ""label"": ""Limpiar Cache"",
                        ""description"": ""Limpia archivos temporales"",
                        ""actions"": []
                    },
                    {
                        ""event"": ""OnServiceStart"",
                        ""description"": ""Sin label, otro evento"",
                        ""actions"": []
                    }
                ]
            }";
            var filePath = WriteTempConfig(json);

            // Act
            var resultado = OnDemandConfigReader.GetOnDemandTriggers(filePath);

            // Assert
            Assert.AreEqual(2, resultado.Count);
            Assert.AreEqual("Reiniciar LPMC", resultado[0].Label);
            Assert.AreEqual("Reinicia el servicio LPMC", resultado[0].Description);
            Assert.AreEqual("Limpiar Cache", resultado[1].Label);
            Assert.AreEqual("Limpia archivos temporales", resultado[1].Description);
        }

        /// <summary>
        /// Escapa caracteres especiales para interpolación en JSON.
        /// </summary>
        private static string EscapeJsonString(string input)
        {
            return input
                .Replace("\\", "\\\\")
                .Replace("\"", "\\\"")
                .Replace("\n", "\\n")
                .Replace("\r", "\\r")
                .Replace("\t", "\\t");
        }
    }
}
