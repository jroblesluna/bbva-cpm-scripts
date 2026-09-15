#!/bin/bash
#
# lpmc-run.sh — Guided installer for Lexmark Print Management Client (macOS)
#
# Unlike lpmc-stepwise.sh (where you invoke each step yourself), this script
# runs the full sequence and DECIDES what to do based on the result of each
# step: it checks a precondition, acts, verifies the effect, and if the
# check fails it attempts a known remediation before giving up.
#
# If a step fails for good, it aborts there with the diagnosis and tells you
# which --from to resume with. The state is kept in $WORK/.lpmc-state, so
# --resume continues where it left off.
#
# Usage:
#   ./lpmc-run.sh --pkg <path.pkg> --config <path/configuration.json> [options]
#
# Options:
#   --mode combined|split   combined (default): the original signed .pkg.
#                           split: re-flattens and installs driver and client
#                           separately (loses the signature; lab only).
#   --work <dir>            working directory (default ~/lpmc-lab)
#   --from <step>           start from that step
#   --resume                continue from the last completed step
#   --list-steps            list the steps and exit
#   --queue-timeout <sec>   max wait for the queue to appear (default 90)
#   --svc-timeout <sec>     max wait for the daemon + port 9167 (default 60)
#   --smoke                 at the end, send a test job
#   --yes                   do not ask anything (unattended)
#   --dry-run               show what it would do, without touching the system
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
set -uo pipefail    # no -e: the checks return != 0 on purpose

# ------------------------------------------------------------------ options
PKG="" ; CONF="" ; WORK="$HOME/lpmc-lab" ; MODE="combined"
FROM="" ; RESUME=0 ; QUEUE_TIMEOUT=90 ; SVC_TIMEOUT=60 ; SMOKE=0 ; ASSUME_YES=0 ; DRY=0

STEPS=(preflight uninstall_previous stage install check_files check_config
       check_services check_queue smoke)

usage() { sed -n '2,30p' "$0" | sed 's|^# \{0,1\}||'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pkg)           PKG="$2"; shift 2 ;;
    --config)        CONF="$2"; shift 2 ;;
    --work)          WORK="$2"; shift 2 ;;
    --mode)          MODE="$2"; shift 2 ;;
    --from)          FROM="$2"; shift 2 ;;
    --resume)        RESUME=1; shift ;;
    --queue-timeout) QUEUE_TIMEOUT="$2"; shift 2 ;;
    --svc-timeout)   SVC_TIMEOUT="$2"; shift 2 ;;
    --smoke)         SMOKE=1; shift ;;
    --yes|-y)        ASSUME_YES=1; shift ;;
    --dry-run)       DRY=1; shift ;;
    --list-steps)    printf '%s\n' "${STEPS[@]}"; exit 0 ;;
    -h|--help)       usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

STATE="$WORK/.lpmc-state"
LOG="$WORK/run-$(date +%Y%m%d-%H%M%S).log"
STAGEDIR="$WORK/install"          # no spaces or parentheses, on purpose

# --------------------------------------------------- input auto-detection
# If --pkg / --config were not passed, we look for them in the working
# directory. $STAGEDIR is excluded (the copies go there) along with the empty
# .pkg files left by the runscript of lpmc-stepwise.sh as a $1 marker.
if [[ -z "$PKG" && -d "$WORK" ]]; then
  found=$(find "$WORK" -maxdepth 1 -type f -name '*.pkg' -size +1024k 2>/dev/null | sort)
  count=$(printf '%s' "$found" | grep -c . )
  if [[ "$count" -eq 1 ]]; then
    PKG="$found"
  elif [[ "$count" -gt 1 ]]; then
    echo "There is more than one .pkg in $WORK; choose one with --pkg:" >&2
    printf '  %s\n' $found >&2
    exit 2
  fi
fi
[[ -z "$CONF" && -f "$WORK/configuration.json" ]] && CONF="$WORK/configuration.json"

# Argument validation BEFORE asking for sudo or entering the steps: a missing
# argument is a usage error, not a failed step that can be resumed.
missing=""
[[ -z "$PKG"  ]] && missing="$missing --pkg"
[[ -z "$CONF" ]] && missing="$missing --config"
if [[ -n "$missing" ]]; then
  echo "Missing:$missing (and I could not infer it from $WORK)" >&2
  echo >&2
  usage >&2
  exit 2
fi
[[ -f "$PKG"  ]] || { echo "The package does not exist: $PKG" >&2; exit 2; }
[[ -f "$CONF" ]] || { echo "The config does not exist: $CONF" >&2; exit 2; }

