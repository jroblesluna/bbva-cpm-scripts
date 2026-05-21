#requires -version 5.1
<#
.SYNOPSIS
    Uninstalls "Clave Impresion / Clave Impresión" MSI product and performs cleanup if MSI uninstall fails.

.DESCRIPTION
    1. Checks if the known ProductCode is installed.
    2. If not found, searches by ProductName: "Clave Impresion" or "Clave Impresión".
    3. Attempts msiexec uninstall using ProductCode.
    4. If it fails, finds LocalPackage MSI path using Windows Installer COM.
    5. Attempts uninstall using LocalPackage.
    6. If it fails, attempts install/repair followed by uninstall.
    7. If still failing, stops/removes LexRest* services, kills Clave*.exe processes,
       and removes %ProgramFiles%\Clave* folders.

.NOTES
    Run as Administrator.
#>

$ErrorActionPreference = "Continue"

# =========================
# Configuration
# =========================

$KnownProductCode = "{C7A8C8C8-BA10-48FA-B01C-DC27FA05FAE8}"
$ProductNamePatterns = @(
    "Clave Impresion",
    "Clave Impresión"
)

$LogRoot = "C:\Temp"
$MainLog = Join-Path $LogRoot "ClaveImpresion_uninstall_script.log"
$MsiUninstallLog_ProductCode = Join-Path $LogRoot "ClaveImpresion_uninstall_productcode.log"
$MsiUninstallLog_LocalPackage = Join-Path $LogRoot "ClaveImpresion_uninstall_localpackage.log"
$MsiInstallLog_LocalPackage = Join-Path $LogRoot "ClaveImpresion_reinstall_localpackage.log"
$MsiUninstallLog_AfterReinstall = Join-Path $LogRoot "ClaveImpresion_uninstall_after_reinstall.log"

# =========================
# Helpers
# =========================

function Write-Log {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message,

        [ValidateSet("INFO", "WARN", "ERROR", "SUCCESS")]
        [string]$Level = "INFO"
    )

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] [$Level] $Message"

    Write-Host $line

    try {
        Add-Content -Path $MainLog -Value $line -Encoding UTF8
    } catch {
        Write-Host "[$timestamp] [WARN] Could not write to log file: $MainLog"
    }
}

function Ensure-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)

    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Log "This script must be executed as Administrator." "ERROR"
        exit 1
    }
}

function Ensure-LogFolder {
    if (-not (Test-Path $LogRoot)) {
        New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
    }

    if (-not (Test-Path $MainLog)) {
        New-Item -ItemType File -Path $MainLog -Force | Out-Null
    }
}

function Normalize-ProductCode {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProductCode
    )

    $code = $ProductCode.Trim()

    if ($code -notmatch "^\{.*\}$") {
        $code = "{$code}"
    }

    return $code.ToUpperInvariant()
}

function Invoke-MsiExec {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    Write-Log "Running: msiexec.exe $($Arguments -join ' ')" "INFO"

    try {
        $process = Start-Process -FilePath "msiexec.exe" `
            -ArgumentList $Arguments `
            -Wait `
            -PassThru `
            -WindowStyle Hidden

        $exitCode = $process.ExitCode

        Write-Log "$Description finished with exit code: $exitCode" "INFO"

        switch ($exitCode) {
            0 {
                Write-Log "$Description completed successfully." "SUCCESS"
                return $true
            }
            3010 {
                Write-Log "$Description completed successfully. Reboot required." "SUCCESS"
                return $true
            }
            1605 {
                Write-Log "$Description result: product is not installed." "SUCCESS"
                return $true
            }
            default {
                Write-Log "$Description failed with exit code: $exitCode" "WARN"
                return $false
            }
        }
    } catch {
        Write-Log "$Description failed with exception: $($_.Exception.Message)" "ERROR"
        return $false
    }
}

