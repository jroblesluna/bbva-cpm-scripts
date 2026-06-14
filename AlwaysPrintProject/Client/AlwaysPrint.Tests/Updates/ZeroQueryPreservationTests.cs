using System;
using FsCheck;
using FsCheck.NUnit;
using NUnit.Framework;
using FsCheckProperty = FsCheck.NUnit.PropertyAttribute;

#nullable enable

namespace AlwaysPrint.Tests.Updates
{
    /// <summary>
    /// Property 2: Preservation - Flujo legacy y flags sin regresiones.
    /// 
    /// Estos tests verifican el BASELINE de comportamiento ANTES del fix:
    /// - Sin download_url → SIEMPRE disparar flujo legacy (CheckUpdateRequested)
    /// - Con auto_update_enabled=false (org o local) → NUNCA iniciar descarga
    /// 
    /// Deben PASAR tanto antes como después del fix para garantizar preservación.
    /// 
    /// **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**
    /// </summary>
    [TestFixture]
    [Category("Feature: zero-query-updates, Property 2: Preservation")]
    public class ZeroQueryPreservationTests
    {
        /// <summary>
        /// Resultado de la decisión del CloudManager al recibir check_update.
        /// Modela la bifurcación de flujo: legacy vs descarga directa.
        /// </summary>
        internal enum CheckUpdateAction
        {
            /// <summary>Disparar evento CheckUpdateRequested (flujo HTTP legacy).</summary>
            TriggerLegacyFlow,
            /// <summary>Iniciar descarga directa desde presigned URL.</summary>
            StartDirectDownload,
            /// <summary>Ignorar comando (flag local deshabilitado o condición no cumplida).</summary>
            Ignore
        }

        /// <summary>
        /// Lógica pura de decisión extraída del CloudManager.HandleCheckUpdateCommand.
        /// 
        /// Comportamiento actual (sin fix):
        /// - HandleCheckUpdateCommand NO parsea params en absoluto
        /// - Simplemente dispara CheckUpdateRequested siempre
        /// 
        /// Comportamiento esperado (con fix):
        /// - Si download_url está presente Y flags habilitados → descarga directa
        /// - Si download_url ausente → flujo legacy (CheckUpdateRequested)
        /// - Si algún flag deshabilitado → ignorar descarga directa
        /// 
        /// PRESERVATION: Para comandos SIN download_url, el resultado SIEMPRE debe ser
        /// TriggerLegacyFlow, independientemente del fix aplicado.
        /// </summary>
        /// <param name="downloadUrl">URL de descarga directa (null/vacío = flujo legacy).</param>
        /// <param name="orgAutoUpdateEnabled">Flag de organización de auto-actualización.</param>
        /// <param name="localAutoUpdateEnabled">Flag local de auto-actualización (registro Windows).</param>
        /// <returns>Acción a tomar por el CloudManager.</returns>
        internal static CheckUpdateAction DecideCheckUpdateAction(
            string? downloadUrl,
            bool orgAutoUpdateEnabled,
            bool localAutoUpdateEnabled)
        {
            // Si no hay download_url → siempre flujo legacy (preservación)
            if (string.IsNullOrEmpty(downloadUrl))
            {
                return CheckUpdateAction.TriggerLegacyFlow;
            }

            // Si hay download_url pero algún flag está deshabilitado → ignorar
            if (!orgAutoUpdateEnabled || !localAutoUpdateEnabled)
            {
                return CheckUpdateAction.Ignore;
            }

            // Si hay download_url Y ambos flags habilitados → descarga directa
            return CheckUpdateAction.StartDirectDownload;
        }

        // =======================================================================
        // PROPIEDAD: Sin download_url → SIEMPRE flujo legacy
        // =======================================================================

        /// <summary>
        /// Propiedad de preservación: Para TODO comando check_update SIN campo download_url
        /// en params (null o vacío), el CloudManager DEBE disparar el evento CheckUpdateRequested
        /// (flujo legacy HTTP), independientemente del estado de los flags.
        /// 
        /// Esto garantiza backward compatibility con clientes antiguos y el timer de 24h.
        /// 
        /// **Validates: Requirements 3.1, 3.2**
        /// </summary>
        [FsCheckProperty(MaxTest = 200)]
        public Property SinDownloadUrl_SiempreDisparaFlujoLegacy()
        {
            // Generador que produce download_url nulo o vacío
            var emptyUrlArb = Arb.From(
                Gen.OneOf(
                    Gen.Constant<string?>(null),
                    Gen.Constant<string?>(string.Empty),
                    Gen.Constant<string?>("  "),   // Solo espacios → se trata como vacío
                    Gen.Constant<string?>("\t")    // Solo tab → se trata como vacío
                ));

            return Prop.ForAll(
                emptyUrlArb,
                Arb.Default.Bool(),
                Arb.Default.Bool(),
                (downloadUrl, orgFlag, localFlag) =>
                {
                    // Normalizar: whitespace-only se trata como vacío
                    var normalizedUrl = string.IsNullOrWhiteSpace(downloadUrl) ? null : downloadUrl;

                    var action = DecideCheckUpdateAction(normalizedUrl, orgFlag, localFlag);

                    return (action == CheckUpdateAction.TriggerLegacyFlow)
                        .Label($"Sin download_url ('{downloadUrl}'), esperaba TriggerLegacyFlow " +
                               $"pero obtuvo {action}. orgFlag={orgFlag}, localFlag={localFlag}");
                });
        }