# ------------------------------------------------------------------ output
c()      { printf '\033[%sm%s\033[0m\n' "$1" "$2"; }
ok()     { c 32 "  ✓ $*"; }
warn()   { c 33 "  ! $*"; }
fail()   { c 31 "  ✗ $*"; }
info()   { printf '    %s\n' "$*"; }
hdr()    { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
die()    { fail "$*"; exit 1; }

# Runs honoring --dry-run. Everything that mutates the system goes through here.
run() {
  if [[ $DRY -eq 1 ]]; then c 36 "    [dry-run] $*"; return 0; fi
  "$@"
}

# Elevación condicional. Si ya somos root (caso habitual en este flujo), NO se
# antepone 'sudo': en máquinas gestionadas (MDM/Jamf) el sudoers suele restringir
# qué comandos puede correr 'sudo' aunque el usuario ya sea root, y meter 'sudo'
# delante hace fallar cosas tan básicas como /bin/mv ("user root is not allowed
# to execute ... as root"). Si no somos root, se usa sudo para escalar.
if [[ "$(id -u)" -eq 0 ]]; then SUDO=""; else SUDO="sudo"; fi

# Directorio del propio script, para ubicar assets versionados en el repo
# (p. ej. assets/keystore.jks, usado para remediar un keystore faltante).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

ask() {
  [[ $ASSUME_YES -eq 1 ]] && return 0
  local a; read -r -p "    $1 [y/N] " a
  [[ "$a" == "y" || "$a" == "Y" ]]
}

# ------------------------------------------------------------------ helpers
# JSON reading in three tiers. plutil is NOT reliable here: it is meant for
# property lists and on several macOS versions it rejects pure JSON with -lint,
# so python3 goes first and plutil stays as a fallback.
JSON_TOOL=""
detect_json_tool() {
  if command -v python3 >/dev/null 2>&1 && python3 -c 'import json' >/dev/null 2>&1; then
    JSON_TOOL=python3
  elif command -v plutil >/dev/null 2>&1; then
    JSON_TOOL=plutil
  else
    JSON_TOOL=sed
  fi
}

# Returns 0 if the file is valid JSON; otherwise, prints the real error.
json_validate() {
  local err
  case "$JSON_TOOL" in
    python3)
      err=$(python3 -c '
import json, sys
try:
    json.load(open(sys.argv[1]))
except Exception as e:
    sys.exit(str(e))
' "$1" 2>&1) && return 0 ;;
    plutil)
      # WATCH OUT: plutil -lint does NOT accept JSON ("Unexpected character { at line 1"):
      # it only lints property lists. -convert does parse JSON, so we validate
      # by converting to /dev/null.
      err=$(plutil -convert xml1 -o /dev/null "$1" 2>&1) && return 0 ;;
    *)
      [[ "$(head -c 1 "$1")" == "{" ]] && return 0; err="does not start with '{'" ;;
  esac
  printf '%s' "$err"
  return 1
}

# Dotted path: hybridPrintSettings.queueName
json_get() {
  local path="$1" out
  case "$JSON_TOOL" in
    python3)
      out=$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
for k in sys.argv[2].split("."):
    if isinstance(d, dict) and k in d:
        d = d[k]
    else:
        sys.exit(1)
print(d)
' "$CONF" "$path" 2>/dev/null) && { printf '%s' "$out"; return 0; } ;;
    plutil)
      out=$(plutil -extract "$path" raw -o - "$CONF" 2>/dev/null) && [[ -n "$out" ]] && { printf '%s' "$out"; return 0; } ;;
  esac
  # Last resort: search the leaf key by text. Fragile, but better than nothing.
  sed -nE "s/.*\"${path##*.}\"[[:space:]]*:[[:space:]]*\"?([^\",]+)\"?.*/\1/p" "$CONF" | head -1
}

state_save() { [[ $DRY -eq 1 ]] || echo "$1" > "$STATE"; }
state_load() { [[ -f "$STATE" ]] && cat "$STATE" || echo ""; }

sudo_keepalive() {
  [[ $DRY -eq 1 ]] && return 0
  # Si ya somos root no hace falta escalar (y 'sudo -v' puede estar vetado por el
  # sudoers gestionado). El keepalive solo aplica cuando realmente usamos sudo.
  [[ -z "$SUDO" ]] && return 0
  sudo -v || die "sudo is required."
  ( while true; do sudo -n true; sleep 50; kill -0 "$$" 2>/dev/null || exit; done ) 2>/dev/null &
  SUDO_PID=$!
}

lpmc_installed() { [[ -d /Library/Lexmark/PrintManagementClient ]]; }
ppd_present()    { lpinfo -m 2>/dev/null | grep -qi "$DRIVER_NAME"; }
queue_present()  { lpstat -p "$QUEUE_NAME" >/dev/null 2>&1; }
port_listening() { $SUDO lsof -nP -iTCP:"$LOOPBACK_PORT" -sTCP:LISTEN >/dev/null 2>&1; }
daemon_loaded()  { $SUDO launchctl print system/com.lexmark.lpmc.universal.service >/dev/null 2>&1; }
# Devuelve el "last exit code" del daemon (vacío si no está cargado). Un valor
# 127 en bucle = crash-loop por binario/launcher inexistente (JRE mal armado).
daemon_last_exit() {
  $SUDO launchctl print system/com.lexmark.lpmc.universal.service 2>/dev/null \
    | awk -F'=' '/last exit code/{gsub(/ /,"",$2); print $2; exit}'
}

