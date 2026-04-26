#Requires -Version 5
<#
.SYNOPSIS
    Builds the solution in Release mode and copies outputs to .\publish\.
    Run this from the AlwaysPrint/ solution root.
#>

$ErrorActionPreference = 'Stop'
$SolutionDir = $PSScriptRoot | Split-Path
$PublishDir  = Join-Path $SolutionDir "publish"

Write-Host "Building solution..." -ForegroundColor Cyan
dotnet publish "$SolutionDir\AlwaysPrint.sln" `
    --configuration Release `
    --framework net48 `
    --output $PublishDir `
    --no-self-contained

if ($LASTEXITCODE -ne 0) { Write-Error "Build failed." ; exit 1 }

Write-Host "Build complete. Output: $PublishDir" -ForegroundColor Green
Write-Host "Run Installer\Install-AlwaysPrint.ps1 -BinDir '$PublishDir' to install."
