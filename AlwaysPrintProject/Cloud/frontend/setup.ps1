# Script de instalación para Frontend
# AlwaysPrint Cloud Manager - Frontend (Next.js)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "AlwaysPrint Frontend - Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Verificar si Node.js está instalado
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCommand) {
    Write-Host "[ERROR] Node.js no está instalado" -ForegroundColor Red
    Write-Host ""
    Write-Host "Por favor instala Node.js desde:"
    Write-Host "https://nodejs.org/ (versión LTS recomendada)"
    Write-Host ""
    Read-Host "Presiona Enter para salir"
    exit 1
}

Write-Host "[1/4] Verificando Node.js y npm..." -ForegroundColor Green
node --version
npm --version
Write-Host ""

Write-Host "[2/4] Instalando dependencias..." -ForegroundColor Green
Write-Host "Esto puede tomar varios minutos..." -ForegroundColor Yellow
npm install

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Falló la instalación de dependencias" -ForegroundColor Red
    Read-Host "Presiona Enter para salir"
    exit 1
}
Write-Host ""

Write-Host "[3/4] Configurando variables de entorno..." -ForegroundColor Green
if (-not (Test-Path .env.local)) {
    if (Test-Path .env.example) {
        Copy-Item .env.example .env.local
        Write-Host "Archivo .env.local creado desde .env.example" -ForegroundColor Yellow
    } else {
        # Crear .env.local básico
        $envContent = @"
# URL del backend API
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
"@
        $envContent | Out-File -FilePath .env.local -Encoding utf8
        Write-Host "Archivo .env.local creado con configuracion por defecto" -ForegroundColor Yellow
    }
} else {
    Write-Host "Archivo .env.local ya existe" -ForegroundColor Gray
}
Write-Host ""

Write-Host "[4/4] Verificando configuracion..." -ForegroundColor Green
if (Test-Path "src/app/page.tsx") {
    Write-Host "Estructura del proyecto correcta" -ForegroundColor Green
} else {
    Write-Host "Advertencia: Estructura del proyecto incompleta" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Instalacion completada!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Para ejecutar el servidor de desarrollo:" -ForegroundColor White
Write-Host "  npm run dev" -ForegroundColor Yellow
Write-Host ""
Write-Host "La aplicacion estara disponible en:" -ForegroundColor White
Write-Host "  http://localhost:3000" -ForegroundColor Cyan
Write-Host ""
Write-Host "Otros comandos utiles:" -ForegroundColor White
Write-Host "  npm run build    - Compilar para produccion" -ForegroundColor Gray
Write-Host "  npm run start    - Ejecutar version de produccion" -ForegroundColor Gray
Write-Host "  npm run lint     - Verificar codigo" -ForegroundColor Gray
Write-Host "  npm run format   - Formatear codigo" -ForegroundColor Gray
Write-Host ""

Read-Host "Presiona Enter para salir"
