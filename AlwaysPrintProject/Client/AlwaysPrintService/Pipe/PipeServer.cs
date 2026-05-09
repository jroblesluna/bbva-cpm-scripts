using System;
using System.IO;
using System.IO.Pipes;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Threading;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using Newtonsoft.Json;

namespace AlwaysPrintService.Pipe
{
    /// <summary>
    /// Named pipe server. Spawns one handler thread per connected client.
    /// Security: pipe DACL grants Authenticated Users read/write access so
    /// the Tray (running as a regular user) can connect.
    /// </summary>
    public sealed class PipeServer : IDisposable
    {
        public const string PipeName = PipeConstants.PipeName;

        private readonly MessageDispatcher _dispatcher;
        private readonly CancellationTokenSource _cts = new CancellationTokenSource();
        private Thread? _listenerThread;
        private bool _disposed;

        public PipeServer(MessageDispatcher dispatcher)
        {
            _dispatcher = dispatcher ?? throw new ArgumentNullException(nameof(dispatcher));
        }

        public void Start()
        {
            _listenerThread = new Thread(ListenerLoop)
            {
                IsBackground = true,
                Name = "AlwaysPrint-PipeListener"
            };
            _listenerThread.Start();
            AlwaysPrintLogger.WriteInfo($"PipeServer started. Pipe=\\\\.\\pipe\\{PipeName}",
                AlwaysPrintLogger.EvtPipeServerStarted);
        }

        public void Stop()
        {
            _cts.Cancel();
            _listenerThread?.Join(TimeSpan.FromSeconds(5));
        }

        private void ListenerLoop()
        {
            AlwaysPrintLogger.WriteInfo("PipeServer.ListenerLoop: iniciado");

            while (!_cts.IsCancellationRequested)
            {
                NamedPipeServerStream? pipe = null;
                try
                {
                    AlwaysPrintLogger.WriteInfo("PipeServer.ListenerLoop: esperando conexión");
                    pipe = CreatePipe();
                    pipe.WaitForConnection();
                    AlwaysPrintLogger.WriteInfo("PipeServer.ListenerLoop: cliente conectado");

                    var clientPipe = pipe;
                    var t = new Thread(() => HandleClient(clientPipe))
                    {
                        IsBackground = true,
                        Name = "AlwaysPrint-PipeClient"
                    };
                    t.Start();
                    pipe = null; // ownership transferred to HandleClient
                }
                catch (OperationCanceledException)
                {
                    break;
                }
                catch (Exception ex) when (!_cts.IsCancellationRequested)
                {
                    AlwaysPrintLogger.WriteError("PipeServer listener error.", ex);
                    pipe?.Dispose();
                    Thread.Sleep(1000);
                }
            }

            AlwaysPrintLogger.WriteInfo("PipeServer.ListenerLoop: finalizado");
        }

        private static NamedPipeServerStream CreatePipe()
        {
            var security = new PipeSecurity();

            security.AddAccessRule(new PipeAccessRule(
                new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null),
                PipeAccessRights.FullControl,
                AccessControlType.Allow));

            security.AddAccessRule(new PipeAccessRule(
                new SecurityIdentifier(WellKnownSidType.AuthenticatedUserSid, null),
                PipeAccessRights.ReadWrite,
                AccessControlType.Allow));

            return new NamedPipeServerStream(
                PipeName,
                PipeDirection.InOut,
                NamedPipeServerStream.MaxAllowedServerInstances,
                PipeTransmissionMode.Byte,
                PipeOptions.None,
                inBufferSize:  65536,
                outBufferSize: 65536,
                security);
        }

        private void HandleClient(NamedPipeServerStream pipe)
        {
            using (pipe)
            {
                pipe.ReadMode = PipeTransmissionMode.Byte;
                using var reader = new StreamReader(pipe, Encoding.UTF8, detectEncodingFromByteOrderMarks: false,
                    bufferSize: 65536, leaveOpen: true);
                using var writer = new StreamWriter(pipe, Encoding.UTF8, bufferSize: 65536, leaveOpen: true)
                {
                    AutoFlush = true
                };

                try
                {
                    string? line;
                    while (!_cts.IsCancellationRequested && (line = reader.ReadLine()) != null)
                    {
                        if (string.IsNullOrWhiteSpace(line)) continue;

                        PipeMessage? request;
                        try
                        {
                            request = PipeMessage.Deserialize(line);
                        }
                        catch (JsonException)
                        {
                            var errReply = PipeMessage.Create(MessageType.Error,
                                new ErrorPayload { Code = "PARSE_ERROR", Message = "Invalid JSON." });
                            writer.WriteLine(errReply.Serialize());
                            continue;
                        }

                        if (request == null) continue;

                        var response = _dispatcher.Dispatch(request);
                        writer.WriteLine(response.Serialize());
                    }
                }
                catch (IOException) { /* cliente desconectado */ }
                catch (Exception ex)
                {
                    AlwaysPrintLogger.WriteError("PipeServer client handler error.", ex);
                }
            }
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            Stop();
            _cts.Dispose();
        }
    }
}
