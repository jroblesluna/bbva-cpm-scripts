# Bugs Pendientes - 2026-07-04

## BUG: RunProcess.store_result_in guarda en diccionario incorrecto

**Estado**: ✅ CORREGIDO — commit pendiente de build MSI  
**Archivo**: `AlwaysPrintProject/Client/AlwaysPrintService/Actions/ActionEngine.cs`  
**Línea**: 1006-1009  
**Workaround aplicado**: El alwaysconfig usa un solo script PowerShell con lógica interna (no depende de Conditional + store_result_in de RunProcess)

### Descripción

`ExecuteRunProcess` usa `SetConfigVariable(action.StoreResultIn, ...)` que guarda en `_configVariables`.  
Sin embargo, `EvaluateCondition` usa `GetVariable()` que busca en `_variables`.

Son dos diccionarios distintos:
- `_configVariables` → Dictionary<string, string> — usado para variables estáticas (corporate_queue_name, registry_path)
- `_variables` → Dictionary<string, object> — usado para runtime (inactive_users, orphaned_recent, etc.)

### Evidencia

Log de producción (v1.26.702.2322 y v1.26.704.650):
```
ActionEngine: variable de configuración 'msi_local_check' establecida.
ActionEngine: acción 'RunProcess' falló
ActionEngine: ejecutando acción 'Conditional': Si MSI local no existe...
ActionEngine: variable 'msi_local_check' no existe    ← GetVariable busca en _variables, no la encuentra
ActionEngine: condición evaluada: False
```

### Verificación de otros actions con store_result_in

| Acción | Diccionario usado | Estado |
|--------|-------------------|--------|
| `GetLoggedInUsers` | `_variables[action.StoreResultIn!] = users` | ✅ Correcto |
| `ClassifyOrphanedUsers` | `_variables[baseVarName + "_recent"] = ...` | ✅ Correcto |
| `ReadAppSetting` | `_variables` + `_configVariables` (ambos) | ✅ Correcto |
| `ReadRegistryValue` | `_variables` + `_configVariables` (ambos) | ✅ Correcto |
| `ReadPrintQueuePort` | `_variables` + `_configVariables` (ambos) | ✅ Correcto |
| `CheckPrintQueueExists` | `_variables[action.StoreResultIn] = ...` | ✅ Correcto |
| **`RunProcess`** | **`SetConfigVariable()` → solo `_configVariables`** | ❌ **BUG** |

### Fix propuesto

```csharp
// En ExecuteRunProcess (línea ~1006), reemplazar:
SetConfigVariable(action.StoreResultIn, result ? "success" : "failed");

// Por:
_variables[action.StoreResultIn!] = result ? "success" : "failed";
_configVariables[action.StoreResultIn!] = result ? "success" : "failed";
AlwaysPrintLogger.WriteInfo(
    $"ActionEngine: resultado de RunProcess almacenado en variable '{action.StoreResultIn}': {(result ? "success" : "failed")}");
```

Nota: escribir en AMBOS diccionarios (como hacen ReadAppSetting y ReadPrintQueuePort) para que:
- `EvaluateCondition` → `GetVariable()` lo encuentre en `_variables`
- `ReplaceTemplates` → lo encuentre en `_configVariables` para uso en templates

### Impacto

- Cualquier `Conditional` que dependa del resultado de un `RunProcess` vía `store_result_in` NO funciona.
- Workaround actual: toda la lógica de decisión va dentro de un solo script PowerShell.
- Corregir en el próximo build del MSI (v1.26.705.x o superior).
