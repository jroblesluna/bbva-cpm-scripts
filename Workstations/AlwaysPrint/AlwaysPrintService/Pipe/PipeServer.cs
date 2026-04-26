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
        // PipeName centralizado en Shared para que el cliente no dependa de este ensamblado.
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
            EventLogWriter.WriteInfo($"PipeServer started. Pipe=\\\\.\\pipe\\{PipeName}",
                EventLogWriter.EvtPipeServerStarted);
        }

        public void Stop()
        {
            _cts.Cancel();
            _listenerThread?.Join(TimeSpan.FromSeconds(5));
        }

        private void ListenerLoop()
        {
            string logFile = @"C:\ProgramData\AlwaysPrint\service.log";
            System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] PipeServer.ListenerLoop: iniciado\n");
            
            while (!_cts.IsCancellationRequested)
            {
                NamedPipeServerStream? pipe = null;
                try
                {
                    System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] PipeServer.ListenerLoop: creando pipe\n");
                    pipe = CreatePipe();

                    // Block until a client connects (or cancellation).
                    System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] PipeServer.ListenerLoop: esperando conexión\n");
                    pipe.WaitForConnection();
                    System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] PipeServer.ListenerLoop: cliente conectado\n");

                    // Hand off to a client thread; we immediately loop to accept the next.
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
                    System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] PipeServer.ListenerLoop: cancelado\n");
                    break; 
                }
                catch (Exception ex) when (!_cts.IsCancellationRequested)
                {
                    System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] PipeServer.ListenerLoop: error - {ex.GetType().Name}: {ex.Message}\n");
                    EventLogWriter.WriteError("PipeServer listener error.", ex);
                    pipe?.Dispose();
                    Thread.Sleep(1000); // brief back-off before re-creating the pipe
                }
            }
            System.IO.File.AppendAllText(logFile, $"[{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}] PipeServer.ListenerLoop: finalizado\n");
        }

        private static NamedPipeServerStream CreatePipe()
        {
            var security = new PipeSecurity();

            // LocalSystem (the service account) has full control.
            security.AddAccessRule(new PipeAccessRule(
                new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null),
                PipeAccessRights.FullControl,
                AccessControlType.Allow));

            // Authenticated users (the Tray, running as logged-on user) may read/write.
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
                catch (IOException) { /* client disconnected */ }
                catch (Exception ex)
                {
                    EventLogWriter.WriteError("PipeServer client handler error.", ex);
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