function Get-MsiProductInfoByCode {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProductCode
    )

    $ProductCode = Normalize-ProductCode $ProductCode

    try {
        $installer = New-Object -ComObject WindowsInstaller.Installer

        foreach ($product in $installer.Products()) {
            $currentCode = Normalize-ProductCode $product

            if ($currentCode -eq $ProductCode) {
                $productName = $null
                $version = $null
                $localPackage = $null
                $installSource = $null

                try { $productName = $installer.ProductInfo($product, "ProductName") } catch {}
                try { $version = $installer.ProductInfo($product, "VersionString") } catch {}
                try { $localPackage = $installer.ProductInfo($product, "LocalPackage") } catch {}
                try { $installSource = $installer.ProductInfo($product, "InstallSource") } catch {}

                return [PSCustomObject]@{
                    ProductCode   = $currentCode
                    ProductName   = $productName
                    Version       = $version
                    LocalPackage  = $localPackage
                    InstallSource = $installSource
                }
            }
        }
    } catch {
        Write-Log "Could not query Windows Installer COM by ProductCode. Error: $($_.Exception.Message)" "ERROR"
    }

    return $null
}

function Get-MsiProductInfoByName {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$NamePatterns
    )

    try {
        $installer = New-Object -ComObject WindowsInstaller.Installer
        $matches = @()

        foreach ($product in $installer.Products()) {
            $productCode = Normalize-ProductCode $product
            $productName = $null
            $version = $null
            $localPackage = $null
            $installSource = $null

            try { $productName = $installer.ProductInfo($product, "ProductName") } catch {}

            if ([string]::IsNullOrWhiteSpace($productName)) {
                continue
            }

            foreach ($pattern in $NamePatterns) {
                if ($productName -like "*$pattern*") {
                    try { $version = $installer.ProductInfo($product, "VersionString") } catch {}
                    try { $localPackage = $installer.ProductInfo($product, "LocalPackage") } catch {}
                    try { $installSource = $installer.ProductInfo($product, "InstallSource") } catch {}

                    $matches += [PSCustomObject]@{
                        ProductCode   = $productCode
                        ProductName   = $productName
                        Version       = $version
                        LocalPackage  = $localPackage
                        InstallSource = $installSource
                    }

                    break
                }
            }
        }

        return $matches
    } catch {
        Write-Log "Could not query Windows Installer COM by ProductName. Error: $($_.Exception.Message)" "ERROR"
        return @()
    }
}

function Stop-And-Remove-LexRestServices {
    Write-Log "Searching Windows services matching LexRest*..." "INFO"

    $services = Get-Service -Name "LexRest*" -ErrorAction SilentlyContinue

    if (-not $services -or $services.Count -eq 0) {
        Write-Log "No LexRest* services found." "INFO"
        return
    }

    foreach ($svc in $services) {
        Write-Log "Processing service: $($svc.Name), Status: $($svc.Status)" "INFO"

        try {
            if ($svc.Status -ne "Stopped") {
                Write-Log "Stopping service: $($svc.Name)" "INFO"
                Stop-Service -Name $svc.Name -Force -ErrorAction Stop

                $svc.WaitForStatus("Stopped", "00:00:20")
                Write-Log "Service stopped: $($svc.Name)" "SUCCESS"
            }
        } catch {
            Write-Log "Could not stop service $($svc.Name). Error: $($_.Exception.Message)" "WARN"

            try {
                $wmiSvc = Get-CimInstance Win32_Service -Filter "Name='$($svc.Name)'" -ErrorAction Stop

                if ($wmiSvc.ProcessId -and $wmiSvc.ProcessId -ne 0) {
                    Write-Log "Killing service process PID $($wmiSvc.ProcessId) for service $($svc.Name)" "WARN"
                    Stop-Process -Id $wmiSvc.ProcessId -Force -ErrorAction Stop
                    Start-Sleep -Seconds 2
                }
            } catch {
                Write-Log "Could not kill process for service $($svc.Name). Error: $($_.Exception.Message)" "WARN"
            }
        }

        try {
            Write-Log "Deleting service: $($svc.Name)" "INFO"
            sc.exe delete $svc.Name | Out-Null
            Write-Log "Service delete command executed: $($svc.Name)" "SUCCESS"
        } catch {
            Write-Log "Could not delete service $($svc.Name). Error: $($_.Exception.Message)" "ERROR"
        }
    }
}

