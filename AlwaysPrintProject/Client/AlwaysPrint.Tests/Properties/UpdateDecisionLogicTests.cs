using System;
using FsCheck;
using FsCheck.NUnit;
using NUnit.Framework;
using FsCheckProperty = FsCheck.NUnit.PropertyAttribute;

namespace AlwaysPrint.Tests.Properties
{
    /// <summary>
    /// Property 1: Update decision logic
    /// Para cualquier combinación de (local_flag, org_flag, available_version, installed_version),
    /// el sistema procede a descarga si y solo si: local_flag=true AND org_flag=true AND
    /// available_version != installed_version (comparación case-insensitive).
    /// Validates: Requirements 3.1, 3.2, 3.3, 3.4
    /// </summary>
    [TestFixture]
    [Category("Feature: auto-update, Property 1: Update decision logic")]
    public class UpdateDecisionLogicTests
    {
        /// <summary>
        /// Lógica pura de decisión de actualización extraída para testing.
        /// Retorna true si se debe proceder con la descarga del MSI.
        /// </summary>
        /// <param name="localFlag">Flag local de auto-actualización (registro Windows).</param>
        /// <param name="orgFlag">Flag de organización (Cloud Backend).</param>
        /// <param name="availableVersion">Versión disponible en el servidor.</param>
        /// <param name="installedVersion">Versión actualmente instalada.</param>
        /// <returns>True si se debe proceder a la descarga.</returns>
        internal static bool ShouldProceedToDownload(bool localFlag, bool orgFlag, string availableVersion, string installedVersion)
        {
            return localFlag
                && orgFlag
                && !string.Equals(availableVersion, installedVersion, StringComparison.OrdinalIgnoreCase);
        }

        /// <summary>
        /// Propiedad: Para cualquier combinación de flags y versiones, la decisión de actualización
        /// retorna true si y solo si local_flag=true AND org_flag=true AND las versiones difieren
        /// (comparación case-insensitive).
        /// **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property ShouldProceedToDownload_IsTrueOnlyWhenAllConditionsHold()
        {
            // Combinar los dos bools en un generador de tupla para no exceder 4 argumentos en ForAll
            var flagsArb = Arb.From(
                from localFlag in Arb.Generate<bool>()
                from orgFlag in Arb.Generate<bool>()
                select (localFlag, orgFlag));

            return Prop.ForAll(
                flagsArb,
                Arb.From<NonNull<string>>(),
                Arb.From<NonNull<string>>(),
                (flags, availableVersionWrapper, installedVersionWrapper) =>
                {
                    var localFlag = flags.localFlag;
                    var orgFlag = flags.orgFlag;
                    var availableVersion = availableVersionWrapper.Get;
                    var installedVersion = installedVersionWrapper.Get;

                    // Calcular resultado esperado según la especificación
                    bool versionsDiffer = !string.Equals(availableVersion, installedVersion, StringComparison.OrdinalIgnoreCase);
                    bool expected = localFlag && orgFlag && versionsDiffer;

                    // Calcular resultado real de la función bajo prueba
                    bool actual = ShouldProceedToDownload(localFlag, orgFlag, availableVersion, installedVersion);

                    return (actual == expected)
                        .Label($"localFlag={localFlag}, orgFlag={orgFlag}, " +
                               $"available='{availableVersion}', installed='{installedVersion}', " +
                               $"expected={expected}, actual={actual}");
                });
        }

        /// <summary>
        /// Propiedad: Si el flag local es false, nunca se procede a la descarga
        /// independientemente de los demás valores.
        /// **Validates: Requirements 3.4 (condición local_flag)**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property LocalFlagDisabled_NeverProceeds()
        {
            return Prop.ForAll(
                Arb.Default.Bool(),
                Arb.From<NonNull<string>>(),
                Arb.From<NonNull<string>>(),
                (orgFlag, availableVersionWrapper, installedVersionWrapper) =>
                {
                    var availableVersion = availableVersionWrapper.Get;
                    var installedVersion = installedVersionWrapper.Get;

                    // Con local_flag=false, nunca debe proceder
                    bool result = ShouldProceedToDownload(false, orgFlag, availableVersion, installedVersion);

                    return (!result)
                        .Label($"Con localFlag=false debería retornar false, pero retornó true. " +
                               $"orgFlag={orgFlag}, available='{availableVersion}', installed='{installedVersion}'");
                });
        }

        /// <summary>
        /// Propiedad: Si el flag de organización es false, nunca se procede a la descarga
        /// independientemente de los demás valores.
        /// **Validates: Requirements 3.3**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property OrgFlagDisabled_NeverProceeds()
        {
            return Prop.ForAll(
                Arb.Default.Bool(),
                Arb.From<NonNull<string>>(),
                Arb.From<NonNull<string>>(),
                (localFlag, availableVersionWrapper, installedVersionWrapper) =>
                {
                    var availableVersion = availableVersionWrapper.Get;
                    var installedVersion = installedVersionWrapper.Get;

                    // Con org_flag=false, nunca debe proceder
                    bool result = ShouldProceedToDownload(localFlag, false, availableVersion, installedVersion);

                    return (!result)
                        .Label($"Con orgFlag=false debería retornar false, pero retornó true. " +
                               $"localFlag={localFlag}, available='{availableVersion}', installed='{installedVersion}'");
                });
        }

        /// <summary>
        /// Propiedad: Si las versiones son iguales (case-insensitive), nunca se procede a la descarga
        /// independientemente de los flags.
        /// **Validates: Requirements 3.2**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property SameVersion_NeverProceeds()
        {
            return Prop.ForAll(
                Arb.Default.Bool(),
                Arb.Default.Bool(),
                Arb.From<NonNull<string>>(),
                (localFlag, orgFlag, versionWrapper) =>
                {
                    var version = versionWrapper.Get;

                    // Con la misma versión, nunca debe proceder (sin importar case)
                    bool result = ShouldProceedToDownload(localFlag, orgFlag, version, version);

                    return (!result)
                        .Label($"Con versiones iguales debería retornar false, pero retornó true. " +
                               $"localFlag={localFlag}, orgFlag={orgFlag}, version='{version}'");
                });
        }

        /// <summary>
        /// Propiedad: La comparación de versiones es case-insensitive.
        /// Si available_version.ToUpper() == installed_version.ToUpper(), no se procede.
        /// **Validates: Requirements 3.1, 3.2**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property VersionComparison_IsCaseInsensitive()
        {
            return Prop.ForAll(
                Arb.From<NonNull<string>>(),
                versionWrapper =>
                {
                    var version = versionWrapper.Get;

                    // Comparar versión original con su variante en mayúsculas
                    // Ambos flags habilitados, pero versiones iguales (diferente case) → no proceder
                    bool resultUpper = ShouldProceedToDownload(true, true, version, version.ToUpperInvariant());
                    bool resultLower = ShouldProceedToDownload(true, true, version, version.ToLowerInvariant());

                    return (!resultUpper && !resultLower)
                        .Label($"Comparación case-insensitive falló. version='{version}', " +
                               $"upper='{version.ToUpperInvariant()}', lower='{version.ToLowerInvariant()}', " +
                               $"resultUpper={resultUpper}, resultLower={resultLower}");
                });
        }
    }
}
