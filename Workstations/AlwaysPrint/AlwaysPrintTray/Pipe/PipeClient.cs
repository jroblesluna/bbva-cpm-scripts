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
    /// Named pipe client for the Tray application.
    /// Maintains a single persistent connection to the service pipe.
    /// All sends are serialized with a lock so multiple UI threads can call safely.
    /// Reconnects automatically on disconnect (for session edge cases).
    /// </summary>
    public sealed class PipeClient : IDisposable
    {
        private const int ConnectTimeoutMs   = 60_000;
        // Timeout de lectura: evita que ReadLine bloquee indefinidamente si el servicio
        // no responde (p.ej. tarea WMI colgada). El servidor siempre responde; 30 s es
        // suficiente margen incluso para consultas WMI lentas.
        private const int ReadTimeoutMs      = 30_000;

        private readonly object _lock = new object();
        private NamedPipeClientStream? _pipe;
        private StreamReader? _reader;
        private StreamWriter? _writer;
        private bool _disposed;

        public bool IsConnected => _pipe?.IsConnected == true;

        /// <summary>Attempts to connect to the service pipe. Returns false on timeout.</summary>
        public bool Connect()
        {
            lock (_lock)
            {
                DisposeTransport();
                _pipe = new NamedPipeClientStream(".", AlwaysPrint.Shared.Messages.PipeConstants.PipeName,
                    PipeDirection.InOut, PipeOptions.None);

                try
                {
                    _pipe.Connect(ConnectTimeoutMs);
                    _pipe.ReadMode = PipeTransmissionMode.Byte;
                    _pipe.ReadTimeout = ReadTimeoutMs;
                    _reader = new StreamReader(_pipe, Encoding.UTF8, false, 65536, leaveOpen: true);
                    _writer = new StreamWriter(_pipe, Encoding.UTF8, 65536, leaveOpen: true) { AutoFlush = true };
                    return true;
                }
                catch (TimeoutException)
                {
                    EventLogWriter.WriteError("PipeClient: connection timed out.", EventLogWriter.EvtGenericError);
                    DisposeTransport();
                    return false;
                }
                catch (Exception ex)
                {
                    EventLogWriter.WriteError("PipeClient: connection failed.", ex, EventLogWriter.EvtGenericError);
                    DisposeTransport();
                    return false;
                }
            }
        }

        /// <summary>Sends a request and returns the response, or null on failure.</summary>
        public PipeMessage? Send(PipeMessage request)
        {
            lock (_lock)
            {
                if (!EnsureConnected()) return null;

                try
                {
                    _writer!.WriteLine(request.Serialize());

                    // The server always responds; read the next line as the reply.
                    string? line = _reader!.ReadLine();
                    if (line == null)
                    {
                        // Server disconnected.
                        DisposeTransport();
                        return null;
                    }
                    return PipeMessage.Deserialize(line);
                }
                catch (Exception ex)
                {
                    EventLogWriter.WriteError("PipeClient: send/receive failed.", ex, EventLogWriter.EvtGenericError);
                    DisposeTransport();
                    return null;
                }
            }
        }

        /// <summary>Sends a Ping; returns true if the service is alive.</summary>
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
