# Plan: Cliente MSI Multi-Entorno (Dev / Prod)

## Objetivo

Compilar el cliente AlwaysPrint con configuración diferente según el entorno destino:
- **MSI Dev**: apunta a `alwaysprint.dev.iol.pe`, icono diferente, About muestra "[DEV]"
- **MSI Prod**: apunta a `alwaysprint.apps.iol.pe`, icono normal, About muestra versión prod

Los MSI de Dev NO deben usarse en Prod y viceversa.

---

## Estrategia

Pasar el entorno como parámetro de compilación (`-d "Environment=dev"` o `"Environment=prod"`) en WiX y como constante de compilación en C# (`/p:DefineConstants=ENV_DEV`). Esto permite que un solo codebase genere ambos MSI sin duplicar archivos.

---

## Archivos que Requieren Cambio

### 1. Cliente C# (Compilación condicional)

| Archivo | Cambio | Tipo |
|---|---|---|
| `AppConfiguration.cs` | Default de `BootstrapDomains` según `#if ENV_DEV` | Código |
| `RegistryConfigManager.cs` | Defaults de fallback según `#if ENV_DEV` | Código |
| `Product.wxs` | Valor de `BootstrapDomains` en registro según variable WiX `$(var.Environment)` | Instalador |
| `Product.wxs` | Nombre del producto: "AlwaysPrint [DEV]" vs "AlwaysPrint" | Instalador |
| `Product.wxs` | Icono diferente para dev (opcional) | Instalador |
| `MainWindow.xaml.cs` (About) | Mostrar "[DEV]" en título/about si `ENV_DEV` | UI |

### 2. Backend (Defaults de BD — NO requiere cambio para multi-env)

| Archivo | Estado | Razón |
|---|---|---|
| `001_initial_schema.py` | ✅ No cambiar | Es un default de BD, las workstations lo sobreescriben |
| `app/models/config.py` | ✅ No cambiar | Mismo caso — default del modelo |
| `app/services/config.py` | ✅ No cambiar | Default al crear config nueva |
| `app/core/config.py` | ✅ Ya parametrizado | Lee de variable de entorno |
| `tests/unit/test_models.py` | ✅ No cambiar | Tests usan valores de prod (correcto) |

### 3. Frontend

| Archivo | Estado | Razón |
|---|---|---|
| `client.ts` | ✅ Ya parametrizado | Lee de `NEXT_PUBLIC_API_URL` (build-arg en workflow) |

### 4. Scripts y Docs (Solo comentarios/ejemplos)

| Archivo | Estado | Razón |
|---|---|---|
| `test-client.sh` | ⚠ Opcional | Agregar opción `dev` para apuntar a dev.iol.pe |
| `DomainHealthChecker.cs` | ✅ No cambiar | Solo comentarios XML doc |
| `UpdateChecker.cs` | ✅ No cambiar | Solo comentarios XML doc |
| `UpdateDownloader.cs` | ✅ No cambiar | Solo comentarios XML doc |
| `README.md` (Client) | ⚠ Opcional | Documentar ambos entornos |
| `setup-conda.sh` | ✅ No cambiar | Script de setup local |

---

## Implementación Detallada

### Paso 1: Definir constantes de compilación

En los `.csproj` de Service y Tray, agregar:
```xml
<PropertyGroup Condition="'$(Environment)' == 'dev'">
  <DefineConstants>$(DefineConstants);ENV_DEV</DefineConstants>
</PropertyGroup>
```

### Paso 2: Compilación condicional en AppConfiguration.cs

```csharp
#if ENV_DEV
    public string BootstrapDomains { get; set; } = "dev.iol.pe";
#else
    public string BootstrapDomains { get; set; } = "apps.iol.pe,sistemas.com.pe";
#endif
```

### Paso 3: Compilación condicional en RegistryConfigManager.cs

Todos los defaults de `BootstrapDomains` usan la misma constante:
```csharp
#if ENV_DEV
    private const string DefaultBootstrapDomains = "dev.iol.pe";
#else
    private const string DefaultBootstrapDomains = "apps.iol.pe,sistemas.com.pe";
#endif
```

Y reemplazar todas las ocurrencias hardcodeadas por `DefaultBootstrapDomains`.

### Paso 4: Product.wxs — Nombre e icono condicional

