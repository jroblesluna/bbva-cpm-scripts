using System;
using System.IO;
using System.Text;
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
        private readonly Action? _reloadActionConfigCallback;

        // Raised when the Tray sends TrayInitialized.
        public event Action<bool, string?>? TrayInitializedReceived;

        public MessageDispatcher(
            RegistryConfigManager registry,
            TaskQueueManager taskQueue,
            ServiceStateMachine stateMachine,
            Action? reloadActionConfigCallback = null)
        {
            _registry     = registry     ?? throw new ArgumentNullException(nameof(registry));
            _taskQueue    = taskQueue    ?? throw new ArgumentNullException(nameof(taskQueue));
            _stateMachine = stateMachine ?? throw new ArgumentNullException(nameof(stateMachine));
            _reloadActionConfigCallback = reloadActionConfigCallback;
        }

        public PipeMessage Dispatch(PipeMessage request)
        {
            try
            {
                return request.Type switch
                {
                    MessageType.Ping                        => HandlePing(request),
                    MessageType.TrayInitialized             => HandleTrayInitialized(request),
                    MessageType.UpdateConfiguration         => HandleUpdateConfiguration(request),
                    MessageType.GetCurrentConfiguration     => HandleGetConfig(request),
                    MessageType.CheckCorporateQueue         => HandleCheckCorporateQueue(request),
                    MessageType.CheckServiceStatus          => HandleCheckServiceStatus(request),
                    MessageType.CloudConfigurationReceived  => HandleCloudConfigurationReceived(request),
                    MessageType.ActionConfigChanged         => HandleActionConfigChanged(request),
                    MessageType.SaveActionConfig            => HandleSaveActionConfig(request),
                    MessageType.InstallUpdate               => HandleInstallUpdate(request),
                    _ => PipeMessage.Reply(request, MessageType.Error,
                            new ErrorPayload { Code = "UNKNOWN_TYPE", Message = $"Unknown message type: {request.Type}" })
                };
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError($"MessageDispatcher unhandled error for type {request.Type}.", ex);
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
            AlwaysPrintLogger.WriteInfo(
                $"TrayInitialized received. Success={payload?.Success} Details={payload?.Details}",
                AlwaysPrintLogger.EvtTrayStarted);
            return PipeMessage.Reply(req, MessageType.Ack, new AckPayload { Success = true, Message = "Acknowledged." });
        }

        private PipeMessage HandleUpdateConfiguration(PipeMessage req)
        {
            var payload = req.GetPayload<UpdateConfigurationPayload>();
            if (payload?.Configuration == null)
                return PipeMessage.Reply(req, MessageType.Error,
                    new ErrorPayload { Code = "INVALID_PAYLOAD", Message = "Configuration payload missing." });

            var task = new UpdateConfigurationTask(payload.Configuration, _registry, payload.AutoUpdateEnabled);
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

        private PipeMessage HandleCloudConfigurationReceived(PipeMessage req)
        {
            var payload = req.GetPayload<CloudConfigurationReceivedPayload>();
            if (payload?.Configuration == null)
            {
                AlwaysPrintLogger.WriteError(
                    "Configuración Cloud recibida con payload inválido o ausente.",
                    AlwaysPrintLogger.EvtGenericError);
                return PipeMessage.Reply(req, MessageType.Ack,
                    new AckPayload { Success = false, Message = "Payload de configuración Cloud ausente." });
            }

            try
            {
                // Save() llama cfg.Validate() internamente; si lanza, no escribe nada.
                _registry.Save(payload.Configuration);
                AlwaysPrintLogger.WriteInfo(
                    $"Configuración Cloud aplicada correctamente. Fuente={payload.Source}, Hash={payload.ConfigHash}",
                    AlwaysPrintLogger.EvtConfigSaved);
                return PipeMessage.Reply(req, MessageType.Ack,
                    new AckPayload { Success = true, Message = "Configuración Cloud guardada." });
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"Error al guardar configuración Cloud en registro. Hash={payload.ConfigHash}. {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
                return PipeMessage.Reply(req, MessageType.Ack,
                    new AckPayload { Success = false, Message = $"Error al persistir configuración: {ex.Message}" });
            }
        }
        
        /// <summary>
        /// Maneja la solicitud de instalación de actualización MSI desde el Tray.
        /// Valida el payload y delega la ejecución al UpdateInstallHandler.
        /// </summary>
        private PipeMessage HandleInstallUpdate(PipeMessage req)
        {
            AlwaysPrintLogger.WriteInfo(
                "InstallUpdate: solicitud de instalación de actualización recibida del Tray.",
                AlwaysPrintLogger.EvtTaskDispatched);

            var payload = req.GetPayload<InstallUpdatePayload>();
            if (string.IsNullOrWhiteSpace(payload?.MsiFilePath))
            {
                AlwaysPrintLogger.WriteError(
                    "InstallUpdate: payload inválido — MsiFilePath es vacío o nulo.",
                    AlwaysPrintLogger.EvtGenericError);
                return PipeMessage.Reply(req, MessageType.Error,
                    new ErrorPayload { Code = "INVALID_PAYLOAD", Message = "MsiFilePath es obligatorio." });
            }

            var handler = new UpdateInstallHandler();
            var result = handler.Execute(payload.MsiFilePath);
            return PipeMessage.Reply(req, MessageType.InstallUpdateResponse, result);
        }

        /// <summary>
        /// Maneja la solicitud del Tray para guardar la configuración de acciones en disco.
        /// Escribe atómicamente (tmp + rename) en C:\ProgramData\AlwaysPrint\config\active.alwaysconfig
        /// y luego dispara la recarga de configuración.
        /// </summary>
        private PipeMessage HandleSaveActionConfig(PipeMessage req)
        {
            try
            {
                AlwaysPrintLogger.WriteInfo(
                    "SaveActionConfig: solicitud de escritura de configuración recibida del Tray",
                    AlwaysPrintLogger.EvtConfigSaved);

                var payload = req.GetPayload<SaveActionConfigPayload>();
                if (payload == null)
                {
                    AlwaysPrintLogger.WriteError(
                        "SaveActionConfig: payload ausente o inválido",
                        AlwaysPrintLogger.EvtGenericError);
                    return PipeMessage.Reply(req, MessageType.Error,
                        new ErrorPayload { Code = "INVALID_PAYLOAD", Message = "SaveActionConfigPayload ausente." });
                }

                string configDir = PipeConstants.ActionConfigDirectory;
                string configFilePath = PipeConstants.ActionConfigFilePath;

                // Asegurar que el directorio existe
                if (!Directory.Exists(configDir))
                {
                    Directory.CreateDirectory(configDir);
                    AlwaysPrintLogger.WriteInfo($"SaveActionConfig: directorio creado: {configDir}");
                }

                // Si el contenido está vacío, eliminar el archivo (config desactivada en Cloud)
                if (string.IsNullOrEmpty(payload.ConfigJson))
                {
                    if (File.Exists(configFilePath))
                    {
                        File.Delete(configFilePath);
                        AlwaysPrintLogger.WriteInfo("SaveActionConfig: archivo de configuración eliminado (config vacía)");
                    }

                    // Disparar recarga para que el ActionEngine limpie su estado
                    TriggerReloadActionConfig();

                    return PipeMessage.Reply(req, MessageType.Ack,
                        new AckPayload { Success = true, Message = "Configuración eliminada." });
                }

                // Escritura atómica: escribir en .tmp y luego renombrar
                string tempPath = configFilePath + ".tmp";
                File.WriteAllText(tempPath, payload.ConfigJson, Encoding.UTF8);

                // Reemplazar archivo activo
                if (File.Exists(configFilePath))
                    File.Delete(configFilePath);

                File.Move(tempPath, configFilePath);

                AlwaysPrintLogger.WriteInfo(
                    $"SaveActionConfig: configuración guardada exitosamente. Hash={payload.Hash}, Path={configFilePath}",
                    AlwaysPrintLogger.EvtConfigSaved);

                // Disparar recarga de configuración (equivalente a ActionConfigChanged)
                TriggerReloadActionConfig();

                return PipeMessage.Reply(req, MessageType.Ack,
                    new AckPayload { Success = true, Message = "Configuración guardada y recarga iniciada." });
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"SaveActionConfig: error al guardar configuración: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
                return PipeMessage.Reply(req, MessageType.Ack,
                    new AckPayload { Success = false, Message = $"Error al guardar: {ex.Message}" });
            }
        }

        /// <summary>
        /// Encola la tarea de recarga de configuración de acciones.
        /// Reutilizado por HandleSaveActionConfig y HandleActionConfigChanged.
        /// </summary>
        private void TriggerReloadActionConfig()
        {
            if (_reloadActionConfigCallback == null)
            {
                AlwaysPrintLogger.WriteWarning(
                    "TriggerReloadActionConfig: callback no configurado",
                    AlwaysPrintLogger.EvtGenericWarning);
                return;
            }

            var task = new ReloadActionConfigTask(_reloadActionConfigCallback);
            bool queued = _taskQueue.Enqueue(task);

            if (queued)
                AlwaysPrintLogger.WriteInfo("TriggerReloadActionConfig: tarea de recarga encolada");
            else
                AlwaysPrintLogger.WriteWarning("TriggerReloadActionConfig: cola llena, no se pudo encolar");
        }

        private PipeMessage HandleActionConfigChanged(PipeMessage req)
        {
            try
            {
                AlwaysPrintLogger.WriteInfo(
                    "Notificación de cambio de configuración de acciones recibida del Tray",
                    AlwaysPrintLogger.EvtConfigSaved);
                
                if (_reloadActionConfigCallback == null)
                {
                    AlwaysPrintLogger.WriteWarning(
                        "No se configuró callback de recarga de configuración de acciones",
                        AlwaysPrintLogger.EvtGenericWarning);
                    return PipeMessage.Reply(req, MessageType.Ack,
                        new AckPayload { Success = false, Message = "Callback no configurado." });
                }
                
                // Encolar tarea para recargar configuración y ejecutar trigger OnConfigChange
                var task = new ReloadActionConfigTask(_reloadActionConfigCallback);
                bool queued = _taskQueue.Enqueue(task);
                
                if (queued)
                {
                    AlwaysPrintLogger.WriteInfo("Tarea de recarga de configuración de acciones encolada");
                    return PipeMessage.Reply(req, MessageType.Ack,
                        new AckPayload { Success = true, Message = "Recarga de configuración encolada." });
                }
                else
                {
                    AlwaysPrintLogger.WriteWarning("Cola llena, no se pudo encolar recarga de configuración");
                    return PipeMessage.Reply(req, MessageType.Ack,
                        new AckPayload { Success = false, Message = "Cola llena; intente más tarde." });
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError(
                    $"Error procesando cambio de configuración de acciones: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericError);
                return PipeMessage.Reply(req, MessageType.Ack,
                    new AckPayload { Success = false, Message = $"Error: {ex.Message}" });
            }
        }
    }
}
