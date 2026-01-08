# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a hybrid Linux-Windows print management system integrating **Lexmark Cloud Print Manager (CPM)** in a BBVA banking environment. The architecture uses:
- **Linux SUSE 12 server** running CUPS with custom filters
- **Windows workstations** running CPM client with LPD services
- Dynamic hostname-to-user-to-IP mapping maintained by Windows clients

## Key Architecture Concepts

### Dynamic Queue Creation
The system dynamically creates and updates CUPS queues based on workstation mappings. Queue names follow the pattern `w10###0SpYY` where:
- `###` = agency code (3 digits)
- `S` = Linux server identifier (1 char)
- `YY` = normalized position number (2 digits)

### Two Print Modes

1. **Production Mode** (`filtro_nacarpr.cpm`): Routes through CPM with PJL headers
2. **Contingency Mode** (`filtro_contingencia`): Direct LPD to physical printer, bypassing CPM

### Mapping Database
The file `/var/lib/lexmark/win_hostname_user.txt` contains dynamic mappings in format:
```
w1038401p12|ope01|118.45.23.12
```
Updated by Windows clients via `update_winhostuser.bat` → `CPMWinHostUser` queue → `filtro_winhostuser` filter.

## Testing & Validation

### Manual Print Test (Linux → Windows)
```bash
echo test > /var/lib/lexmark/test.txt
/usr/lib/cups/backend/lpd 999 user Job 1 "" /var/lib/lexmark/test.txt lpd://118.63.108.x:515/LexmarkBBVA
```

### Check Services Status
```bash
# LPD service listening
ss -lntp | grep :515
systemctl status xinetd

# CUPS queues
lpstat -v
lpstat -p -d

# View mapping database
cat /var/lib/lexmark/win_hostname_user.txt

# Check logs
tail -f /var/lib/lexmark/lexmark.log
tail -f /var/lib/lexmark/lexmark_winhostuser.log
```

### Firewall Verification
```bash
iptables -L -n | grep 515
```

## Critical File Locations

### Linux Server (`/root/bin`)
- `filtro_nacarpr` - Main production filter (rename from `filtro_nacarpr.cpm`)
- `filtro_contingencia` - Contingency filter for direct printing
- `filtro_winhostuser` - Mapping database updater
- `create_CPMWinHostUser.sh` - Creates the mapping receiver queue
- `Lexmark.Cups.ppd.gz` - Base PPD for dynamic queues

### Mapping & Logs
- `/var/lib/lexmark/win_hostname_user.txt` - Hostname→User→IP database
- `/var/lib/lexmark/lexmark.log` - Main filter logs
- `/var/lib/lexmark/lexmark_winhostuser.log` - Mapping update logs

### Windows Client
- `Workstations/Startup/update_winhostuser.bat` - Sends mapping to Linux server
- `Workstations/Client Installer/configuration.json` - CPM client config
- `Workstations/SetupLPD/lprlpd.ps1` - Enables LPR/LPD services

## Filter Behaviors

### `filtro_nacarpr`
1. Extracts workstation code from CUPS queue name
2. Looks up Windows IP from mapping database using regex pattern matching
3. Verifies TCP/515 connectivity
4. Creates/updates dynamic CUPS queue with URI `lpd://$WINIP:515/LexmarkBBVA`
5. Injects PJL headers (USERNAME, JOBNAME, HOLDKEY, etc.)
6. Handles PCL5, PostScript, and generic formats
7. Optionally duplicates to Tea4Cups queue `p<puesto>` for PDF archival

### `filtro_contingencia`
1. Extracts physical printer IP from queue's DEVICE_URI
2. Sends original spool unchanged via `/usr/lib/cups/backend/lpd`
3. Optionally duplicates to Tea4Cups for PDF
4. No PJL injection or job modification

### `filtro_winhostuser`
1. Parses first line: `hostname|usuario|ip`
2. Validates: hostname 11-12 chars, user starts with 'o'/'p', IP starts with '118.'
3. Normalizes hostname to 11 chars
4. Updates mapping database, replacing previous entries for same host

## Creating Print Queues

### Production Queue (CPM)
```bash
lpadmin -p w012301p01 -D 'Impresora con filtro_nacarpr Lexmark' -L 'filtro_nacarpr' -E -v lpd://118.64.40.11:515/lp -i /root/bin/filtro_nacarpr
```

### Contingency Queue (Direct)
```bash
lpadmin -p w012301p01 -D 'Impresora con filtro_contingencia Lexmark' -L 'filtro_contingencia' -E -v lpd://118.64.40.11:515/lp -i /root/bin/filtro_contingencia
```

### Mapping Receiver Queue
```bash
/root/bin/create_CPMWinHostUser.sh
```

## Windows Client Setup

### Install LPD Service Monitor
```powershell
msiexec /i .\LpdServiceMonitor.msi /qn /L*v install.log
```

### Check Services
```powershell
Get-Service LpdServiceMonitor
Get-Service LPDSVC
```

## Common Issues

### No Mapping for Workstation
- Verify `update_winhostuser.bat` runs at startup
- Check `CPMWinHostUser` queue exists and is enabled
- Review `/var/lib/lexmark/lexmark_winhostuser.log`

### Port 515 Closed
- Check firewall rules on both Linux server and Windows client
- Verify xinetd running and cups-lpd enabled
- Test connectivity: `bash -c "</dev/tcp/IP/515"`

### Queue Points to Wrong IP
- Check mapping database: `/var/lib/lexmark/win_hostname_user.txt`
- Verify with: `lpstat -v <queue_name>`
- Filter auto-corrects URI on next print job

### Tea4Cups Not Generating PDF
- Confirm `p<puesto>` queue exists
- Verify queue uses Tea4Cups backend
- Check both filters duplicate to this queue

## Version History Format

Updates follow pattern: `v202509150000` (YYYYMMDDhhmm)
- v202510231800: Latest updates to `filtro_nacarpr`
- v202509150000: Added `filtro_contingencia` for direct printing

## Security Notes

- LPD is plaintext - restrict to internal networks
- Firewall allows TCP/515 only from authorized subnets (e.g., `118.63.108.0/24`)
- `sudoers` limited to: `lpadmin`, `cupsenable`, `cupsaccept` for user `lp`
- Backend permissions: `chmod 755 /usr/lib/cups/backend/lpd`