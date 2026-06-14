# Implementation Plan: Reconnection Jitter

## Overview

Implementación de jitter configurable para reconexiones WebSocket de workstations al backend de AlwaysPrint. El plan se divide en: backend (modelo + migración + schema + config service), cliente C# (JitterCalculator + RegistryConfigManager + CloudWebSocketClient + Service timestamps + TrayApplicationContext startup), frontend (input de configuración con cálculo dinámico), y property-based tests con Hypothesis.

## Tasks

- [x] 1. Backend: Modelo, migración y schemas
  - [x] 1.1 Agregar columna `jitter_window_seconds` al modelo Organization y crear migración Alembic
    - Agregar `jitter_window_seconds = Column(Integer, nullable=False, default=30, server_default='30')` en `app/models/organization.py`
    - Importar Base desde `app.core.database`
    - Crear migración `20260615_add_jitter_window_seconds.py` que agrega la columna con server_default='30'
    - _Requirements: 1.1, 1.5_

  - [x] 1.2 Actualizar schemas Pydantic de Organization
    - En `OrganizationUpdate` schema: agregar `jitter_window_seconds: Optional[int] = Field(None, ge=5, le=300)`
    - En `OrganizationResponse` schema: agregar `jitter_window_seconds: int`
    - Validación automática por Pydantic rechaza valores fuera de [5, 300] con HTTP 422
    - _Requirements: 1.2, 1.3_

  - [x] 1.3 Incluir `jitter_window_seconds` en el config service (effective config)
    - Modificar el método que construye la configuración efectiva para incluir `jitter_window_seconds` leyéndolo de la organización
    - El campo debe aparecer en todo payload `config_update` enviado a workstations
    - _Requirements: 1.4, 7.1_

  - [x] 1.4 Disparar broadcast `config_update` tras actualización de `jitter_window_seconds`
    - En el endpoint PATCH/PUT de organización, si `jitter_window_seconds` cambió, llamar `ConnectionManager.broadcast_to_organization()` con el config actualizado
    - _Requirements: 7.1_

  - [x] 1.5 Write property tests para validación backend (Hypothesis)
    - **Property 1: Backend validation accepts valid values and rejects invalid values**
    - Generar enteros en [5, 300] → PUT/PATCH exitoso y valor persistido
    - Generar enteros fuera de [5, 300] o no-enteros → HTTP 422, valor sin cambio
    - Mínimo 100 iteraciones
    - **Validates: Requirements 1.2, 1.3**

  - [x] 1.6 Write property test para presencia en config payload (Hypothesis)
    - **Property 2: Config payload always includes jitter_window_seconds**
    - Para cualquier org con jitter configurado, verificar que config_update contiene el campo con el valor correcto
    - Mínimo 100 iteraciones
    - **Validates: Requirements 1.4**