# Reconstruye INSTALL_PATH/jre cuando el postinstall dejó 'mv Contents/Home -> jre'
# a medias (queda el bundle 'zulu*'/'jdk*' pero no 'jre/' ni los launchers lpmc-*).
# Replica exactamente lo que hace extractJre() del postinstall de LPMC:
#   mv <bundle>/Contents/Home -> jre  +  cp java a 4 launchers  +  chmod.
# Devuelve 0 si el launcher del servicio queda ejecutable; 1 si no pudo repararlo.
rebuild_jre() {
  local base=/Library/Lexmark/PrintManagementClient
  local home=""

  # 1) Si ya existe un jre/ real con java, no hay bundle que mover: solo faltan
  #    los launchers (caso raro pero posible si un mv previo dejó el java suelto).
  if [[ -x "$base/jre/bin/java" ]]; then
    home="$base/jre"
  else
    # 2) Ubicar el <bundle>/Contents/Home poblado (con bin/java) del JRE embebido.
    #    Se prefiere el que coincide con la arquitectura, con fallback a cualquiera.
    local arch; arch=$(uname -m)
    local pat="zulu*"
    case "$arch" in
      arm64|arm64e) pat="zulu*aarch64" ;;
      x86_64|x86_64h) pat="zulu*x64" ;;
    esac
    local bundle
    bundle=$(find "$base" -maxdepth 1 -type d \( -iname "$pat" -o -iname 'zulu*' -o -iname 'jdk*' \) 2>/dev/null | head -1)
    [[ -n "$bundle" && -x "$bundle/Contents/Home/bin/java" ]] || { fail "no se encontró un bundle JRE con Contents/Home/bin/java bajo $base"; return 1; }

    warn "reconstruyendo jre/ desde $(basename "$bundle") (postinstall incompleto)"
    # Detener el servicio para no mover archivos en uso.
    run $SUDO launchctl bootout system/com.lexmark.lpmc.universal.service 2>/dev/null
    [[ -d "$base/jre" ]] && run $SUDO rm -rf "$base/jre"
    run $SUDO mv "$bundle/Contents/Home" "$base/jre" || { fail "el mv Contents/Home -> jre falló"; return 1; }
    home="$base/jre"
  fi

  # 3) Crear los 4 launchers como copias de java (argv[0] decide qué arranca).
  local l
  for l in lpmc-universal-service lpmc-install-agent lpmc-systemtray-app lpmc-universal-ui; do
    run $SUDO cp -f "$home/bin/java" "$home/bin/$l" || { fail "no se pudo crear el launcher $l"; return 1; }
  done

  # 4) cacerts.original + permisos, idéntico a setPermissions() del postinstall.
  [[ -f "$home/lib/security/cacerts" ]] && run $SUDO cp -f "$home/lib/security/cacerts" "$home/lib/security/cacerts.original"
  run $SUDO chmod 500 "$home/bin/lpmc-universal-service"
  run $SUDO chmod 500 "$home/bin/lpmc-install-agent"
  run $SUDO chmod 555 "$home/bin/lpmc-systemtray-app"
  run $SUDO chmod 555 "$home/bin/lpmc-universal-ui"

  [[ -x "$home/bin/lpmc-universal-service" ]] || { fail "el launcher del servicio sigue sin ser ejecutable"; return 1; }
  ok "jre/ reconstruido: $home/bin/lpmc-universal-service"

  # 5) Re-cargar el daemon que hicimos bootout arriba. Si no lo recargamos, queda
  #    descargado y check_services reportaría "daemon not loaded" (no crash).
  run $SUDO launchctl bootstrap system /Library/LaunchDaemons/com.lexmark.lpmc.universal.service.plist 2>/dev/null
  return 0
}

