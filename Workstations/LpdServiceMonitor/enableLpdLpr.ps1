# Enable LPD and LPR on Windows 10/11 and Windows Server 2016/2019/2022
# Run this script with administrative privileges
# Example:
# powershell.exe -ExecutionPolicy Bypass -File enableLpdLpr.ps1

dism /online /Enable-Feature /FeatureName:Printing-Foundation-LPDPrintService /All /NoRestart ; `
dism /online /Enable-Feature /FeatureName:Printing-Foundation-LPRPortMonitor /All /NoRestart