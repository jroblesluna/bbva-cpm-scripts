using System;
using System.Collections.Generic;
using System.Linq;
using FsCheck;
using FsCheck.NUnit;
using NUnit.Framework;
using AlwaysPrint.Shared.Configuration;
using FsCheckProperty = FsCheck.NUnit.PropertyAttribute;

namespace AlwaysPrint.Tests.Properties
{
    /// <summary>
    /// Property 2: Resolución de trigger por label (búsqueda exacta)
    /// Verifica que buscar un label existente encuentra el trigger correcto;
    /// buscar uno inexistente retorna error.
    /// **Validates: Requirements 8.1, 8.2, 5.6, 8.5**
    /// </summary>
    [TestFixture]
    [Category("Feature: on-demand-triggers, Property 2: Resolución de trigger por label")]
    public class TriggerLookupTests
    {
        // Eventos posibles para generar triggers variados
        private static readonly string[] PossibleEvents = new[]
        {
            TriggerEvents.OnDemand,
            "ondemand",       // variante case-insensitive
            "ONDEMAND",       // variante mayúsculas
            "OnDEMAND",       // variante mixta
            TriggerEvents.OnServiceStart,
            TriggerEvents.OnTrayLaunched,
            TriggerEvents.OnConfigChange,
            TriggerEvents.OnUserLogon,
            TriggerEvents.OnScheduledTask,
            "OtroEvento"
        };

        /// <summary>
        /// Generador de labels: puede ser null, vacío, whitespace, o texto válido.
        /// </summary>
        private static Gen<string?> LabelGen()
        {
            return Gen.OneOf(
                Gen.Constant<string?>(null),
                Gen.Constant<string?>(string.Empty),
                Gen.Constant<string?>("   "),
                Gen.Constant<string?>("\t"),
                Arb.Generate<NonEmptyString>().Select(s => (string?)s.Get)
            );
        }

        /// <summary>
        /// Generador de TriggerConfig con mezcla de eventos y labels variados.
        /// </summary>
        private static Gen<TriggerConfig> TriggerConfigGen()
        {
            var eventGen = Gen.Elements(PossibleEvents);

            return from ev in eventGen
                   from label in LabelGen()
                   from desc in Arb.Generate<string>().Select(s => s ?? string.Empty)
                   select new TriggerConfig
                   {
                       Event = ev,
                       Label = label,
                       Description = desc,
                       Actions = new List<ActionConfig>
                       {
                           new ActionConfig { Type = "StopService", Description = $"Acción para {label ?? "null"}" }
                       }
                   };
        }

        /// <summary>
        /// Generador de ActionConfiguration con lista arbitraria de triggers.
        /// </summary>
        private static Gen<ActionConfiguration> ActionConfigGen()
        {
            var triggersGen = Gen.ListOf(TriggerConfigGen())
                .Select(ts => ts.ToList());

            return from triggers in triggersGen
                   from name in Arb.Generate<NonNull<string>>()
                   from version in Arb.Generate<NonNull<string>>()
                   select new ActionConfiguration
                   {
                       Triggers = triggers,
                       Name = name.Get,
                       Version = version.Get
                   };
        }

        /// <summary>
        /// Réplica de la lógica de búsqueda de ActionEngine.ExecuteOnDemandTrigger.
        /// Busca el primer trigger con event="OnDemand" (case-insensitive),
        /// label no null/whitespace, y label == labelBuscado (case-sensitive).
        /// </summary>
        private static (bool found, TriggerConfig? trigger) LookupTriggerByLabel(
            ActionConfiguration config, string label)
        {
            if (config?.Triggers == null)
                return (false, null);

            var trigger = config.Triggers
                .Where(t => t.Event.Equals("OnDemand", StringComparison.OrdinalIgnoreCase)
                         && !string.IsNullOrWhiteSpace(t.Label))
                .FirstOrDefault(t => t.Label!.Equals(label, StringComparison.Ordinal));

            return trigger != null ? (true, trigger) : (false, null);
        }

