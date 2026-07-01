# Runbook: Actualización Forzada de Workstations Legacy

## Contexto

Cuando se activa la firma ECDSA en una organización, las workstations con versiones antiguas del client
(`< 1.26.701`) no pueden descargar la ActionConfig porque:

1. **Versión 1.26.617.x**: Usa flujo legacy `CheckAndDownloadConfigAsync` que verifica SHA256 del body
   descargado vs hash esperado. El body ahora es un signed envelope → hash mismatch.
2. **Versión 1.26.629.x**: Usa flujo push-based `PushMessageHandler.SyncFromState` que necesita
   `config_s3_url` del enrichment. Con `cert_version=0` no hay URL S3.

Sin la config, la acción `WriteAppSetting AutoUpdateEnabled=1` nunca se ejecuta → deadlock.

## Prerequisitos

- AWS CLI configurado con perfil `AlwaysPrint-prod-425642439683`
- Instance ID del servidor: `i-0b42738edf1860c00`
- Org ID de BBVA: `cc22b376-15c1-4849-8c5b-662ca4aa0b66`
- DB URL: `postgresql://alwaysprint_admin:XlpP1KD8ZkI5Nl0QIbgyHqTEKpqVnmRU@alwaysprint-prod-postgres.croiioqgsskk.us-west-2.rds.amazonaws.com/alwaysprint`

## Procedimiento

### Fase 1 — Desactivar firma temporalmente

**Paso 1.1** — Verificar estado actual:

```bash
# Crear archivo de comando
cat > /tmp/ssm_cmd.json << 'EOF'
{
  "commands": ["docker exec alwaysprint-backend-1 psql \"postgresql://alwaysprint_admin:XlpP1KD8ZkI5Nl0QIbgyHqTEKpqVnmRU@alwaysprint-prod-postgres.croiioqgsskk.us-west-2.rds.amazonaws.com/alwaysprint\" -c \"SELECT id, name, ecdsa_cert_version FROM organizations WHERE id = 'cc22b376-15c1-4849-8c5b-662ca4aa0b66';\""]
}
EOF

aws --profile AlwaysPrint-prod-425642439683 ssm send-command \
  --instance-ids i-0b42738edf1860c00 \
  --document-name AWS-RunShellScript \
  --parameters file:///tmp/ssm_cmd.json
```

Confirmar que `ecdsa_cert_version = 1` (o el valor actual).

**Paso 1.2** — Desactivar firma (poner cert_version = 0):

```bash
cat > /tmp/ssm_cmd.json << 'EOF'
{
  "commands": ["docker exec alwaysprint-backend-1 psql \"postgresql://alwaysprint_admin:XlpP1KD8ZkI5Nl0QIbgyHqTEKpqVnmRU@alwaysprint-prod-postgres.croiioqgsskk.us-west-2.rds.amazonaws.com/alwaysprint\" -c \"UPDATE organizations SET ecdsa_cert_version = 0 WHERE id = 'cc22b376-15c1-4849-8c5b-662ca4aa0b66'; SELECT id, name, ecdsa_cert_version FROM organizations WHERE id = 'cc22b376-15c1-4849-8c5b-662ca4aa0b66';\""]
}
EOF

aws --profile AlwaysPrint-prod-425642439683 ssm send-command \
  --instance-ids i-0b42738edf1860c00 \
  --document-name AWS-RunShellScript \
  --parameters file:///tmp/ssm_cmd.json
```

**Paso 1.3** — Reiniciar backend para invalidar caché:

```bash
cat > /tmp/ssm_cmd.json << 'EOF'
{
  "commands": ["docker restart alwaysprint-backend-1 && sleep 15 && docker ps --filter name=alwaysprint-backend-1 --format '{{.Names}} {{.Status}}'"]
}
EOF

aws --profile AlwaysPrint-prod-425642439683 ssm send-command \
  --instance-ids i-0b42738edf1860c00 \
  --document-name AWS-RunShellScript \
  --parameters file:///tmp/ssm_cmd.json
```

Esperar ~30s y verificar que el backend está UP.

### Fase 2 — Prueba con 1 workstation

1. Desde el frontend, mandar `restart_service` a la workstation de prueba.
2. Esperar ~2 minutos.
3. Verificar en el log:
   - `ConfigManager: configuración guardada exitosamente` (NO debe mostrar "hash no coincide")
   - `WriteAppSetting: AutoUpdateEnabled = '1'` escrito
   - `UpdateChecker: actualización disponible`
   - `AutoUpdate: instalación iniciada exitosamente`
4. Esperar ~3 minutos a que reinicie con la nueva versión.

**Para versiones 1.26.629.x** (que usan push-based y no descargan config via endpoint legacy):
- El auto-update YA está habilitado en estas versiones.
- Mandar `check_update` legacy desde el frontend.
- Verificar que `UpdateChecker: actualización disponible` aparece y descarga/instala.

