using FsCheck;
using FsCheck.NUnit;
using Newtonsoft.Json;
using NUnit.Framework;
using AlwaysPrint.Shared.Messages;
using FsCheckProperty = FsCheck.NUnit.PropertyAttribute;

namespace AlwaysPrint.Tests.Properties
{
    /// <summary>
    /// Property 3: Serialización round-trip de ExecuteOnDemandTriggerPayload
    /// Para cualquier string label no nulo, serializar a JSON y deserializar
    /// debe producir un payload con el mismo label original.
    /// **Validates: Requirements 7.1, 7.2**
    /// </summary>
    [TestFixture]
    [Category("Feature: on-demand-triggers, Property 3: Serialización round-trip de ExecuteOnDemandTriggerPayload")]
    public class OnDemandPayloadSerializationTests
    {
        // Generador personalizado para ExecuteOnDemandTriggerPayload con label no-nulo
        private static Arbitrary<ExecuteOnDemandTriggerPayload> ExecuteOnDemandTriggerPayloadArbitrary()
        {
            return Arb.From(
                from label in Arb.Generate<NonNull<string>>()
                select new ExecuteOnDemandTriggerPayload
                {
                    Label = label.Get
                });
        }

        /// <summary>
        /// Propiedad: Para cualquier ExecuteOnDemandTriggerPayload con Label no-nulo,
        /// serializar a JSON y deserializar produce un objeto con el mismo Label.
        /// **Validates: Requirements 7.1, 7.2**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property ExecuteOnDemandTriggerPayload_RoundTrip_PreservesLabel()
        {
            return Prop.ForAll(
                ExecuteOnDemandTriggerPayloadArbitrary(),
                original =>
                {
                    // Serializar a JSON
                    var json = JsonConvert.SerializeObject(original);

                    // Deserializar de vuelta
                    var deserialized = JsonConvert.DeserializeObject<ExecuteOnDemandTriggerPayload>(json);

                    // Verificar que el label resultante es idéntico al original
                    return (deserialized != null &&
                            deserialized.Label == original.Label)
                        .Label($"Label: esperado='{original.Label}', actual='{deserialized?.Label}'");
                });
        }
    }
}