function Stop-ClaveProcesses {
    Write-Log "Searching processes matching Clave*.exe..." "INFO"

    $processes = Get-Process -Name "Clave*" -ErrorAction SilentlyContinue

    if (-not $processes -or $processes.Count -eq 0) {
        Write-Log "No Clave*.exe processes found." "INFO"
        return
    }

    foreach ($proc in $processes) {
        try {
            Write-Log "Killing process: $($proc.ProcessName), PID: $($proc.Id)" "WARN"
            Stop-Process -Id $proc.Id -Force -ErrorAction Stop
            Write-Log "Process killed: $($proc.ProcessName), PID: $($proc.Id)" "SUCCESS"
        } catch {
            Write-Log "Could not kill process $($proc.ProcessName), PID $($proc.Id). Error: $($_.Exception.Message)" "ERROR"
        }
    }
}

function Remove-ClaveFolders {
    $programFilesPaths = @()

    if ($env:ProgramFiles) {
        $programFilesPaths += $env:ProgramFiles
    }

    if (${env:ProgramFiles(x86)}) {
        $programFilesPaths += ${env:ProgramFiles(x86)}
    }

    $programFilesPaths = $programFilesPaths | Select-Object -Unique

    foreach ($basePath in $programFilesPaths) {
        Write-Log "Searching folders matching Clave* under: $basePath" "INFO"

        try {
            $folders = Get-ChildItem -Path $basePath -Directory -Filter "Clave*" -Force -ErrorAction SilentlyContinue

            if (-not $folders -or $folders.Count -eq 0) {
                Write-Log "No Clave* folders found under: $basePath" "INFO"
                continue
            }

            foreach ($folder in $folders) {
                Write-Log "Removing folder content: $($folder.FullName)" "WARN"

                try {
                    Get-ChildItem -Path $folder.FullName -Force -ErrorAction SilentlyContinue |
                        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

                    Write-Log "Removing folder: $($folder.FullName)" "WARN"
                    Remove-Item -Path $folder.FullName -Recurse -Force -ErrorAction Stop

                    Write-Log "Folder removed: $($folder.FullName)" "SUCCESS"
                } catch {
                    Write-Log "Could not remove folder $($folder.FullName). Error: $($_.Exception.Message)" "ERROR"
                }
            }
        } catch {
            Write-Log "Error searching under $basePath. Error: $($_.Exception.Message)" "ERROR"
        }
    }
}

function Test-ProductStillInstalled {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProductCode
    )

    $info = Get-MsiProductInfoByCode -ProductCode $ProductCode
    return ($null -ne $info)
}

# =========================
# Main
# =========================

Ensure-LogFolder
Ensure-Admin

Write-Log "Starting Clave Impresion uninstall script." "INFO"
Write-Log "Known ProductCode: $KnownProductCode" "INFO"

$productInfo = Get-MsiProductInfoByCode -ProductCode $KnownProductCode

if ($null -eq $productInfo) {
    Write-Log "Known ProductCode was not found. Searching by ProductName..." "WARN"

    $matches = Get-MsiProductInfoByName -NamePatterns $ProductNamePatterns

    if ($matches.Count -eq 0) {
        Write-Log "Product not found by ProductCode or ProductName. Proceeding with cleanup only." "WARN"
        Stop-And-Remove-LexRestServices
        Stop-ClaveProcesses
        Remove-ClaveFolders
        Write-Log "Cleanup finished. Product was not found as installed MSI." "SUCCESS"
        exit 0
    }

    if ($matches.Count -gt 1) {
        Write-Log "Multiple matching MSI products found. The first one will be used." "WARN"

        foreach ($match in $matches) {
            Write-Log "Match: ProductCode=$($match.ProductCode), ProductName=$($match.ProductName), Version=$($match.Version), LocalPackage=$($match.LocalPackage)" "INFO"
        }
    }

    $productInfo = $matches | Select-Object -First 1
}

