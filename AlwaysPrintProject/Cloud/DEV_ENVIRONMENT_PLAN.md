# Plan de Implementación: Entorno Dev en AWS

## Progreso

| Paso | Descripción | Estado |
|------|-------------|--------|
| 1 | Configurar credenciales AWS cuenta Dev | ✅ Completado |
| 2 | Configurar zona DNS dev.iol.pe | ⏳ Pendiente |
| 3 | Crear archivo dev.tfvars | ✅ Completado |
| 4 | Levantar infraestructura Dev con Terraform | ⏳ Pendiente (requiere paso 2) |
| 5 | Configurar GitHub Environments y Secrets | ⏳ Pendiente |
| 6 | Crear workflows unificados | ⏳ Pendiente |
| 7 | Test E2E deploy a Dev | ⏳ Pendiente |
| 8 | Test E2E aprobación a Prod | ⏳ Pendiente |

### Cambios ya aplicados en Prod
- ✅ Terraform workspace `prod` creado y funcionando
- ✅ Bucket S3 renombrado: `alwaysprint-artifacts` → `alwaysprint-prod-artifacts`
- ✅ Backend parametrizado: lee `S3_ARTIFACTS_BUCKET` de variable de entorno
- ✅ Módulos Terraform (`s3`, `ec2`) usan nombre de bucket dinámico
- ✅ `force_destroy = true` en bucket S3 (evita errores al destruir)
- ✅ `.gitignore` actualizado para `tfplan*` y `terraform.tfstate.d/`
- ✅ Push a main realizado (commit `2626bf4`)

---

## Resumen

Crear un entorno de desarrollo (`alwaysprint.dev.iol.pe`) en la cuenta AWS **040982755196** (free tier), separado de producción (`alwaysprint.apps.iol.pe`). Despliegue automático a Dev en cada push a main; promoción a Prod solo con aprobación manual vía GitHub Environments.

| Entorno | Cuenta AWS | Dominio | Trigger | Gate |
|---------|-----------|---------|---------|------|
| Dev | 040982755196 | alwaysprint.dev.iol.pe | Push a main (automático) | Ninguno |
| Prod | 425642439683 | alwaysprint.apps.iol.pe | Aprobación manual | Required Reviewer |

## Flujo de Despliegue

```
Push a main ──→ Job 1: Deploy a DEV (automático)
                         ↓
              Verificas en alwaysprint.dev.iol.pe
                         ↓
              Apruebas en GitHub Actions UI
                         ↓
                Job 2: Deploy a PROD
```

Aplica a los 3 componentes: Backend, Frontend y Cliente MSI.


---

## Paso 1: Configurar credenciales AWS de la cuenta Dev

### Requisitos previos
- Acceso a la consola AWS de la cuenta 040982755196
- Permisos para crear usuarios IAM

### Acciones
1. Entrar a la consola AWS de la cuenta 040982755196
2. IAM → Users → Create User: `github-actions-dev`
3. Adjuntar políticas:
   - `AmazonEC2FullAccess`
   - `AmazonRDSFullAccess`
   - `AmazonVPCFullAccess`
   - `AmazonRoute53FullAccess`
   - `AmazonEC2ContainerRegistryFullAccess`
   - `AmazonSSMFullAccess`
   - `SecretsManagerReadWrite`
   - `AmazonSESFullAccess`
   - `AmazonS3FullAccess`
   - `IAMFullAccess` (necesario para que Terraform cree roles)
4. Crear Access Key (tipo: "Third-party service")
5. Guardar `AWS_ACCESS_KEY_ID` y `AWS_SECRET_ACCESS_KEY`

### Verificación
```bash
aws configure --profile AlwaysPrint-dev-040982755196
# Ingresar keys, region: us-west-2

aws sts get-caller-identity --profile AlwaysPrint-dev-040982755196
```

**Resultado esperado**: `Account: 040982755196` y ARN del usuario.

---

## Paso 2: Configurar zona DNS dev.iol.pe

### Requisitos previos
- Paso 1 completado
- Acceso al registrador del dominio `iol.pe` (para delegar NS)

