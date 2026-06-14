# Bugfix Requirements Document

## Introduction

Cuando un administrador envía un comando `check_update` a todas las workstations de una organización (hasta 303 simultáneas), cada workstation llama individualmente al backend (`/api/v1/updates/check` y `/api/v1/updates/download`), saturando el pool de conexiones a la BD (20 + overflow 10 = 30 conexiones) y provocando timeouts generalizados. El resultado es que NINGUNA workstation se actualiza porque el backend se vuelve no-responsivo.

La causa raíz es que el mensaje WebSocket `check_update` solo indica "hay una actualización disponible" sin incluir la información necesaria para descargar directamente, forzando a cada workstation a consultar al backend de forma independiente (thundering herd problem).

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN el admin envía un comando `check_update` a N workstations (N > 30) via WebSocket THEN todas las N workstations simultáneamente hacen HTTP requests al endpoint `/api/v1/updates/check` del backend

1.2 WHEN N workstations (N > 30) llaman simultáneamente a `/api/v1/updates/check` THEN el pool de conexiones a la BD (30 máximo) se satura y las conexiones excedentes reciben timeout

1.3 WHEN las workstations reciben respuesta exitosa de `/updates/check` THEN cada una llama adicionalmente a `/api/v1/updates/download`, duplicando la carga sobre el backend

1.4 WHEN el pool de BD está saturado por las consultas simultáneas de check+download THEN el backend retorna errores de timeout y NINGUNA workstation completa la actualización

### Expected Behavior (Correct)

2.1 WHEN el admin envía un comando `check_update` a N workstations THEN el backend SHALL generar UNA sola presigned URL de S3 y broadcast el mensaje WebSocket incluyendo `download_url`, `version` y `file_size`

2.2 WHEN una workstation recibe un comando `check_update` con campo `download_url` presente THEN la workstation SHALL descargar directamente desde la presigned URL de S3 sin llamar a `/api/v1/updates/check` ni `/api/v1/updates/download`

2.3 WHEN N workstations descargan simultáneamente desde la presigned URL de S3 THEN el backend SHALL tener CERO queries adicionales a la BD por concepto de esas descargas (la carga se distribuye a S3)

2.4 WHEN el backend genera la presigned URL para el broadcast THEN la URL SHALL tener una expiración de 1 hora (3600 segundos)

### Unchanged Behavior (Regression Prevention)

3.1 WHEN una workstation recibe un comando `check_update` SIN campo `download_url` (clientes antiguos o comando legacy) THEN la workstation SHALL CONTINUE TO llamar a `/api/v1/updates/check` y `/api/v1/updates/download` como antes (backward compatibility)

3.2 WHEN una workstation ejecuta la verificación periódica de actualización (timer de 24 horas) THEN la workstation SHALL CONTINUE TO llamar a `/api/v1/updates/check` normalmente

3.3 WHEN el flag `auto_update_enabled` de la organización es `false` THEN el sistema SHALL CONTINUE TO respetar el flag y no proceder con la descarga, incluso si `download_url` está presente en el mensaje

3.4 WHEN una workstation individual llama al endpoint `/api/v1/updates/download` directamente (sin broadcast masivo) THEN el endpoint SHALL CONTINUE TO funcionar normalmente con su flujo actual de presigned URL y streaming

3.5 WHEN el flag local de auto-actualización está deshabilitado en la workstation THEN la workstation SHALL CONTINUE TO ignorar el comando `check_update` sin iniciar descarga

---

## Bug Condition (Pseudocode)

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type CheckUpdateCommand
  OUTPUT: boolean
  
  // El bug se manifiesta cuando el comando check_update se envía
  // a múltiples workstations sin incluir download_url (flujo actual)
  RETURN X.command_type = "check_update" 
     AND X.params.download_url IS NULL
     AND X.target_count > pool_size (30)
END FUNCTION
```

```pascal
// Property: Fix Checking - Zero Backend Queries
FOR ALL X WHERE isBugCondition(X) DO
  result ← broadcast_check_update'(X)
  ASSERT result.message CONTAINS "download_url"
  ASSERT result.message CONTAINS "version"
  ASSERT result.message CONTAINS "file_size"
  ASSERT backend_queries_count(result) = 0
  ASSERT all_workstations_can_download(result) = TRUE
END FOR
```

```pascal
// Property: Preservation Checking - Legacy Flow
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT F(X) = F'(X)
  // Workstations sin download_url siguen usando el flujo HTTP existente
  // Verificación periódica (timer 24h) sigue funcionando igual
END FOR
```
