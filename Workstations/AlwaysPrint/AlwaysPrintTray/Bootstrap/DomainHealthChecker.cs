using System;
using System.Net;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.Bootstrap
{
    /// <summary>
    /// Performs an HTTP health check against "alwaysprint.{domain}/health" for each domain
    /// in the configured BootstrapDomains list. Returns the first domain that responds with
    /// HTTP 200 (and optionally validates the response body).
    ///
    /// Why this design:
    ///   - Subdomain "alwaysprint.{domain}" is a predictable, dedicated health endpoint.
    ///   - A 200 response means the bootstrap server is reachable and the license is active.
    ///   - Timeout of 10 seconds per domain prevents indefinite blocking.
    ///   - If no domain responds, the Tray reports failure to the service but continues running
    ///     (the service may still be useful for local tasks).
    /// </summary>
    public static class DomainHealthChecker
    {
        private const string HealthPath  = "/health";
        private const int    TimeoutSecs = 10;

        // Optional: the body must contain this string to be considered healthy.
        // Set to null to accept any 200 response.
        private const string? ExpectedBodyFragment = null;

        public static (bool Success, string? RespondingDomain, string? Details)
            CheckAll(string bootstrapDomains, CancellationToken ct = default)
        {
            if (string.IsNullOrWhiteSpace(bootstrapDomains))
                return (false, null, "No bootstrap domains configured.");

            using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(TimeoutSecs) };

            foreach (var raw in bootstrapDomains.Split(','))
            {
                if (ct.IsCancellationRequested) break;

                string domain = raw.Trim();
                if (string.IsNullOrWhiteSpace(domain)) continue;

                string url = $"https://alwaysprint.{domain}{HealthPath}";
                try
                {
                    var response = http.GetAsync(url, ct).GetAwaiter().GetResult();

                    if (response.StatusCode != HttpStatusCode.OK)
                    {
                        EventLogWriter.WriteInfo($"Bootstrap: {url} returned {(int)response.StatusCode}.");
                        continue;
                    }

                    if (ExpectedBodyFragment != null)
                    {
                        string body = response.Content.ReadAsStringAsync().GetAwaiter().GetResult();
                        if (!body.Contains(ExpectedBodyFragment))
                        {
                            EventLogWriter.WriteInfo($"Bootstrap: {url} body did not contain expected fragment.");
                            continue;
                        }
                    }

                    EventLogWriter.WriteInfo($"Bootstrap: {url} responded OK.", EventLogWriter.EvtServiceStarted);
                    return (true, domain, url);
                }
                catch (OperationCanceledException) { break; }
                catch (Exception ex)
                {
                    EventLogWriter.WriteInfo($"Bootstrap: {url} error – {ex.Message}");
                }
            }

            return (false, null, "No bootstrap domain responded successfully.");
        }
    }
}