### Acciones
1. En la consola AWS de la cuenta 040982755196:
   - Route53 → Hosted Zones → Create Hosted Zone
   - Domain: `dev.iol.pe`
   - Type: Public Hosted Zone
2. Copiar los 4 registros NS que Route53 asigna
3. En el registrador de `iol.pe` (o cuenta AWS donde está la zona `iol.pe`):
   - Crear registro NS para `dev.iol.pe` apuntando a los 4 nameservers

### Verificación
```bash
# Esperar 5-10 minutos, luego:
dig NS dev.iol.pe
```

**Resultado esperado**: Retorna los NS de Route53 de la cuenta dev.

---

## Paso 3: Crear archivo dev.tfvars

### Requisitos previos
- Pasos 1 y 2 completados
- Terraform >= 1.5 instalado localmente

### Acciones
1. Renombrar `terraform.tfvars` → `prod.tfvars`:
   ```bash
   cd AlwaysPrintProject/Cloud/terraform
   mv terraform.tfvars prod.tfvars
   ```

2. Crear `dev.tfvars`:
   ```hcl
   aws_region   = "us-west-2"
   project_name = "alwaysprint-dev"
   environment  = "dev"

   vpc_cidr              = "10.0.0.0/16"
   public_subnet_cidrs   = ["10.0.1.0/24", "10.0.2.0/24"]
   database_subnet_cidrs = ["10.0.21.0/24", "10.0.22.0/24"]
   availability_zones    = ["us-west-2a", "us-west-2b"]

   ecr_image_tag_limit = 5

   db_name                   = "alwaysprint"
   db_username               = "alwaysprint_admin"
   db_instance_class         = "db.t3.micro"
   db_allocated_storage      = 20
   db_max_allocated_storage  = 50
   rds_deletion_protection   = false
   rds_backup_retention_days = 0

   zone_name      = "dev.iol.pe"
   subdomain      = "alwaysprint"
   ses_from_email = "noreply@dev.iol.pe"

   backend_port  = 8000
   frontend_port = 3000
   ec2_instance_type = "t3.micro"

   backend_env_vars = {
     LOG_LEVEL                   = "DEBUG"
     SES_ENABLED                 = "true"
     SES_FROM_EMAIL              = "noreply@dev.iol.pe"
     ACCESS_TOKEN_EXPIRE_MINUTES = "1440"
     ALGORITHM                   = "HS256"
     DB_POOL_SIZE                = "5"
     DB_MAX_OVERFLOW             = "3"
     DB_POOL_TIMEOUT             = "30"
     DB_POOL_RECYCLE             = "3600"
     WS_PING_INTERVAL            = "30"
     WS_PING_TIMEOUT             = "60"
     RATE_LIMIT_LOGIN            = "50"
     RATE_LIMIT_API              = "500"
     CACHE_TTL_SECONDS           = "60"
     API_V1_STR                  = "/api/v1"
     S3_ARTIFACTS_BUCKET         = "alwaysprint-dev-dev-artifacts"
   }
   ```

   > **Nota**: `project_name = "alwaysprint-dev"` genera recursos con prefijo
   > `alwaysprint-dev-dev-*`. El bucket S3 será `alwaysprint-dev-dev-artifacts`.
   > Esto es intencional para evitar colisión de nombres globales S3.

3. Verificar `.gitignore` incluye:
   ```
   AlwaysPrintProject/Cloud/terraform/terraform*.tfstate*
   AlwaysPrintProject/Cloud/terraform/terraform.tfstate.d/
   AlwaysPrintProject/Cloud/terraform/tfplan*
   AlwaysPrintProject/Cloud/terraform/.terraform/
   ```

### Verificación
```bash
cd AlwaysPrintProject/Cloud/terraform
terraform validate

# Verificar que prod sigue OK con el rename
export AWS_PROFILE=AlwaysPrint-prod-425642439683
terraform workspace select prod
terraform plan -var-file=prod.tfvars
```

