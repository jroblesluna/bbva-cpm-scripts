using System;
using System.Reflection;
using NUnit.Framework;
using AlwaysPrintService.Actions;
using Win32Exception = System.ComponentModel.Win32Exception;

#nullable enable

namespace AlwaysPrint.Tests.Actions
{
    /// <summary>
    /// Tests unitarios para el manejo tolerante de servicios inexistentes en AdminActions.
    /// Verifica que StopService/StartService retornan true cuando el servicio no existe,
    /// y que IsServiceNotFound detecta correctamente Win32Exception con código 1060.
    ///
    /// **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5**
    /// </summary>
    [TestFixture]
    [Category("Feature: reconnection-reliability-fixes, Unit Tests: AdminActions Service Handling")]
    public class AdminActionsServiceTests
    {
        // ===================================================================
        // IsServiceNotFound: Detección correcta de Win32Exception(1060)
        // ===================================================================

        /// <summary>
        /// IsServiceNotFound con InnerException Win32Exception(1060) → retorna true.
        /// El código 1060 es ERROR_SERVICE_DOES_NOT_EXIST de Windows.
        /// </summary>
        [Test]
        public void IsServiceNotFound_Win32Exception1060_RetornaTrue()
        {
            // Arrange: Crear InvalidOperationException con InnerException Win32Exception(1060)
            var win32Ex = CreateWin32Exception(1060);
            var invalidOpEx = new InvalidOperationException(
                "Cannot open LPDSVC service on computer '.'.", win32Ex);

            // Act
            bool result = InvokeIsServiceNotFound(invalidOpEx);

            // Assert
            Assert.That(result, Is.True,
                "IsServiceNotFound debe retornar true para Win32Exception con NativeErrorCode 1060");
        }

        /// <summary>
        /// IsServiceNotFound con InnerException Win32Exception(5) (access denied) → retorna false.
        /// El código 5 es ERROR_ACCESS_DENIED — no es "servicio no encontrado".
        /// </summary>
        [Test]
        public void IsServiceNotFound_Win32Exception5_AccessDenied_RetornaFalse()
        {
            // Arrange: Crear InvalidOperationException con InnerException Win32Exception(5) — ACCESS_DENIED
            var win32Ex = CreateWin32Exception(5);
            var invalidOpEx = new InvalidOperationException(
                "Cannot open SomeService service on computer '.'.", win32Ex);

            // Act
            bool result = InvokeIsServiceNotFound(invalidOpEx);

            // Assert
            Assert.That(result, Is.False,
                "IsServiceNotFound debe retornar false para Win32Exception con NativeErrorCode 5 (access denied)");
        }

        /// <summary>
        /// IsServiceNotFound con InnerException no Win32Exception → verifica fallback por mensaje.
        /// Si el mensaje contiene "was not found", retorna true por fallback de string.
        /// </summary>
        [Test]
        public void IsServiceNotFound_MensajeContainsWasNotFound_RetornaTrue()
        {
            // Arrange: InvalidOperationException con mensaje de fallback (sin Win32Exception inner)
            var invalidOpEx = new InvalidOperationException(
                "Service 'MiServicio' was not found on computer '.'.");

            // Act
            bool result = InvokeIsServiceNotFound(invalidOpEx);

            // Assert
            Assert.That(result, Is.True,
                "IsServiceNotFound debe retornar true por fallback de string 'was not found'");
        }

        /// <summary>
        /// IsServiceNotFound con InnerException no Win32Exception y mensaje genérico → retorna false.
        /// No debe dar falso positivo para excepciones genéricas.
        /// </summary>
        [Test]
        public void IsServiceNotFound_MensajeGenerico_RetornaFalse()
        {
            // Arrange: InvalidOperationException genérica sin indicadores de "no encontrado"
            var invalidOpEx = new InvalidOperationException(
                "An error occurred while performing the operation.");

            // Act
            bool result = InvokeIsServiceNotFound(invalidOpEx);

            // Assert
            Assert.That(result, Is.False,
                "IsServiceNotFound debe retornar false para excepciones genéricas sin indicadores");
        }

        // ===================================================================
        // StopService / StartService: Servicios inexistentes (solo Windows)
        // ===================================================================

