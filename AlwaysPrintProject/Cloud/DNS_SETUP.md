# Configuración DNS — SES AlwaysPrint

## Obtener los valores

Después de ejecutar `terraform apply`, corre:

```bash
cd AlwaysPrintProject/Cloud/terraform
terraform output ses_dns_records
```

Reemplaza cada `<PLACEHOLDER>` de esta guía con los valores del output.

---

## Acceso al editor DNS

Ingresa al panel de tu proveedor DNS y abre el editor de zona para **`iol.pe`**.

> **Importante**: en la mayoría de proveedores el campo **Nombre / Host**
> no lleva el sufijo de la zona al final — el proveedor lo agrega automáticamente.  
> Donde esta guía indica `_amazonses.apps.iol.pe`, escribe solo `_amazonses.apps`.

---

## Registros a agregar (6 en total)

### 1 — Verificación de dominio

| Campo | Valor |
|-------|-------|
| **Tipo** | `TXT` |
| **Nombre** | `_amazonses.apps` |
| **Valor** | `<1_verificacion_dominio.valor>` |
| **TTL** | `600` |

---

### 2, 3, 4 — DKIM (tres registros CNAME)

| Campo | Registro 2 | Registro 3 | Registro 4 |
|-------|-----------|-----------|-----------|
| **Tipo** | `CNAME` | `CNAME` | `CNAME` |
| **Nombre** | `<2_dkim_1.nombre>` | `<3_dkim_2.nombre>` | `<4_dkim_3.nombre>` |
| **Apunta a** | `<2_dkim_1.valor>` | `<3_dkim_2.valor>` | `<4_dkim_3.valor>` |
| **TTL** | `600` | `600` | `600` |

---

### 5 — MAIL FROM (MX)

| Campo | Valor |
|-------|-------|
| **Tipo** | `MX` |
| **Nombre** | `mail.apps` |
| **Servidor** | `<5_mail_from_mx.valor>` |
| **Prioridad** | `10` |
| **TTL** | `600` |

---

### 6 — SPF para MAIL FROM (TXT)

| Campo | Valor |
|-------|-------|
| **Tipo** | `TXT` |
| **Nombre** | `mail.apps` |
| **Valor** | `<6_mail_from_spf.valor>` |
| **TTL** | `600` |

---

## Verificar propagación

Tras guardar los registros, espera 15–60 minutos y confirma cada uno:

```bash
nslookup -type=TXT _amazonses.apps.iol.pe
nslookup -type=CNAME <2_dkim_1.nombre>.iol.pe
nslookup -type=MX mail.apps.iol.pe
nslookup -type=TXT mail.apps.iol.pe
```

En AWS → **SES → Identidades verificadas**, el dominio pasará de **Pending** a **Verified**.

---

## Salir del sandbox de SES

Por defecto SES solo envía a emails verificados manualmente. Para habilitar envío a cualquier destinatario:

1. AWS Console → **SES → Account dashboard**
2. **Request production access**
3. Completar formulario (uso transaccional, volumen estimado)
4. AWS responde en 24–48 horas

---

## Flujo completo

```
terraform apply
      │
      ▼
terraform output ses_dns_records  →  copiar los 6 valores
      │
      ▼
Editor DNS del proveedor (zona iol.pe)  →  agregar los 6 registros
      │
      ▼
~30 min propagación
      │
      ▼
SES: Pending → Verified
      │
      ▼
Solicitar salida de sandbox
```
