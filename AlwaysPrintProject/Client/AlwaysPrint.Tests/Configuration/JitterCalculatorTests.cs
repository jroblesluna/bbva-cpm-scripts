using System;
using NUnit.Framework;
using AlwaysPrint.Shared.Configuration;

#nullable enable

namespace AlwaysPrint.Tests.Configuration
{
    /// <summary>
    /// Tests unitarios para JitterCalculator.
    /// Verifican comportamiento determinístico usando Random con seed fijo.
    /// 
    /// **Validates: Requirements 3.1, 3.2, 3.4, 3.5, 4.1, 4.2, 4.4, 4.5, 5.1, 5.4**
    /// </summary>
    [TestFixture]
    [Category("Feature: reconnection-jitter, Unit Tests: JitterCalculator")]
    public class JitterCalculatorTests
    {
        // ===================================================================
        // ComputeStartupDelay: Timestamp reciente (< 60s)
        // ===================================================================

        /// <summary>
        /// Timestamp de actualización de hace 30s con jitter window 45 → delay en [0, 45000).
        /// Verifica que un evento reciente produce un delay dentro del rango esperado.
        /// </summary>
        [Test]
        public void ComputeStartupDelay_TimestampHace30s_Window45_DelayEnRango()
        {
            // Arrange
            var utcNow = new DateTime(2026, 6, 15, 12, 0, 0, DateTimeKind.Utc);
            var lastUpdate = utcNow.AddSeconds(-30); // Hace 30 segundos
            var rng = new Random(42); // Seed fijo para determinismo

            // Act
            var (delayMs, reason) = JitterCalculator.ComputeStartupDelay(
                utcNow, lastUpdate, null, 45, rng);

            // Assert: delay debe estar en [0, 45000)
            Assert.That(delayMs, Is.GreaterThanOrEqualTo(0));
            Assert.That(delayMs, Is.LessThan(45000));
            Assert.That(reason, Is.EqualTo("post-update"));
        }

        // ===================================================================
        // ComputeStartupDelay: Timestamp antiguo (>= 60s)
        // ===================================================================

        /// <summary>
        /// Timestamp de hace 120s → delay = 0.
        /// Un evento con más de 60s de antigüedad no activa jitter.
        /// </summary>
        [Test]
        public void ComputeStartupDelay_TimestampHace120s_DelayEsCero()
        {
            // Arrange
            var utcNow = new DateTime(2026, 6, 15, 12, 0, 0, DateTimeKind.Utc);
            var lastUpdate = utcNow.AddSeconds(-120); // Hace 120 segundos
            var rng = new Random(42);

            // Act
            var (delayMs, reason) = JitterCalculator.ComputeStartupDelay(
                utcNow, lastUpdate, null, 45, rng);

            // Assert
            Assert.That(delayMs, Is.EqualTo(0));
            Assert.That(reason, Is.Null);
        }

        // ===================================================================
        // ComputeStartupDelay: Timestamp null (ausente)
        // ===================================================================

        /// <summary>
        /// Timestamp null → delay = 0.
        /// Si no hay timestamp registrado, no se aplica jitter.
        /// </summary>
        [Test]
        public void ComputeStartupDelay_TimestampNull_DelayEsCero()
        {
            // Arrange
            var utcNow = new DateTime(2026, 6, 15, 12, 0, 0, DateTimeKind.Utc);
            var rng = new Random(42);

            // Act
            var (delayMs, reason) = JitterCalculator.ComputeStartupDelay(
                utcNow, null, null, 45, rng);

            // Assert
            Assert.That(delayMs, Is.EqualTo(0));
            Assert.That(reason, Is.Null);
        }

        // ===================================================================
        // ComputeStartupDelay: Timestamp futuro (inválido)
        // ===================================================================

        /// <summary>
        /// Timestamp futuro → delay = 0.
        /// Un timestamp en el futuro se trata como inválido/ausente.
        /// </summary>
        [Test]
        public void ComputeStartupDelay_TimestampFuturo_DelayEsCero()
        {
            // Arrange
            var utcNow = new DateTime(2026, 6, 15, 12, 0, 0, DateTimeKind.Utc);
            var futureTimestamp = utcNow.AddMinutes(5); // 5 minutos en el futuro
            var rng = new Random(42);

            // Act
            var (delayMs, reason) = JitterCalculator.ComputeStartupDelay(
                utcNow, futureTimestamp, null, 45, rng);

            // Assert
            Assert.That(delayMs, Is.EqualTo(0));
            Assert.That(reason, Is.Null);
        }

        // ===================================================================
        // NormalizeJitterWindow: Valores fuera de rango
        // ===================================================================

        /// <summary>
        /// JitterWindow = 0 → NormalizeJitterWindow retorna 30 (default).
        /// Valores menores a 5 se normalizan al default.
        /// </summary>
        [Test]
        public void NormalizeJitterWindow_ValorCero_Retorna30()
        {
            // Act
            var result = JitterCalculator.NormalizeJitterWindow(0);

            // Assert
            Assert.That(result, Is.EqualTo(30));
        }

