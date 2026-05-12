# Fase 4 — Telemetría y Monitoreo de Conectividad

**Prerrequisito**: Fase 3 completada  
**Entregable**: El Tray reporta telemetría periódica y ejecuta checks de conectividad configurados  
**Estimación**: 4–6 días

---

## Objetivo

1. **Telemetría**: el Tray recopila y envía periódicamente a APCM:
   - Estado de la cola corporativa
   - Log de desconexiones (inicio, fin, duración)
   - Trabajos de impresión identificados
   - Tiempo promedio de liberación de trabajos

2. **Monitoreo de conectividad**: el Tray ejecuta los checks configurados (HTTP, TCP, ping, DNS) y reporta resultados a APCM.

---

## Componentes

### 4.1 — `TelemetryReporter.cs`

**Archivo**: `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/TelemetryReporter.cs`

```csharp
namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Recopila y envía telemetría periódica a APCM.
    ///
    /// Fuentes de datos:
    ///   - Estado de cola: solicita al Service vía Named Pipe (CheckCorporateQueue)
    ///   - Desconexiones: registradas por CloudManager al detectar cambios de estado
    ///   - Jobs: el Service reporta vía ReportTelemetry cuando detecta trabajos
    ///   - Tiempos: calculados por el Service y reportados vía ReportTelemetry
    /// </summary>
    public sealed class TelemetryReporter : IDisposable
    {
        public TelemetryReporter(
            CloudWebSocketClient wsClient,
            PipeClient pipe,
            int intervalSeconds = 300) { }

        public void Start() { }
        public void Stop() { }

        /// <summary>Registra un evento de desconexión (llamado por CloudManager).</summary>
        public void RecordDisconnection(DateTime startedAt, DateTime? reconnectedAt = null) { }

        /// <summary>Registra un job identificado (llamado al recibir ReportTelemetry del Service).</summary>
        public void RecordJob(long releaseTimeMs) { }

        public void Dispose() { }
    }
}
```

**Ciclo de telemetría** (cada `TelemetryIntervalSeconds`):

```
1. Solicitar estado de cola al Service: Send(CheckCorporateQueue)
2. Recopilar log de desconexiones acumulado
3. Calcular avg_release_time_ms de los jobs registrados
4. Enviar por WebSocket:
   {
     "type": "telemetry",
     "queue_status": "ok|missing|error",
     "contingency_active": bool,
     "jobs_identified": int,
     "avg_release_time_ms": long|null,
     "disconnection_log": [...]
   }
5. Limpiar log de desconexiones y jobs procesados
```

---

### 4.2 — `ReportTelemetry` — Mensaje Service → Tray

El Service ya tiene visibilidad de los jobs de impresión (WMI). Cuando detecta un job completado, envía al Tray:

```csharp
// En AlwaysPrintService, al completar un job:
_dispatcher.EnqueueTelemetryEvent(new TelemetryPayload
{
    QueueStatus    = "ok",
    JobsIdentified = 1,
    AvgReleaseTimeMs = releaseTimeMs
});
```

El Tray recibe `ReportTelemetry` y lo acumula en `TelemetryReporter`.

**Handler en `MessageDispatcher.cs`** (Service):

```csharp
MessageType.ReportTelemetry => HandleReportTelemetry(request),
```

El Service no envía telemetría directamente a la nube — la pasa al Tray que tiene acceso a Internet.

---

### 4.3 — `ConnectivityMonitor.cs`

**Archivo**: `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/ConnectivityMonitor.cs`

```csharp
namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Ejecuta los checks de conectividad configurados y reporta resultados a APCM.
    ///
    /// Tipos de check soportados:
    ///   - "http"  → HTTP GET con timeout, verifica código 200
    ///   - "tcp"   → TCP connect a host:port con timeout
    ///   - "ping"  → ICMP ping (requiere privilegios elevados en algunos entornos)
    ///   - "dns"   → Resolución DNS de hostname
    ///
    /// Los checks se ejecutan en paralelo. Cada resultado se envía individualmente
    /// por WebSocket para no bloquear el reporte de otros checks.
    /// </summary>
    public sealed class ConnectivityMonitor : IDisposable
    {
        public ConnectivityMonitor(
            CloudWebSocketClient wsClient,
            List<ConnectivityCheck> checks,
            int intervalSeconds = 60) { }

        public void Start() { }
        public void Stop() { }
        public void UpdateChecks(List<ConnectivityCheck> newChecks) { }
        public void Dispose() { }
    }
}
```

**Implementación de cada tipo de check**:

```csharp
// HTTP
private async Task<ConnectivityResult> CheckHttp(ConnectivityCheck check)
{
    var sw = Stopwatch.StartNew();
    try
    {
        using var cts = new CancellationTokenSource(check.TimeoutMs);
        var response = await _http.GetAsync(check.Url, cts.Token);
        return new ConnectivityResult
        {
            CheckId   = check.Id,
            Success   = response.IsSuccessStatusCode,
            LatencyMs = sw.ElapsedMilliseconds
        };
    }
    catch (Exception ex)
    {
        return new ConnectivityResult { CheckId = check.Id, Success = false, Error = ex.Message };
    }
}

// TCP
private ConnectivityResult CheckTcp(ConnectivityCheck check)
{
    var sw = Stopwatch.StartNew();
    try
    {
        using var client = new TcpClient();
        var task = client.ConnectAsync(check.Host!, check.Port!.Value);
        if (!task.Wait(check.TimeoutMs))
            return new ConnectivityResult { CheckId = check.Id, Success = false, Error = "Timeout" };
        return new ConnectivityResult { CheckId = check.Id, Success = true, LatencyMs = sw.ElapsedMilliseconds };
    }
    catch (Exception ex)
    {
        return new ConnectivityResult { CheckId = check.Id, Success = false, Error = ex.Message };
    }
}

// DNS
private ConnectivityResult CheckDns(ConnectivityCheck check)
{
    var sw = Stopwatch.StartNew();
    try
    {
        var addresses = Dns.GetHostAddresses(check.Hostname!);
        return new ConnectivityResult
        {
            CheckId   = check.Id,
            Success   = addresses.Length > 0,
            LatencyMs = sw.ElapsedMilliseconds
        };
    }
    catch (Exception ex)
    {
        return new ConnectivityResult { CheckId = check.Id, Success = false, Error = ex.Message };
    }
}

// PING (ICMP)
private ConnectivityResult CheckPing(ConnectivityCheck check)
{
    var sw = Stopwatch.StartNew();
    try
    {
        using var ping = new System.Net.NetworkInformation.Ping();
        var reply = ping.Send(check.Host!, check.TimeoutMs);
        return new ConnectivityResult
        {
            CheckId   = check.Id,
            Success   = reply.Status == System.Net.NetworkInformation.IPStatus.Success,
            LatencyMs = reply.RoundtripTime
        };
    }
    catch (Exception ex)
    {
        return new ConnectivityResult { CheckId = check.Id, Success = false, Error = ex.Message };
    }
}
```

**Payload enviado por WebSocket** (por cada check):

```json
{
  "type": "connectivity_result",
  "check_id": "c1",
  "success": true,
  "latency_ms": 45,
  "error": null
}
```

---

### 4.4 — Backend: recibir telemetría y resultados de conectividad

**Endpoint existente** (verificar que acepta el payload completo):
`POST /api/v1/workstations/{id}/telemetry`

Si no existe, crear en `AlwaysPrintProject/Cloud/backend/app/api/v1/endpoints/workstations.py`:

```python
@router.post("/{workstation_id}/telemetry", status_code=204)
def receive_telemetry(
    workstation_id: UUID,
    telemetry: TelemetryPayload,
    db: Session = Depends(get_db)
):
    """Recibe telemetría de una workstation."""
    # Guardar en audit_logs o tabla dedicada
    # Actualizar workstation.last_connection
    pass
```

**WebSocket**: los mensajes `telemetry` y `connectivity_result` ya se reciben en el handler WebSocket existente — agregar los casos correspondientes.

---

### 4.5 — Modelo de datos: `TelemetryLog` (opcional Fase 4, requerido Fase 6)

Si se quiere persistir telemetría en BD:

```python
class TelemetryLog(Base):
    __tablename__ = "telemetry_logs"
    id             = Column(GUID, primary_key=True, default=uuid.uuid4)
    workstation_id = Column(GUID, ForeignKey("workstations.id"), nullable=False)
    account_id     = Column(GUID, ForeignKey("accounts.id"),     nullable=False)
    queue_status   = Column(String(20), nullable=True)
    contingency_active = Column(Boolean, nullable=True)
    jobs_identified    = Column(Integer, nullable=True)
    avg_release_time_ms = Column(BigInteger, nullable=True)
    disconnection_count = Column(Integer, nullable=True)
    recorded_at    = Column(DateTime, nullable=False, default=datetime.utcnow)
```

---

### 4.6 — Integración en `CloudManager`

```csharp
// En CloudManager.Start():
_telemetryReporter = new TelemetryReporter(_wsClient, _pipe, _config.TelemetryIntervalSeconds);
_connectivityMonitor = new ConnectivityMonitor(_wsClient, _config.ConnectivityChecks);

if (_config.TelemetryEnabled)
    _telemetryReporter.Start();

if (_config.ConnectivityChecks.Count > 0)
    _connectivityMonitor.Start();

// Al recibir nueva config (Fase 3):
_connectivityMonitor.UpdateChecks(newConfig.ConnectivityChecks);
```

---

## Criterios de Aceptación

- [ ] El Tray envía telemetría cada `TelemetryIntervalSeconds` segundos
- [ ] La telemetría incluye: estado de cola, contingencia, jobs, avg_release_time_ms, log de desconexiones
- [ ] Los checks HTTP, TCP, DNS funcionan correctamente
- [ ] El check PING funciona (o loggea advertencia si no tiene permisos ICMP)
- [ ] Los resultados de conectividad se envían por WebSocket individualmente
- [ ] Al actualizar la config (Fase 3), los checks de conectividad se actualizan sin reiniciar
- [ ] Si `TelemetryEnabled=false`: no se envía telemetría
- [ ] Si no hay checks configurados: no se ejecuta `ConnectivityMonitor`
- [ ] El log de desconexiones se limpia después de enviarse

---

## Notas para el Desarrollador

- El ping ICMP puede requerir privilegios elevados en algunos entornos corporativos. Si falla con `SocketException`, loggear como warning y marcar el check como `success=false, error="ICMP not permitted"`.
- Los checks de conectividad se ejecutan en threads de fondo — no bloquear el hilo UI.
- El `ConnectivityMonitor` usa el mismo `HttpClient` estático para los checks HTTP.
- La telemetría se acumula en memoria entre envíos — si el Tray se reinicia, se pierde el acumulado. Esto es aceptable para Fase 4.
- El `avg_release_time_ms` es `null` si no se han registrado jobs en el intervalo.