**Resultado esperado**: `terraform validate` sin errores. Plan de prod: "No changes."

---

## Paso 4: Levantar infraestructura Dev con Terraform

### Requisitos previos
- Paso 3 completado
- Perfil `AlwaysPrint-dev-040982755196` configurado
- Perfil `AlwaysPrint-prod-425642439683` configurado

### Estrategia: Terraform Workspaces

Se usa **workspaces** para separar el state de cada entorno. Misma carpeta, mismos módulos, diferente state automático:
- Workspace `prod` → state de producción (cuenta 425642439683)
- Workspace `dev` → state de desarrollo (cuenta 040982755196)

Los states se almacenan en `terraform.tfstate.d/{workspace}/terraform.tfstate`.

### Acciones
```bash
cd AlwaysPrintProject/Cloud/terraform

# 1. Seleccionar workspace dev y aplicar
export AWS_PROFILE=AlwaysPrint-dev-040982755196
terraform workspace select dev

# 2. Plan para revisar qué se va a crear
terraform plan -var-file=dev.tfvars -out=tfplan-dev

# 3. Revisar el plan (~20-30 recursos a crear). Si todo se ve bien:
terraform apply tfplan-dev

# --- Para trabajar con prod: ---
export AWS_PROFILE=AlwaysPrint-prod-425642439683
terraform workspace select prod
terraform plan -var-file=prod.tfvars
```

### Verificación
```bash
# EC2 corriendo
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=alwaysprint-dev-ec2" \
            "Name=instance-state-name,Values=running" \
  --query "Reservations[0].Instances[0].{ID:InstanceId,IP:PublicIpAddress}" \
  --profile AlwaysPrint-dev-040982755196

# DNS resuelve
dig alwaysprint.dev.iol.pe

# RDS disponible
aws rds describe-db-instances \
  --query "DBInstances[?DBInstanceIdentifier=='alwaysprint-dev'].DBInstanceStatus" \
  --profile AlwaysPrint-dev-040982755196

# ECR repos creados
aws ecr describe-repositories --profile AlwaysPrint-dev-040982755196 \
  --query "repositories[].repositoryName"

# S3 bucket para artefactos del cliente
aws s3 ls --profile AlwaysPrint-dev-040982755196 | grep alwaysprint
```

**Resultado esperado**: EC2 running, DNS resuelve, RDS available, ECR repos y S3 bucket creados.

---

## Paso 5: Configurar GitHub Environments y Secrets

### Requisitos previos
- Paso 4 completado
- Acceso de admin al repositorio en GitHub

### Acciones
1. GitHub → Repositorio → Settings → Environments
2. Crear environment **`dev`**:
   - Add secret: `AWS_ACCESS_KEY_ID` → (key de cuenta 040982755196)
   - Add secret: `AWS_SECRET_ACCESS_KEY` → (secret de cuenta 040982755196)
   - Sin protecciones adicionales (deploy automático)
3. Crear environment **`production`**:
   - Add secret: `AWS_ACCESS_KEY_ID` → (key de cuenta 425642439683)
   - Add secret: `AWS_SECRET_ACCESS_KEY` → (secret de cuenta 425642439683)
   - ✅ Activar **"Required reviewers"** → agregarte como reviewer
   - (Opcional) Activar "Wait timer" de 5 minutos para tener margen de cancelar

### Verificación
- En Settings → Environments: aparecen `dev` y `production`
- `production` muestra el badge "Protection rules" con reviewer configurado
- Cada environment muestra 2 secrets

**Resultado esperado**: Ambos environments visibles. Production tiene required reviewer activo.

---

## Paso 6: Crear workflows unificados (Dev → Prod con aprobación)

### Requisitos previos
- Paso 5 completado

### Acciones

Reemplazar los 3 workflows actuales por 3 workflows con 2 jobs cada uno (dev + prod):