# Asegura /var/Lexmark/PrintManagementClient/keystore.jks.
#
# Causa raíz (confirmada en install.log de una workstation gestionada): el
# postinstall de LPMC usa 'sudo mv/cp' internamente en extractJre, y el sudoers
# de la máquina VETA esos comandos aunque el proceso ya sea root ("user root is
# not allowed to execute /bin/mv ... as root"). Resultado en cascada:
#   1) no se crea jre/  ->  2) no hay jre/bin/keytool  ->
#   3) .createkeystore.sh falla ("keytool: No such file or directory") y el
#      keystore NUNCA se genera.
# Por eso el servicio arranca la JVM pero aborta con
# 'FileNotFoundException: keystore.jks' y jamás abre el puerto.
#
# Como rebuild_jre ya repone jre/ (y por tanto keytool), aquí regeneramos el
# keystore replicando EXACTAMENTE .createkeystore.sh del pkg (mismo alias,
# algoritmo, dname, SAN y storepass), en vez de bypassear TLS o traer un .jks
# externo. Los valores son los del propio instalador de Lexmark.
KEYSTORE_LIVE="/var/Lexmark/PrintManagementClient/keystore.jks"
LPMC_KEYSTORE_ALIAS="lpmc_self_signed_cert"
LPMC_KEYSTORE_STOREPASS="h5Tv4PB67fNkRBWL"
LPMC_CLIENT_SECRET_ALIAS="lpmc_client_secret"
LPMC_CLIENT_SECRET="b50313da01274ce868934536efea7e8c5f9f782a78d05776a7b8032d4f8b3eb3"
ensure_keystore() {
  if $SUDO test -f "$KEYSTORE_LIVE"; then
    ok "keystore.jks presente"
    return 0
  fi
  fail "missing $KEYSTORE_LIVE"

  local kt=/Library/Lexmark/PrintManagementClient/jre/bin/keytool
  if [[ ! -x "$kt" ]]; then
    info "no está $kt — el jre/ debe reconstruirse primero (rebuild_jre)"
    return 1
  fi

  info "el postinstall no generó el keystore (sudoers bloqueó extractJre); regenerando con keytool"
  if ! ask "Regenerar keystore.jks (self-signed loopback, igual que el instalador)?"; then
    return 1
  fi

  run $SUDO mkdir -p "$(dirname "$KEYSTORE_LIVE")"

  # 1) keypair self-signed para el loopback 127.0.0.1 (idéntico a .createkeystore.sh)
  run $SUDO "$kt" -genkeypair \
      -alias "$LPMC_KEYSTORE_ALIAS" -keyalg RSA -keysize 2048 \
      -keystore "$KEYSTORE_LIVE" \
      -dname "CN=LPMC, OU=Software, O=Lexmark, L=Lexington, S=KY, C=US" \
      -ext "SAN=IP:127.0.0.1" \
      -storepass "$LPMC_KEYSTORE_STOREPASS" -keypass "$LPMC_KEYSTORE_STOREPASS" \
      -validity 365000 \
    || { fail "keytool -genkeypair falló"; return 1; }

  # 2) secret del cliente (entrada -importpass), igual que el instalador
  if [[ $DRY -eq 1 ]]; then
    c 36 "    [dry-run] $SUDO $kt -importpass -alias $LPMC_CLIENT_SECRET_ALIAS ..."
  else
    printf '%s\n' "$LPMC_CLIENT_SECRET" | $SUDO "$kt" -importpass \
      -alias "$LPMC_CLIENT_SECRET_ALIAS" -keystore "$KEYSTORE_LIVE" \
      -storepass "$LPMC_KEYSTORE_STOREPASS" -keypass "$LPMC_KEYSTORE_STOREPASS" \
      || warn "keytool -importpass del client secret falló (el servicio puede regenerarlo)"
  fi

  run $SUDO chmod 644 "$KEYSTORE_LIVE"
  $SUDO test -f "$KEYSTORE_LIVE" && { ok "keystore.jks regenerado"; return 0; }
  return 1
}

# ==================================================================== STEPS
# Each step returns 0 (continue) or 1 (definitive failure). The ones that have
# a remediation attempt it internally and check again.

step_preflight() {
  hdr "1/9 Preflight"

  [[ "$(uname -s)" == "Darwin" ]] || { fail "This is for macOS only."; return 1; }
  info "macOS $(sw_vers -productVersion) · $(uname -m)"

  info "pkg:    $PKG"
  info "config: $CONF"
  ok "package and configuration present"

  detect_json_tool
  info "JSON parser: $JSON_TOOL"

  local jerr json_ok=1
  jerr=$(json_validate "$CONF") || json_ok=0
  if [[ $json_ok -eq 1 ]]; then
    ok "valid JSON"
  else
    fail "the validator rejected configuration.json:"
    printf '      %s\n' "$jerr"
  fi

  QUEUE_NAME="$(json_get hybridPrintSettings.queueName)"
  [[ -z "$QUEUE_NAME" ]] && QUEUE_NAME="$(json_get defaultQueueName)"
  DRIVER_NAME="$(json_get driverName)"
  LOOPBACK_PORT="$(json_get hybridPrintSettings.loopbackPort)"
  AUTH_PORT="$(json_get listenerPortSettings.authCodePort)"
  IDP_URL="$(json_get serverSettings.idpServerUrl)"

  [[ -n "$QUEUE_NAME"    ]] || { fail "Could not read queueName or defaultQueueName from the config."; return 1; }
  [[ -n "$DRIVER_NAME"   ]] || { fail "Could not read driverName from the config."; return 1; }
  [[ -n "$LOOPBACK_PORT" ]] || LOOPBACK_PORT=9167

  # If the file does not lint but all keys come out clean, the most likely
  # cause is the validator and not the file. We warn and let the user decide,
  # instead of blocking on a false negative.
  if [[ $json_ok -eq 0 ]]; then
    warn "the required keys were read anyway — probably the validator fails, not the file"
    ask "Continue anyway?" || { fail "aborted by the JSON validator"; return 1; }
  fi

  info "queue:     $QUEUE_NAME"
  info "driver:    $DRIVER_NAME"
  info "loopback:  $LOOPBACK_PORT   ·  auth: ${AUTH_PORT:-?}"
  info "IdP:       ${IDP_URL:-?}"

  # The postinstall does dirname "$1" to find the config: if the path has
  # spaces or parentheses, the unquoted variables in the Lexmark script break.
  # That is why we set up our own staging further down.
  case "$PKG" in *[\ \(\)]*) warn "the .pkg path has spaces or parentheses; it will be copied to $STAGEDIR" ;; esac

  STAGED_PKG="$STAGEDIR/$(basename "$PKG")"

  local avail; avail=$(df -g / | awk 'NR==2{print $4}')
  [[ "${avail:-0}" -ge 2 ]] || warn "low free space on /: ${avail}G"
  ok "preflight OK"
  return 0
}

