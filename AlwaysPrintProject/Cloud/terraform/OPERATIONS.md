# Operaciones — AlwaysPrint Cloud

Referencia para operaciones sobre la infraestructura existente.

---

## Acceso al servidor

El EC2 no tiene el puerto 22 abierto. El acceso es exclusivamente vía **AWS SSM Session Manager**.

```bash
# Sesión interactiva (terminal en el servidor)
aws ssm start-session \
  --target $(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=alwaysprint-prod-ec2" \
              "Name=instance-state-name,Values=running" \
    --query "Reservations[0].Instances[0].InstanceId" --output text) \
  --region us-west-2 \
  --profile alwaysprint
```

Una vez dentro:

```bash
# Estado de los containers
docker compose -f /opt/alwaysprint/docker-compose.yml ps

# Logs del backend
docker logs alwaysprint-backend-1 --tail 50 -f

# Logs del frontend
docker logs alwaysprint-frontend-1 --tail 50 -f

# Logs de nginx
tail -f /var/log/nginx/error.log

# Logs de SSL (setup inicial)
tail -f /var/log/setup_ssl.log
```

**SSH de emergencia** (requiere tener la clave privada):

```bash
aws secretsmanager get-secret-value \
  --secret-id /alwaysprint/prod/ssh_private_key \
  --region us-west-2 \
  --query SecretString --output text > server.pem
chmod 600 server.pem

EC2_IP=$(cd /ruta/al/terraform && terraform output -raw ec2_public_ip)
ssh -i server.pem ec2-user@$EC2_IP
```

---

## Deploy manual

Los deploys normales ocurren automáticamente al hacer push a `main`. Para forzar un deploy:

```
GitHub → Actions → Deploy Backend  → Run workflow
GitHub → Actions → Deploy Frontend → Run workflow
```

O desde el EC2 (vía SSM):

```bash
cd /opt/alwaysprint
bash deploy.sh backend    # solo backend
bash deploy.sh frontend   # solo frontend
bash deploy.sh all        # ambos
```

---

## Destroy y recreación desde cero

### Antes del destroy — backup de la BD

La BD no tiene backups automáticos (`backup_retention_days = 0`). Hacer dump antes de destruir:

```bash
# Dentro de sesión SSM
docker exec alwaysprint-backend-1 \
  sh -c 'pg_dump $DATABASE_URL' > backup_$(date +%Y%m%d).sql
```

### Destruir

```bash
cd AlwaysPrintProject/Cloud/terraform
terraform destroy
```

### Recrear

```bash
./setup.sh apply
```

### Pasos manuales post-recreación

1. **Actualizar registro A en DNS** — la Elastic IP cambia con cada recreación:
   ```bash
   terraform output ec2_public_ip
   # Actualizar en Hostinger: alwaysprint.apps → nueva IP
   ```

2. **Verificar si los registros DKIM cambiaron** — SES genera nuevas claves al recrearse:
   ```bash
   terraform output ses_dns_records
   # Comparar con los CNAME existentes en Hostinger y actualizar si difieren
   ```

3. **Esperar propagación DNS** (15–60 min) — SSL se configura automáticamente una vez que el DNS apunta a la nueva IP.

4. **Subir imágenes a ECR** — los repositorios quedan vacíos tras el destroy:
   ```
   GitHub → Actions → Deploy Backend  → Run workflow
   GitHub → Actions → Deploy Frontend → Run workflow
   ```

5. **Crear primer admin**:
   ```
   https://alwaysprint.apps.iol.pe/setup
   ```

6. **No hay que tocar GitHub Actions** — el instance ID se deriva automáticamente por tag, las ECR URLs por el registry de ECR login, y la región viene de `terraform.tfvars`.

---

## Rotación de clave SSH

```bash
./setup.sh apply --rotate-key
```

Genera un nuevo par ed25519, actualiza Secrets Manager y sincroniza `terraform.tfvars`. El apply siguiente recrea el key pair en AWS.

---

## Cambiar la contraseña de la BD

La contraseña no se gestiona con Terraform (tiene `lifecycle { ignore_changes }`). Para cambiarla manualmente:

```bash
# 1. Generar nueva contraseña URL-safe (solo alfanumérico + - _)
NEW_PASS=$(python3 -c "import secrets, string; \
  chars=string.ascii_letters+string.digits+'-_'; \
  print(''.join(secrets.choice(chars) for _ in range(32)))")

# 2. Aplicar en RDS
aws rds modify-db-instance \
  --db-instance-identifier alwaysprint-prod-postgres \
  --master-user-password "$NEW_PASS" \
  --apply-immediately \
  --region us-west-2

# 3. Esperar a que RDS aplique el cambio
aws rds wait db-instance-available \
  --db-instance-identifiers alwaysprint-prod-postgres \
  --region us-west-2

# 4. Actualizar secretos en Secrets Manager
DB_HOST=$(aws rds describe-db-instances \
  --db-instance-identifier alwaysprint-prod-postgres \
  --query 'DBInstances[0].Endpoint.Address' --output text --region us-west-2)

aws secretsmanager put-secret-value \
  --secret-id /alwaysprint/prod/db_password \
  --secret-string "$NEW_PASS" --region us-west-2

aws secretsmanager put-secret-value \
  --secret-id /alwaysprint/prod/database_url \
  --secret-string "postgresql://alwaysprint_admin:${NEW_PASS}@${DB_HOST}/alwaysprint" \
  --region us-west-2

# 5. Actualizar .env.backend en el EC2 y reiniciar backend (via SSM)
```

> La contraseña debe contener **solo** caracteres `[a-zA-Z0-9-_]`. Caracteres como
> `%`, `+`, `=`, `[`, `]` rompen el parsing de la URL de conexión en psycopg2.

---

## Actualizar infraestructura (cambios de configuración)

Para cualquier cambio en módulos o variables:

```bash
./setup.sh plan    # revisar impacto
./setup.sh apply   # aplicar
```

Si el cambio afecta `user_data` del EC2, **no** se recrea automáticamente
(`user_data_replace_on_change = false`). Los cambios al script de inicialización
solo aplican si el EC2 se recrea manualmente.

---

## Costos estimados (AWS us-west-2)

| Recurso | Tipo | $/mes aprox. |
|---------|------|-------------|
| EC2 | t3.micro | $0 (Free Tier 12 meses) / ~$8 después |
| RDS | db.t3.micro | $0 (Free Tier 12 meses) / ~$15 después |
| ECR | almacenamiento | ~$0.5 (500 MB) |
| SES | 1,000 emails | ~$0.10 |
| Secrets Manager | 4 secretos | ~$1.60 |
| Elastic IP | (asociada) | $0 |
| **Total estimado** | | **~$2/mes en Free Tier** |

> Pasado el Free Tier (12 meses), el costo sube a ~$25/mes.
> Para reducir: apagar el EC2 cuando no se use o migrar a instancias ARM (Graviton).
