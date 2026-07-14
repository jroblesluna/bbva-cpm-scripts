using System;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.RemoteView
{
    /// <summary>
    /// Construye frames binarios para envío por WebSocket en modo Stream/Interactive.
    /// Formato del frame:
    ///   [4 bytes: session_id_hash (primeros 4 bytes del UUID parseado como Guid)]
    ///   [1 byte: flags]
    ///     bit 0: keyframe (1=IDR)
    ///     bit 1-2: monitor_index (0-3)
    ///     bit 3-7: reserved
    ///   [2 bytes: width (uint16 big-endian)]
    ///   [2 bytes: height (uint16 big-endian)]
    ///   [N bytes: H.264 NAL unit payload]
    ///
    /// Total header: 9 bytes.
    /// El frontend usa el session_id_hash para rutear el frame al tab correcto.
    /// </summary>
    public static class BinaryFrameBuilder
    {
        /// <summary>Tamaño fijo del header binario en bytes.</summary>
        public const int HEADER_SIZE = 9;

        /// <summary>
        /// Construye un frame binario completo (header + payload) listo para envío por WebSocket.
        /// </summary>
        /// <param name="sessionId">UUID de la sesión (string). Se extraen los primeros 4 bytes del Guid.</param>
        /// <param name="payload">Datos codificados H.264 (o JPEG placeholder).</param>
        /// <param name="isKeyframe">Indica si es un frame IDR (keyframe).</param>
        /// <param name="monitorIndex">Índice del monitor (0-3). Se clampea al rango válido.</param>
        /// <param name="width">Ancho del frame en píxeles.</param>
        /// <param name="height">Alto del frame en píxeles.</param>
        /// <returns>Array de bytes con header de 9 bytes + payload, listo para WebSocket binary frame.</returns>
        public static byte[] BuildFrame(
            string sessionId,
            byte[] payload,
            bool isKeyframe,
            int monitorIndex,
            int width,
            int height)
        {
            if (payload == null)
                throw new ArgumentNullException(nameof(payload));

            if (string.IsNullOrEmpty(sessionId))
                throw new ArgumentException("El sessionId no puede ser nulo o vacío.", nameof(sessionId));

            // Obtener hash de sesión (primeros 4 bytes del UUID)
            byte[] sessionHash = GetSessionHash(sessionId);

            // Construir byte de flags:
            // bit 0 = isKeyframe
            // bit 1-2 = monitorIndex (clampeado a 0-3)
            // bit 3-7 = 0 (reservados)
            int clampedMonitor = Math.Max(0, Math.Min(3, monitorIndex));
            byte flags = (byte)(
                (isKeyframe ? 1 : 0) |
                ((clampedMonitor & 0x03) << 1)
            );

            // Clampear width/height a rango uint16 (0-65535)
            ushort w = (ushort)Math.Max(0, Math.Min(65535, width));
            ushort h = (ushort)Math.Max(0, Math.Min(65535, height));

            // Construir frame completo: 9 bytes header + N bytes payload
            byte[] frame = new byte[HEADER_SIZE + payload.Length];

            // [0-3] Session hash (4 bytes)
            Buffer.BlockCopy(sessionHash, 0, frame, 0, 4);

            // [4] Flags (1 byte)
            frame[4] = flags;

            // [5-6] Width big-endian (2 bytes)
            frame[5] = (byte)(w >> 8);   // byte alto
            frame[6] = (byte)(w & 0xFF); // byte bajo

            // [7-8] Height big-endian (2 bytes)
            frame[7] = (byte)(h >> 8);   // byte alto
            frame[8] = (byte)(h & 0xFF); // byte bajo

            // [9..N] Payload
            Buffer.BlockCopy(payload, 0, frame, HEADER_SIZE, payload.Length);

            return frame;
        }

        /// <summary>
        /// Extrae los primeros 4 bytes del UUID parseado como Guid.
        /// Estos bytes sirven como identificador compacto de sesión para el frontend.
        /// </summary>
        /// <param name="sessionId">UUID como string (ej: "550e8400-e29b-41d4-a716-446655440000").</param>
        /// <returns>Array de 4 bytes con el hash de la sesión.</returns>
        public static byte[] GetSessionHash(string sessionId)
        {
            if (string.IsNullOrEmpty(sessionId))
                throw new ArgumentException("El sessionId no puede ser nulo o vacío.", nameof(sessionId));

            Guid guid;
            try
            {
                guid = Guid.Parse(sessionId);
            }
            catch (FormatException ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"BinaryFrameBuilder: sessionId no es un UUID válido: '{sessionId}'. {ex.Message}");
                throw new ArgumentException(
                    $"El sessionId no es un UUID válido: '{sessionId}'", nameof(sessionId), ex);
            }

            // ToByteArray() retorna 16 bytes en formato .NET (mixed-endian).
            // Tomamos los primeros 4 bytes que corresponden al primer grupo del GUID.
            byte[] guidBytes = guid.ToByteArray();
            byte[] hash = new byte[4];
            Buffer.BlockCopy(guidBytes, 0, hash, 0, 4);

            return hash;
        }
    }
}