**`.github/workflows/deploy-backend.yml`** (reemplaza el actual):
```yaml
name: Deploy Backend

on:
  push:
    branches: [main]
    paths:
      - 'AlwaysPrintProject/Cloud/backend/**'
  workflow_dispatch:

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true

jobs:
  deploy-dev:
    runs-on: ubuntu-latest
    environment: dev
    steps:
      - uses: actions/checkout@v4

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-west-2

      - name: Login to ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Build and push
        env:
          ECR_URL: ${{ steps.login-ecr.outputs.registry }}/alwaysprint-dev-backend
        working-directory: AlwaysPrintProject/Cloud/backend
        run: |
          TAG=${GITHUB_SHA::8}
          docker build -t $ECR_URL:$TAG -t $ECR_URL:latest .
          docker push $ECR_URL:$TAG
          docker push $ECR_URL:latest

      - name: Deploy via SSM
        run: |
          INSTANCE_ID=$(aws ec2 describe-instances \
            --filters "Name=tag:Name,Values=alwaysprint-dev-ec2" \
                      "Name=instance-state-name,Values=running" \
            --query "Reservations[0].Instances[0].InstanceId" \
            --output text)
          TAG=${GITHUB_SHA::8}
          COMMAND_ID=$(aws ssm send-command \
            --instance-ids "$INSTANCE_ID" \
            --document-name "AWS-RunShellScript" \
            --parameters "{\"commands\":[\"sed -i '/^BUILD_TAG=/d' /opt/alwaysprint/.env && echo 'BUILD_TAG=${TAG}' >> /opt/alwaysprint/.env && bash /opt/alwaysprint/deploy.sh backend\"]}" \
            --comment "Deploy backend DEV ${{ github.sha }}" \
            --query "Command.CommandId" --output text)
          aws ssm wait command-executed \
            --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID"
          STATUS=$(aws ssm get-command-invocation \
            --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" \
            --query "Status" --output text)
          [ "$STATUS" = "Success" ] || exit 1

  deploy-prod:
    runs-on: ubuntu-latest
    needs: deploy-dev
    environment: production    # ← Requiere aprobación manual
    steps:
      - uses: actions/checkout@v4

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-west-2

      - name: Login to ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Build and push
        env:
          ECR_URL: ${{ steps.login-ecr.outputs.registry }}/alwaysprint-prod-backend
        working-directory: AlwaysPrintProject/Cloud/backend
        run: |
          TAG=${GITHUB_SHA::8}
          docker build -t $ECR_URL:$TAG -t $ECR_URL:latest .
          docker push $ECR_URL:$TAG
          docker push $ECR_URL:latest

      - name: Deploy via SSM
        run: |
          INSTANCE_ID=$(aws ec2 describe-instances \
            --filters "Name=tag:Name,Values=alwaysprint-prod-ec2" \
                      "Name=instance-state-name,Values=running" \
            --query "Reservations[0].Instances[0].InstanceId" \
            --output text)
          TAG=${GITHUB_SHA::8}
          COMMAND_ID=$(aws ssm send-command \
            --instance-ids "$INSTANCE_ID" \
            --document-name "AWS-RunShellScript" \
            --parameters "{\"commands\":[\"sed -i '/^BUILD_TAG=/d' /opt/alwaysprint/.env && echo 'BUILD_TAG=${TAG}' >> /opt/alwaysprint/.env && bash /opt/alwaysprint/deploy.sh backend\"]}" \
            --comment "Deploy backend PROD ${{ github.sha }}" \
            --query "Command.CommandId" --output text)
          aws ssm wait command-executed \
            --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID"
          STATUS=$(aws ssm get-command-invocation \
            --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" \
            --query "Status" --output text)
          [ "$STATUS" = "Success" ] || exit 1
```