### Fase 3 — Actualizar las demás workstations

1. Mandar `restart_service` masivo a todas las workstations con versión antigua.
2. Para las 1.26.629.x, mandar `check_update` después del restart.
3. Monitorear en el dashboard que `tray_version` cambia.

### Fase 4 — Restaurar firma

**Paso 4.1** — Reactivar ecdsa_cert_version:

```bash
cat > /tmp/ssm_cmd.json << 'EOF'
{
  "commands": ["docker exec alwaysprint-backend-1 psql \"postgresql://alwaysprint_admin:XlpP1KD8ZkI5Nl0QIbgyHqTEKpqVnmRU@alwaysprint-prod-postgres.croiioqgsskk.us-west-2.rds.amazonaws.com/alwaysprint\" -c \"UPDATE organizations SET ecdsa_cert_version = 1 WHERE id = 'cc22b376-15c1-4849-8c5b-662ca4aa0b66'; SELECT id, name, ecdsa_cert_version FROM organizations WHERE id = 'cc22b376-15c1-4849-8c5b-662ca4aa0b66';\""]
}
EOF

aws --profile AlwaysPrint-prod-425642439683 ssm send-command \
  --instance-ids i-0b42738edf1860c00 \
  --document-name AWS-RunShellScript \
  --parameters file:///tmp/ssm_cmd.json
```

**Paso 4.2** — Reiniciar backend:

```bash
cat > /tmp/ssm_cmd.json << 'EOF'
{
  "commands": ["docker restart alwaysprint-backend-1 && sleep 15 && docker ps --filter name=alwaysprint-backend-1 --format '{{.Names}} {{.Status}}'"]
}
EOF

aws --profile AlwaysPrint-prod-425642439683 ssm send-command \
  --instance-ids i-0b42738edf1860c00 \
  --document-name AWS-RunShellScript \
  --parameters file:///tmp/ssm_cmd.json
```

**Paso 4.3** — Verificar que las workstations actualizadas funcionan con firma:
- Mandar `restart_service` a una workstation ya actualizada.
- Confirmar en el log: `SignatureVerifier: verificación de firma ECDSA exitosa`.

## Obtener resultados de comandos SSM

```bash
# Después de enviar un comando, copiar el CommandId y ejecutar:
aws --profile AlwaysPrint-prod-425642439683 ssm get-command-invocation \
  --command-id <COMMAND_ID> \
  --instance-id i-0b42738edf1860c00
```

## Troubleshooting

### El MSI se descarga pero la versión no cambia (loop de reinstalación)

**Síntoma**: El log muestra `InstallUpdate: script lanzado` seguido de reinicio en <12 segundos
y la versión sigue igual.

**Causa**: El Service Recovery de Windows reinicia el servicio antes de que msiexec complete.

**Solución**: Requiere intervención manual en la workstation o cambiar la Recovery Policy
del servicio remotamente.

### Versión 1.26.629.x no descarga MSI con push-based distribution

**Síntoma**: Recibe `MsiVersion=1.26.701.x` en enrichment pero no descarga porque no hay `msi_url`.

**Causa**: Con `cert_version=0`, el state map no genera URLs de S3 para push-based.

**Solución**: Mandar `check_update` legacy (sin download_url) desde el frontend.
Esta versión tiene `CheckNowAsync()` disponible como fallback.

### ConfigManager: hash no coincide (en versiones 1.26.617.x)

**Síntoma**: `hash no coincide. Esperado: f5b53c8a, Obtenido: XXXX`

**Causa**: El endpoint retornaba JSON pretty-printed pero el hash se calcula sobre JSON compacto.

**Fix permanente**: Commit `b57749e` normaliza el JSON a formato compacto en el endpoint de descarga.
Asegurar que el backend tenga este fix desplegado antes de ejecutar el procedimiento.

## Riesgos de la ventana sin firma

- **Duración estimada**: 15-30 minutos (según cantidad de workstations).
- **Impacto**: Las configs se sirven sin verificación de integridad durante la ventana.
- **Mitigación**: Las workstations ya están autenticadas por workstation_id (UUID único).
  El JSON de config no contiene datos sensibles, solo acciones administrativas.
- **No se modifica**: `ecdsa_private_key_encrypted`, `ecdsa_cert_s3_key`, ni `ecdsa_cert_expires_at`.
  Solo se cambia `ecdsa_cert_version` temporalmente.

## Historial de ejecuciones

| Fecha | Org | WS actualizadas | Duración ventana | Operador |
|---|---|---|---|---|
| 2026-07-01 | BBVA | ~20 (de 1.26.617/629 → 1.26.701.312) | ~45 min | Antonio Robles |

---

*Última actualización: 2026-07-01*
