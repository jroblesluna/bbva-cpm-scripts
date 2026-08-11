using System;
using System.Net.Http;
using System.Reflection;
using System.Threading;
using NUnit.Framework;
using AlwaysPrintTray.Bootstrap;

#nullable enable

namespace AlwaysPrint.Tests.Bootstrap
{
    /// <summary>
    /// Tests para verificar que DomainHealthChecker.Http está correctamente inicializado
    /// con el proxy corporativo configurado via ProxyHelper.CreateHandler().
    ///
    /// **Validates: Requirements 2.1, 2.2**
    /// </summary>
    [TestFixture]
    [Category("Feature: reconnection-reliability-fixes, Unit Tests: DomainHealthChecker Proxy")]
    public class DomainHealthCheckerProxyTests
    {
        // ===================================================================
        // Test: DomainHealthChecker.Http no es null después de inicialización
        // ===================================================================

        /// <summary>
        /// Verifica que la propiedad estática Http no es null después de la
        /// inicialización estática de la clase. Confirma que el HttpClient
        /// fue construido exitosamente con ProxyHelper.CreateHandler().
        /// </summary>
        [Test]
        public void Http_DespuesDeInicializacion_NoEsNull()
        {
            // Act: Acceder a la propiedad interna Http via reflexión
            // (es internal static, accesible porque el archivo está linkeado al proyecto de test)
            HttpClient? http = DomainHealthChecker.Http;

            // Assert
            Assert.That(http, Is.Not.Null,
                "DomainHealthChecker.Http debe estar inicializado (no null) " +
                "después de la inicialización estática de la clase");
        }

        /// <summary>
        /// Verifica que el HttpClient fue construido con un HttpClientHandler
        /// (no el handler por defecto sin proxy). Usa reflexión para inspeccionar
        /// el campo privado _http y extraer el handler subyacente.
        /// </summary>
        [Test]
        public void Http_TieneHandlerConfigurado_NoEsDefault()
        {
            // Arrange: Obtener el campo privado estático _http
            var httpField = typeof(DomainHealthChecker).GetField(
                "_http",
                BindingFlags.NonPublic | BindingFlags.Static);

            Assert.That(httpField, Is.Not.Null,
                "El campo privado _http debe existir en DomainHealthChecker");

            var httpClient = httpField!.GetValue(null) as HttpClient;
            Assert.That(httpClient, Is.Not.Null,
                "El campo _http no debe ser null");

            // Act: Obtener el handler interno del HttpClient via reflexión.
            // En .NET Framework 4.8, HttpMessageInvoker (base de HttpClient) tiene
            // un campo privado "_handler" que contiene el HttpMessageHandler.
            var handlerField = typeof(HttpMessageInvoker).GetField(
                "_handler",
                BindingFlags.NonPublic | BindingFlags.Instance);

            // Fallback: en algunas versiones el campo se llama "handler"
            if (handlerField == null)
            {
                handlerField = typeof(HttpMessageInvoker).GetField(
                    "handler",
                    BindingFlags.NonPublic | BindingFlags.Instance);
            }

            Assert.That(handlerField, Is.Not.Null,
                "HttpMessageInvoker debe tener un campo interno para el handler");

            var handler = handlerField!.GetValue(httpClient);

            // Assert: El handler debe ser un HttpClientHandler (lo que retorna ProxyHelper.CreateHandler())
            Assert.That(handler, Is.Not.Null,
                "El handler del HttpClient no debe ser null");
            Assert.That(handler, Is.InstanceOf<HttpClientHandler>(),
                "El handler debe ser de tipo HttpClientHandler (configurado por ProxyHelper.CreateHandler())");

            // Verificar que UseProxy está habilitado en el handler
            var httpHandler = (HttpClientHandler)handler!;
            Assert.That(httpHandler.UseProxy, Is.True,
                "El handler debe tener UseProxy = true (proxy corporativo habilitado)");
        }

        /// <summary>
        /// Verifica que el Timeout del HttpClient es de 10 segundos
        /// (el valor configurado en TimeoutSecs).
        /// </summary>
        [Test]
        public void Http_TieneTimeoutDe10Segundos()
        {
            // Act
            HttpClient http = DomainHealthChecker.Http;

            // Assert
            Assert.That(http.Timeout, Is.EqualTo(TimeSpan.FromSeconds(10)),
                "El HttpClient debe tener un timeout de 10 segundos");
        }

        // ===================================================================
        // Smoke test: CheckAll() funciona correctamente con dominio alcanzable
        // ===================================================================

        /// <summary>
        /// Smoke test de integración: verifica que CheckAll() puede ejecutarse
        /// sin excepciones y retorna un resultado coherente.
        /// Marcado como Integration porque depende de conectividad de red.
        /// </summary>
        [Test]
        [Category("Integration")]
        public void CheckAll_ConDominioAlcanzable_RetornaResultadoCoherente()
        {
            // Arrange: Usar dominios bootstrap de producción
            string bootstrapDomains = "apps.iol.pe";
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(15));

            // Act: Ejecutar CheckAll — no debe lanzar excepciones
            var (success, respondingDomain, details) = DomainHealthChecker.CheckAll(
                bootstrapDomains, cts.Token);

            // Assert: Verificar que el resultado es coherente (no importa si tuvo éxito o no)
            // En un entorno sin red o detrás de firewall, puede fallar — lo importante es
            // que no lanza excepciones y retorna una tupla válida.
            if (success)
            {
                Assert.That(respondingDomain, Is.Not.Null.And.Not.Empty,
                    "Si CheckAll retorna success=true, debe incluir el dominio que respondió");
                Assert.That(respondingDomain, Does.Contain("alwaysprint."),
                    "El dominio respondiente debe contener el prefijo 'alwaysprint.'");
            }
            else
            {
                Assert.That(details, Is.Not.Null,
                    "Si CheckAll retorna success=false, debe incluir detalles del fallo");
            }
        }

        /// <summary>
        /// Verifica que CheckAll() con dominios vacíos retorna failure sin excepción.
        /// </summary>
        [Test]
        public void CheckAll_ConDominiosVacios_RetornaFalse()
        {
            // Act
            var (success, respondingDomain, details) = DomainHealthChecker.CheckAll("");

            // Assert
            Assert.That(success, Is.False,
                "CheckAll con dominios vacíos debe retornar false");
            Assert.That(respondingDomain, Is.Null,
                "No debe haber dominio respondiente cuando no hay dominios configurados");
            Assert.That(details, Does.Contain("No hay dominios bootstrap configurados"),
                "Debe indicar que no hay dominios configurados");
        }
    }
}
