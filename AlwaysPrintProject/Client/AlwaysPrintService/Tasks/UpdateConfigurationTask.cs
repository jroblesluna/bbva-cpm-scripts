using System;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintService.Tasks
{
    public sealed class UpdateConfigurationTask : IServiceTask
    {
        private readonly AppConfiguration _newConfig;
        private readonly RegistryConfigManager _registry;
        private readonly bool? _autoUpdateEnabled;

        public UpdateConfigurationTask(AppConfiguration newConfig, RegistryConfigManager registry, bool? autoUpdateEnabled = null)
        {
            _newConfig = newConfig ?? throw new ArgumentNullException(nameof(newConfig));
            _registry  = registry  ?? throw new ArgumentNullException(nameof(registry));
            _autoUpdateEnabled = autoUpdateEnabled;
        }

        public ServiceTaskResult Execute()
        {
            try
            {
                _registry.Save(_newConfig);

                // Persistir flag de auto-actualización si fue enviado por el Tray
                if (_autoUpdateEnabled.HasValue)
                {
                    _registry.SaveAutoUpdateEnabled(_autoUpdateEnabled.Value);
                    AlwaysPrintLogger.WriteInfo(
                        $"Flag de auto-actualización actualizado: {_autoUpdateEnabled.Value}",
                        AlwaysPrintLogger.EvtConfigSaved);
                }

                AlwaysPrintLogger.WriteInfo(
                    $"Configuration updated. CorporateQueueName='{_newConfig.CorporateQueueName}' " +
                    $"PollMinutes={_newConfig.PendingTaskPollingMinutes}",
                    AlwaysPrintLogger.EvtConfigSaved);
                return ServiceTaskResult.Ok("Configuration saved successfully.");
            }
            catch (ArgumentOutOfRangeException ex)
            {
                return ServiceTaskResult.Fail($"Validation error: {ex.Message}");
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteError("UpdateConfigurationTask failed.", ex);
                return ServiceTaskResult.Fail($"Registry write failed: {ex.Message}");
            }
        }
    }
}
