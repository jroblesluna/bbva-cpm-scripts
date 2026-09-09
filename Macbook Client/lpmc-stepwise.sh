#!/bin/bash
#
# lpmc-stepwise.sh — Step-by-step installation of the Lexmark Print Management Client (LPMC) on macOS
#
# Lets you expand the .pkg, read the scripts before running them, install the
# payload, and run pre/postinstall separately, controlling EXACTLY which
# configuration.json is applied.
#
# Key mechanism: the Lexmark postinstall receives the full path to the .pkg as
# $1 and derives the parent folder with dirname. It reads configuration.json
# from there. That is why this script lets you choose the config directory on
# each run.
#
# Usage:
#   ./lpmc-stepwise.sh expand <path-to-.pkg>       expand the package
#   ./lpmc-stepwise.sh list                        components and their scripts
#   ./lpmc-stepwise.sh inspect <index>             PackageInfo, payload and scripts
#   ./lpmc-stepwise.sh install                     RECOMMENDED: flatten + installer(8)
#   ./lpmc-stepwise.sh verify                      queue, listener, daemons, config
#   ./lpmc-stepwise.sh services <up|down|status>   bootstrap/bootout the daemons
#   ./lpmc-stepwise.sh logs                        client logs and install.log
#   ./lpmc-stepwise.sh flatten <index>             rebuild an individual .pkg
#   ./lpmc-stepwise.sh runscript <index> <preinstall|postinstall> <config-dir>
#   ./lpmc-stepwise.sh payload <index>             raw copy (diagnostics only)
#   ./lpmc-stepwise.sh purge --yes                 uninstall everything
#
# -----------------------------------------------------------------------------
# Robles.AI — AlwaysPrint / Lexmark CPM automation
# Author:  Robles.AI  <antonio@robles.ai>
# Phone:   +1 408 590 0153
# Web:     https://robles.ai
#
# © 2026 Inversiones On Line SAC - All rights reserved.
# Part of the Robles.AI automation family.
# Unauthorized use is prohibited without written consent from Inversiones On Line SAC.
# -----------------------------------------------------------------------------
#
set -euo pipefail

WORK="${LPMC_WORK:-$HOME/lpmc-lab}"
FULL="$WORK/expanded-full"    # --expand-full : payload and scripts as files (to READ)
FLAT="$WORK/expanded"         # --expand      : payload as a single file (to RE-PACKAGE)
STAGE="$WORK/stage"           # folder the install runs from (holds configuration.json)

