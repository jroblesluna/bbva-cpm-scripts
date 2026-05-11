# Configuración DNS — SES AlwaysPrint

Registros generados por `terraform apply` el 2026-05-10.  
Agregar en el editor de zona DNS de **`iol.pe`** en tu proveedor DNS.

> **Importante**: en el campo **Nombre / Host** ingresa solo la parte del subdominio,
> **sin** el sufijo `.iol.pe` — el proveedor lo agrega automáticamente.

---

## Registros requeridos (8 en total)

### 0 — Servidor de aplicación (A record)

| Campo | Valor |
|-------|-------|
| **Tipo** | `A` |
| **Nombre** | `alwaysprint.apps` |
| **IP** | `34.213.90.95` |
| **TTL** | `600` |

> Es la Elastic IP del EC2. No cambia aunque el servidor se reinicie.  
> Si se destruye y recrea la infraestructura, obtener la nueva IP con:  
> `terraform output ec2_public_ip`

---

### 1 — Verificación de dominio

| Campo | Valor |
|-------|-------|
| **Tipo** | `TXT` |
| **Nombre** | `_amazonses.apps` |
| **Valor** | `Ag0fFzm//4Y2hDnD3Qy2k8iJcALQ6/0EwtaGy0wEL0k=` |
| **TTL** | `600` |

---

### 2 — DKIM 1

| Campo | Valor |
|-------|-------|
| **Tipo** | `CNAME` |
| **Nombre** | `747nftpdxxtgstnrzognxq5p677xkvuc._domainkey.apps` |
| **Apunta a** | `747nftpdxxtgstnrzognxq5p677xkvuc.dkim.amazonses.com` |
| **TTL** | `600` |

---

### 3 — DKIM 2

| Campo | Valor |
|-------|-------|
| **Tipo** | `CNAME` |
| **Nombre** | `36toxjwf6nmzy4rtsvemymfmeksssa32._domainkey.apps` |
| **Apunta a** | `36toxjwf6nmzy4rtsvemymfmeksssa32.dkim.amazonses.com` |
| **TTL** | `600` |

---

### 4 — DKIM 3

| Campo | Valor |
|-------|-------|
| **Tipo** | `CNAME` |
| **Nombre** | `6asyw5tayk6tkfigloleydr5vn7q57k6._domainkey.apps` |
| **Apunta a** | `6asyw5tayk6tkfigloleydr5vn7q57k6.dkim.amazonses.com` |
| **TTL** | `600` |

---

### 5 — MAIL FROM (MX)

| Campo | Valor |
|-------|-------|
| **Tipo** | `MX` |
| **Nombre** | `mail.apps` |
| **Servidor** | `feedback-smtp.us-west-2.amazonses.com` |
| **Prioridad** | `10` |
| **TTL** | `600` |

---

### 6 — SPF para MAIL FROM

| Campo | Valor |
|-------|-------|
| **Tipo** | `TXT` |
| **Nombre** | `mail.apps` |
| **Valor** | `v=spf1 include:amazonses.com ~all` |
| **TTL** | `600` |

---

### 8 — CAA (autorización de emisión de certificados SSL)

Los registros CAA se definen en `@` (`iol.pe`) y heredan a todos los subdominios.
Deben existir los siguientes 3 registros:

| Tipo | Nombre | Flag | Valor | TTL |
|------|--------|------|-------|-----|
| `CAA` | `@` | `0` | `issue "letsencrypt.org"` | `14400` |
| `CAA` | `@` | `0` | `issuewild "letsencrypt.org"` | `14400` |
| `CAA` | `@` | `0` | `issue "amazon.com"` | `14400` |

| Registro | Propósito |
|----------|-----------|
| `issue "letsencrypt.org"` | Permite a Certbot emitir certificados normales para `alwaysprint.apps.iol.pe` |
| `issuewild "letsencrypt.org"` | Permite emitir certificados wildcard `*.iol.pe` desde Let's Encrypt |
| `issue "amazon.com"` | Permite emitir certificados desde AWS ACM (reservado para uso futuro) |

> `issue` cubre certificados normales — es el que usa Certbot.  
> `issuewild` solo cubre wildcards (`*.dominio`) — no reemplaza a `issue`.  
>
> **Estado actual**: ✅ los 3 presentes — `issuewild "letsencrypt.org"` e `issue "amazon.com"`
> configurados manualmente; `issue "letsencrypt.org"` agregado por el proveedor DNS como default.

---

## Verificar propagación

Tras guardar los registros espera 15–60 minutos y confirma cada uno:

```bash
nslookup alwaysprint.apps.iol.pe
nslookup -type=TXT _amazonses.apps.iol.pe
nslookup -type=CNAME 747nftpdxxtgstnrzognxq5p677xkvuc._domainkey.apps.iol.pe
nslookup -type=MX mail.apps.iol.pe
nslookup -type=TXT mail.apps.iol.pe
```

En AWS → **SES → Identidades verificadas**, el dominio `apps.iol.pe` cambiará de **Pending** a **Verified**.

---

## Salir del sandbox de SES

Por defecto SES solo envía a emails verificados manualmente. Para habilitar envío a cualquier destinatario:

1. AWS Console → **SES → Account dashboard**
2. **Request production access**
3. Completar formulario (uso transaccional, volumen estimado)
4. AWS responde en 24–48 horas

---

## Estado

```
✅ terraform apply completado — 2026-05-10
✅ Registros DNS propagados y verificados con nslookup — 2026-05-10
⏳ Verificación SES en proceso (AWS verifica automáticamente, puede tardar horas)
⏳ Salida de sandbox pendiente (solicitar en AWS Console → SES → Account dashboard)
```