step_uninstall_previous() {
  hdr "2/9 Previous installation"

  if ! lpmc_installed; then ok "no LPMC installed, nothing to clean up"; return 0; fi

  local ver; ver=$(cat /Library/Lexmark/PrintManagementClient/version.txt 2>/dev/null | head -1)
  warn "LPMC is already installed: ${ver:-unknown version}"

  # Reinstalling on top works (the postinstall does stopServices), but if the
  # previous installation ended up with wrong owners it is better to clean up.
  local notroot
  notroot=$($SUDO find /Library/Lexmark/PrintManagementClient -maxdepth 1 ! -user root 2>/dev/null | head -1)
  if [[ -n "$notroot" ]]; then
    warn "there are files not owned by root — previous installation is corrupt"
    if ask "Uninstall before continuing?"; then
      run $SUDO /Library/Lexmark/PrintManagementClient/uninstall.sh
      run $SUDO pkgutil --forget com.lexmark.LPMClientUniversal.pkg 2>/dev/null
      run $SUDO pkgutil --forget com.lexmark.Universal_Color_Print.pkg 2>/dev/null
      ok "uninstalled"
    else
      warn "continuing on top of an installation with dubious permissions"
    fi
  else
    ok "correct ownership; it will install on top"
  fi
  return 0
}

step_stage() {
  hdr "3/9 Staging"

  run mkdir -p "$STAGEDIR"
  # We copy the .pkg and the config together to a clean path. This is what makes
  # the postinstall find the config: it looks for it in the dirname of the .pkg.
  run cp -f "$PKG" "$STAGEDIR/"
  run cp -f "$CONF" "$STAGEDIR/configuration.json"

  if [[ $DRY -eq 0 ]]; then
    [[ -f "$STAGED_PKG" && -f "$STAGEDIR/configuration.json" ]] || { fail "staging did not complete"; return 1; }
  fi
  ok "staging in $STAGEDIR"
  info "the postinstall will read: $STAGEDIR/configuration.json"
  return 0
}

step_install() {
  hdr "4/9 Installation"

  if [[ "$MODE" == "combined" ]]; then
    info "combined mode — original signed package"
    run $SUDO installer -pkg "$STAGED_PKG" -target / -verbose
  else
    info "split mode — re-flattened components (driver first)"
    local full="$WORK/expanded-full" flat="$WORK/expanded"
    [[ -d "$full" ]] || run pkgutil --expand-full "$STAGED_PKG" "$full"
    [[ -d "$flat" ]] || run pkgutil --expand      "$STAGED_PKG" "$flat"

    local comp
    # The driver goes first: without its PPD installed, queue creation fails.
    for pat in '*Universal_Color_Print*' '*LPMClientUniversal*'; do
      comp=$(find "$flat" -maxdepth 1 -type d -name "$pat" | head -1)
      [[ -n "$comp" ]] || { warn "component $pat not found"; continue; }
      local out="$STAGEDIR/$(basename "$comp")"
      run rm -f "$out"
      run pkgutil --flatten "$comp" "$out" || { fail "could not flatten $(basename "$comp")"; return 1; }
      info "installing $(basename "$comp")"
      run $SUDO installer -pkg "$out" -target / -verbose
    done
  fi

  [[ $DRY -eq 1 ]] && return 0
  lpmc_installed || { fail "the installer finished but /Library/Lexmark/PrintManagementClient does not exist"; return 1; }
  ok "installation executed"
  return 0
}