c_ok()   { printf '\033[32m%s\033[0m\n' "$*"; }
c_warn() { printf '\033[33m%s\033[0m\n' "$*"; }
c_err()  { printf '\033[31m%s\033[0m\n' "$*" >&2; }
c_hdr()  { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

need_expanded() {
  [[ -d "$FULL" ]] || { c_err "No expanded package found. Run: $0 expand <path.pkg>"; exit 1; }
}

components() {
  find "$FULL" -maxdepth 1 -type d -name '*.pkg' | sort
}

comp_by_index() {
  local idx="$1" n=0
  while IFS= read -r c; do
    n=$((n+1))
    [[ "$n" == "$idx" ]] && { echo "$c"; return 0; }
  done < <(components)
  c_err "Index $idx out of range. Run: $0 list"; exit 1
}

pkginfo_attr() {
  /usr/bin/xmllint --xpath "string(/pkg-info/@$2)" "$1/PackageInfo" 2>/dev/null || true
}

# A real "script": a regular text file with a shebang. Discards the .lproj
# directories (localization) and stray binaries such as background.tiff.
is_script() {
  [[ -f "$1" ]] || return 1
  [[ "$(head -c 2 "$1" 2>/dev/null)" == "#!" ]]
}

interp_of() {
  local sb; sb="$(head -1 "$1" 2>/dev/null)"
  printf '%s' "${sb#\#!}" | sed 's/^ *//'
}

# Can it be traced with -x? Only POSIX shells.
is_shell_script() {
  interp_of "$1" | grep -qE '(^|/)(bash|sh|zsh|ksh)( |$)'
}

# /var and /etc are symlinks on macOS; resolve the first level.
resolve_top() {
  local name="$1"
  if [[ -L "/$name" ]]; then
    printf '/%s' "$(readlink "/$name")"
  else
    printf '/%s' "$name"
  fi
}

# ---------------------------------------------------------------- expand
cmd_expand() {
  local pkg="${1:?missing path to the .pkg}"
  [[ -f "$pkg" ]] || { c_err "Does not exist: $pkg"; exit 1; }

  rm -rf "$FULL" "$FLAT"
  mkdir -p "$WORK" "$STAGE"

  c_hdr "Expanding (read mode: payload and scripts unpacked)"
  pkgutil --expand-full "$pkg" "$FULL"

  c_hdr "Expanding (re-package mode: payload intact)"
  # --expand keeps the Payload as a single file, which is what lets you flatten
  # it again with pkgutil --flatten without corrupting the BOM.
  pkgutil --expand "$pkg" "$FLAT"

  c_hdr "Distribution"
  [[ -f "$FULL/Distribution" ]] && /usr/bin/xmllint --format "$FULL/Distribution" | sed -n '1,60p'

  # The original configuration.json lives next to the .pkg; copy it to the stage.
  local src_conf
  src_conf="$(dirname "$pkg")/configuration.json"
  if [[ -f "$src_conf" ]]; then
    cp "$src_conf" "$STAGE/configuration.json"
    c_ok "Original configuration.json copied to $STAGE/"
  else
    c_warn "No configuration.json found next to the .pkg."
    c_warn "Place yours in $STAGE/configuration.json before running the postinstall."
  fi

  cmd_list
}

# ---------------------------------------------------------------- list
cmd_list() {
  need_expanded
  c_hdr "Components"
  local n=0
  while IFS= read -r c; do
    n=$((n+1))
    printf '  [%d] %-45s id=%s ver=%s install-location=%s\n' \
      "$n" "$(basename "$c")" \
      "$(pkginfo_attr "$c" identifier)" \
      "$(pkginfo_attr "$c" version)" \
      "$(pkginfo_attr "$c" install-location)"
    if [[ -d "$c/Scripts" ]]; then
      local found=""
      for s in "$c/Scripts"/*; do is_script "$s" && found+="$(basename "$s") "; done
      printf '        scripts: %s\n' "${found:-(none)}"
    fi
  done < <(components)
}

# ---------------------------------------------------------------- inspect
cmd_inspect() {
  need_expanded
  local comp; comp="$(comp_by_index "${1:?missing index}")"

  c_hdr "PackageInfo — $(basename "$comp")"
  /usr/bin/xmllint --format "$comp/PackageInfo" | sed -n '1,40p'

  c_hdr "Payload tree (first 3 levels)"
  [[ -d "$comp/Payload" ]] && find "$comp/Payload" -maxdepth 3 | sed "s|$comp/Payload||" | sed -n '1,60p'

  if [[ -d "$comp/Scripts" ]]; then
    for s in "$comp/Scripts"/*; do
      [[ -f "$s" ]] || continue
      is_script "$s" || continue
      c_hdr "Script: $(basename "$s")  ($(wc -l < "$s") lines, interpreter: $(interp_of "$s"))"
      c_warn "Read it in full before running it:  less $s"
      # Show only the lines that touch configuration and queues — the relevant bits.
      grep -nE 'configuration\.json|dirname|lpadmin|queue|QUEUE|\$1|\$2|launchctl' "$s" | sed -n '1,40p' || true
    done
  fi
}

# ---------------------------------------------------------------- payload
cmd_payload() {
  need_expanded
  local comp; comp="$(comp_by_index "${1:?missing index}")"
  [[ -d "$comp/Payload" ]] || { c_warn "This component has no payload."; return 0; }

  c_hdr "Installing the payload of $(basename "$comp") by hand"
  c_err "THIS IS NOT A REPLACEMENT FOR THE INSTALLER."
  c_warn "pkgutil --expand-full extracts the payload with YOUR identity, not the BOM's."
  c_warn "ditto, even as root, copies with the source ownership: the files end up"
  c_warn "owned by you and not root:wheel. It is corrected below with chown, but for a"
  c_warn "real installation use:  $0 flatten <index>  +  installer -pkg"
  echo
  read -r -p "Continue anyway? [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "Aborted."; return 0; }

  # Copy per top-level entry, resolving the system symlinks
  # (/var -> private/var), which is where ditto fails with "Not a directory".
  local entry name target
  for entry in "$comp/Payload"/*; do
    [[ -e "$entry" ]] || continue
    name="$(basename "$entry")"
    target="$(resolve_top "$name")"
    echo "  $name -> $target"
    sudo /usr/bin/ditto "$entry" "$target"
  done

  # Restore ownership over exactly the payload paths.
  c_hdr "Fixing ownership to root:wheel"
  local rel dst
  while IFS= read -r rel; do
    dst="/${rel#./}"
    [[ -e "$dst" ]] && sudo /usr/sbin/chown root:wheel "$dst"
  done < <(cd "$comp/Payload" && find . -mindepth 1)

  c_ok "Payload copied."
  c_warn "Still no receipt is written to pkgutil, and the modes come from the expand,"
  c_warn "not from the BOM. Verify with: $0 verify"
}

# ---------------------------------------------------------------- runscript
cmd_runscript() {
  need_expanded
  local comp; comp="$(comp_by_index "${1:?missing index}")"
  local which="${2:?missing preinstall|postinstall}"
  local confdir="${3:-$STAGE}"

  local script="$comp/Scripts/$which"
  if [[ ! -f "$script" ]]; then
    c_err "Does not exist: $script"
    c_warn "Scripts available in this component:"
    for s in "$comp/Scripts"/*; do is_script "$s" && echo "    $(basename "$s")"; done
    exit 1
  fi

  confdir="$(cd "$confdir" && pwd)"   # absolute
  [[ -f "$confdir/configuration.json" ]] || {
    c_err "No configuration.json in $confdir"
    c_err "The postinstall reads it from there (dirname of \$1). Place it before continuing."
    exit 1
  }

  # The script derives the config folder with dirname "$1". We give it a .pkg
  # path *inside* confdir; the file itself only needs to exist.
  local fake_pkg="$confdir/LPMC-stepwise.pkg"
  [[ -e "$fake_pkg" ]] || : > "$fake_pkg"

  c_hdr "Running $which of $(basename "$comp")"
  echo "  interpreter          = $(interp_of "$script")"
  echo "  \$1 (package path)   = $fake_pkg"
  echo "  \$2 (install target) = /"
  echo "  \$3 (volume)         = /"
  echo "  config read from     = $confdir/configuration.json"
  echo
  grep -iE '"(queueName|defaultQueueName|driverName|loopbackPort)"' "$confdir/configuration.json" || true
  echo
  read -r -p "Continue? [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "Aborted."; exit 0; }

  # Honor the shebang: the universal driver postinstall is Perl, not shell.
  # Forcing bash there produces "use: command not found".
  local log="$WORK/$which-$(date +%H%M%S).log"
  if is_shell_script "$script"; then
    sudo /bin/bash -x "$script" "$fake_pkg" "/" "/" "/" 2>&1 | tee "$log"
  else
    c_warn "Not a shell script: it runs with its own interpreter, without -x tracing."
    sudo /usr/bin/env "$(interp_of "$script")" "$script" "$fake_pkg" "/" "/" "/" 2>&1 | tee "$log"
  fi
  c_ok "Done. Trace at $log"
  c_warn "If the script stopped/started services, the legacy launchctl load/unload"
  c_warn "calls fail outside the installd context. Bring them up with: $0 services up"
}

# ---------------------------------------------------------------- services
# launchctl load/unload give "Input/output error" when the postinstall is run
# by hand from a Terminal. bootstrap/bootout are the modern equivalents.
cmd_services() {
  local action="${1:-status}"
  local daemon=/Library/LaunchDaemons/com.lexmark.lpmc.universal.service.plist
  local agent=/Library/LaunchAgents/com.lexmark.lpmc.systemtray.app.plist
  case "$action" in
    up)
      [[ -f "$daemon" ]] && sudo launchctl bootstrap system "$daemon" || c_warn "no daemon"
      [[ -f "$agent" ]]  && launchctl bootstrap "gui/$(id -u)" "$agent" || c_warn "no agent"
      c_ok "Services brought up." ;;
    down)
      sudo launchctl bootout system/com.lexmark.lpmc.universal.service 2>/dev/null || true
      launchctl bootout "gui/$(id -u)/com.lexmark.lpmc.systemtray.app" 2>/dev/null || true
      c_ok "Services brought down." ;;
    status|*)
      sudo launchctl print system/com.lexmark.lpmc.universal.service 2>/dev/null \
        | grep -E 'state|pid|last exit' || c_warn "daemon not loaded"
      launchctl print "gui/$(id -u)/com.lexmark.lpmc.systemtray.app" 2>/dev/null \
        | grep -E 'state|pid|last exit' || c_warn "agent not loaded" ;;
  esac
}

# ---------------------------------------------------------------- install
# The correct path: re-flatten each component and install it with installer(8),
# which does restore ownership from the BOM and writes receipts. The driver
# FIRST, so the PPD exists when the LPMC helper creates the queue.
cmd_install() {
  need_expanded
  mkdir -p "$STAGE"
  [[ -f "$STAGE/configuration.json" ]] || { c_err "Missing $STAGE/configuration.json"; exit 1; }

  local n idx name driver_idx="" client_idx=""
  n=0
  while IFS= read -r c; do
    n=$((n+1)); name="$(basename "$c")"
    [[ "$name" == *Universal_Color_Print* ]] && driver_idx=$n
    [[ "$name" == *LPMClientUniversal*   ]] && client_idx=$n
  done < <(components)

  for idx in "$driver_idx" "$client_idx"; do
    [[ -n "$idx" ]] || continue
    name="$(basename "$(comp_by_index "$idx")")"
    pkgutil --flatten "$FLAT/$name" "$STAGE/$name" 2>/dev/null || {
      rm -f "$STAGE/$name"; pkgutil --flatten "$FLAT/$name" "$STAGE/$name"; }
    c_hdr "installer -pkg $name"
    sudo installer -pkg "$STAGE/$name" -target / -verbose
  done

  c_ok "Installation complete. The queue takes ~30s to appear (created by the install-agent)."
  c_warn "Verify with: $0 verify"
}

# ---------------------------------------------------------------- flatten
cmd_flatten() {
  need_expanded
  local idx="${1:?missing index}"
  local name; name="$(basename "$(comp_by_index "$idx")")"
  local src="$FLAT/$name"
  [[ -d "$src" ]] || { c_err "Does not exist: $src"; exit 1; }

  mkdir -p "$STAGE"
  local out="$STAGE/$name"
  rm -f "$out"
  pkgutil --flatten "$src" "$out"
  c_ok "Generated: $out"
  echo
  echo "Install it with the config in the same folder:"
  echo "  sudo installer -pkg \"$out\" -target / -verbose"
  c_warn "The regenerated package loses the Lexmark signature. installer(8) accepts it,"
  c_warn "but do not distribute it this way to the BBVA machines — use the original."
}

# ---------------------------------------------------------------- verify
cmd_verify() {
  c_hdr "CUPS queues"
  lpstat -p -d 2>/dev/null || true
  lpstat -v 2>/dev/null || true

  c_hdr "Service listener (loopback hybrid print)"
  sudo lsof -nP -iTCP:9167 -sTCP:LISTEN || c_warn "Nobody is listening on 9167"

  c_hdr "Daemons and agents"
  sudo launchctl list | grep -i lexmark || c_warn "No system daemons"
  launchctl list | grep -i lexmark || c_warn "No user agents"

  c_hdr "Installed files"
  sudo ls -la /Library/Lexmark/PrintManagementClient/ 2>/dev/null || c_warn "Not installed"

  c_hdr "Ownership (everything should be root/wheel)"
  if [[ -d /Library/Lexmark/PrintManagementClient ]]; then
    local bad
    bad=$(sudo find /Library/Lexmark/PrintManagementClient -maxdepth 1 ! -user root 2>/dev/null | head -20)
    if [[ -n "$bad" ]]; then
      c_err "Files NOT owned by root — a sign of a manual ditto install:"
      echo "$bad"
      c_warn "Fix it by reinstalling with: $0 install"
    else
      c_ok "Ownership correct."
    fi
  fi

  c_hdr "Where the configuration ended up"
  # NOTE: the real path is /var/Lexmark/PrintManagementClient/configuration.json,
  # NOT /Library/Lexmark/... — the postinstall copies it there via LPMC_DATA_PATH.
  sudo find /Library/Lexmark /var/Lexmark /Library/Preferences \
       -iname '*.json' -not -path '*/jre/*' -not -path '*/zulu*' 2>/dev/null \
    || c_warn "No .json found — the service runs with defaults"
  sudo grep -iE '"(queueName|defaultQueueName|driverName)"' \
       /var/Lexmark/PrintManagementClient/configuration.json 2>/dev/null || true
}

# ---------------------------------------------------------------- logs
cmd_logs() {
  c_hdr "Client logs"
  sudo ls -lt /var/Lexmark/PrintManagementClient/Logs/ 2>/dev/null || c_warn "No log directory"
  sudo /bin/bash -c 'tail -n 60 /var/Lexmark/PrintManagementClient/Logs/*.log 2>/dev/null' || true

  c_hdr "Queued jobs"
  sudo ls -la /var/Lexmark/PrintManagementClient/Jobs/ 2>/dev/null || true

  c_hdr "install.log (Lexmark only, no JRE noise)"
  grep -iE 'lexmark|lpmc|lpadmin' /var/log/install.log \
    | grep -vE 'zulu|legal|LICENSE|ASSEMBLY|ADDITIONAL' | tail -40 || true
}

# ---------------------------------------------------------------- purge
cmd_purge() {
  [[ "${1:-}" == "--yes" ]] || { c_err "Destructive. Repeat with: $0 purge --yes"; exit 1; }

  c_hdr "Uninstalling"
  [[ -x /Library/Lexmark/PrintManagementClient/uninstall.sh ]] \
    && sudo /Library/Lexmark/PrintManagementClient/uninstall.sh || c_warn "No uninstall.sh"

  for q in $(lpstat -p 2>/dev/null | awk '/^printer Lexmark/ {print $2}'); do
    echo "Removing queue $q"
    sudo lpadmin -x "$q" || true
  done

  sudo pkgutil --forget com.lexmark.LPMClientUniversal.pkg 2>/dev/null || true
  sudo pkgutil --forget com.lexmark.Universal_Color_Print.pkg 2>/dev/null || true
  c_ok "Clean. Verify with: $0 verify"
}

# ---------------------------------------------------------------- main
case "${1:-}" in
  expand)    shift; cmd_expand "$@" ;;
  install)   shift; cmd_install "$@" ;;
  services)  shift; cmd_services "$@" ;;
  list)      shift; cmd_list "$@" ;;
  inspect)   shift; cmd_inspect "$@" ;;
  payload)   shift; cmd_payload "$@" ;;
  runscript) shift; cmd_runscript "$@" ;;
  flatten)   shift; cmd_flatten "$@" ;;
  verify)    shift; cmd_verify "$@" ;;
  logs)      shift; cmd_logs "$@" ;;
  purge)     shift; cmd_purge "$@" ;;
  *)
    sed -n '2,25p' "$0" | sed 's|^# \{0,1\}||'
    exit 1 ;;
esac