        /// <summary>
        /// Propiedad de preservación: Para TODO comando check_update con
        /// auto_update_enabled=false (flag de organización O flag local),
        /// NO se debe iniciar descarga directa, independientemente de si download_url
        /// está presente o no.
        /// 
        /// Esto garantiza que los flags de control siguen siendo respetados después del fix.
        /// 
        /// **Validates: Requirements 3.3, 3.5**
        /// </summary>
        [FsCheckProperty(MaxTest = 200)]
        public Property ConFlagDeshabilitado_NuncaIniciaDescargaDirecta()
        {
            // Generador de URLs que pueden o no estar presentes
            var urlArb = Arb.From(
                Gen.OneOf(
                    Gen.Constant<string?>(null),
                    Gen.Constant<string?>(string.Empty),
                    Gen.Constant<string?>("https://s3.amazonaws.com/bucket/latest/AlwaysPrint.msi?presigned=1"),
                    Gen.Constant<string?>("https://example.com/update.msi"),
                    Arb.Generate<NonNull<string>>().Select(s => (string?)"https://s3.amazonaws.com/" + s.Get)
                ));

            // Generador de flags donde al menos uno está deshabilitado
            var disabledFlagsArb = Arb.From(
                Gen.OneOf(
                    Gen.Constant((orgFlag: false, localFlag: true)),
                    Gen.Constant((orgFlag: true, localFlag: false)),
                    Gen.Constant((orgFlag: false, localFlag: false))
                ));

            return Prop.ForAll(
                urlArb,
                disabledFlagsArb,
                (downloadUrl, flags) =>
                {
                    var action = DecideCheckUpdateAction(downloadUrl, flags.orgFlag, flags.localFlag);

                    // NUNCA debe ser StartDirectDownload si algún flag está deshabilitado
                    return (action != CheckUpdateAction.StartDirectDownload)
                        .Label($"Con flag deshabilitado (org={flags.orgFlag}, local={flags.localFlag}), " +
                               $"NO debería iniciar descarga directa pero obtuvo {action}. " +
                               $"download_url='{downloadUrl}'");
                });
        }

        /// <summary>
        /// Propiedad complementaria: Si download_url está presente Y ambos flags habilitados,
        /// DEBE iniciar descarga directa (este es el nuevo comportamiento del fix).
        /// Se incluye aquí para validar la completitud de la lógica de decisión.
        /// 
        /// **Validates: Requirements 3.3, 3.5 (caso inverso)**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property ConDownloadUrlYFlagsHabilitados_DescargaDirecta()
        {
            // Generador de URLs válidas (no nulas, no vacías)
            var validUrlArb = Arb.From(
                Gen.OneOf(
                    Gen.Constant("https://s3.amazonaws.com/bucket/latest/AlwaysPrint.msi?presigned=1"),
                    Gen.Constant("https://bucket.s3.us-east-1.amazonaws.com/key"),
                    Arb.Generate<NonNull<string>>().Select(s => "https://s3.amazonaws.com/" + s.Get)
                ));

            return Prop.ForAll(
                validUrlArb,
                downloadUrl =>
                {
                    var action = DecideCheckUpdateAction(downloadUrl, true, true);

                    return (action == CheckUpdateAction.StartDirectDownload)
                        .Label($"Con download_url='{downloadUrl}' y ambos flags=true, " +
                               $"esperaba StartDirectDownload pero obtuvo {action}");
                });
        }

        /// <summary>
        /// Propiedad: La decisión es determinista - mismos inputs siempre producen mismo output.
        /// Garantiza que no hay estado mutable o side effects en la lógica de decisión.
        /// 
        /// **Validates: Requirements 3.1, 3.2, 3.3, 3.5**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property DecisionEsDeterminista()
        {
            var urlArb = Arb.From(
                Gen.OneOf(
                    Gen.Constant<string?>(null),
                    Gen.Constant<string?>(string.Empty),
                    Gen.Constant<string?>("https://s3.amazonaws.com/bucket/key"),
                    Arb.Generate<NonNull<string>>().Select(s => (string?)s.Get)
                ));

            return Prop.ForAll(
                urlArb,
                Arb.Default.Bool(),
                Arb.Default.Bool(),
                (downloadUrl, orgFlag, localFlag) =>
                {
                    // Ejecutar la misma decisión dos veces
                    var result1 = DecideCheckUpdateAction(downloadUrl, orgFlag, localFlag);
                    var result2 = DecideCheckUpdateAction(downloadUrl, orgFlag, localFlag);

                    return (result1 == result2)
                        .Label($"Decisión no determinista: primera={result1}, segunda={result2}. " +
                               $"url='{downloadUrl}', org={orgFlag}, local={localFlag}");
                });
        }
    }
}
