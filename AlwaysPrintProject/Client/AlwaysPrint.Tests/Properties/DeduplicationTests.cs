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
    /// Property 5: Deduplicación preserva orden (primero encontrado gana)
    /// Verifica que cuando múltiples triggers OnDemand comparten el mismo label,
    /// se seleccionan las acciones del primer trigger en el array.
    /// **Validates: Requirements 5.6, 8.5**
    /// </summary>
    [TestFixture]
    [Category("Feature: on-demand-triggers, Property 5: Deduplicación")]
    public class DeduplicationTests
    {
        /// <summary>
        /// Réplica de la lógica de búsqueda de ActionEngine.ExecuteOnDemandTrigger.
        /// Filtra triggers OnDemand válidos y retorna el primero cuyo label coincide.
        /// </summary>
        private static TriggerConfig? LookupFirstTriggerByLabel(
            ActionConfiguration config, string label)
        {
            if (config?.Triggers == null)
                return null;

            return config.Triggers
                .Where(t => t.Event.Equals("OnDemand", StringComparison.OrdinalIgnoreCase)
                         && !string.IsNullOrWhiteSpace(t.Label))
                .FirstOrDefault(t => t.Label!.Equals(label, StringComparison.Ordinal));
        }

        /// <summary>
        /// Genera un label válido (no vacío, no whitespace).
        /// </summary>
        private static Gen<string> ValidLabelGen()
        {
            return Arb.Generate<NonEmptyString>()
                .Where(s => !string.IsNullOrWhiteSpace(s.Get))
                .Select(s => s.Get);
        }

        /// <summary>
        /// Genera una lista de acciones distinguibles por su descripción única.
        /// Cada trigger tendrá un conjunto de acciones distinto para poder verificar
        /// cuál fue seleccionado.
        /// </summary>
        private static Gen<List<ActionConfig>> UniqueActionsGen(int index)
        {
            return Gen.Constant(new List<ActionConfig>
            {
                new ActionConfig
                {
                    Type = "StopService",
                    Description = $"Acción_Trigger_Index_{index}"
                }
            });
        }

        /// <summary>
        /// Genera una configuración con N triggers OnDemand que comparten el mismo label,
        /// intercalados opcionalmente con triggers de otros eventos.
        /// </summary>
        private static Gen<(ActionConfiguration config, string sharedLabel, int firstIndex)> ConfigWithDuplicateLabelsGen()
        {
            return from label in ValidLabelGen()
                   from duplicateCount in Gen.Choose(2, 6)
                   from prefixCount in Gen.Choose(0, 3)
                   from interleaveOtherEvents in Arb.Generate<bool>()
                   select BuildConfigWithDuplicates(label, duplicateCount, prefixCount, interleaveOtherEvents);
        }

        /// <summary>
        /// Construye una configuración con triggers duplicados a partir de los parámetros.
        /// </summary>
        private static (ActionConfiguration config, string sharedLabel, int firstIndex) BuildConfigWithDuplicates(
            string label, int duplicateCount, int prefixCount, bool interleaveOtherEvents)
        {
            var triggers = new List<TriggerConfig>();

            // Agregar triggers prefijo (otros eventos) para que el primer duplicado
            // no siempre esté en posición 0
            for (int i = 0; i < prefixCount; i++)
            {
                triggers.Add(new TriggerConfig
                {
                    Event = TriggerEvents.OnTrayLaunched,
                    Label = null,
                    Description = $"Trigger prefijo {i}",
                    Actions = new List<ActionConfig>
                    {
                        new ActionConfig { Type = "StartService", Description = $"Prefijo_{i}" }
                    }
                });
            }

            // Índice donde aparecerá el primer trigger con el label compartido
            int firstIndex = triggers.Count;

            // Agregar triggers OnDemand duplicados con el mismo label
            for (int i = 0; i < duplicateCount; i++)
            {
                triggers.Add(new TriggerConfig
                {
                    Event = TriggerEvents.OnDemand,
                    Label = label,
                    Description = $"Descripción duplicado #{i}",
                    Actions = new List<ActionConfig>
                    {
                        new ActionConfig
                        {
                            Type = "StopService",
                            Description = $"Acción_Trigger_Index_{firstIndex + i}"
                        }
                    }
                });

                // Intercalar triggers de otros eventos entre duplicados
                if (interleaveOtherEvents && i < duplicateCount - 1)
                {
                    triggers.Add(new TriggerConfig
                    {
                        Event = TriggerEvents.OnConfigChange,
                        Label = null,
                        Description = $"Intercalado {i}",
                        Actions = new List<ActionConfig>
                        {
                            new ActionConfig { Type = "StartService", Description = $"Intercalado_{i}" }
                        }
                    });
                }
            }

            var config = new ActionConfiguration
            {
                Name = "TestDedup",
                Version = "1.0",
                Triggers = triggers
            };

            return (config, label, firstIndex);
        }

        /// <summary>
        /// Propiedad: Con múltiples triggers OnDemand que comparten label,
        /// la búsqueda siempre retorna el primer trigger del array.
        /// **Validates: Requirements 5.6, 8.5**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property PrimerTriggerEncontradoGana()
        {
            return Prop.ForAll(
                Arb.From(ConfigWithDuplicateLabelsGen()),
                tuple =>
                {
                    var (config, sharedLabel, firstIndex) = tuple;

                    // Ejecutar la búsqueda (réplica de la lógica de ActionEngine)
                    var triggerEncontrado = LookupFirstTriggerByLabel(config, sharedLabel);

                    if (triggerEncontrado == null)
                        return false.Label("No se encontró ningún trigger con el label compartido");

                    // El trigger encontrado debe ser el primero en el array (por posición)
                    var primerTriggerEsperado = config.Triggers[firstIndex];

                    // Verificamos que es el mismo objeto (referencia) o que tiene las acciones del primero
                    var esElPrimero = ReferenceEquals(triggerEncontrado, primerTriggerEsperado);
                    var tieneAccionesDelPrimero = triggerEncontrado.Actions.Count > 0
                        && triggerEncontrado.Actions[0].Description == $"Acción_Trigger_Index_{firstIndex}";

                    return (esElPrimero || tieneAccionesDelPrimero)
                        .Label($"Label='{sharedLabel}', firstIndex={firstIndex}, " +
                               $"acciónEncontrada='{triggerEncontrado.Actions.FirstOrDefault()?.Description}', " +
                               $"acciónEsperada='Acción_Trigger_Index_{firstIndex}'");
                });
        }

        /// <summary>
        /// Propiedad: El trigger seleccionado siempre coincide con el primer trigger
        /// del subconjunto filtrado (OnDemand + label no vacío + label exacto).
        /// Verifica la semántica de FirstOrDefault sobre el filtrado.
        /// **Validates: Requirements 5.6, 8.5**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property TriggerSeleccionadoCoincideConPrimeroFiltrado()
        {
            return Prop.ForAll(
                Arb.From(ConfigWithDuplicateLabelsGen()),
                tuple =>
                {
                    var (config, sharedLabel, _) = tuple;

                    // Obtener todos los triggers que coinciden con el label
                    var todosCoincidentes = config.Triggers
                        .Where(t => t.Event.Equals("OnDemand", StringComparison.OrdinalIgnoreCase)
                                 && !string.IsNullOrWhiteSpace(t.Label)
                                 && t.Label!.Equals(sharedLabel, StringComparison.Ordinal))
                        .ToList();

                    if (todosCoincidentes.Count < 2)
                        return true.Label("Menos de 2 coincidencias, caso trivial");

                    // El resultado de la búsqueda debe ser el primer elemento de la lista filtrada
                    var triggerEncontrado = LookupFirstTriggerByLabel(config, sharedLabel);
                    var primerCoincidente = todosCoincidentes.First();

                    return ReferenceEquals(triggerEncontrado, primerCoincidente)
                        .Label($"El trigger seleccionado no es el primero del filtrado. " +
                               $"Coincidentes: {todosCoincidentes.Count}");
                });
        }

        /// <summary>
        /// Propiedad: Los triggers posteriores con el mismo label nunca son seleccionados.
        /// Verificación complementaria: ningún trigger duplicado posterior es el resultado.
        /// **Validates: Requirements 5.6, 8.5**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property TriggersPosterioresNuncaSonSeleccionados()
        {
            return Prop.ForAll(
                Arb.From(ConfigWithDuplicateLabelsGen()),
                tuple =>
                {
                    var (config, sharedLabel, firstIndex) = tuple;

                    var triggerEncontrado = LookupFirstTriggerByLabel(config, sharedLabel);
                    if (triggerEncontrado == null)
                        return false.Label("No se encontró trigger");

                    // Obtener triggers duplicados posteriores al primero
                    var posteriores = config.Triggers
                        .Where(t => t.Event.Equals("OnDemand", StringComparison.OrdinalIgnoreCase)
                                 && !string.IsNullOrWhiteSpace(t.Label)
                                 && t.Label!.Equals(sharedLabel, StringComparison.Ordinal))
                        .Skip(1) // omitir el primero
                        .ToList();

                    if (posteriores.Count == 0)
                        return true.Label("Sin duplicados posteriores");

                    // Ninguno de los posteriores debe ser el seleccionado
                    var ningunoEsSeleccionado = posteriores.All(t => !ReferenceEquals(t, triggerEncontrado));

                    return ningunoEsSeleccionado
                        .Label($"Un trigger posterior fue seleccionado. " +
                               $"Posteriores: {posteriores.Count}, Label: '{sharedLabel}'");
                });
        }
    }
}