**`.github/workflows/deploy-frontend.yml`** (reemplaza el actual):
```yaml
name: Deploy Frontend

on:
  push:
    branches: [main]
    paths:
      - 'AlwaysPrintProject/Cloud/frontend/**'
  workflow_dispatch:

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true

jobs:
  deploy-dev:
    runs-on: ubuntu-latest
    environment: dev
    steps:
      - uses: actions/checkout@v4

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-west-2

      - name: Login to ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Build and push
        env:
          ECR_URL: ${{ steps.login-ecr.outputs.registry }}/alwaysprint-dev-frontend
        working-directory: AlwaysPrintProject/Cloud/frontend
        run: |
          TAG=${GITHUB_SHA::8}
          docker build \
            --build-arg NEXT_PUBLIC_API_URL="https://alwaysprint.dev.iol.pe" \
            --build-arg NEXT_PUBLIC_WS_URL="wss://alwaysprint.dev.iol.pe" \
            --build-arg NEXT_PUBLIC_APP_NAME="AlwaysPrint Cloud [DEV]" \
            --build-arg NEXT_PUBLIC_BUILD_TAG="$TAG" \
            -t $ECR_URL:$TAG -t $ECR_URL:latest .
          docker push $ECR_URL:$TAG
          docker push $ECR_URL:latest

      - name: Deploy via SSM
        run: |
          INSTANCE_ID=$(aws ec2 describe-instances \
            --filters "Name=tag:Name,Values=alwaysprint-dev-ec2" \
                      "Name=instance-state-name,Values=running" \
            --query "Reservations[0].Instances[0].InstanceId" \
            --output text)
          COMMAND_ID=$(aws ssm send-command \
            --instance-ids "$INSTANCE_ID" \
            --document-name "AWS-RunShellScript" \
            --parameters 'commands=["bash /opt/alwaysprint/deploy.sh frontend"]' \
            --comment "Deploy frontend DEV ${{ github.sha }}" \
            --query "Command.CommandId" --output text)
          aws ssm wait command-executed \
            --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID"
          STATUS=$(aws ssm get-command-invocation \
            --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" \
            --query "Status" --output text)
          [ "$STATUS" = "Success" ] || exit 1

  deploy-prod:
    runs-on: ubuntu-latest
    needs: deploy-dev
    environment: production
    steps:
      - uses: actions/checkout@v4

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-west-2

      - name: Login to ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Build and push
        env:
          ECR_URL: ${{ steps.login-ecr.outputs.registry }}/alwaysprint-prod-frontend
        working-directory: AlwaysPrintProject/Cloud/frontend
        run: |
          TAG=${GITHUB_SHA::8}
          docker build \
            --build-arg NEXT_PUBLIC_API_URL="https://alwaysprint.apps.iol.pe" \
            --build-arg NEXT_PUBLIC_WS_URL="wss://alwaysprint.apps.iol.pe" \
            --build-arg NEXT_PUBLIC_APP_NAME="AlwaysPrint Cloud Management" \
            --build-arg NEXT_PUBLIC_BUILD_TAG="$TAG" \
            -t $ECR_URL:$TAG -t $ECR_URL:latest .
          docker push $ECR_URL:$TAG
          docker push $ECR_URL:latest

      - name: Deploy via SSM
        run: |
          INSTANCE_ID=$(aws ec2 describe-instances \
            --filters "Name=tag:Name,Values=alwaysprint-prod-ec2" \
                      "Name=instance-state-name,Values=running" \
            --query "Reservations[0].Instances[0].InstanceId" \
            --output text)
          COMMAND_ID=$(aws ssm send-command \
            --instance-ids "$INSTANCE_ID" \
            --document-name "AWS-RunShellScript" \
            --parameters 'commands=["bash /opt/alwaysprint/deploy.sh frontend"]' \
            --comment "Deploy frontend PROD ${{ github.sha }}" \
            --query "Command.CommandId" --output text)
          aws ssm wait command-executed \
            --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID"
          STATUS=$(aws ssm get-command-invocation \
            --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" \
            --query "Status" --output text)
          [ "$STATUS" = "Success" ] || exit 1
```