- [x] 2. Checkpoint - Backend completo
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Client C#: JitterCalculator (lógica pura)
  - [x] 3.1 Crear clase `JitterCalculator` en AlwaysPrint.Shared
    - Crear `AlwaysPrint.Shared/Configuration/JitterCalculator.cs`
    - Implementar método estático `ComputeStartupDelay(DateTime utcNow, DateTime? lastUpdateTimestamp, DateTime? lastRestartTimestamp, int jitterWindowSeconds, Random? rng = null)` que retorna `(int delayMs, string? reason)`
    - Implementar método estático `ComputeReconnectionDelay(int jitterWindowSeconds, Random? rng = null)` que retorna `int delayMs`
    - Implementar método estático `NormalizeJitterWindow(int rawValue)` → retorna 30 si fuera de [5, 300]
    - Lógica: si timestamp reciente (< 60s), delay = U(0, W*1000); si >= 60s o ausente/inválido/futuro, delay = 0
    - Si ambos timestamps recientes, usar el más cercano a utcNow y aplicar jitter una sola vez
    - Todos los comentarios en español
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.4_

  - [x] 3.2 Write unit tests para JitterCalculator
    - Timestamp de hace 30s con jitter window 45 → delay en [0, 45000)
    - Timestamp de hace 120s → delay = 0
    - Timestamp null → delay = 0
    - Timestamp futuro → delay = 0
    - JitterWindow = 0 → NormalizeJitterWindow retorna 30
    - JitterWindow = 500 → NormalizeJitterWindow retorna 30
    - Ambos timestamps recientes → un solo delay, usando el más cercano
    - ComputeReconnectionDelay con window 60 → delay en [0, 60000)
    - Usar Random con seed fijo para determinismo
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 4.1, 4.2, 4.4, 4.5, 5.1, 5.4_

  - [x] 3.3 Write property tests para JitterCalculator (Hypothesis - Python wrapper)
    - **Property 3: Jitter delay bounds for recent trigger events**
    - Generar window ∈ [5, 300] + timestamp con Δt < 60s → delay ∈ [0, W*1000)
    - **Validates: Requirements 3.1, 4.1**

  - [x] 3.4 Write property test: no jitter for old events (Hypothesis)
    - **Property 4: No jitter for old trigger events**
    - Generar timestamp con Δt ≥ 60s → delay = 0
    - **Validates: Requirements 3.2, 4.2**

  - [x] 3.5 Write property test: dual timestamps (Hypothesis)
    - **Property 5: Dual recent timestamps produce single jitter using closest timestamp**
    - Generar dos timestamps ambos < 60s → un solo delay, usando timestamp más cercano
    - **Validates: Requirements 4.4**

  - [x] 3.6 Write property test: invalid/future timestamps (Hypothesis)
    - **Property 6: Invalid or future timestamps are treated as absent**
    - Generar strings no-ISO-8601 + timestamps futuros → delay = 0
    - **Validates: Requirements 3.4, 4.5**

  - [x] 3.7 Write property test: fallback to default (Hypothesis)
    - **Property 7: Invalid JitterWindowSeconds falls back to default**
    - Generar jitter window fuera [5, 300] → effective = 30
    - **Validates: Requirements 3.5, 5.4**

  - [x] 3.8 Write property test: first reconnection delay (Hypothesis)
    - **Property 8: First WebSocket reconnection uses jitter delay**
    - Generar window ∈ [5, 300] → reconnection delay ∈ [0, W*1000)
    - **Validates: Requirements 5.1**