```xml
<!-- Nombre del producto -->
<?if $(var.Environment) = "dev" ?>
  <?define ProductName = "AlwaysPrint [DEV]" ?>
  <?define BootstrapDomainsValue = "dev.iol.pe" ?>
<?else?>
  <?define ProductName = "AlwaysPrint" ?>
  <?define BootstrapDomainsValue = "apps.iol.pe,iol.pe,sistemas.com.pe,robles.ai" ?>
<?endif?>

<Product Name="$(var.ProductName)" ...>

<!-- Registro -->
<RegistryValue Name="BootstrapDomains" Type="string"
               Value="$(var.BootstrapDomainsValue)" />
```

### Paso 5: Icono diferente para Dev

Opciones:
- **Opción A**: Icono con badge naranja/amarillo "DEV" superpuesto
- **Opción B**: Icono con color diferente (ej: azul para dev, verde para prod)
- **Opción C**: Mismo icono pero con texto "[DEV]" en el nombre del programa

Implementación en Product.wxs:
```xml
<?if $(var.Environment) = "dev" ?>
  <Icon Id="AppIcon" SourceFile="$(var.ProjectDir)Assets\icon-dev.ico" />
<?else?>
  <Icon Id="AppIcon" SourceFile="$(var.ProjectDir)Assets\icon.ico" />
<?endif?>
```

### Paso 6: About / Título de ventana

En `MainWindow.xaml.cs` o donde se muestre el About:
```csharp
#if ENV_DEV
    private const string AppSuffix = " [DEV]";
#else
    private const string AppSuffix = "";
#endif

Title = $"AlwaysPrint{AppSuffix} v{version}";
```

### Paso 7: GitHub Actions — Workflows de build

**`build-client-dev.yml`** ya existe. Agregar parámetro de entorno al build:
```yaml
      - name: Publish AlwaysPrintService
        run: |
          dotnet publish ... /p:Environment=dev

      - name: Build MSI
        run: |
          wix build ... -d "Environment=dev"
```

**`build-client-prod.yml`** — igual pero con `Environment=prod` (o sin parámetro, ya que prod es el default).

---

## Diferencias entre MSI Dev y MSI Prod

| Aspecto | MSI Dev | MSI Prod |
|---|---|---|
| Nombre del producto | AlwaysPrint [DEV] | AlwaysPrint |
| Icono | icon-dev.ico (con badge) | icon.ico |
| BootstrapDomains default | `dev.iol.pe` | `apps.iol.pe,iol.pe,sistemas.com.pe,robles.ai` |
| S3 destino | `alwaysprint-dev-artifacts` | `alwaysprint-prod-artifacts` |
| About / Título | Muestra "[DEV]" | Sin sufijo |
| ProductCode (WiX) | **Mismo** (permite upgrade entre dev builds) | **Mismo** (permite upgrade entre prod builds) |
| UpgradeCode (WiX) | **Diferente de prod** | **Diferente de dev** |

**IMPORTANTE**: Los UpgradeCode deben ser diferentes entre dev y prod para que ambos puedan coexistir en la misma máquina sin conflicto (si fuera necesario para testing).

---

## Archivos Nuevos a Crear

| Archivo | Propósito |
|---|---|
| `Assets/icon-dev.ico` | Icono con badge DEV |
| (Ningún archivo .cs nuevo) | Todo se resuelve con compilación condicional |

---

## Orden de Ejecución

1. Crear `icon-dev.ico` (puede ser temporal, un icono placeholder)
2. Modificar `.csproj` para soportar `DefineConstants` con `Environment`
3. Modificar `AppConfiguration.cs` y `RegistryConfigManager.cs` con `#if ENV_DEV`
4. Modificar `Product.wxs` con condicionales WiX
5. Modificar About/título en Tray
6. Actualizar `build-client-dev.yml` con `/p:Environment=dev` y `-d "Environment=dev"`
7. Actualizar `build-client-prod.yml` con `/p:Environment=prod` y `-d "Environment=prod"`
8. Test: compilar ambos MSI y verificar que cada uno apunta al dominio correcto

---

## Notas

- El backend NO necesita cambios — los defaults de `bootstrap_domains` en la BD son para workstations nuevas que se registran. Cada instancia de backend (dev/prod) ya corre en su propia cuenta AWS con su propia BD.
- El frontend NO necesita cambios — ya se parametriza vía `NEXT_PUBLIC_API_URL` en el build.
- `test-client.sh` podría aceptar un parámetro `dev` para apuntar a `alwaysprint.dev.iol.pe` (mejora opcional).
