using System;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Threading;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;

namespace AlwaysPrintTray.Pipe
{
    /// <summary>
    /// Named pipe client para el Tray.
    /// Mantiene una conexión persistente al pipe del servicio.
    /// Todos los envíos están serializados con un lock para que múltiples hilos UI puedan llamar de forma segura.
    /// </summary>
    public sealed class PipeClient : IDisposable
    {
        private const int ConnectTimeoutMs = 60_000;

        private readonly object _lock = new object();
        private NamedPipeClientStream? _pipe;
        private StreamReader? _reader;
        private StreamWriter? _writer;
        private bool _disposed;

        public bool IsConnected => _pipe?.IsConnected == true;

        /// <summary>Intenta conectar al pipe del servicio. Retorna false si hay timeout.</summary>
        public bool Connect()
        {
            lock (_lock)
            {
                DisposeTransport();
                _pipe = new NamedPipeClientStream(".", PipeConstants.PipeName, PipeDirection.InOut, PipeOptions.None);

                try
                {
                    _pipe.Connect(ConnectTimeoutMs);
                    _pipe.ReadMode = PipeTransmissionMode.Byte;
                    // NOTA: Named Pipes no soportan ReadTimeout en .NET Framework.
                    _reader = new StreamReader(_pipe, Encoding.UTF8, false, 65536, leaveOpen: true);
                    _writer = new StreamWriter(_pipe, Encoding.UTF8, 65536, leaveOpen: true) { AutoFlush = true };
                    AlwaysPrintLogger.WriteTrayInfo("PipeClient: conectado al servicio.");
                    return true;
                }
                catch (TimeoutException ex)
                {
                    AlwaysPrintLogger.WriteTrayError($"PipeClient: timeout al conectar. {ex.Message}", AlwaysPrintLogger.EvtGenericError);
                    DisposeTransport();
                    return false;
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayError($"PipeClient: error al conectar. {ex.GetType().Name}: {ex.Message}", AlwaysPrintLogger.EvtGenericError);
                    DisposeTransport();
                    return false;
                }
            }
        }

        /// <summary>Envía un request y retorna la respuesta, o null si falla.</summary>
        public PipeMessage? Send(PipeMessage request)
        {
            lock (_lock)
            {
                if (!EnsureConnected()) return null;

                try
                {
                    _writer!.WriteLine(request.Serialize());

                    string? line = _reader!.ReadLine();
                    if (line == null)
                    {
                        DisposeTransport();
                        return null;
                    }
                    return PipeMessage.Deserialize(line);
                }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteTrayError("PipeClient: send/receive falló.", ex, AlwaysPrintLogger.EvtGenericError);
                    DisposeTransport();
                    return null;
                }
            }
        }

        /// <summary>Envía un Ping; retorna true si el servicio está activo.</summary>
        public bool Ping()
        {
            var response = Send(PipeMessage.Create(MessageType.Ping));
            return response?.Type == MessageType.Pong;
        }

        private bool EnsureConnected()
        {
            if (_pipe?.IsConnected == true) return true;
            return Connect();
        }

        private void DisposeTransport()
        {
            _reader?.Dispose(); _reader = null;
            _writer?.Dispose(); _writer = null;
            _pipe?.Dispose();   _pipe   = null;
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            lock (_lock) { DisposeTransport(); }
        }
    }
}
