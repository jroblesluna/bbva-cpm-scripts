using System;
using System.Net;
using System.Net.Http;
using System.Threading;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.Bootstrap
{
    /// <summary>
    /// Realiza un HTTP GET a "https://alwaysprint.{dominio}/health" para cada dominio
    /// configurado en BootstrapDomains. Devuelve el primer dominio que responda HTTP 200.
    ///
    /// Diseño:
    ///   - HttpClient es static readonly para reutilizar el pool de conexiones TCP y evitar
    ///     socket exhaustion (antipatrón: instanciar HttpClient por llamada).
    ///   - Timeout por dominio: 10 s. Si ninguno responde, el Tray opera en modo local.
    ///   - Se usa un CancellationTokenSource combinado para respetar tanto el timeout por
    ///     dominio como el token de cancelación global del Tray.
    /// </summary>
    public static class DomainHealthChecker
    {
        private const string HealthPath  = "/health";
        private const int    TimeoutSecs = 10;

        // Opcional: el body debe contener este fragmento para considerarse saludable.
        // Cambiar a una cadena no-null para activar la validación del body.
        // Campo estático (no const) para evitar CS0162 cuando es null.
        private static readonly string? ExpectedBodyFragment = null;

        // HttpClient reutilizable: el pool de conexiones subyacente gestiona el ciclo de vida.
        // No se dispone nunca — es intencional para instancias static.
        private static readonly HttpClient _http = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(TimeoutSecs)
        };

        public static (bool Success, string? RespondingDomain, string? Details)
            CheckAll(string bootstrapDomains, CancellationToken ct = default)
        {
            if (string.IsNullOrWhiteSpace(bootstrapDomains))
                return (false, null, "No hay dominios bootstrap configurados.");

            foreach (var raw in bootstrapDomains.Split(','))
            {
                if (ct.IsCancellationRequested) break;

                string domain = raw.Trim();
                if (string.IsNullOrWhiteSpace(domain)) continue;

                string url = $"https://alwaysprint.{domain}{HealthPath}";
                try
                {
                    // Combina el timeout del HttpClient con el token de cancelación global.
                    using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                    linkedCts.CancelAfter(TimeSpan.FromSeconds(TimeoutSecs));

                    var response = _http.GetAsync(url, linkedCts.Token).GetAwaiter().GetResult();

                    if (response.StatusCode != HttpStatusCode.OK)
                    {
                        EventLogWriter.WriteTrayInfo($"Bootstrap: {url} devolvió {(int)response.StatusCode}.");
                        continue;
                    }

                    if (ExpectedBodyFragment != null)
                    {
                        string body = response.Content.ReadAsStringAsync().GetAwaiter().GetResult();
                        if (body.IndexOf(ExpectedBodyFragment, StringComparison.Ordinal) < 0)
                        {
                            EventLogWriter.WriteTrayInfo($"Bootstrap: {url} no contiene el fragmento esperado.");
                            continue;
                        }
                    }

                    EventLogWriter.WriteTrayInfo($"Bootstrap: {url} respondió OK.", EventLogWriter.EvtServiceStarted);
                    return (true, domain, url);
                }
                catch (OperationCanceledException) when (ct.IsCancellationRequested)
                {
                    // Cancelación global del Tray — salir inmediatamente.
                    break;
                }
                catch (OperationCanceledException)
                {
                    // Timeout del dominio individual — continuar con el siguiente.
                    EventLogWriter.WriteTrayInfo($"Bootstrap: {url} timeout ({TimeoutSecs} s).");
                }
                catch (Exception ex)
                {
                    EventLogWriter.WriteTrayInfo($"Bootstrap: {url} error – {ex.Message}");
                }
            }

            return (false, null, "Ningún dominio bootstrap respondió correctamente.");
        }
    }
}
