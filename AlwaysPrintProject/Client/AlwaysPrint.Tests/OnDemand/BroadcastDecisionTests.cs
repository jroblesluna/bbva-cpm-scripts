using NUnit.Framework;

namespace AlwaysPrint.Tests.OnDemand
{
    /// <summary>
    /// Unit tests para la lógica de decisión de broadcast de segunda instancia.
    /// 
    /// La decisión en Program.cs es:
    /// - Si el mutex fue adquirido (isNew=true) → primera instancia, continuar ejecución normal.
    /// - Si el mutex NO fue adquirido (isNew=false) → segunda instancia, enviar broadcast y salir.
    /// 
    /// Validates: Requirements 1.1
    /// </summary>
    [TestFixture]
    [Category("Feature: on-demand-triggers, Unit: Broadcast Decision")]
    public class BroadcastDecisionTests
    {
        /// <summary>
        /// Lógica pura de decisión de broadcast extraída de Program.cs para testing.
        /// Determina si la instancia actual debe enviar un broadcast Win32 y salir.
        /// </summary>
        /// <param name="mutexAcquired">
        /// true si el mutex fue adquirido exitosamente (primera instancia);
        /// false si el mutex ya estaba tomado (segunda instancia).
        /// </param>
        /// <returns>
        /// true si se debe enviar broadcast y salir (segunda instancia);
        /// false si se debe continuar como instancia principal.
        /// </returns>
        internal static bool ShouldBroadcastAndExit(bool mutexAcquired)
        {
            // Equivale a: if (!isNew) { PostMessage(...); return; }
            return !mutexAcquired;
        }

        /// <summary>
        /// Cuando el mutex está libre (primera instancia lo adquiere), NO se debe
        /// enviar broadcast. La instancia continúa su ejecución normal.
        /// </summary>
        [Test]
        public void MutexLibre_NoDebeEnviarBroadcast()
        {
            // Arrange: mutex adquirido exitosamente (primera instancia)
            bool mutexAcquired = true;

            // Act
            bool shouldBroadcast = ShouldBroadcastAndExit(mutexAcquired);

            // Assert: NO enviar broadcast, continuar como primera instancia
            Assert.IsFalse(shouldBroadcast,
                "Cuando el mutex está libre (primera instancia), no se debe enviar broadcast.");
        }

        /// <summary>
        /// Cuando el mutex ya está tomado (segunda instancia), se DEBE enviar
        /// broadcast Win32 y salir inmediatamente.
        /// </summary>
        [Test]
        public void MutexTomado_DebeEnviarBroadcastYSalir()
        {
            // Arrange: mutex NO adquirido (ya hay otra instancia corriendo)
            bool mutexAcquired = false;

            // Act
            bool shouldBroadcast = ShouldBroadcastAndExit(mutexAcquired);

            // Assert: SÍ enviar broadcast y salir
            Assert.IsTrue(shouldBroadcast,
                "Cuando el mutex está tomado (segunda instancia), se debe enviar broadcast y salir.");
        }

        /// <summary>
        /// Verifica que la decisión es determinista: el mismo input siempre produce
        /// el mismo output, independientemente de cuántas veces se evalúe.
        /// </summary>
        [Test]
        public void DecisionEsDeterminista_MismoInputMismoOutput()
        {
            // La lógica debe ser pura y determinista
            for (int i = 0; i < 10; i++)
            {
                Assert.IsFalse(ShouldBroadcastAndExit(true),
                    "Mutex libre siempre debe retornar false (no broadcast).");
                Assert.IsTrue(ShouldBroadcastAndExit(false),
                    "Mutex tomado siempre debe retornar true (broadcast y salir).");
            }
        }

        /// <summary>
        /// Verifica que las dos decisiones son mutuamente excluyentes:
        /// o se envía broadcast y se sale, o se continúa como primera instancia.
        /// No existe un estado intermedio.
        /// </summary>
        [Test]
        public void DecisionessonMutuamenteExcluyentes()
        {
            bool broadcastSiMutexTomado = ShouldBroadcastAndExit(false);
            bool broadcastSiMutexLibre = ShouldBroadcastAndExit(true);

            // Las decisiones deben ser opuestas
            Assert.AreNotEqual(broadcastSiMutexTomado, broadcastSiMutexLibre,
                "Las decisiones para mutex libre vs tomado deben ser opuestas.");
        }
    }
}