**`.github/workflows/build-client.yml`** (reemplaza el actual):
```yaml
name: Build and Deploy Client

on:
  push:
    branches: [main]
    paths:
      - 'AlwaysPrintProject/Client/**'
  workflow_dispatch:

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true

jobs:
  build:
    runs-on: windows-latest
    outputs:
      version: ${{ steps.version.outputs.VERSION }}

    steps:
      - uses: actions/checkout@v4

      - name: Setup .NET SDK
        uses: actions/setup-dotnet@v4
        with:
          dotnet-version: '8.x'

      - name: Install .NET Framework 4.8 Targeting Pack
        shell: pwsh
        run: |
          $refPath = "C:\Program Files (x86)\Reference Assemblies\Microsoft\Framework\.NETFramework\v4.8"
          if (-not (Test-Path $refPath)) {
            Write-Error ".NET Framework 4.8 Targeting Pack no encontrado"
            exit 1
          }

      - name: Install WiX CLI v4
        shell: pwsh
        run: |
          dotnet tool install --global wix --version 4.0.5
          wix extension add "WixToolset.Util.wixext/4.0.5" --global

      - name: Generate version
        id: version
        shell: pwsh
        run: |
          $now = [DateTime]::UtcNow
          $version = "1.$([int]$now.ToString('yy')).$([int]$now.ToString('MMdd')).$([int]$now.ToString('HHmm'))"
          Write-Host "Version: $version"
          echo "VERSION=$version" >> $env:GITHUB_OUTPUT

      - name: Publish AlwaysPrintService
        shell: pwsh
        working-directory: AlwaysPrintProject/Client
        run: |
          $v = "${{ steps.version.outputs.VERSION }}"
          dotnet publish .\AlwaysPrintService\AlwaysPrintService.csproj `
            -c Release -f net48 -o .\dist --no-self-contained `
            /p:Version=$v /p:AssemblyVersion=$v /p:FileVersion=$v /p:InformationalVersion=$v

      - name: Publish AlwaysPrintTray
        shell: pwsh
        working-directory: AlwaysPrintProject/Client
        run: |
          $v = "${{ steps.version.outputs.VERSION }}"
          dotnet publish .\AlwaysPrintTray\AlwaysPrintTray.csproj `
            -c Release -f net48 -o .\dist --no-self-contained `
            /p:Version=$v /p:AssemblyVersion=$v /p:FileVersion=$v /p:InformationalVersion=$v

      - name: Build MSI
        shell: pwsh
        working-directory: AlwaysPrintProject/Client
        run: |
          $v = "${{ steps.version.outputs.VERSION }}"
          $projectDir = (Get-Location).Path + "\"
          wix build .\Product.wxs -o .\AlwaysPrint.msi `
            -ext WixToolset.Util.wixext `
            -d "ProductVersion=$v" -d "ProjectDir=$projectDir"

      - name: Upload MSI artifact
        uses: actions/upload-artifact@v4
        with:
          name: alwaysprint-msi
          path: AlwaysPrintProject/Client/AlwaysPrint.msi
          retention-days: 5

  deploy-dev:
    runs-on: ubuntu-latest
    needs: build
    environment: dev
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: alwaysprint-msi

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-west-2

      - name: Upload MSI to S3 (Dev)
        shell: bash
        run: |
          VERSION="${{ needs.build.outputs.version }}"
          COMMIT="${{ github.sha }}"
          SHORT_COMMIT=${COMMIT::7}
          BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
          METADATA="version=${VERSION},build-date=${BUILD_DATE},commit-hash=${SHORT_COMMIT}"

          aws s3 cp AlwaysPrint.msi \
            "s3://alwaysprint-dev-dev-artifacts/latest/AlwaysPrint.msi" \
            --metadata "$METADATA"
          aws s3 cp AlwaysPrint.msi \
            "s3://alwaysprint-dev-dev-artifacts/versions/${VERSION}/AlwaysPrint.msi" \
            --metadata "$METADATA"

          echo "MSI v${VERSION} subido a S3 Dev"

  deploy-prod:
    runs-on: ubuntu-latest
    needs: [build, deploy-dev]
    environment: production    # ← Requiere aprobación manual
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: alwaysprint-msi

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-west-2

      - name: Upload MSI to S3 (Prod)
        shell: bash
        run: |
          VERSION="${{ needs.build.outputs.version }}"
          COMMIT="${{ github.sha }}"
          SHORT_COMMIT=${COMMIT::7}
          BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
          METADATA="version=${VERSION},build-date=${BUILD_DATE},commit-hash=${SHORT_COMMIT}"

          aws s3 cp AlwaysPrint.msi \
            "s3://alwaysprint-prod-artifacts/latest/AlwaysPrint.msi" \
            --metadata "$METADATA"
          aws s3 cp AlwaysPrint.msi \
            "s3://alwaysprint-prod-artifacts/versions/${VERSION}/AlwaysPrint.msi" \
            --metadata "$METADATA"

          echo "MSI v${VERSION} subido a S3 Prod"
```

