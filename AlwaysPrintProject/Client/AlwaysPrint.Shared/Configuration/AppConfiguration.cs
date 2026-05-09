using Newtonsoft.Json;

namespace AlwaysPrint.Shared.Configuration
{
    public class AppConfiguration
    {
        public string CorporateQueueName { get; set; } = string.Empty;
        public SearchTargetsConfig SearchTargets { get; set; } = new SearchTargetsConfig();
        public int PendingTaskPollingMinutes { get; set; } = 3;
        public string BootstrapDomains { get; set; } = "robles.ai,iol.pe,sistemas.com.pe";
        public string RoblesAiLicenseSerial { get; set; } = string.Empty;
    }

    public class SearchTargetsConfig
    {
        [JsonProperty("ips")]
        public string Ips { get; set; } = string.Empty;

        [JsonProperty("ranges")]
        public string Ranges { get; set; } = string.Empty;
    }
}