step_check_files() {
  hdr "5/9 Files and permissions"
  [[ $DRY -eq 1 ]] && { ok "(dry-run)"; return 0; }

  local base=/Library/Lexmark/PrintManagementClient miss=0
  for f in .lpmc-universal-service.sh .lpmc-ui.sh .lpmc-print-queue-helper.sh; do
    if [[ -e "$base/$f" ]]; then ok "$f"; else fail "missing $f"; miss=1; fi
  done

  # NO basta con que exista ALGÚN runtime (un dir jre/zulu*/jdk*): el postinstall
  # de LPMC hace 'mv <zulu>/Contents/Home -> jre' y luego copia 'java' a 4
  # launchers (lpmc-universal-service, etc.). Si ese postinstall queda a medias
  # (p. ej. el .zip del JRE ya fue borrado en una corrida previa y el unzip falla
  # en silencio), queda el dir 'zulu*' pero NO 'jre/' ni los launchers → el daemon
  # crashea con exit 127 ("No such file or directory"). Por eso se verifica el
  # binario EXACTO que el wrapper .lpmc-universal-service.sh va a invocar.
  local svc_wrapper="$base/.lpmc-universal-service.sh"
  local jre_exec=""
  if [[ -r "$svc_wrapper" ]]; then
    # Extrae el primer token que apunta a .../jre/... o .../bin/lpmc-universal-service
    jre_exec=$(grep -oE '/[^"[:space:]]*jre/bin/[^"[:space:]]+' "$svc_wrapper" 2>/dev/null | head -1)
  fi
  [[ -z "$jre_exec" ]] && jre_exec="$base/jre/bin/lpmc-universal-service"
  if [[ -x "$jre_exec" ]]; then
    ok "JRE launcher: ${jre_exec#$base/}"
  else
    fail "missing JRE launcher: $jre_exec"
    # Remediation: el postinstall dejó el 'mv Contents/Home -> jre' a medias.
    # Si hay un bundle Zulu/JDK con un java utilizable, reconstruir jre/ nosotros.
    local have_bundle=0
    find "$base" -maxdepth 1 -type d \( -iname 'zulu*' -o -iname 'jdk*' \) 2>/dev/null | grep -q . && have_bundle=1
    if [[ $have_bundle -eq 1 || -x "$base/jre/bin/java" ]]; then
      info "el postinstall no completó 'mv Contents/Home -> jre'; intentando reconstruir automáticamente"
      if ask "Reconstruir jre/ (mv Contents/Home + launchers lpmc-*)?" && rebuild_jre; then
        # Re-verificar el launcher tras la remediación.
        [[ -x "$jre_exec" ]] || jre_exec="$base/jre/bin/lpmc-universal-service"
        if [[ -x "$jre_exec" ]]; then
          ok "JRE launcher: ${jre_exec#$base/} (reconstruido)"
        else
          miss=1
        fi
      else
        info "reconstrucción manual: sudo mv <zulu>/Contents/Home -> $base/jre y copiar java a los 4 launchers lpmc-*"
        miss=1
      fi
    else
      info "no hay bundle Zulu/JDK para reconstruir jre/ — reinstalar el .pkg o traer el JRE"
      miss=1
    fi
  fi

  ls "$base"/lpmc-universal-service-*.jar >/dev/null 2>&1 && ok "service jar" || { fail "missing the service jar"; miss=1; }

  # keystore.jks: precondición del servicio (sin él la JVM arranca pero aborta al
  # cargar el keypair y nunca abre el puerto). Se remedia desde el asset del repo.
  ensure_keystore || miss=1

  [[ $miss -eq 0 ]] || return 1

  # The PPD is a precondition for the queue to be created.
  if ppd_present; then
    ok "PPD present: $DRIVER_NAME"
  else
    fail "the PPD '$DRIVER_NAME' is not there — the queue cannot be created"
    info "check: lpinfo -m | grep -i universal"
    return 1
  fi

  local notroot
  notroot=$($SUDO find "$base" -maxdepth 1 ! -user root 2>/dev/null | head -5)
  [[ -z "$notroot" ]] && ok "ownership root:wheel" || { warn "non-root files:"; echo "$notroot"; }
  return 0
}

step_check_config() {
  hdr "6/9 Applied configuration"
  [[ $DRY -eq 1 ]] && { ok "(dry-run)"; return 0; }

  # WATCH OUT: the real path is /var/..., not /Library/... It is the classic mistake.
  local live=/var/Lexmark/PrintManagementClient/configuration.json

  if ! $SUDO test -f "$live"; then
    fail "the configuration was not copied to $live"
    info "this means the postinstall did not find configuration.json next to the .pkg"
    info "remediation: re-run from the stage step"
    return 1
  fi
  ok "config installed at $live"

  if $SUDO diff -q "$CONF" "$live" >/dev/null 2>&1; then
    ok "identical to the one you passed"
  else
    warn "the installed config differs from the source one:"
    $SUDO diff "$CONF" "$live" | head -20
  fi
  return 0
}

