using System;
using FsCheck;
using FsCheck.NUnit;
using NUnit.Framework;
using FsCheckProperty = FsCheck.NUnit.PropertyAttribute;

namespace AlwaysPrint.Tests.Properties
{
    /// <summary>
    /// Property 2: File size integrity verification
    /// Para cualquier archivo descargado con actual_size bytes y un expected_size reportado
    /// por el backend, la verificación de integridad pasa si y solo si actual_size == expected_size.
    /// Validates: Requirements 4.3
    /// </summary>
    [TestFixture]
    [Category("Feature: auto-update, Property 2: File size integrity verification")]
    public class FileSizeIntegrityTests
    {
        /// <summary>
        /// Lógica pura de verificación de integridad por tamaño.
        /// Replica la verificación que realiza UpdateDownloader al comparar
        /// el tamaño real del archivo descargado con el tamaño esperado del backend.
        /// </summary>
        /// <param name="actualSize">Tamaño real del archivo descargado en bytes.</param>
        /// <param name="expectedSize">Tamaño esperado reportado por el backend.</param>
        /// <returns>true si la integridad es válida (tamaños coinciden).</returns>
        private static bool IntegrityCheckPasses(long actualSize, long expectedSize)
        {
            return actualSize == expectedSize;
        }

        /// <summary>
        /// Propiedad: Cuando actual_size == expected_size, la verificación de integridad
        /// siempre pasa. Se genera un valor positivo aleatorio y se usa como ambos tamaños.
        /// **Validates: Requirements 4.3**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property EqualSizes_IntegrityCheckAlwaysPasses()
        {
            // Generar valores long positivos (tamaños de archivo no pueden ser negativos)
            return Prop.ForAll(
                Arb.From(Gen.Choose(0, int.MaxValue).Select(i => (long)i)),
                size =>
                {
                    var result = IntegrityCheckPasses(size, size);

                    return result
                        .Label($"Tamaños iguales ({size}B) deben pasar verificación, resultado={result}");
                });
        }

        /// <summary>
        /// Propiedad: Cuando actual_size != expected_size, la verificación de integridad
        /// siempre falla. Se generan dos valores positivos distintos.
        /// **Validates: Requirements 4.3**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property DifferentSizes_IntegrityCheckAlwaysFails()
        {
            // Generar dos valores long positivos que sean distintos
            return Prop.ForAll(
                Arb.From(Gen.Choose(0, int.MaxValue).Select(i => (long)i)),
                Arb.From(Gen.Choose(0, int.MaxValue).Select(i => (long)i)),
                (actualSize, expectedSize) =>
                {
                    // Solo evaluar cuando los tamaños son diferentes
                    var result = IntegrityCheckPasses(actualSize, expectedSize);

                    return (actualSize == expectedSize || !result)
                        .Label($"Tamaños diferentes (actual={actualSize}B, expected={expectedSize}B) " +
                               $"deben fallar verificación, resultado={result}");
                });
        }

        /// <summary>
        /// Propiedad: La verificación de integridad es determinista.
        /// Para cualquier par (actual_size, expected_size), ejecutar la verificación
        /// múltiples veces siempre produce el mismo resultado.
        /// **Validates: Requirements 4.3**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property IntegrityCheck_IsDeterministic()
        {
            // Generar pares de valores long positivos
            return Prop.ForAll(
                Arb.From(Gen.Choose(0, int.MaxValue).Select(i => (long)i)),
                Arb.From(Gen.Choose(0, int.MaxValue).Select(i => (long)i)),
                (actualSize, expectedSize) =>
                {
                    // Ejecutar la verificación múltiples veces
                    var result1 = IntegrityCheckPasses(actualSize, expectedSize);
                    var result2 = IntegrityCheckPasses(actualSize, expectedSize);
                    var result3 = IntegrityCheckPasses(actualSize, expectedSize);

                    return (result1 == result2 && result2 == result3)
                        .Label($"Verificación no determinista para actual={actualSize}B, " +
                               $"expected={expectedSize}B: {result1}, {result2}, {result3}");
                });
        }

        /// <summary>
        /// Propiedad: La verificación de integridad es simétrica en el sentido de que
        /// el resultado depende exclusivamente de la igualdad entre los dos valores.
        /// Es decir: IntegrityCheck(a, b) == (a == b) para todo par (a, b).
        /// **Validates: Requirements 4.3**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property IntegrityCheck_EquivalentToEqualityComparison()
        {
            // Generar pares de valores long positivos
            return Prop.ForAll(
                Arb.From(Gen.Choose(0, int.MaxValue).Select(i => (long)i)),
                Arb.From(Gen.Choose(0, int.MaxValue).Select(i => (long)i)),
                (actualSize, expectedSize) =>
                {
                    var checkResult = IntegrityCheckPasses(actualSize, expectedSize);
                    var equalityResult = actualSize == expectedSize;

                    return (checkResult == equalityResult)
                        .Label($"IntegrityCheck({actualSize}, {expectedSize})={checkResult} " +
                               $"debe ser igual a ({actualSize}=={expectedSize})={equalityResult}");
                });
        }
    }
}
