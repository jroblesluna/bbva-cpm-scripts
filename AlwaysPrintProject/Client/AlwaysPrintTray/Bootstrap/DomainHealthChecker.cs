using System;
using System.Net;
using System.Net.Http;
using System.Threading;
using AlwaysPrint.Shared.Logging;
using AlwaysPrint.Shared.Configuration;
using AlwaysPrint.Shared.Network;
using Microsoft.Win32;

namespace AlwaysPrintTray.Bootstrap
{
    /// <summary>
    /// Realiza un HTTP GET a "https://{dominio}/api/v1/health" para cada dominio
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
        private const string HealthPath  = "/api/v1/health";
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

        /// <summary>
        /// Expone el HttpClient estático para reutilización por otros componentes del Tray
        /// (ej: ConfigurationSync). Evita crear nuevas instancias y socket exhaustion.
        /// 
        /// IMPORTANTE: Antes de usar este HttpClient, asegúrate de agregar el header
        /// X-Workstation-Local-IP con la IP privada de la workstation usando
        /// ConfigureWorkstationHeaders().
        /// </summary>
        internal static HttpClient Http => _http;

        /// <summary>
        /// Configura los headers del HttpClient con la información de la workstation.
        /// Debe llamarse una vez al inicio del Tray.
        /// </summary>
        public static void ConfigureWorkstationHeaders()
        {
            try
            {
                string localIP = NetworkHelper.GetOutboundLocalIP();
                if (!string.IsNullOrEmpty(localIP) && localIP != "unknown")
                {
                    // Limpiar header existente si lo hay
                    _http.DefaultRequestHeaders.Remove("X-Workstation-Local-IP");
                    
                    // Agregar nuevo header
                    _http.DefaultRequestHeaders.Add("X-Workstation-Local-IP", localIP);
                    
                    AlwaysPrintLogger.WriteTrayInfo(
                        $"DomainHealthChecker: configurado header X-Workstation-Local-IP: {localIP}");
                }
                else
                {
                    AlwaysPrintLogger.WriteWarning(
                        "DomainHealthChecker: no se pudo detectar IP local de la workstation",
                        AlwaysPrintLogger.EvtGenericWarning);
                }
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteWarning(
                    $"DomainHealthChecker: error al configurar headers de workstation: {ex.Message}",
                    AlwaysPrintLogger.EvtGenericWarning);
            }
        }

        public static (bool Success, string? RespondingDomain, string? Details)
            CheckAll(string bootstrapDomains, CancellationToken ct = default)
        {
            if (string.IsNullOrWhiteSpace(bootstrapDomains))
                return (false, null, "No hay dominios bootstrap configurados.");

            // Acumula las URLs intentadas y su resultado para incluirlas en el mensaje de fallo.
            var intentos = new System.Collections.Generic.List<string>();

            foreach (var raw in bootstrapDomains.Split(','))
            {
                if (ct.IsCancellationRequested) break;

                string domain = raw.Trim();
                if (string.IsNullOrWhiteSpace(domain)) continue;

                string url = $"https://{domain}{HealthPath}";
                try
                {
                    // Combina el timeout del HttpClient con el token de cancelación global.
                    using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                    linkedCts.CancelAfter(TimeSpan.FromSeconds(TimeoutSecs));

                    var response = _http.GetAsync(url, linkedCts.Token).GetAwaiter().GetResult();

                    if (response.StatusCode != HttpStatusCode.OK)
                    {
                        string motivo = $"{url} → HTTP {(int)response.StatusCode}";
                        intentos.Add(motivo);
                        AlwaysPrintLogger.WriteTrayInfo($"Bootstrap: {motivo}.");
                        continue;
                    }

                    if (ExpectedBodyFragment != null)
                    {
                        string body = response.Content.ReadAsStringAsync().GetAwaiter().GetResult();
                        if (body.IndexOf(ExpectedBodyFragment, StringComparison.Ordinal) < 0)
                        {
                            string motivo = $"{url} → body no contiene fragmento esperado";
                            intentos.Add(motivo);
                            AlwaysPrintLogger.WriteTrayInfo($"Bootstrap: {motivo}.");
                            continue;
                        }
                    }

                    AlwaysPrintLogger.WriteTrayInfo($"Bootstrap: {url} respondió OK.", AlwaysPrintLogger.EvtServiceStarted);
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
                    string motivo = $"{url} → timeout ({TimeoutSecs} s)";
                    intentos.Add(motivo);
                    AlwaysPrintLogger.WriteTrayInfo($"Bootstrap: {motivo}.");
                }
                catch (Exception ex)
                {
                    string motivo = $"{url} → error: {ex.Message}";
                    intentos.Add(motivo);
                    AlwaysPrintLogger.WriteTrayInfo($"Bootstrap: {motivo}.");
                }
            }

            string detalle = intentos.Count > 0
                ? $"Ningún dominio bootstrap respondió correctamente. Intentos: [{string.Join("; ", intentos)}]"
                : "Ningún dominio bootstrap respondió correctamente.";
            return (false, null, detalle);
        }
    }
}
