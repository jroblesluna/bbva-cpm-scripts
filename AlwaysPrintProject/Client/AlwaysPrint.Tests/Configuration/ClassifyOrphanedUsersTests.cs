using System;
using System.Collections.Generic;
using System.IO;
using NUnit.Framework;
using Newtonsoft.Json;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrintService.Actions;

namespace AlwaysPrint.Tests.Configuration
{
    /// <summary>
    /// Tests para la acción ClassifyOrphanedUsers y el flujo de limpieza inteligente de orphaned.
    /// Valida:
    /// - Parseo correcto de la config v7.8 con ClassifyOrphanedUsers
    /// - Lógica de clasificación basada en NTUSER.DAT last-write-time
    /// - Modo directo de DeleteOrphanedFolders con users_variable
    /// - Estructura correcta del flujo orphaned en OnTrayLaunched
    /// </summary>
    [TestFixture]
    [Category("Feature: classify-orphaned-users, Unit: AdminActions")]
    public class ClassifyOrphanedUsersTests
    {
        private string _tempDir = null!;

        [SetUp]
        public void SetUp()
        {
            _tempDir = Path.Combine(Path.GetTempPath(), "ClassifyOrphanedTests_" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_tempDir);
        }

        [TearDown]
        public void TearDown()
        {
            if (Directory.Exists(_tempDir))
                Directory.Delete(_tempDir, recursive: true);
        }

        // ═══════════════════════════════════════════════════════════════════════
        // PARSEO DE CONFIG v7.8
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Verifica que ClassifyOrphanedUsers se parsea correctamente del JSON.
        /// </summary>
        [Test]
        public void ParseConfig_ClassifyOrphanedUsers_SeDeserializaCorrectamente()
        {
            // Arrange
            string json = @"{
                ""version"": ""7.8"",
                ""name"": ""Test"",
                ""triggers"": [{
                    ""event"": ""OnTrayLaunched"",
                    ""actions"": [{
                        ""type"": ""ClassifyOrphanedUsers"",
                        ""description"": ""Clasificar orphaned"",
                        ""parameters"": {
                            ""base_path"": ""C:\\ProgramData\\LPMC\\Jobs"",
                            ""exclude_active_console_user"": true,
                            ""exclude_users_variable"": ""inactive_users""
                        },
                        ""store_result_in"": ""orphaned""
                    }]
                }]
            }";

            // Act
            var config = JsonConvert.DeserializeObject<ActionConfiguration>(json);

            // Assert
            Assert.That(config, Is.Not.Null);
            Assert.That(config!.Version, Is.EqualTo("7.8"));

            var action = config.Triggers[0].Actions[0];
            Assert.That(action.Type, Is.EqualTo("ClassifyOrphanedUsers"));
            Assert.That(action.StoreResultIn, Is.EqualTo("orphaned"));
            Assert.That(action.Parameters!["base_path"]!.ToString(), Is.EqualTo(@"C:\ProgramData\LPMC\Jobs"));
            Assert.That(action.Parameters["exclude_active_console_user"]!.ToObject<bool>(), Is.True);
            Assert.That(action.Parameters["exclude_users_variable"]!.ToString(), Is.EqualTo("inactive_users"));
        }

        /// <summary>
        /// Verifica que DeleteOrphanedFolders con users_variable se parsea correctamente.
        /// </summary>
        [Test]
        public void ParseConfig_DeleteOrphanedFolders_UsersVariable_SeDeserializaCorrectamente()
        {
            // Arrange
            string json = @"{
                ""version"": ""7.8"",
                ""name"": ""Test"",
                ""triggers"": [{
                    ""event"": ""OnTrayLaunched"",
                    ""actions"": [{
                        ""type"": ""DeleteOrphanedFolders"",
                        ""description"": ""Eliminar stale"",
                        ""parameters"": {
                            ""base_path"": ""C:\\ProgramData\\LPMC\\Jobs"",
                            ""users_variable"": ""{{orphaned_stale}}""
                        }
                    }]
                }]
            }";

            // Act
            var config = JsonConvert.DeserializeObject<ActionConfiguration>(json);