**Nota sobre el cliente MSI**: El build se hace una sola vez (job `build`). El mismo MSI se sube primero a S3 de la cuenta dev para testing, y solo después de aprobación se sube a S3 de la cuenta prod. Esto garantiza que el binario que probaste en dev es exactamente el mismo que va a prod.

### Verificación
```bash
# Validar YAML de los 3 workflows
for f in .github/workflows/deploy-*.yml .github/workflows/build-client.yml; do
  python3 -c "import yaml; yaml.safe_load(open('$f'))" && echo "$f: OK"
done
```

**Resultado esperado**: Los 3 archivos pasan validación YAML sin errores.

---

## Paso 7: Test end-to-end — Deploy automático a Dev

### Requisitos previos
- Todos los pasos anteriores completados

### Acciones
1. Hacer un cambio menor en el backend:
   ```bash
   # Agregar un comentario o cambio trivial en main.py
   git add .
   git commit -m "test: verificar deploy automático a dev"
   git push origin main
   ```
2. Ir a GitHub → Actions → verificar que el workflow se ejecuta
3. El job `deploy-dev` debe ejecutarse automáticamente
4. El job `deploy-prod` debe quedar **pausado esperando aprobación**

### Verificación
```bash
# Verificar que dev responde
curl -s https://alwaysprint.dev.iol.pe/api/v1/health

# Verificar que prod NO se actualizó (sigue con versión anterior)
curl -s https://alwaysprint.apps.iol.pe/api/v1/health
```

**Resultado esperado**:
- Job `deploy-dev`: ✅ verde
- Job `deploy-prod`: ⏸️ "Waiting for review"
- Dev responde correctamente
- Prod sin cambios

---

## Paso 8: Test end-to-end — Aprobación manual para Prod

### Requisitos previos
- Paso 7 completado (deploy a dev exitoso)

### Acciones
1. Verificar que todo funciona en `alwaysprint.dev.iol.pe`
2. En GitHub → Actions → el workflow en ejecución:
   - Click en "Review deployments"
   - Seleccionar environment `production`
   - Click "Approve and deploy"
3. El job `deploy-prod` se ejecuta

### Verificación
```bash
# Verificar que prod se actualizó
curl -s https://alwaysprint.apps.iol.pe/api/v1/health

# Para el cliente MSI, verificar S3:
aws s3 ls s3://alwaysprint-prod-artifacts/latest/ --profile AlwaysPrint-prod-425642439683
```

**Resultado esperado**: Prod actualizado. Si es el cliente MSI, el archivo aparece en S3 de prod.

---

## Resumen de Archivos Modificados/Creados

| Archivo | Acción | Estado |
|---------|--------|--------|
| `AlwaysPrintProject/Cloud/terraform/terraform.tfvars` | Renombrado → `prod.tfvars` | ✅ |
| `AlwaysPrintProject/Cloud/terraform/prod.tfvars` | Agregada `S3_ARTIFACTS_BUCKET` | ✅ |
| `AlwaysPrintProject/Cloud/terraform/dev.tfvars` | Creado | ✅ |
| `AlwaysPrintProject/Cloud/terraform/modules/s3/main.tf` | Bucket dinámico + force_destroy | ✅ |
| `AlwaysPrintProject/Cloud/terraform/modules/ec2/main.tf` | IAM policy con bucket dinámico | ✅ |
| `AlwaysPrintProject/Cloud/backend/app/core/config.py` | Agregada `S3_ARTIFACTS_BUCKET` | ✅ |
| `AlwaysPrintProject/Cloud/backend/app/services/s3_update_service.py` | Lee bucket de settings | ✅ |
| `.gitignore` | Actualizado para tfplan* y tfstate.d/ | ✅ |
| `.github/workflows/deploy-backend.yml` | Reescribir (2 jobs: dev + prod) | ⏳ Pendiente |
| `.github/workflows/deploy-frontend.yml` | Reescribir (2 jobs: dev + prod) | ⏳ Pendiente |
| `.github/workflows/build-client.yml` | Reescribir (build + deploy-dev + deploy-prod) | ⏳ Pendiente |