        /// <summary>
        /// StopService("ServicioInexistente") retorna true.
        /// Cuando el servicio no existe, se captura la excepción y se retorna éxito.
        /// Solo se ejecuta en Windows donde ServiceController está disponible.
        /// </summary>
        [Test]
        [Platform("Win")]
        public void StopService_ServicioInexistente_RetornaTrue()
        {
            // Act: Intentar detener un servicio que no existe en la máquina
            bool result = AdminActions.StopService("ServicioQueNoExisteEnNingunaMaquina_XYZ123");

            // Assert: Debe retornar true (nada que detener = éxito)
            Assert.That(result, Is.True,
                "StopService debe retornar true para un servicio que no existe (nada que detener)");
        }

        /// <summary>
        /// StartService("ServicioInexistente") retorna true.
        /// Cuando el servicio no existe, se captura la excepción y se retorna éxito.
        /// Solo se ejecuta en Windows donde ServiceController está disponible.
        /// </summary>
        [Test]
        [Platform("Win")]
        public void StartService_ServicioInexistente_RetornaTrue()
        {
            // Act: Intentar iniciar un servicio que no existe en la máquina
            bool result = AdminActions.StartService("ServicioQueNoExisteEnNingunaMaquina_XYZ123");

            // Assert: Debe retornar true (nada que iniciar = éxito)
            Assert.That(result, Is.True,
                "StartService debe retornar true para un servicio que no existe (estado deseado no aplica)");
        }

        // ===================================================================
        // ActionEngine continúa ejecución después de servicio no encontrado
        // ===================================================================

        /// <summary>
        /// Verificar que la ejecución continúa después de un servicio no encontrado.
        /// Como StopService retorna true para servicios inexistentes,
        /// el ActionEngine (que no hace break en fallo) continúa con las siguientes acciones.
        /// Este test verifica el contrato: retornar true NO interrumpe la secuencia.
        /// Solo se ejecuta en Windows donde ServiceController está disponible.
        /// </summary>
        [Test]
        [Platform("Win")]
        public void ActionEngine_ContinuaEjecucion_DespuesDeServicioNoEncontrado()
        {
            // Arrange: Simular la secuencia que haría ActionEngine:
            // 1. StopService → servicio no existe → retorna true
            // 2. La siguiente acción se ejecuta normalmente

            // Act: StopService para servicio inexistente retorna true (no interrumpe)
            bool stopResult = AdminActions.StopService("ServicioQueNoExisteEnNingunaMaquina_XYZ123");

            // Una acción subsecuente (StartService con servicio inexistente también retorna true)
            bool startResult = AdminActions.StartService("OtroServicioInexistente_ABC789");

            // Assert: Ambas retornaron true, la secuencia no se interrumpió
            Assert.That(stopResult, Is.True,
                "StopService debe retornar true para servicio inexistente");
            Assert.That(startResult, Is.True,
                "StartService debe retornar true para servicio inexistente — la ejecución continuó");
        }

        // ===================================================================
        // Helpers: Reflexión para invocar método privado IsServiceNotFound
        // ===================================================================

        /// <summary>
        /// Invoca el método privado estático IsServiceNotFound via reflexión.
        /// Necesario porque el método es private y no queremos cambiar su visibilidad.
        /// </summary>
        private static bool InvokeIsServiceNotFound(InvalidOperationException ex)
        {
            var method = typeof(AdminActions).GetMethod(
                "IsServiceNotFound",
                BindingFlags.NonPublic | BindingFlags.Static);

            Assert.That(method, Is.Not.Null,
                "El método IsServiceNotFound debe existir como private static en AdminActions");

            object? result = method!.Invoke(null, new object[] { ex });
            return (bool)result!;
        }

        /// <summary>
        /// Crea una Win32Exception con un NativeErrorCode específico.
        /// Usa el constructor que acepta un int (error code de Win32).
        /// </summary>
        private static Win32Exception CreateWin32Exception(int nativeErrorCode)
        {
            // Win32Exception(int error) establece NativeErrorCode = error
            return new Win32Exception(nativeErrorCode);
        }
    }
}