$productCode = Normalize-ProductCode $productInfo.ProductCode
$productName = $productInfo.ProductName
$productVersion = $productInfo.Version
$localPackage = $productInfo.LocalPackage
$installSource = $productInfo.InstallSource

Write-Log "Target product found." "SUCCESS"
Write-Log "ProductCode   : $productCode" "INFO"
Write-Log "ProductName   : $productName" "INFO"
Write-Log "Version       : $productVersion" "INFO"
Write-Log "LocalPackage  : $localPackage" "INFO"
Write-Log "InstallSource : $installSource" "INFO"

# Step 1: Uninstall by ProductCode
$uninstalled = Invoke-MsiExec `
    -Description "Uninstall by ProductCode" `
    -Arguments @(
        "/x",
        $productCode,
        "/qn",
        "/norestart",
        "/L*v",
        $MsiUninstallLog_ProductCode
    )

if ($uninstalled -and -not (Test-ProductStillInstalled -ProductCode $productCode)) {
    Write-Log "Product is no longer installed after ProductCode uninstall." "SUCCESS"
    exit 0
}

Write-Log "ProductCode uninstall did not remove the product or failed. Trying LocalPackage MSI." "WARN"

# Refresh product info, because LocalPackage can sometimes be queried again after failure
$refreshedInfo = Get-MsiProductInfoByCode -ProductCode $productCode
if ($null -ne $refreshedInfo -and -not [string]::IsNullOrWhiteSpace($refreshedInfo.LocalPackage)) {
    $localPackage = $refreshedInfo.LocalPackage
}

# Step 2: Uninstall by LocalPackage
if (-not [string]::IsNullOrWhiteSpace($localPackage) -and (Test-Path $localPackage)) {
    Write-Log "LocalPackage exists: $localPackage" "SUCCESS"

    $uninstalled = Invoke-MsiExec `
        -Description "Uninstall by LocalPackage" `
        -Arguments @(
            "/x",
            $localPackage,
            "/qn",
            "/norestart",
            "/L*v",
            $MsiUninstallLog_LocalPackage
        )

    if ($uninstalled -and -not (Test-ProductStillInstalled -ProductCode $productCode)) {
        Write-Log "Product is no longer installed after LocalPackage uninstall." "SUCCESS"
        exit 0
    }
} else {
    Write-Log "LocalPackage does not exist or is empty: $localPackage" "WARN"
}

Write-Log "LocalPackage uninstall did not remove the product or failed. Trying reinstall/repair followed by uninstall." "WARN"

# Step 3: Reinstall/repair using LocalPackage, then uninstall
if (-not [string]::IsNullOrWhiteSpace($localPackage) -and (Test-Path $localPackage)) {
    $installed = Invoke-MsiExec `
        -Description "Repair/Reinstall by LocalPackage" `
        -Arguments @(
            "/i",
            $localPackage,
            "/qn",
            "/norestart",
            "/L*v",
            $MsiInstallLog_LocalPackage
        )

    if ($installed) {
        $uninstalled = Invoke-MsiExec `
            -Description "Uninstall after Repair/Reinstall" `
            -Arguments @(
                "/x",
                $localPackage,
                "/qn",
                "/norestart",
                "/L*v",
                $MsiUninstallLog_AfterReinstall
            )

        if ($uninstalled -and -not (Test-ProductStillInstalled -ProductCode $productCode)) {
            Write-Log "Product is no longer installed after repair/reinstall + uninstall." "SUCCESS"
            exit 0
        }
    }
} else {
    Write-Log "Cannot perform repair/reinstall because LocalPackage is missing: $localPackage" "WARN"
}

# Step 4: Manual cleanup
Write-Log "MSI uninstall methods did not fully remove the product. Starting manual cleanup." "WARN"

Stop-And-Remove-LexRestServices
Stop-ClaveProcesses
Remove-ClaveFolders

if (Test-ProductStillInstalled -ProductCode $productCode) {
    Write-Log "Product still appears registered in Windows Installer after cleanup. Review MSI logs in $LogRoot." "ERROR"
    exit 2
} else {
    Write-Log "Product no longer appears registered after cleanup." "SUCCESS"
}

