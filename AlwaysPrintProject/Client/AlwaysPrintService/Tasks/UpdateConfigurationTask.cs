using System;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintService.Tasks
{
    public sealed class UpdateConfigurationTask : IServiceTask
    {
        private readonly AppConfiguration _newConfig;
        private readonly RegistryConfigManager _registry;

        public UpdateConfigurationTask(AppConfiguration newConfig, RegistryConfigManager registry)
        {
            _newConfig = newConfig ?? throw new ArgumentNullException(nameof(newConfig));
            _registry  = registry  ?? throw new ArgumentNullException(nameof(registry));
        }

        public ServiceTaskResult Execute()
        {
            try
            {
                _registry.Save(_newConfig);
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
