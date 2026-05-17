using System;
using FsCheck;
using FsCheck.NUnit;
using Newtonsoft.Json;
using NUnit.Framework;
using AlwaysPrint.Shared.Messages;
using FsCheckProperty = FsCheck.NUnit.PropertyAttribute;

namespace AlwaysPrint.Tests.Properties
{
    /// <summary>
    /// Property 8: IPC payload serialization round-trip
    /// Verifica que serializar a JSON y deserializar produce un objeto igual al original.
    /// Validates: Requirements 10.3, 10.4
    /// </summary>
    [TestFixture]
    [Category("Feature: auto-update, Property 8: IPC payload serialization round-trip")]
    public class IpcPayloadSerializationTests
    {
        // Generador personalizado para InstallUpdatePayload con strings no-nulos
        private static Arbitrary<InstallUpdatePayload> InstallUpdatePayloadArbitrary()
        {
            return Arb.From(
                from msiPath in Arb.Generate<NonNull<string>>()
                select new InstallUpdatePayload
                {
                    MsiFilePath = msiPath.Get
                });
        }

        // Generador personalizado para InstallUpdateResponsePayload con valores arbitrarios
        private static Arbitrary<InstallUpdateResponsePayload> InstallUpdateResponsePayloadArbitrary()
        {
            return Arb.From(
                from success in Arb.Generate<bool>()
                from message in Arb.Generate<string>()
                from exitCode in Arb.Generate<int>()
                select new InstallUpdateResponsePayload
                {
                    Success = success,
                    Message = message,
                    ExitCode = exitCode
                });
        }

        /// <summary>
        /// Propiedad: Para cualquier InstallUpdatePayload con MsiFilePath no-nulo,
        /// serializar a JSON y deserializar produce un objeto con los mismos valores.
        /// **Validates: Requirements 10.3**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property InstallUpdatePayload_RoundTrip_PreservesData()
        {
            return Prop.ForAll(
                InstallUpdatePayloadArbitrary(),
                original =>
                {
                    // Serializar a JSON
                    var json = JsonConvert.SerializeObject(original);

                    // Deserializar de vuelta
                    var deserialized = JsonConvert.DeserializeObject<InstallUpdatePayload>(json);

                    // Verificar igualdad de campos
                    return (deserialized != null &&
                            deserialized.MsiFilePath == original.MsiFilePath)
                        .Label($"MsiFilePath: esperado='{original.MsiFilePath}', actual='{deserialized?.MsiFilePath}'");
                });
        }

        /// <summary>
        /// Propiedad: Para cualquier InstallUpdateResponsePayload con valores arbitrarios,
        /// serializar a JSON y deserializar produce un objeto con los mismos valores.
        /// **Validates: Requirements 10.4**
        /// </summary>
        [FsCheckProperty(MaxTest = 100)]
        public Property InstallUpdateResponsePayload_RoundTrip_PreservesData()
        {
            return Prop.ForAll(
                InstallUpdateResponsePayloadArbitrary(),
                original =>
                {
                    // Serializar a JSON
                    var json = JsonConvert.SerializeObject(original);

                    // Deserializar de vuelta
                    var deserialized = JsonConvert.DeserializeObject<InstallUpdateResponsePayload>(json);

                    // Verificar igualdad de todos los campos
                    var successMatch = deserialized != null && deserialized.Success == original.Success;
                    var messageMatch = deserialized != null && deserialized.Message == original.Message;
                    var exitCodeMatch = deserialized != null && deserialized.ExitCode == original.ExitCode;

                    return (successMatch && messageMatch && exitCodeMatch)
                        .Label($"Success: {original.Success}=={deserialized?.Success}, " +
                               $"Message: '{original.Message}'=='{deserialized?.Message}', " +
                               $"ExitCode: {original.ExitCode}=={deserialized?.ExitCode}");
                });
        }
    }
}