# =========================
# Step 5: Remove orphan services LexRestarSpool and LexrRestartSpool
# =========================

Write-Log "Checking for orphan services LexRestarSpool and LexrRestartSpool..." "INFO"

$orphanServices = @("LexRestarSpool", "LexrRestartSpool")

foreach ($svcName in $orphanServices) {
    $svc = Get-Service -Name $svcName -ErrorAction SilentlyContinue

    if ($null -eq $svc) {
        Write-Log "Service '$svcName' not found. Nothing to do." "INFO"
        continue
    }

    Write-Log "Service '$svcName' found. Status: $($svc.Status)" "WARN"

    # Attempt to stop it if running
    try {
        if ($svc.Status -ne "Stopped") {
            Write-Log "Stopping service '$svcName'..." "INFO"
            Stop-Service -Name $svcName -Force -ErrorAction Stop
            Start-Sleep -Seconds 2
            Write-Log "Service '$svcName' stopped." "SUCCESS"
        }
    } catch {
        Write-Log "Could not stop service '$svcName'. Error: $($_.Exception.Message)" "WARN"
    }

    # Delete the service permanently
    try {
        Write-Log "Deleting service '$svcName' from service registry..." "INFO"
        sc.exe delete $svcName | Out-Null
        Write-Log "Service '$svcName' deleted successfully." "SUCCESS"
    } catch {
        Write-Log "Could not delete service '$svcName'. Error: $($_.Exception.Message)" "ERROR"
    }
}

# =========================
# Step 6: Remove folder "C:\Program Files (x86)\Lexmark\Clave Impresion"
# =========================

$claveFolder = "C:\Program Files (x86)\Lexmark\Clave Impresion"

Write-Log "Checking for folder: $claveFolder" "INFO"

if (Test-Path $claveFolder) {
    Write-Log "Folder found: $claveFolder" "WARN"

    # Search for .EXE files inside the folder
    $exeFiles = Get-ChildItem -Path $claveFolder -Filter "*.exe" -Recurse -Force -ErrorAction SilentlyContinue

    if ($exeFiles -and $exeFiles.Count -gt 0) {
        Write-Log "Found $($exeFiles.Count) .EXE file(s) in the folder." "INFO"

        foreach ($exe in $exeFiles) {
            $exeName = $exe.Name
            Write-Log "Searching for running processes of: $exeName" "INFO"

            # Find and kill all processes matching the image name
            $processName = [System.IO.Path]::GetFileNameWithoutExtension($exeName)
            $runningProcs = Get-Process -Name $processName -ErrorAction SilentlyContinue

            if ($runningProcs -and $runningProcs.Count -gt 0) {
                foreach ($proc in $runningProcs) {
                    try {
                        Write-Log "Killing process: $($proc.ProcessName), PID: $($proc.Id)" "WARN"
                        Stop-Process -Id $proc.Id -Force -ErrorAction Stop
                        Write-Log "Process killed: $($proc.ProcessName), PID: $($proc.Id)" "SUCCESS"
                    } catch {
                        Write-Log "Could not kill process $($proc.ProcessName), PID $($proc.Id). Error: $($_.Exception.Message)" "ERROR"
                    }
                }

                # Wait for processes to terminate
                Start-Sleep -Seconds 2
            } else {
                Write-Log "No running processes found for '$exeName'." "INFO"
            }
        }
    } else {
        Write-Log "No .EXE files found in the folder." "INFO"
    }

    # Remove the entire folder
    try {
        Write-Log "Removing folder: $claveFolder" "WARN"
        Remove-Item -Path $claveFolder -Recurse -Force -ErrorAction Stop
        Write-Log "Folder removed successfully: $claveFolder" "SUCCESS"
    } catch {
        Write-Log "Could not remove folder $claveFolder. Error: $($_.Exception.Message)" "ERROR"
    }
} else {
    Write-Log "Folder not found: $claveFolder. Nothing to do." "INFO"
}

Write-Log "Uninstall script finished." "SUCCESS"
exit 0