step_check_services() {
  hdr "7/9 Services"
  [[ $DRY -eq 1 ]] && { ok "(dry-run)"; return 0; }

  # El daemon NO abre el socket 9167 apenas launchd lo carga: hay un warm-up
  # (arranca la JVM, inicializa el listener) que tarda varios segundos. Por eso
  # NO se chequea una sola vez (falso negativo por probear demasiado pronto),
  # sino que se espera con polling hasta SVC_TIMEOUT, igual que check_queue.
  info "waiting for the daemon + port $LOOPBACK_PORT (up to ${SVC_TIMEOUT}s; the service needs a warm-up)"
  local dae=0 prt=0
  daemon_loaded  && { ok "daemon com.lexmark.lpmc.universal.service loaded"; dae=1; }

  local waited=0
  while [[ $waited -lt $SVC_TIMEOUT ]]; do
    [[ $dae -eq 1 ]] || daemon_loaded && dae=1
    if [[ $dae -eq 1 ]] && port_listening; then
      ok "listening on $LOOPBACK_PORT after ${waited}s"
      return 0
    fi
    sleep 5; waited=$((waited+5)); printf '.'
  done
  echo

  # Solo tras agotar la espera se recurre al remediation: bootstrap del daemon.
  # Las llamadas legacy launchctl load/unload fallan fuera del contexto de
  # installd ("Input/output error"); bootstrap es el equivalente moderno.
  [[ $dae -eq 1 ]] || fail "daemon not loaded"
  fail "port $LOOPBACK_PORT not listening after ${SVC_TIMEOUT}s"
  warn "remediating with launchctl bootstrap…"
  run $SUDO launchctl bootstrap system /Library/LaunchDaemons/com.lexmark.lpmc.universal.service.plist 2>/dev/null
  run launchctl bootstrap "gui/$(id -u)" /Library/LaunchAgents/com.lexmark.lpmc.systemtray.app.plist 2>/dev/null

  # Segunda espera tras el bootstrap.
  waited=0
  while [[ $waited -lt $SVC_TIMEOUT ]]; do
    daemon_loaded && dae=1
    if [[ $dae -eq 1 ]] && port_listening; then
      ok "listening on $LOOPBACK_PORT after remediation (${waited}s)"
      return 0
    fi
    sleep 5; waited=$((waited+5)); printf '.'
  done
  echo

  fail "the services did not come up"

  # Diagnóstico de causa raíz: si el daemon está cargado pero muere con exit 127,
  # es crash-loop por binario inexistente — típicamente el launcher del JRE
  # (jre/bin/lpmc-universal-service) que el postinstall no creó (mv Home->jre
  # incompleto). En ese caso esperar más NO ayuda; hay que reconstruir el jre/.
  local lec; lec=$(daemon_last_exit)
  if [[ "$lec" == "127" ]]; then
    fail "daemon crash-loop (last exit code 127): el launcher del servicio no existe o no es ejecutable"
    info "causa probable: postinstall dejó 'mv Contents/Home -> jre' a medias; falta jre/bin/lpmc-universal-service"
    info "verificar: ls -la /Library/Lexmark/PrintManagementClient/jre/bin/lpmc-universal-service"
    info "reconstruir: sudo mv <zulu>/Contents/Home /Library/Lexmark/PrintManagementClient/jre && copiar java a los 4 launchers lpmc-*"
  elif [[ -n "$lec" && "$lec" != "0" ]]; then
    fail "daemon crash-loop (last exit code $lec)"
  fi
  info "look at: sudo launchctl print system/com.lexmark.lpmc.universal.service"
  info "and:     sudo tail -50 /var/Lexmark/PrintManagementClient/Logs/*.log"
  return 1
}

