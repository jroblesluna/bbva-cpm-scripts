# Instalación desde cero — AlwaysPrint Cloud

Guía completa para aprovisionar la infraestructura por primera vez, asumiendo que no existe ningún recurso AWS ni configuración previa.

---

## Requisitos previos

| Herramienta | Versión mínima | Verificar |
|-------------|---------------|-----------|
| Terraform | 1.5+ | `terraform -version` |
| AWS CLI | 2.x | `aws --version` |
| Git | cualquiera | `git --version` |

Una cuenta AWS con permisos suficientes (ver sección de IAM más abajo).

---

## 1. Credenciales AWS

### Crear usuario IAM para Terraform

En AWS Console → IAM → Users → Create user:

- **Nombre**: `alwaysprint-terraform` (o similar)
- **Políticas**: adjuntar las siguientes managed policies:
  - `AmazonEC2FullAccess`
  - `AmazonRDSFullAccess`
  - `AmazonECR_FullAccess` (o `AmazonEC2ContainerRegistryFullAccess`)
  - `AmazonVPCFullAccess`
  - `SecretsManagerReadWrite`
  - `AmazonSESFullAccess`
  - `IAMFullAccess`

Generar **Access Key** (tipo: CLI) y guardar el `Access Key ID` y `Secret Access Key`.

### Configurar AWS CLI

```bash
aws configure --profile alwaysprint
# AWS Access Key ID: <tu key>
# AWS Secret Access Key: <tu secret>
# Default region name: us-west-2
# Default output format: json
```

Verificar:

```bash
aws sts get-caller-identity --profile alwaysprint
```

Activar el perfil para la sesión:

```bash
export AWS_PROFILE=alwaysprint
```

---

## 2. Revisar terraform.tfvars

El archivo `terraform.tfvars` está commiteado con los valores de producción. Revisar y ajustar si el entorno es diferente:

```hcl
aws_region   = "us-west-2"       # región donde se despliega todo
project_name = "alwaysprint"     # prefijo de todos los recursos
environment  = "prod"

zone_name      = "apps.iol.pe"   # zona DNS donde vive el subdominio
subdomain      = "alwaysprint"   # resultado: alwaysprint.apps.iol.pe
ses_from_email = "noreply@alwaysprint.apps.iol.pe"

db_name     = "alwaysprint"
db_username = "alwaysprint_admin"
# La contraseña se genera automáticamente (solo alfanumérica, URL-safe)

ec2_instance_type = "t3.micro"   # Free Tier eligible
db_instance_class = "db.t3.micro"
rds_backup_retention_days = 0    # 0 = Free Tier; cambiar a 7+ con plan pagado
```

No editar `ssh_public_key` — `setup.sh` lo gestiona automáticamente.

---

## 3. Primer apply

```bash
cd AlwaysPrintProject/Cloud/terraform

chmod +x setup.sh
./setup.sh plan    # revisar qué se va a crear (~30 recursos)
./setup.sh apply   # aprovisionar (tarda ~10 min)
```

Lo que hace `setup.sh` la primera vez:
1. Detecta que no existe el secret SSH en Secrets Manager
2. Genera un par de claves ed25519
3. Guarda la clave privada en Secrets Manager (`/alwaysprint/prod/ssh_private_key`)
4. Escribe la clave pública en `terraform.tfvars`
5. Ejecuta `terraform init` + `terraform apply`

---

## 4. Obtener los outputs

```bash
terraform output
```

Los valores importantes:

```
app_url          = "https://alwaysprint.apps.iol.pe"
ec2_public_ip    = "X.X.X.X"          ← necesario para DNS
ses_dns_records  = { ... }             ← necesario para SES + email
```

---

## 5. Configurar DNS (Hostinger — zona iol.pe)

Acceder al editor de zona de `iol.pe` en Hostinger y agregar los siguientes registros.

> En el campo **Nombre/Host** ingresar solo la parte del subdominio, sin el sufijo `.iol.pe`.

### 5.1 Registro A — servidor de aplicación

| Tipo | Nombre | Valor | TTL |
|------|--------|-------|-----|
| `A` | `alwaysprint.apps` | `<ec2_public_ip del output>` | `600` |

