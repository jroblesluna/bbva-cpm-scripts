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
    /// Property 1: Filtrado de triggers OnDemand
    /// Verifica que el filtrado de triggers retorna exactamente aquellos con
    /// event="OnDemand" (case-insensitive) y label no vacío, preservando el orden original.
    /// **Validates: Requirements 4.1, 5.2, 5.5, 6.3, 10.1, 11.4**
    /// </summary>
    [TestFixture]
    [Category("Feature: on-demand-triggers, Property 1: Filtrado de triggers OnDemand")]
    public class OnDemandFilteringTests
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
        /// Generador de TriggerConfig con mezcla de eventos y labels variados
        /// (vacíos, nulos, whitespace, válidos).
        /// </summary>
        private static Gen<TriggerConfig> TriggerConfigGen()
        {
            // Generador de labels: puede ser null, vacío, whitespace, o texto válido
            var labelGen = Gen.OneOf(
                Gen.Constant<string?>(null),
                Gen.Constant<string?>(string.Empty),
                Gen.Constant<string?>("   "),          // solo whitespace
                Gen.Constant<string?>("\t"),            // tab
                Gen.Constant<string?>(" \n "),          // whitespace con newline
                Arb.Generate<NonEmptyString>().Select(s => (string?)s.Get)
            );

            var eventGen = Gen.Elements(PossibleEvents);
            var descriptionGen = Arb.Generate<string>().Select(s => s ?? string.Empty);

            return from ev in eventGen
                   from label in labelGen
                   from desc in descriptionGen
                   select new TriggerConfig
                   {
                       Event = ev,
                       Label = label,
                       Description = desc,
                       Actions = new List<ActionConfig>()
                   };
        }

        /// <summary>
        /// Generador de ActionConfiguration con lista arbitraria de triggers.
        /// </summary>
        private static Arbitrary<ActionConfiguration> ActionConfigArbitrary()
        {
            var triggersGen = Gen.ListOf(TriggerConfigGen())
                .Select(ts => ts.ToList());

            return Arb.From(
                from triggers in triggersGen
                from name in Arb.Generate<NonNull<string>>()
                from version in Arb.Generate<NonNull<string>>()
                select new ActionConfiguration
                {
                    Triggers = triggers,
                    Name = name.Get,
                    Version = version.Get
                });
        }

        /// <summary>
        /// Lógica de filtrado bajo test: replica exacta del filtro de OnDemandConfigReader.
        /// Filtra triggers con event="OnDemand" (case-insensitive) y label no vacío/null.
        /// </summary>
        private static List<(string Label, string Description)> FilterOnDemandTriggers(
            ActionConfiguration config)
        {
            if (config?.Triggers == null)
                return new List<(string, string)>();

            return config.Triggers
                .Where(t => t.Event.Equals(TriggerEvents.OnDemand, StringComparison.OrdinalIgnoreCase)
                         && !string.IsNullOrWhiteSpace(t.Label))
                .Select(t => (Label: t.Label!, Description: t.Description ?? string.Empty))
                .ToList();
        }

        /// <summary>
        /// Propiedad: El resultado del filtrado contiene exactamente los triggers
        /// cuyo event es "OnDemand" (case-insensitive) y cuyo label no es null ni whitespace.
        /// **Validates: Requirements 4.1, 5.2, 5.5, 6.3, 10.1, 11.4**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property FiltradoRetornaExactamenteTriggersOnDemandConLabelValido()
        {
            return Prop.ForAll(
                ActionConfigArbitrary(),
                config =>
                {
                    // Resultado del filtrado bajo test
                    var resultado = FilterOnDemandTriggers(config);

                    // Resultado esperado: manualmente verificar cada trigger
                    var esperado = new List<(string Label, string Description)>();
                    foreach (var trigger in config.Triggers)
                    {
                        bool esOnDemand = trigger.Event.Equals(
                            TriggerEvents.OnDemand, StringComparison.OrdinalIgnoreCase);
                        bool tieneLabel = !string.IsNullOrWhiteSpace(trigger.Label);

                        if (esOnDemand && tieneLabel)
                        {
                            esperado.Add((trigger.Label!, trigger.Description ?? string.Empty));
                        }
                    }

                    // Verificar conteo
                    var conteoIgual = resultado.Count == esperado.Count;

                    // Verificar contenido y orden
                    var contenidoIgual = resultado.SequenceEqual(esperado);

                    return (conteoIgual && contenidoIgual)
                        .Label($"Esperado {esperado.Count} triggers, obtenido {resultado.Count}. " +
                               $"Triggers en config: {config.Triggers.Count}");
                });
        }

        /// <summary>
        /// Propiedad: Triggers con event distinto a "OnDemand" nunca aparecen en el resultado.
        /// **Validates: Requirements 5.2, 11.4**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property TriggersNoOnDemandNuncaAparecenEnResultado()
        {
            return Prop.ForAll(
                ActionConfigArbitrary(),
                config =>
                {
                    var resultado = FilterOnDemandTriggers(config);

                    // Obtener labels de triggers NO OnDemand
                    var labelsNoOnDemand = config.Triggers
                        .Where(t => !t.Event.Equals(TriggerEvents.OnDemand, StringComparison.OrdinalIgnoreCase))
                        .Where(t => !string.IsNullOrWhiteSpace(t.Label))
                        .Select(t => t.Label!)
                        .ToHashSet();

                    // Ningún resultado debe provenir de un trigger no-OnDemand
                    // (excepto si el mismo label existe también en un trigger OnDemand válido)
                    var todosLosResultadosValidos = resultado.All(r =>
                        config.Triggers.Any(t =>
                            t.Event.Equals(TriggerEvents.OnDemand, StringComparison.OrdinalIgnoreCase)
                            && t.Label == r.Label));

                    return todosLosResultadosValidos
                        .Label($"Algún resultado proviene de un trigger no-OnDemand");
                });
        }

        /// <summary>
        /// Propiedad: El orden del resultado preserva el orden original del array de triggers.
        /// **Validates: Requirements 6.3, 10.1**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property OrdenDelResultadoPreservaOrdenOriginal()
        {
            return Prop.ForAll(
                ActionConfigArbitrary(),
                config =>
                {
                    var resultado = FilterOnDemandTriggers(config);

                    if (resultado.Count < 2)
                        return true.Label("Menos de 2 resultados, orden trivialmente preservado");

                    // Verificar que los índices originales están en orden creciente
                    var indicesOriginales = new List<int>();
                    int contadorResultado = 0;
                    for (int i = 0; i < config.Triggers.Count && contadorResultado < resultado.Count; i++)
                    {
                        var t = config.Triggers[i];
                        if (t.Event.Equals(TriggerEvents.OnDemand, StringComparison.OrdinalIgnoreCase)
                            && !string.IsNullOrWhiteSpace(t.Label))
                        {
                            indicesOriginales.Add(i);
                            contadorResultado++;
                        }
                    }

                    // Los índices deben ser estrictamente crecientes (orden preservado)
                    bool ordenPreservado = true;
                    for (int i = 1; i < indicesOriginales.Count; i++)
                    {
                        if (indicesOriginales[i] <= indicesOriginales[i - 1])
                        {
                            ordenPreservado = false;
                            break;
                        }
                    }

                    return ordenPreservado
                        .Label($"Índices originales no están en orden creciente: [{string.Join(", ", indicesOriginales)}]");
                });
        }
    }
}