step_check_queue() {
  hdr "8/9 Print queue"
  [[ $DRY -eq 1 ]] && { ok "(dry-run)"; return 0; }

  # The queue is NOT created by the postinstall: the install-agent creates it a
  # few seconds later. That is why we wait instead of checking just once.
  info "waiting for '$QUEUE_NAME' (up to ${QUEUE_TIMEOUT}s; the install-agent creates it)"
  local waited=0
  while [[ $waited -lt $QUEUE_TIMEOUT ]]; do
    if queue_present; then
      ok "queue present after ${waited}s"
      lpstat -v "$QUEUE_NAME" | sed 's/^/    /'
      local uri; uri=$(lpstat -v "$QUEUE_NAME" | sed 's/.*: //')
      case "$uri" in
        *"$LOOPBACK_PORT"*) ok "points to the correct loopback" ;;
        *) warn "unexpected URI for hybrid print: $uri" ;;
      esac
      return 0
    fi
    sleep 5; waited=$((waited+5)); printf '.'
  done
  echo

  fail "the queue did not appear in ${QUEUE_TIMEOUT}s"

  if ask "Restart the services and wait again?"; then
    run $SUDO launchctl bootout system/com.lexmark.lpmc.universal.service 2>/dev/null
    sleep 3
    run $SUDO launchctl bootstrap system /Library/LaunchDaemons/com.lexmark.lpmc.universal.service.plist
    waited=0
    while [[ $waited -lt 45 ]]; do
      queue_present && { ok "queue created after the restart"; return 0; }
      sleep 5; waited=$((waited+5)); printf '.'
    done
    echo
  fi

  warn "last resort: create the queue by hand (it falls outside LPMC's control)"
  if ask "Create it with lpadmin?"; then
    local ppd; ppd=$(lpinfo -m | grep -i "$DRIVER_NAME" | head -1 | awk '{print $1}')
    [[ -n "$ppd" ]] || { fail "PPD not found"; return 1; }
    run $SUDO lpadmin -p "$QUEUE_NAME" -E -v "socket://127.0.0.1:$LOOPBACK_PORT" -P "$ppd" -o printer-is-shared=false
    run $SUDO lpadmin -d "$QUEUE_NAME"
    queue_present && { ok "queue created manually"; warn "an LPMC reinstall may replace it"; return 0; }
  fi

  info "diagnostics: sudo tail -80 /var/Lexmark/PrintManagementClient/Logs/*.log"
  return 1
}

step_smoke() {
  hdr "9/9 Print test"
  if [[ $SMOKE -eq 0 ]]; then info "skipped (pass --smoke to run it)"; return 0; fi
  [[ $DRY -eq 1 ]] && { ok "(dry-run)"; return 0; }

  local before; before=$($SUDO ls /var/Lexmark/PrintManagementClient/Jobs 2>/dev/null | wc -l | tr -d ' ')
  run lp -d "$QUEUE_NAME" /etc/hosts >/dev/null || { fail "lp rejected the job"; return 1; }
  info "job sent; watching for 20s…"

  local i=0 ui=0
  while [[ $i -lt 20 ]]; do
    pgrep -f lpmc-universal-ui >/dev/null 2>&1 && { ui=1; break; }
    sleep 2; i=$((i+2))
  done

  local after; after=$($SUDO ls /var/Lexmark/PrintManagementClient/Jobs 2>/dev/null | wc -l | tr -d ' ')
  [[ $ui -eq 1 ]] && ok "the authentication UI opened — the flow works" \
                  || warn "the authentication UI did not appear"
  info "jobs in spool: $before → $after"
  [[ "$after" -gt "$before" ]] && ok "the service captured the job" \
                               || warn "the spool did not grow; check the logs"
  lpstat -W not-completed -o "$QUEUE_NAME" 2>/dev/null | sed 's/^/    /'
  return 0
}

# ==================================================================== driver
mkdir -p "$WORK"
[[ $DRY -eq 0 ]] && exec > >(tee -a "$LOG") 2>&1

c 1 "LPMC — guided installation"
info "work: $WORK"
info "log:     $LOG"
[[ $DRY -eq 1 ]] && c 36 "DRY-RUN MODE: the system is not touched"

# Starting point
START="${STEPS[0]}"
if [[ -n "$FROM" ]]; then
  START="$FROM"
elif [[ $RESUME -eq 1 ]]; then
  last="$(state_load)"
  if [[ -n "$last" ]]; then
    for i in "${!STEPS[@]}"; do
      [[ "${STEPS[$i]}" == "$last" ]] && START="${STEPS[$((i+1))]:-smoke}"
    done
    info "resuming from: $START (last completed: $last)"
  fi
fi

# preflight always runs: it defines QUEUE_NAME, DRIVER_NAME and the other
# variables that all the later checks depend on.
if [[ "$START" != "preflight" ]]; then
  step_preflight >/dev/null 2>&1 || { step_preflight; die "preflight failed"; }
fi

started=0
sudo_ready=0
for s in "${STEPS[@]}"; do
  [[ $started -eq 0 && "$s" != "$START" ]] && continue
  started=1
  # preflight does not need privileges; the rest do. We ask for sudo just once,
  # after preflight has validated that it makes sense to continue.
  if [[ "$s" != "preflight" && $sudo_ready -eq 0 ]]; then
    sudo_keepalive; sudo_ready=1
  fi
  if "step_$s"; then
    state_save "$s"
  else
    echo
    c 31 "═══ Stopped at step: $s ═══"
    info "Fix what was indicated and resume with:"
    info "  $0 --pkg \"$PKG\" --config \"$CONF\" --from $s"
    info "Full log: $LOG"
    exit 1
  fi
done

echo
c 32 "═══ Completed ═══"
info "queue '$QUEUE_NAME' ready over socket://127.0.0.1:$LOOPBACK_PORT"
info "log: $LOG"
