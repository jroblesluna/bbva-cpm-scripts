using System;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Messages;
using AlwaysPrintService.Queue;
using AlwaysPrintService.Tasks;

namespace AlwaysPrintService.Pipe
{
    /// <summary>
    /// Routes incoming Named Pipe messages to the appropriate handler.
    /// Synchronous commands (Ping, GetCurrentConfiguration) are handled inline.
    /// State-mutating commands (UpdateConfiguration, CheckX) are enqueued for the worker thread
    /// so the pipe handler returns immediately and the client doesn't block long.
    ///
    /// Exception: CheckCorporateQueue and CheckServiceStatus are executed inline because
    /// the Tray needs the result synchronously. Adjust by making them async-queued if
    /// latency becomes a problem.
    /// </summary>
    public sealed class MessageDispatcher
    {
        private readonly RegistryConfigManager _registry;
        private readonly TaskQueueManager _taskQueue;
        private readonly ServiceStateMachine _stateMachine;

        // Raised when the Tray sends TrayInitialized.
        public event Action<bool, string?>? TrayInitializedReceived;

        public MessageDispatcher(
            RegistryConfigManager registry,
            TaskQueueManager taskQueue,
            ServiceStateMachine stateMachine)
        {
            _registry     = registry     ?? throw new ArgumentNullException(nameof(registry));
            _taskQueue    = taskQueue    ?? throw new ArgumentNullException(nameof(taskQueue));
            _stateMachine = stateMachine ?? throw new ArgumentNullException(nameof(stateMachine));
        }

        public PipeMessage Dispatch(PipeMessage request)
        {
            try
            {
                return request.Type switch
                {
                    MessageType.Ping                 => HandlePing(request),
                    MessageType.TrayInitialized      => HandleTrayInitialized(request),
                    MessageType.UpdateConfiguration  => HandleUpdateConfiguration(request),
                    MessageType.GetCurrentConfiguration => HandleGetConfig(request),
                    MessageType.CheckCorporateQueue  => HandleCheckCorporateQueue(request),
                    MessageType.CheckServiceStatus   => HandleCheckServiceStatus(request),
                    _ => PipeMessage.Reply(request, MessageType.Error,
                            new ErrorPayload { Code = "UNKNOWN_TYPE", Message = $"Unknown message type: {request.Type}" })
                };
            }
            catch (Exception ex)
            {
                EventLogWriter.WriteError($"MessageDispatcher unhandled error for type {request.Type}.", ex);
                return PipeMessage.Reply(request, MessageType.Error,
                    new ErrorPayload { Code = "INTERNAL_ERROR", Message = ex.Message });
            }
        }

        private static PipeMessage HandlePing(PipeMessage req)
            => PipeMessage.Reply(req, MessageType.Pong);

        private PipeMessage HandleTrayInitialized(PipeMessage req)
        {
            var payload = req.GetPayload<TrayInitializedPayload>();
            TrayInitializedReceived?.Invoke(payload?.Success ?? false, payload?.Details);
            EventLogWriter.WriteInfo(
                $"TrayInitialized received. Success={payload?.Success} Details={payload?.Details}",
                EventLogWriter.EvtTrayStarted);
            return PipeMessage.Reply(req, MessageType.Ack, new AckPayload { Success = true, Message = "Acknowledged." });
        }

        private PipeMessage HandleUpdateConfiguration(PipeMessage req)
        {
            var payload = req.GetPayload<UpdateConfigurationPayload>();
            if (payload?.Configuration == null)
                return PipeMessage.Reply(req, MessageType.Error,
                    new ErrorPayload { Code = "INVALID_PAYLOAD", Message = "Configuration payload missing." });

            var task = new UpdateConfigurationTask(payload.Configuration, _registry);
            bool queued = _taskQueue.Enqueue(task);

            return PipeMessage.Reply(req, MessageType.Ack,
                new AckPayload
                {
                    Success = queued,
                    Message = queued ? "Configuration update queued." : "Queue full; try again later."
                });
        }

        private PipeMessage HandleGetConfig(PipeMessage req)
        {
            var cfg = _registry.Load();
            return PipeMessage.Reply(req, MessageType.Ack,
                new GetConfigurationResponsePayload { Configuration = cfg });
        }

        private PipeMessage HandleCheckCorporateQueue(PipeMessage req)
        {
            var payload = req.GetPayload<CheckCorporateQueuePayload>();
            if (string.IsNullOrWhiteSpace(payload?.QueueName))
                return PipeMessage.Reply(req, MessageType.Error,
                    new ErrorPayload { Code = "INVALID_PAYLOAD", Message = "QueueName es obligatorio." });

            var cfg = _registry.Load();
            var task = new CheckCorporateQueueTask(payload!.QueueName, cfg.SearchTargets);
            var result = task.Execute();   // inline — la consulta WMI es suficientemente rápida

            if (!result.Success)
                return PipeMessage.Reply(req, MessageType.Error,
                    new ErrorPayload { Code = "CHECK_FAILED", Message = result.Message });

            // Devuelve el payload tipado para que el Tray pueda leer Exists, Cloud, PortType, etc.
            return PipeMessage.Reply(req, MessageType.Ack, result.Data);
        }

        private PipeMessage HandleCheckServiceStatus(PipeMessage req)
        {
            var payload = req.GetPayload<CheckServiceStatusPayload>();
            if (string.IsNullOrWhiteSpace(payload?.ServiceName))
                return PipeMessage.Reply(req, MessageType.Error,
                    new ErrorPayload { Code = "INVALID_PAYLOAD", Message = "ServiceName es obligatorio." });

            var task = new CheckServiceStatusTask(payload!.ServiceName);
            var result = task.Execute();

            // Devuelve el payload tipado para que el Tray pueda leer State, BinaryPath, StartTime.
            return PipeMessage.Reply(req, MessageType.Ack, result.Data ?? new AckPayload { Success = result.Success, Message = result.Message });
        }
    }
}