### 5.2 Registros SES — obtener valores exactos con:

```bash
terraform output ses_dns_records
```

El output tiene 6 registros. Agregarlos todos:

| Tipo | Nombre | Valor |
|------|--------|-------|
| `TXT` | `_amazonses.apps` | valor de verificación del dominio |
| `CNAME` | `<token1>._domainkey.apps` | `<token1>.dkim.amazonses.com` |
| `CNAME` | `<token2>._domainkey.apps` | `<token2>.dkim.amazonses.com` |
| `CNAME` | `<token3>._domainkey.apps` | `<token3>.dkim.amazonses.com` |
| `MX` | `mail.apps` | `feedback-smtp.us-west-2.amazonses.com` (prioridad `10`) |
| `TXT` | `mail.apps` | `v=spf1 include:amazonses.com ~all` |

### 5.3 Registros CAA — autorización SSL

Verificar que existan en `@` (`iol.pe`). Si no, agregarlos:

| Tipo | Nombre | Valor |
|------|--------|-------|
| `CAA` | `@` | `0 issue "letsencrypt.org"` |
| `CAA` | `@` | `0 issuewild "letsencrypt.org"` |
| `CAA` | `@` | `0 issue "amazon.com"` |

---

## 6. Esperar propagación DNS y SSL

La propagación DNS tarda entre 15 y 60 minutos. El EC2 ejecuta Certbot automáticamente en background con 20 reintentos (1 minuto de pausa entre cada uno) — obtiene el certificado SSL en cuanto el DNS apunte a la IP correcta.

Verificar propagación:

```bash
nslookup alwaysprint.apps.iol.pe
# debe devolver la IP del output ec2_public_ip
```

---

## 7. Configurar GitHub Actions

En el repositorio GitHub → **Settings → Secrets and variables → Actions → Secrets**:

Agregar **únicamente** estos 2 secretos:

| Secret | Valor |
|--------|-------|
| `AWS_ACCESS_KEY_ID` | Access Key ID del usuario IAM de CI/CD (ver abajo) |
| `AWS_SECRET_ACCESS_KEY` | Secret Access Key correspondiente |

### Usuario IAM para CI/CD (distinto al de Terraform)

Crear un segundo usuario IAM `alwaysprint-cicd` con permisos mínimos:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ssm:SendCommand",
        "ssm:GetCommandInvocation"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances"
      ],
      "Resource": "*"
    }
  ]
}
```

> `AWS_REGION`, ECR URLs y el instance ID **no** se configuran en GitHub — los workflows
> los leen de `terraform.tfvars` o los derivan dinámicamente de AWS.

---

## 8. Primer deploy de imágenes

Los repositorios ECR están vacíos tras el apply. Disparar los workflows manualmente:

```
GitHub → Actions → Deploy Backend  → Run workflow → main
GitHub → Actions → Deploy Frontend → Run workflow → main
```

Esto construye las imágenes Docker y las sube a ECR. El EC2 las descarga y levanta los containers.

---

## 9. Crear el primer administrador

Una vez que el DNS propagó y los containers están corriendo:

```
https://alwaysprint.apps.iol.pe/setup
```

Este endpoint solo funciona una vez (cuando no existe ningún usuario en la BD). Crear el superadmin con email y contraseña seguros.

---

## 10. Habilitar SES para producción (salir del sandbox)

Por defecto SES solo envía emails a direcciones verificadas manualmente. Para habilitar envío a cualquier destinatario:

1. AWS Console → **SES → Account dashboard**
2. **Request production access**
3. Completar formulario: uso transaccional, volumen estimado (~100/día)
4. AWS responde en 24–48 horas

---

## Verificación final

```bash
# Sitio accesible y con SSL
curl -I https://alwaysprint.apps.iol.pe

# API respondiendo
curl https://alwaysprint.apps.iol.pe/api/v1/

# SES verificado
aws ses get-identity-verification-attributes \
  --identities apps.iol.pe \
  --region us-west-2
# VerificationStatus debe ser "Success"
```