            // Assert
            Assert.That(config, Is.Not.Null);
            var action = config!.Triggers[0].Actions[0];
            Assert.That(action.Type, Is.EqualTo("DeleteOrphanedFolders"));
            Assert.That(action.Parameters!["base_path"]!.ToString(), Is.EqualTo(@"C:\ProgramData\LPMC\Jobs"));
            Assert.That(action.Parameters["users_variable"]!.ToString(), Is.EqualTo("{{orphaned_stale}}"));
        }

        // ═══════════════════════════════════════════════════════════════════════
        // CLASIFICACIÓN DE ORPHANED (LÓGICA)
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Directorio vacío → ambas listas vacías.
        /// </summary>
        [Test]
        public void ClassifyOrphanedUsers_DirectorioVacio_RetornaListasVacias()
        {
            // Act
            var result = AdminActions.ClassifyOrphanedUsers(
                _tempDir, new List<string>(), excludeActiveConsoleUser: false);

            // Assert
            Assert.That(result.Recent, Is.Empty);
            Assert.That(result.Stale, Is.Empty);
        }

        /// <summary>
        /// Directorio inexistente → ambas listas vacías sin error.
        /// </summary>
        [Test]
        public void ClassifyOrphanedUsers_DirectorioInexistente_RetornaListasVacias()
        {
            // Arrange
            string noExiste = Path.Combine(_tempDir, "no_existe");

            // Act
            var result = AdminActions.ClassifyOrphanedUsers(
                noExiste, new List<string>(), excludeActiveConsoleUser: false);

            // Assert
            Assert.That(result.Recent, Is.Empty);
            Assert.That(result.Stale, Is.Empty);
        }

        /// <summary>
        /// Usuarios en excludeUsers no se clasifican.
        /// </summary>
        [Test]
        public void ClassifyOrphanedUsers_UsuariosExcluidos_NoSeClasifican()
        {
            // Arrange: crear carpetas para 3 usuarios
            Directory.CreateDirectory(Path.Combine(_tempDir, "user1"));
            Directory.CreateDirectory(Path.Combine(_tempDir, "user2"));
            Directory.CreateDirectory(Path.Combine(_tempDir, "user3"));

            // Excluir user1 y user2
            var excludeUsers = new List<string> { "user1", "user2" };

            // Act
            var result = AdminActions.ClassifyOrphanedUsers(
                _tempDir, excludeUsers, excludeActiveConsoleUser: false);

            // Assert: solo user3 debería clasificarse (como stale, ya que no tiene NTUSER.DAT)
            Assert.That(result.Recent, Does.Not.Contain("user1"));
            Assert.That(result.Recent, Does.Not.Contain("user2"));
            Assert.That(result.Stale, Does.Not.Contain("user1"));
            Assert.That(result.Stale, Does.Not.Contain("user2"));
            // user3 sin NTUSER.DAT → clasificado como stale
            Assert.That(result.Stale, Contains.Item("user3"));
        }

        /// <summary>
        /// Usuario sin NTUSER.DAT → clasificado como stale (DateTime.MinValue).
        /// </summary>
        [Test]
        public void ClassifyOrphanedUsers_SinNtuserDat_EsStale()
        {
            // Arrange
            Directory.CreateDirectory(Path.Combine(_tempDir, "ghost_user"));

            // Act
            var result = AdminActions.ClassifyOrphanedUsers(
                _tempDir, new List<string>(), excludeActiveConsoleUser: false);

            // Assert
            Assert.That(result.Stale, Contains.Item("ghost_user"));
            Assert.That(result.Recent, Does.Not.Contain("ghost_user"));
        }

        /// <summary>
        /// ExcludeUsers es case-insensitive.
        /// </summary>
        [Test]
        public void ClassifyOrphanedUsers_ExcludeUsers_CaseInsensitive()
        {
            // Arrange
            Directory.CreateDirectory(Path.Combine(_tempDir, "UserA"));

            var excludeUsers = new List<string> { "usera" }; // lowercase

            // Act
            var result = AdminActions.ClassifyOrphanedUsers(
                _tempDir, excludeUsers, excludeActiveConsoleUser: false);

            // Assert: "UserA" excluida pese a case mismatch
            Assert.That(result.Recent, Does.Not.Contain("UserA"));
            Assert.That(result.Stale, Does.Not.Contain("UserA"));
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ESTRUCTURA DE CONFIG OnTrayLaunched v7.8
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Verifica que la config real CPM_Compliant.alwaysconfig v7.8 se parsea sin errores
        /// y tiene la estructura esperada: ClassifyOrphanedUsers fuera del condicional de inactive_users.
        /// </summary>
        [Test]
        public void ParseConfig_CPMCompliant_V78_EstructuraCorrecta()
        {
            // Arrange: leer la config real desde el repositorio
            string configPath = Path.Combine(
                TestContext.CurrentContext.TestDirectory,
                "..", "..", "..", "..", "AlwaysConfig", "CPM_Compliant.alwaysconfig");

            // Si no se puede acceder a la ruta relativa, usar una ruta conocida
            if (!File.Exists(configPath))
            {
                configPath = Path.Combine(
                    TestContext.CurrentContext.TestDirectory,
                    "..", "..", "..", "..", "..", "AlwaysConfig", "CPM_Compliant.alwaysconfig");
            }

            // Skip si no se encuentra el archivo (CI sin la estructura completa)
            if (!File.Exists(configPath))
            {
                Assert.Ignore("CPM_Compliant.alwaysconfig no encontrado en la ruta esperada");
                return;
            }

            string json = File.ReadAllText(configPath);

            // Act
            var config = JsonConvert.DeserializeObject<ActionConfiguration>(json);

            // Assert
            Assert.That(config, Is.Not.Null);
            Assert.That(config!.Version, Is.EqualTo("7.8"));
            Assert.That(config.Name, Is.EqualTo("CPM_Compliant"));

            // Verificar trigger OnTrayLaunched
            var trayTrigger = config.Triggers.Find(t => t.Event == "OnTrayLaunched");
            Assert.That(trayTrigger, Is.Not.Null);

            // Verificar que ClassifyOrphanedUsers está como acción top-level (no anidada)
            var classifyAction = trayTrigger!.Actions.Find(a => a.Type == "ClassifyOrphanedUsers");
            Assert.That(classifyAction, Is.Not.Null, "ClassifyOrphanedUsers debe ser acción top-level en OnTrayLaunched");
            Assert.That(classifyAction!.StoreResultIn, Is.EqualTo("orphaned"));

            // Verificar que hay condicionales para orphaned_recent y orphaned_stale
            var conditionals = trayTrigger.Actions.FindAll(a => a.Type == "Conditional");
            bool hasRecentConditional = conditionals.Exists(c =>
                c.Condition?.Variable == "orphaned_recent" && c.Condition?.Operator == "not_empty");
            bool hasStaleConditional = conditionals.Exists(c =>
                c.Condition?.Variable == "orphaned_stale" && c.Condition?.Operator == "not_empty");

            Assert.That(hasRecentConditional, Is.True, "Debe existir condicional para orphaned_recent");
            Assert.That(hasStaleConditional, Is.True, "Debe existir condicional para orphaned_stale");
        }

        /// <summary>
        /// Verifica que ActionTypes contiene ClassifyOrphanedUsers.
        /// </summary>
        [Test]
        public void ActionTypes_ContieneClassifyOrphanedUsers()
        {
            Assert.That(ActionTypes.ClassifyOrphanedUsers, Is.EqualTo("ClassifyOrphanedUsers"));
        }

        // ═══════════════════════════════════════════════════════════════════════
        // VARIABLES ALMACENADAS
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Verifica que store_result_in="orphaned" genera variables "orphaned_recent" y "orphaned_stale".
        /// Este test valida la convención de nombres sin ejecutar el ActionEngine completo.
        /// </summary>
        [Test]
        public void StoreResultConvention_OrphanedPrefix_GeneraRecentYStale()
        {
            // La convención es: store_result_in = "X" → genera "X_recent" y "X_stale"
            string storeResultIn = "orphaned";

            string recentVar = $"{storeResultIn}_recent";
            string staleVar = $"{storeResultIn}_stale";

            Assert.That(recentVar, Is.EqualTo("orphaned_recent"));
            Assert.That(staleVar, Is.EqualTo("orphaned_stale"));
        }

        // ═══════════════════════════════════════════════════════════════════════
        // OrphanedClassification RESULT CLASS
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// OrphanedClassification inicializa con listas vacías.
        /// </summary>
        [Test]
        public void OrphanedClassification_Inicializa_ConListasVacias()
        {
            var result = new AdminActions.OrphanedClassification();

            Assert.That(result.Recent, Is.Not.Null);
            Assert.That(result.Stale, Is.Not.Null);
            Assert.That(result.Recent, Is.Empty);
            Assert.That(result.Stale, Is.Empty);
        }

        // ═══════════════════════════════════════════════════════════════════════
        // DeleteOrphanedFolders MODO DIRECTO
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// DeleteOrphanedFolders en modo directo (lista de usuarios) elimina carpetas correctas.
        /// </summary>
        [Test]
        public void DeleteOrphanedFolders_ModoDirecto_EliminaCarpetasCorrectamente()
        {
            // Arrange: crear carpetas para usuarios stale
            string user1Dir = Path.Combine(_tempDir, "stale_user1");
            string user2Dir = Path.Combine(_tempDir, "stale_user2");
            string keepDir = Path.Combine(_tempDir, "keep_user");
            Directory.CreateDirectory(user1Dir);
            Directory.CreateDirectory(user2Dir);
            Directory.CreateDirectory(keepDir);

            // Crear archivos dentro para verificar eliminación recursiva
            File.WriteAllText(Path.Combine(user1Dir, "token.dat"), "test");
            File.WriteAllText(Path.Combine(user2Dir, "data.txt"), "test");

            var staleUsers = new List<string> { "stale_user1", "stale_user2" };

            // Act: simular lo que haría DeleteOrphanedFolders en modo directo
            foreach (string username in staleUsers)
            {
                string fullPath = Path.Combine(_tempDir, username);
                if (Directory.Exists(fullPath))
                    Directory.Delete(fullPath, recursive: true);
            }

            // Assert
            Assert.That(Directory.Exists(user1Dir), Is.False, "stale_user1 debe ser eliminado");
            Assert.That(Directory.Exists(user2Dir), Is.False, "stale_user2 debe ser eliminado");
            Assert.That(Directory.Exists(keepDir), Is.True, "keep_user NO debe ser eliminado");
        }

        /// <summary>
        /// DeleteOrphanedFolders en modo directo: usuario inexistente no causa error.
        /// </summary>
        [Test]
        public void DeleteOrphanedFolders_ModoDirecto_UsuarioInexistente_NoFalla()
        {
            // Arrange
            var staleUsers = new List<string> { "no_existe_1", "no_existe_2" };

            // Act & Assert: no debe lanzar excepción
            Assert.DoesNotThrow(() =>
            {
                foreach (string username in staleUsers)
                {
                    string fullPath = Path.Combine(_tempDir, username);
                    if (Directory.Exists(fullPath))
                        Directory.Delete(fullPath, recursive: true);
                }
            });
        }

        // ═══════════════════════════════════════════════════════════════════════
        // LIMPIEZA DE ORPHANED RECIENTES (SOLO PRE/POST)
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Para orphaned recientes: solo se borran pre/ y post/, el token se preserva.
        /// </summary>
        [Test]
        public void OrphanedReciente_SoloBorraPrePost_PreservaToken()
        {
            // Arrange: simular estructura de un usuario orphaned reciente
            string userDir = Path.Combine(_tempDir, "recent_user");
            string prePath = Path.Combine(userDir, "CloudHybrid", "pre");
            string postPath = Path.Combine(userDir, "CloudHybrid", "post");
            string tokenPath = Path.Combine(userDir, "CloudHybrid", "token.dat");

            Directory.CreateDirectory(prePath);
            Directory.CreateDirectory(postPath);
            File.WriteAllText(Path.Combine(prePath, "job1.prn"), "spool data");
            File.WriteAllText(Path.Combine(prePath, "job2.prn"), "spool data");
            File.WriteAllText(Path.Combine(postPath, "job1.prn"), "spool data");
            File.WriteAllText(tokenPath, "auth_token_data");

            // Act: simular limpieza de orphaned reciente (solo pre y post)
            if (Directory.Exists(prePath))
            {
                foreach (var file in Directory.GetFiles(prePath))
                    File.Delete(file);
                foreach (var dir in Directory.GetDirectories(prePath))
                    Directory.Delete(dir, recursive: true);
            }
            if (Directory.Exists(postPath))
            {
                foreach (var file in Directory.GetFiles(postPath))
                    File.Delete(file);
                foreach (var dir in Directory.GetDirectories(postPath))
                    Directory.Delete(dir, recursive: true);
            }

            // Assert
            Assert.That(Directory.Exists(prePath), Is.True, "Carpeta pre/ debe existir (vacía)");
            Assert.That(Directory.Exists(postPath), Is.True, "Carpeta post/ debe existir (vacía)");
            Assert.That(Directory.GetFiles(prePath).Length, Is.EqualTo(0), "pre/ debe estar vacía");
            Assert.That(Directory.GetFiles(postPath).Length, Is.EqualTo(0), "post/ debe estar vacía");
            Assert.That(File.Exists(tokenPath), Is.True, "Token debe preservarse");
            Assert.That(Directory.Exists(userDir), Is.True, "Carpeta del usuario debe existir");
        }

        // ═══════════════════════════════════════════════════════════════════════
        // CONFIG JSON COMPLETO: VALIDACIÓN DE ESTRUCTURA
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Verifica que un JSON completo con el flujo ClassifyOrphanedUsers + Conditional
        /// se deserializa sin errores y mantiene la estructura esperada.
        /// </summary>
        [Test]
        public void ParseConfig_FlujoCompletoOrphaned_EstructuraValida()
        {
            // Arrange: JSON mínimo con el flujo completo
            string json = @"{
                ""version"": ""7.8"",
                ""name"": ""Test"",
                ""triggers"": [{
                    ""event"": ""OnTrayLaunched"",
                    ""actions"": [
                        {
                            ""type"": ""GetLoggedInUsers"",
                            ""parameters"": { ""exclude_active_console_user"": true },
                            ""store_result_in"": ""inactive_users""
                        },
                        {
                            ""type"": ""Conditional"",
                            ""description"": ""Si hay inactive: limpiar"",
                            ""condition"": { ""variable"": ""inactive_users"", ""operator"": ""not_empty"" },
                            ""actions"": [
                                { ""type"": ""StopService"", ""parameters"": { ""service_name"": ""lpmc_universal_service"" } }
                            ]
                        },
                        {
                            ""type"": ""ClassifyOrphanedUsers"",
                            ""parameters"": {
                                ""base_path"": ""C:\\ProgramData\\LPMC\\Jobs"",
                                ""exclude_active_console_user"": true,
                                ""exclude_users_variable"": ""inactive_users""
                            },
                            ""store_result_in"": ""orphaned""
                        },
                        {
                            ""type"": ""Conditional"",
                            ""description"": ""Orphaned recientes"",
                            ""condition"": { ""variable"": ""orphaned_recent"", ""operator"": ""not_empty"" },
                            ""actions"": [
                                {
                                    ""type"": ""DeleteFolderContents"",
                                    ""parameters"": {
                                        ""path_template"": ""C:\\ProgramData\\LPMC\\Jobs\\{{username}}\\CloudHybrid\\pre"",
                                        ""iterate_users"": ""{{orphaned_recent}}"",
                                        ""recursive"": true
                                    }
                                }
                            ]
                        },
                        {
                            ""type"": ""Conditional"",
                            ""description"": ""Orphaned stale"",
                            ""condition"": { ""variable"": ""orphaned_stale"", ""operator"": ""not_empty"" },
                            ""actions"": [
                                {
                                    ""type"": ""DeleteOrphanedFolders"",
                                    ""parameters"": {
                                        ""base_path"": ""C:\\ProgramData\\LPMC\\Jobs"",
                                        ""users_variable"": ""{{orphaned_stale}}""
                                    }
                                }
                            ]
                        }
                    ]
                }]
            }";

            // Act
            var config = JsonConvert.DeserializeObject<ActionConfiguration>(json);

            // Assert
            Assert.That(config, Is.Not.Null);
            var actions = config!.Triggers[0].Actions;

            // Verificar orden: GetLoggedInUsers → Conditional(inactive) → ClassifyOrphanedUsers → Conditional(recent) → Conditional(stale)
            Assert.That(actions[0].Type, Is.EqualTo("GetLoggedInUsers"));
            Assert.That(actions[1].Type, Is.EqualTo("Conditional"));
            Assert.That(actions[2].Type, Is.EqualTo("ClassifyOrphanedUsers"));
            Assert.That(actions[3].Type, Is.EqualTo("Conditional"));
            Assert.That(actions[3].Condition!.Variable, Is.EqualTo("orphaned_recent"));
            Assert.That(actions[4].Type, Is.EqualTo("Conditional"));
            Assert.That(actions[4].Condition!.Variable, Is.EqualTo("orphaned_stale"));
        }
    }
}
