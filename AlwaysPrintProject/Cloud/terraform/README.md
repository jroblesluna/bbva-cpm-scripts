# AlwaysPrint Cloud — Infraestructura (Terraform)

Infraestructura AWS para AlwaysPrint Cloud Manager, gestionada con Terraform.

## Qué despliega

| Recurso | Detalle |
|---------|---------|
| EC2 `t3.micro` | Amazon Linux 2023, nginx + Docker Compose, Let's Encrypt SSL |
| RDS PostgreSQL 16 | `db.t3.micro`, subnet privada, cifrado en reposo |
| ECR | 2 repositorios: `alwaysprint-prod-backend` / `alwaysprint-prod-frontend` |
| SES | Identidad de dominio `apps.iol.pe`, DKIM, MAIL FROM |
| Secrets Manager | `db_password`, `secret_key`, `database_url`, `ssh_private_key` |
| Networking | VPC `10.0.0.0/16`, 2 subnets públicas, 2 subnets DB privadas, IGW, SGs |

**URL de producción**: `https://alwaysprint.apps.iol.pe`  
**Región**: `us-west-2`

## Uso

```bash
./setup.sh plan    # ver cambios antes de aplicar
./setup.sh apply   # provisionar / actualizar infraestructura
```

`setup.sh` es el único punto de entrada — gestiona la clave SSH automáticamente
(la genera y guarda en Secrets Manager la primera vez).

No ejecutes `terraform apply` directamente.

## Archivos

```
terraform/
├── setup.sh          # Punto de entrada (usar este)
├── main.tf           # Módulos y recursos raíz
├── variables.tf      # Declaración de variables
├── outputs.tf        # Outputs tras el apply
├── terraform.tfvars  # Valores de configuración (commiteado)
└── modules/
    ├── ec2/          # EC2 + IAM + EIP + user_data
    ├── rds/          # PostgreSQL
    ├── ecr/          # Container registry
    ├── networking/   # VPC + subnets + SGs
    ├── secrets/      # Secrets Manager
    └── ses/          # SES + DKIM + IAM policy
```

## Documentación

- [INSTALL.md](./INSTALL.md) — Instalación desde cero
- [OPERATIONS.md](./OPERATIONS.md) — Operaciones del día a día