---

## Costos Estimados

| Recurso | Cuenta Dev (040982755196) | Notas |
|---------|--------------------------|-------|
| EC2 t3.micro | $0 (free tier: 750h/mes) | 1 instancia 24/7 = 720h |
| RDS t3.micro | $0 (free tier: 750h/mes) | 20GB storage incluido |
| ECR | ~$0 | Poco storage |
| Route53 | $0.50/mes | 1 hosted zone |
| S3 | ~$0 | Pocos MB de MSIs |
| **Total** | **~$0.50/mes** | |

---

## Diagrama del Flujo Completo

```
┌─────────────────────────────────────────────────────────────────┐
│                     PUSH A MAIN                                  │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│  JOB: deploy-dev (automático)                                    │
│  • Cuenta AWS: 040982755196                                      │
│  • ECR: alwaysprint-dev-*                                        │
│  • EC2: alwaysprint-dev-ec2                                      │
│  • URL: alwaysprint.dev.iol.pe                                   │
│  • S3 (MSI): bucket en cuenta dev                                │
└─────────────────────┬───────────────────────────────────────────┘
                      │ ✅ Éxito
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│  ⏸️  ESPERANDO APROBACIÓN MANUAL                                 │
│  • Verificas en alwaysprint.dev.iol.pe                           │
│  • Si OK → "Approve and deploy" en GitHub                        │
│  • Si NO OK → Rechazar o dejar expirar                           │
└─────────────────────┬───────────────────────────────────────────┘
                      │ ✅ Aprobado
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│  JOB: deploy-prod                                                │
│  • Cuenta AWS: 425642439683 (prod)                               │
│  • ECR: alwaysprint-prod-*                                       │
│  • EC2: alwaysprint-prod-ec2                                     │
│  • URL: alwaysprint.apps.iol.pe                                  │
│  • S3 (MSI): bucket en cuenta prod                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Troubleshooting

### Job de prod no aparece como "Waiting for review"
- Verificar que el environment `production` tiene "Required reviewers" activado
- Verificar que el job usa `environment: production` (exacto, case-sensitive)

### Deploy a dev falla con "AccessDenied"
- Verificar secrets en GitHub environment `dev` (son de la cuenta 040982755196)
- Verificar que el usuario IAM tiene las políticas del Paso 1

### Terraform: Cambiar entre entornos
```bash
# Dev
export AWS_PROFILE=AlwaysPrint-dev-040982755196
terraform workspace select dev
terraform plan -var-file=dev.tfvars -out=tfplan-dev

# Prod
export AWS_PROFILE=AlwaysPrint-prod-425642439683
terraform workspace select prod
terraform plan -var-file=prod.tfvars -out=tfplan-prod
```

### DNS no resuelve alwaysprint.dev.iol.pe
- Verificar delegación NS de `dev.iol.pe` en el registrador
- `dig +trace dev.iol.pe` para diagnosticar

### SSM falla con "InvalidInstanceId"
- EC2 necesita SSM Agent + IAM role con `AmazonSSMManagedInstanceCore`
- Verificar instancia running: filtrar por tag `alwaysprint-dev-ec2`

### MSI no aparece en S3 de dev
- Verificar que el bucket existe en la cuenta 040982755196
- El nombre del bucket debe coincidir con lo que Terraform creó (ver outputs)
