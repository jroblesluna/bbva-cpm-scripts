using System.ServiceProcess;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.EventLog;

var builder = Host.CreateDefaultBuilder(args)
    .UseWindowsService(options => options.ServiceName = "LpdServiceMonitor")
    .ConfigureAppConfiguration((ctx, config) =>
    {
        config.AddJsonFile("appsettings.json", optional: true)
              .AddEnvironmentVariables(prefix: "SM_"); // override: SM_Monitor__TargetServiceName, etc.
    })
    .ConfigureLogging((ctx, logging) =>
    {
        logging.ClearProviders();
        logging.AddEventLog(new EventLogSettings
        {
            SourceName = "LpdServiceMonitor",
            LogName = "Application"
        });
        // Si ejecutas en consola para pruebas, muestra también en stdout.
        if (Environment.UserInteractive) logging.AddSimpleConsole();
        logging.SetMinimumLevel(LogLevel.Information);
    })
    .ConfigureServices((ctx, services) =>
    {
        services.Configure<MonitorOptions>(ctx.Configuration.GetSection("Monitor"));
        services.AddHostedService<MonitorWorker>();
    });

await builder.Build().RunAsync();

public class MonitorOptions
{
    public string TargetServiceName { get; set; } = "LPDSVC";
    public int CheckIntervalMs { get; set; } = 5000;
    public int StartTimeoutSeconds { get; set; } = 30;
    public int MaxRestartsInWindow { get; set; } = 5;
    public int RestartWindowSeconds { get; set; } = 300;
    public int CooldownAfterBurstSeconds { get; set; } = 600;
    public string? MaintenanceFlagPath { get; set; }
}

public class MonitorWorker : BackgroundService
{
    private readonly ILogger<MonitorWorker> _logger;
    private readonly IHostApplicationLifetime _lifetime;
    private readonly MonitorOptions _opt;

    private readonly Queue<DateTime> _restartTimestamps = new();

    public MonitorWorker(
        ILogger<MonitorWorker> logger,
        Microsoft.Extensions.Options.IOptions<MonitorOptions> opt,
        IHostApplicationLifetime lifetime)
    {
        _logger = logger;
        _opt = opt.Value;
        _lifetime = lifetime;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        // --- Chequeo inicial: si el servicio objetivo NO existe, apagamos el monitor. ---
        if (!ServiceExists(_opt.TargetServiceName))
        {
            _logger.LogError("Servicio objetivo {svc} no está instalado. LpdServiceMonitor se detendrá.", _opt.TargetServiceName);
            _lifetime.StopApplication(); // Pide al SCM detener este servicio
            return;
        }

        _logger.LogInformation("Monitor iniciado. Vigilando servicio {svc}", _opt.TargetServiceName);

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                // Si durante la ejecución el servicio fuera desinstalado, nos detenemos.
                if (!ServiceExists(_opt.TargetServiceName))
                {
                    _logger.LogError("Servicio objetivo {svc} ya no existe. LpdServiceMonitor se detendrá.", _opt.TargetServiceName);
                    _lifetime.StopApplication();
                    return;
                }

                if (!string.IsNullOrWhiteSpace(_opt.MaintenanceFlagPath) &&
                    File.Exists(_opt.MaintenanceFlagPath))
                {
                    _logger.LogWarning("Flag de mantenimiento detectado en {flag}. No se reiniciará por ahora.",
                        _opt.MaintenanceFlagPath);
                }
                else
                {
                    using var sc = new ServiceController(_opt.TargetServiceName);
                    sc.Refresh();

                    if (sc.Status == ServiceControllerStatus.Stopped ||
                        sc.Status == ServiceControllerStatus.StopPending)
                    {
                        if (DebeEntrarEnCooldown())
                        {
                            _logger.LogWarning("Umbral de reinicios excedido. Cooldown por {secs}s.",
                                _opt.CooldownAfterBurstSeconds);
                            await EsperarConCancel(_opt.CooldownAfterBurstSeconds * 1000, stoppingToken);
                        }
                        else
                        {
                            _logger.LogWarning("Servicio {svc} detenido (estado: {status}). Intentando iniciar...",
                                _opt.TargetServiceName, sc.Status);
                            try
                            {
                                sc.Start();
                                sc.WaitForStatus(ServiceControllerStatus.Running,
                                    TimeSpan.FromSeconds(_opt.StartTimeoutSeconds));

                                RegistraRestart();
                                _logger.LogInformation("Servicio {svc} iniciado correctamente.", _opt.TargetServiceName);
                            }
                            catch (Exception ex)
                            {
                                _logger.LogError(ex, "No se pudo iniciar {svc}.", _opt.TargetServiceName);
                            }
                        }
                    }
                }
            }
            catch (InvalidOperationException ex)
            {
                // Este error suele indicar que el servicio objetivo no existe o no es accesible
                _logger.LogError(ex, "Servicio {svc} no encontrado. LpdServiceMonitor se detendrá.",
                    _opt.TargetServiceName);
                _lifetime.StopApplication();
                return;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error monitoreando {svc}.", _opt.TargetServiceName);
            }

            await EsperarConCancel(_opt.CheckIntervalMs, stoppingToken);
        }
    }

    private static bool ServiceExists(string serviceName)
    {
        try
        {
            // GetServices es rápido y seguro aquí
            return ServiceController.GetServices().Any(s => s.ServiceName.Equals(serviceName, StringComparison.OrdinalIgnoreCase));
        }
        catch
        {
            // Ante cualquier fallo inesperado, asumimos que no podemos continuar
            return false;
        }
    }

    private void RegistraRestart()
    {
        var now = DateTime.UtcNow;
        _restartTimestamps.Enqueue(now);
        var cutoff = now.AddSeconds(-_opt.RestartWindowSeconds);
        while (_restartTimestamps.Count > 0 && _restartTimestamps.Peek() < cutoff)
            _restartTimestamps.Dequeue();
    }

    private bool DebeEntrarEnCooldown()
    {
        var now = DateTime.UtcNow;
        var cutoff = now.AddSeconds(-_opt.RestartWindowSeconds);
        while (_restartTimestamps.Count > 0 && _restartTimestamps.Peek() < cutoff)
            _restartTimestamps.Dequeue();

        return _restartTimestamps.Count >= _opt.MaxRestartsInWindow;
    }

    private static async Task EsperarConCancel(int ms, CancellationToken ct)
    {
        try { await Task.Delay(ms, ct); } catch { /* cancelado */ }
    }
}