        /// <summary>
        /// JitterWindow = 500 → NormalizeJitterWindow retorna 30 (default).
        /// Valores mayores a 300 se normalizan al default.
        /// </summary>
        [Test]
        public void NormalizeJitterWindow_Valor500_Retorna30()
        {
            // Act
            var result = JitterCalculator.NormalizeJitterWindow(500);

            // Assert
            Assert.That(result, Is.EqualTo(30));
        }

        /// <summary>
        /// JitterWindow = 5 (mínimo válido) → NormalizeJitterWindow retorna 5.
        /// Valor en el límite inferior del rango válido.
        /// </summary>
        [Test]
        public void NormalizeJitterWindow_ValorMinimo5_Retorna5()
        {
            // Act
            var result = JitterCalculator.NormalizeJitterWindow(5);

            // Assert
            Assert.That(result, Is.EqualTo(5));
        }

        /// <summary>
        /// JitterWindow = 300 (máximo válido) → NormalizeJitterWindow retorna 300.
        /// Valor en el límite superior del rango válido.
        /// </summary>
        [Test]
        public void NormalizeJitterWindow_ValorMaximo300_Retorna300()
        {
            // Act
            var result = JitterCalculator.NormalizeJitterWindow(300);

            // Assert
            Assert.That(result, Is.EqualTo(300));
        }

        /// <summary>
        /// JitterWindow = 4 (justo debajo del mínimo) → NormalizeJitterWindow retorna 30.
        /// </summary>
        [Test]
        public void NormalizeJitterWindow_Valor4_Retorna30()
        {
            // Act
            var result = JitterCalculator.NormalizeJitterWindow(4);

            // Assert
            Assert.That(result, Is.EqualTo(30));
        }

        /// <summary>
        /// JitterWindow negativo → NormalizeJitterWindow retorna 30 (default).
        /// </summary>
        [Test]
        public void NormalizeJitterWindow_ValorNegativo_Retorna30()
        {
            // Act
            var result = JitterCalculator.NormalizeJitterWindow(-10);

            // Assert
            Assert.That(result, Is.EqualTo(30));
        }

        // ===================================================================
        // ComputeStartupDelay: Ambos timestamps recientes
        // ===================================================================

        /// <summary>
        /// Ambos timestamps recientes → un solo delay, usando el más cercano a utcNow.
        /// Cuando update está a 30s y restart a 10s, se usa restart (más cercano).
        /// </summary>
        [Test]
        public void ComputeStartupDelay_AmbosRecientes_UsaElMasCercano()
        {
            // Arrange
            var utcNow = new DateTime(2026, 6, 15, 12, 0, 0, DateTimeKind.Utc);
            var lastUpdate = utcNow.AddSeconds(-30);  // Hace 30 segundos
            var lastRestart = utcNow.AddSeconds(-10); // Hace 10 segundos (más cercano)
            var rng = new Random(42);

            // Act
            var (delayMs, reason) = JitterCalculator.ComputeStartupDelay(
                utcNow, lastUpdate, lastRestart, 45, rng);

            // Assert: debe usar el timestamp más cercano (restart) → reason = "post-restart"
            Assert.That(delayMs, Is.GreaterThanOrEqualTo(0));
            Assert.That(delayMs, Is.LessThan(45000));
            Assert.That(reason, Is.EqualTo("post-restart"));
        }

        /// <summary>
        /// Ambos timestamps recientes pero update es más cercano → reason = "post-update".
        /// Verifica que la selección del más cercano funciona en ambas direcciones.
        /// </summary>
        [Test]
        public void ComputeStartupDelay_AmbosRecientes_UpdateMasCercano_UsaUpdate()
        {
            // Arrange
            var utcNow = new DateTime(2026, 6, 15, 12, 0, 0, DateTimeKind.Utc);
            var lastUpdate = utcNow.AddSeconds(-5);   // Hace 5 segundos (más cercano)
            var lastRestart = utcNow.AddSeconds(-50); // Hace 50 segundos
            var rng = new Random(42);

            // Act
            var (delayMs, reason) = JitterCalculator.ComputeStartupDelay(
                utcNow, lastUpdate, lastRestart, 45, rng);

            // Assert: debe usar update (más cercano) → reason = "post-update"
            Assert.That(delayMs, Is.GreaterThanOrEqualTo(0));
            Assert.That(delayMs, Is.LessThan(45000));
            Assert.That(reason, Is.EqualTo("post-update"));
        }

        // ===================================================================
        // ComputeReconnectionDelay: Delay para reconexión WebSocket
        // ===================================================================

