using FsCheck;
using FsCheck.NUnit;
using NUnit.Framework;
using AlwaysPrintTray.OnDemand;
using FsCheckProperty = FsCheck.NUnit.PropertyAttribute;

namespace AlwaysPrint.Tests.Properties
{
    /// <summary>
    /// Property 4: Formato de display de configuración activa
    /// Para cualquier ActionConfiguration con Name y Version no vacíos,
    /// el texto de display generado debe ser exactamente "{Name} v{Version}".
    /// **Validates: Requirements 2.5**
    /// </summary>
    [TestFixture]
    [Category("Feature: on-demand-triggers, Property 4: Formato de display de configuración activa")]
    public class DisplayFormatTests
    {
        /// <summary>
        /// Generador de strings no vacíos (sin whitespace-only).
        /// Filtra strings que no sean null, vacíos ni solo espacios.
        /// </summary>
        private static Arbitrary<string> NonEmptyStringArbitrary()
        {
            return Arb.From(
                Arb.Generate<NonEmptyString>()
                    .Where(s => !string.IsNullOrWhiteSpace(s.Get))
                    .Select(s => s.Get));
        }

        /// <summary>
        /// Propiedad: Para cualquier par (name, version) no vacío,
        /// FormatConfigDisplay produce exactamente "{name} v{version}".
        /// **Validates: Requirements 2.5**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property ConfigDisplay_Format_IsExactly_Name_v_Version()
        {
            return Prop.ForAll(
                NonEmptyStringArbitrary(),
                NonEmptyStringArbitrary(),
                (name, version) =>
                {
                    // Generar el texto de display
                    var result = StatusDisplayHelper.FormatConfigDisplay(name, version);

                    // El formato esperado es exactamente "{name} v{version}"
                    var expected = $"{name} v{version}";

                    return (result == expected)
                        .Label($"Esperado: '{expected}', Actual: '{result}'");
                });
        }
    }
}