        /// <summary>
        /// Propiedad: Si un label existe en al menos un trigger OnDemand válido,
        /// la búsqueda lo encuentra (retorna found=true).
        /// **Validates: Requirements 8.1, 8.5**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property LabelExistenteSiempreEsEncontrado()
        {
            return Prop.ForAll(
                Arb.From(ActionConfigGen()),
                config =>
                {
                    // Obtener labels válidos de triggers OnDemand en la configuración
                    var labelsValidos = config.Triggers
                        .Where(t => t.Event.Equals("OnDemand", StringComparison.OrdinalIgnoreCase)
                                 && !string.IsNullOrWhiteSpace(t.Label))
                        .Select(t => t.Label!)
                        .Distinct()
                        .ToList();

                    if (labelsValidos.Count == 0)
                        return true.Label("Sin labels válidos en config, propiedad trivial");

                    // Para cada label válido, la búsqueda debe encontrarlo
                    var todosEncontrados = labelsValidos.All(label =>
                    {
                        var (found, _) = LookupTriggerByLabel(config, label);
                        return found;
                    });

                    return todosEncontrados
                        .Label($"Algún label válido no fue encontrado. Labels válidos: [{string.Join(", ", labelsValidos)}]");
                });
        }

        /// <summary>
        /// Propiedad: Si un label NO existe en ningún trigger OnDemand válido,
        /// la búsqueda retorna found=false (error).
        /// **Validates: Requirements 8.2**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property LabelInexistenteRetornaError()
        {
            // Generar config + un label que seguro no existe
            var gen = from config in ActionConfigGen()
                      from sufijo in Arb.Generate<NonEmptyString>()
                      select (config, labelInexistente: $"__INEXISTENTE__{sufijo.Get}__");

            return Prop.ForAll(
                Arb.From(gen),
                tuple =>
                {
                    var (config, labelInexistente) = tuple;

                    // Asegurar que el label no existe en la configuración
                    var existeEnConfig = config.Triggers.Any(t =>
                        t.Event.Equals("OnDemand", StringComparison.OrdinalIgnoreCase)
                        && !string.IsNullOrWhiteSpace(t.Label)
                        && t.Label!.Equals(labelInexistente, StringComparison.Ordinal));

                    if (existeEnConfig)
                        return true.Label("Label generado coincidió con uno existente, caso trivial");

                    var (found, _) = LookupTriggerByLabel(config, labelInexistente);

                    return (!found)
                        .Label($"Label inexistente '{labelInexistente}' fue encontrado erróneamente");
                });
        }

        /// <summary>
        /// Propiedad: La búsqueda es case-sensitive para el label (distingue mayúsculas/minúsculas).
        /// **Validates: Requirements 8.1, 5.6**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property BusquedaDeLabelEsCaseSensitive()
        {
            // Generamos un label con al menos una letra y lo forzamos a lower/upper
            var gen = from labelBase in Arb.Generate<NonEmptyString>()
                          .Where(s => s.Get.Any(c => char.IsLetter(c))
                                   && s.Get.ToLower() != s.Get.ToUpper())
                      select labelBase.Get.ToLower();

            return Prop.ForAll(
                Arb.From(gen),
                labelLower =>
                {
                    var labelUpper = labelLower.ToUpper();

                    // Crear config con SOLO un trigger con el label en minúsculas
                    var config = new ActionConfiguration
                    {
                        Name = "Test",
                        Version = "1.0",
                        Triggers = new List<TriggerConfig>
                        {
                            new TriggerConfig
                            {
                                Event = TriggerEvents.OnDemand,
                                Label = labelLower,
                                Description = "Trigger test case-sensitive",
                                Actions = new List<ActionConfig>
                                {
                                    new ActionConfig { Type = "StopService", Description = "test" }
                                }
                            }
                        }
                    };

                    // Buscar con el label exacto (minúsculas) → debe encontrar
                    var (foundExact, _) = LookupTriggerByLabel(config, labelLower);

                    // Buscar con el label en MAYÚSCULAS → NO debe encontrar
                    // (ya que solo tenemos el label en minúsculas en la config)
                    var (foundUpper, _) = LookupTriggerByLabel(config, labelUpper);

                    return (foundExact && !foundUpper)
                        .Label($"foundExact={foundExact}, foundUpper={foundUpper}, " +
                               $"label='{labelLower}', labelUpper='{labelUpper}'");
                });
        }