        /// <summary>
        /// ComputeReconnectionDelay con window 60 → delay en [0, 60000).
        /// La reconexión siempre aplica jitter dentro de la ventana normalizada.
        /// </summary>
        [Test]
        public void ComputeReconnectionDelay_Window60_DelayEnRango()
        {
            // Arrange
            var rng = new Random(42);

            // Act
            var delayMs = JitterCalculator.ComputeReconnectionDelay(60, rng);

            // Assert
            Assert.That(delayMs, Is.GreaterThanOrEqualTo(0));
            Assert.That(delayMs, Is.LessThan(60000));
        }

        /// <summary>
        /// ComputeReconnectionDelay con window inválido → normaliza a 30 y delay en [0, 30000).
        /// Verifica que la normalización se aplica también en reconexión.
        /// </summary>
        [Test]
        public void ComputeReconnectionDelay_WindowInvalido_NormalizaA30()
        {
            // Arrange
            var rng = new Random(42);

            // Act
            var delayMs = JitterCalculator.ComputeReconnectionDelay(0, rng);

            // Assert: normaliza a 30, por lo que delay en [0, 30000)
            Assert.That(delayMs, Is.GreaterThanOrEqualTo(0));
            Assert.That(delayMs, Is.LessThan(30000));
        }

        // ===================================================================
        // Determinismo: Random con seed fijo produce resultados reproducibles
        // ===================================================================

        /// <summary>
        /// Verifica que usando el mismo seed, el resultado es reproducible.
        /// Garantiza que los tests son determinísticos con Random inyectado.
        /// </summary>
        [Test]
        public void ComputeStartupDelay_MismoSeed_ResultadoReproducible()
        {
            // Arrange
            var utcNow = new DateTime(2026, 6, 15, 12, 0, 0, DateTimeKind.Utc);
            var lastUpdate = utcNow.AddSeconds(-20);
            const int seed = 12345;

            // Act: ejecutar dos veces con el mismo seed
            var rng1 = new Random(seed);
            var (delayMs1, _) = JitterCalculator.ComputeStartupDelay(
                utcNow, lastUpdate, null, 45, rng1);

            var rng2 = new Random(seed);
            var (delayMs2, _) = JitterCalculator.ComputeStartupDelay(
                utcNow, lastUpdate, null, 45, rng2);

            // Assert: ambos resultados deben ser idénticos
            Assert.That(delayMs1, Is.EqualTo(delayMs2));
        }

        /// <summary>
        /// Verifica determinismo en ComputeReconnectionDelay con seed fijo.
        /// </summary>
        [Test]
        public void ComputeReconnectionDelay_MismoSeed_ResultadoReproducible()
        {
            // Arrange
            const int seed = 99;

            // Act
            var rng1 = new Random(seed);
            var delay1 = JitterCalculator.ComputeReconnectionDelay(60, rng1);

            var rng2 = new Random(seed);
            var delay2 = JitterCalculator.ComputeReconnectionDelay(60, rng2);

            // Assert
            Assert.That(delay1, Is.EqualTo(delay2));
        }

        // ===================================================================
        // ComputeStartupDelay: Solo restart reciente (sin update)
        // ===================================================================

        /// <summary>
        /// Solo lastRestartTimestamp reciente (update null) → reason = "post-restart".
        /// Verifica el flujo cuando solo hay reinicio reciente.
        /// </summary>
        [Test]
        public void ComputeStartupDelay_SoloRestartReciente_ReasonPostRestart()
        {
            // Arrange
            var utcNow = new DateTime(2026, 6, 15, 12, 0, 0, DateTimeKind.Utc);
            var lastRestart = utcNow.AddSeconds(-15);
            var rng = new Random(42);

            // Act
            var (delayMs, reason) = JitterCalculator.ComputeStartupDelay(
                utcNow, null, lastRestart, 30, rng);

            // Assert
            Assert.That(delayMs, Is.GreaterThanOrEqualTo(0));
            Assert.That(delayMs, Is.LessThan(30000));
            Assert.That(reason, Is.EqualTo("post-restart"));
        }

        // ===================================================================
        // ComputeStartupDelay: Jitter window inválido con timestamp reciente
        // ===================================================================

        /// <summary>
        /// Timestamp reciente + window fuera de rango → normaliza window a 30 y aplica jitter.
        /// Verifica que NormalizeJitterWindow se aplica internamente.
        /// </summary>
        [Test]
        public void ComputeStartupDelay_WindowInvalido_NormalizaYAplicaJitter()
        {
            // Arrange
            var utcNow = new DateTime(2026, 6, 15, 12, 0, 0, DateTimeKind.Utc);
            var lastUpdate = utcNow.AddSeconds(-20);
            var rng = new Random(42);

            // Act: window = 999 (fuera de rango) → normaliza a 30
            var (delayMs, reason) = JitterCalculator.ComputeStartupDelay(
                utcNow, lastUpdate, null, 999, rng);

            // Assert: delay en [0, 30000) porque se normaliza a 30
            Assert.That(delayMs, Is.GreaterThanOrEqualTo(0));
            Assert.That(delayMs, Is.LessThan(30000));
            Assert.That(reason, Is.EqualTo("post-update"));
        }
    }
}