- [x] 4. Client C#: RegistryConfigManager (lectura/escritura Registry)
  - [x] 4.1 Agregar métodos de jitter al RegistryConfigManager
    - Agregar `LoadJitterWindowSeconds()` → lee DWORD `JitterWindowSeconds`, retorna int (30 si ausente o error)
    - Agregar `SaveJitterWindowSeconds(int value)` → escribe DWORD
    - Agregar `LoadLastUpdateTimestamp()` → lee String ISO 8601, retorna DateTime? (null si ausente/inválido/futuro)
    - Agregar `SaveLastUpdateTimestamp(DateTime utcNow)` → escribe String ISO 8601
    - Agregar `LoadLastRestartTimestamp()` → lee String ISO 8601, retorna DateTime? (null si ausente/inválido/futuro)
    - Agregar `SaveLastRestartTimestamp(DateTime utcNow)` → escribe String ISO 8601
    - Manejo de errores: log con AlwaysPrintLogger.WriteWarning y continuar sin interrumpir
    - Ruta Registry: `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 5. Client C#: Integración en CloudWebSocketClient y TrayApplicationContext
  - [x] 5.1 Modificar CloudWebSocketClient para jitter en primer reconexión
    - Agregar flag `_isFirstReconnect = true` que se resetea a `true` en `OnConnected`
    - En `ScheduleReconnect`: si `_isFirstReconnect && !_longRetryMode`, calcular delay con `JitterCalculator.ComputeReconnectionDelay(jitterWindow)`
    - Setear `_isFirstReconnect = false` tras usar jitter; `_currentDelayMs = 2000` para siguiente intento
    - Leer jitter window del Registry vía `RegistryConfigManager.LoadJitterWindowSeconds()`
    - Log del delay aplicado con AlwaysPrintLogger
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 5.2 Implementar lógica de startup delay en TrayApplicationContext
    - Al iniciar, antes de conectar WebSocket:
      - Leer `JitterWindowSeconds`, `LastUpdateTimestamp`, `LastRestartTimestamp` del Registry
      - Llamar `JitterCalculator.ComputeStartupDelay(...)` para obtener delay y reason
      - Si delay > 0, loggear "Aplicando jitter de Xs por {reason}" y esperar con `Task.Delay` o `Thread.Sleep`
    - Luego proceder con la conexión WebSocket normal
    - _Requirements: 3.1, 3.2, 3.3, 3.6, 4.1, 4.2, 4.3, 4.6_

  - [x] 5.3 Persistir `jitter_window_seconds` en Registry al recibir config_update
    - En el handler de `config_update` del Tray (CloudManager/HandleConfigUpdate), extraer `jitter_window_seconds` del payload
    - Llamar `RegistryConfigManager.SaveJitterWindowSeconds(value)` 
    - Si falla, loggear y continuar con valor previo
    - _Requirements: 7.2, 7.3, 7.4_

- [x] 6. Client C#: Service timestamps
  - [x] 6.1 Escribir `LastUpdateTimestamp` tras actualización MSI exitosa
    - En AlwaysPrintWindowsService, después de que msiexec complete exitosamente, llamar `RegistryConfigManager.SaveLastUpdateTimestamp(DateTime.UtcNow)`
    - Si falla escritura, loggear error y continuar
    - _Requirements: 2.3, 2.5_

  - [x] 6.2 Escribir `LastRestartTimestamp` antes de reiniciar Tray
    - En AlwaysPrintWindowsService, justo antes de matar el proceso Tray para reiniciarlo, llamar `RegistryConfigManager.SaveLastRestartTimestamp(DateTime.UtcNow)`
    - Si falla escritura, loggear error y continuar con reinicio
    - _Requirements: 2.4, 2.5_

- [x] 7. Checkpoint - Client C# completo
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Frontend: Input de configuración de jitter
  - [x] 8.1 Agregar input numérico de jitter window en la página de settings de organización
    - Input tipo number, min=5, max=300, step=1
    - Validación client-side: mostrar error si < 5 o > 300 antes de enviar
    - Al submit exitoso: mostrar notificación de éxito
    - Al submit fallido: mostrar toast de error, restaurar valor anterior
    - _Requirements: 6.1, 6.4, 6.7_

  - [x] 8.2 Implementar cálculo dinámico de tasa de conexiones
    - Obtener count de workstations activas (N) al cargar la página de settings
    - Mostrar texto: "Con X segundos de ventana y N workstations activas, aproximadamente N/X conexiones por segundo durante eventos masivos"
    - Actualizar cálculo dentro de 300ms del último keystroke (debounce)
    - Si N = 0: mostrar texto sin la tasa (indicar que no hay workstations activas)
    - _Requirements: 6.2, 6.3, 6.5, 6.6_

  - [x] 8.3 Write property test: cálculo frontend (Hypothesis)
    - **Property 9: Frontend calculation correctness**
    - Generar X ∈ [5, 300], N > 0 → texto muestra N/X
    - **Validates: Requirements 6.2**

  - [x] 8.4 Write property test: validación frontend (Hypothesis)
    - **Property 10: Frontend validation rejects out-of-range values**
    - Generar V < 5 o V > 300 → validación rechaza
    - **Validates: Requirements 6.4**

- [x] 9. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties (Hypothesis, min 100 iteraciones)
- Unit tests validate specific examples and edge cases
- Todos los comentarios y logs en código deben estar en español
- Importar Base desde `app.core.database` (nunca desde `app.db`)
- Usar `AlwaysPrintLogger` para todos los logs en C# (nunca `Console.WriteLine`)
- Migración Alembic con nombre date-based: `20260615_add_jitter_window_seconds`
- JitterCalculator acepta `Random?` como parámetro para testing determinístico

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "3.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "3.2", "3.3", "3.4", "3.5", "3.6", "3.7", "3.8", "4.1"] },
    { "id": 2, "tasks": ["1.4", "1.5", "1.6", "5.1", "5.2", "5.3"] },
    { "id": 3, "tasks": ["6.1", "6.2"] },
    { "id": 4, "tasks": ["8.1"] },
    { "id": 5, "tasks": ["8.2", "8.3", "8.4"] }
  ]
}
```