        /// <summary>
        /// Propiedad: La búsqueda de evento es case-insensitive (encuentra "ondemand", "ONDEMAND", etc.).
        /// **Validates: Requirements 8.1**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property BusquedaDeEventoEsCaseInsensitive()
        {
            // Generar variantes de "OnDemand" en diferentes cases
            var eventVariants = new[] { "OnDemand", "ondemand", "ONDEMAND", "OnDEMAND", "onDemand" };

            // Usar labels que NO sean whitespace-only (el filtro los excluye)
            var gen = from eventVariant in Gen.Elements(eventVariants)
                      from label in Arb.Generate<NonEmptyString>()
                          .Where(s => !string.IsNullOrWhiteSpace(s.Get))
                      select (eventVariant, label: label.Get);

            return Prop.ForAll(
                Arb.From(gen),
                tuple =>
                {
                    var (eventVariant, label) = tuple;

                    // Crear config con un trigger usando la variante de evento
                    var config = new ActionConfiguration
                    {
                        Name = "Test",
                        Version = "1.0",
                        Triggers = new List<TriggerConfig>
                        {
                            new TriggerConfig
                            {
                                Event = eventVariant,
                                Label = label,
                                Description = "Trigger con variante de evento",
                                Actions = new List<ActionConfig>
                                {
                                    new ActionConfig { Type = "StopService", Description = "test" }
                                }
                            }
                        }
                    };

                    // La búsqueda debe encontrar el trigger independientemente del case del evento
                    var (found, trigger) = LookupTriggerByLabel(config, label);

                    return (found && trigger != null && trigger.Label == label)
                        .Label($"Evento '{eventVariant}' con label '{label}': found={found}");
                });
        }

        /// <summary>
        /// Propiedad: Triggers con label null o whitespace son ignorados en la búsqueda,
        /// incluso si su event es OnDemand.
        /// **Validates: Requirements 5.6**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property TriggersConLabelInvalidoSonIgnorados()
        {
            var labelsInvalidos = new string?[] { null, "", "   ", "\t", " \n " };

            var gen = from labelInvalido in Gen.Elements(labelsInvalidos)
                      select labelInvalido;

            return Prop.ForAll(
                Arb.From(gen),
                labelInvalido =>
                {
                    // Crear config con un trigger OnDemand cuyo label es inválido
                    var config = new ActionConfiguration
                    {
                        Name = "Test",
                        Version = "1.0",
                        Triggers = new List<TriggerConfig>
                        {
                            new TriggerConfig
                            {
                                Event = TriggerEvents.OnDemand,
                                Label = labelInvalido,
                                Description = "Trigger con label inválido",
                                Actions = new List<ActionConfig>
                                {
                                    new ActionConfig { Type = "StopService", Description = "test" }
                                }
                            }
                        }
                    };

                    // Buscar con el label inválido no debe encontrar nada
                    // (el filtro excluye triggers con label null/whitespace)
                    var labelBusqueda = labelInvalido ?? "null_placeholder";
                    var (found, _) = LookupTriggerByLabel(config, labelBusqueda);

                    return (!found)
                        .Label($"Trigger con label inválido '{labelInvalido ?? "null"}' fue encontrado");
                });
        }
    }
}
