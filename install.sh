#!/bin/sh
set -eu

# Install the complete Jev Codex Router stack from this monorepo. The embedded
# router is the only source checkout used by the service: no clone, submodule,
# or second source tree is required.
self=$0
while [ -L "$self" ]; do
  link=$(readlink "$self")
  case $link in
    /*) self=$link ;;
    *) self=$(dirname -- "$self")/$link ;;
  esac
done
repo_dir=$(CDPATH='' cd -P -- "$(dirname -- "$self")" && pwd -P)
router_dir=$repo_dir/router
router_cli=$router_dir/bin/codex-router
codex_home=${CODEX_HOME:-$HOME/.codex}
state_dir=${MODEL_ROUTER_STATE_DIR:-${CODEX_ROUTER_STATE_DIR:-${KIMI_CODEX_STATE_DIR:-$codex_home/codex-router}}}
export CODEX_HOME=$codex_home
export CODEX_ROUTER_STATE_DIR=$state_dir
export CODEX_ROUTER_ISOLATED=1
umask 077

usage() {
  cat <<'EOF'
Usage: ./install.sh [--prepare-only | --desktop]

Install Jev Codex Router from the embedded router fork.

  --prepare-only  Install the embedded router's dependencies without changing
                  Codex configuration, services, credentials, or local state.
  --desktop       Also prepare the optional Desktop launcher; never start the app.
  -h, --help      Show this help.

The full install preserves any configured router providers, adds or updates the
local Jev provider and both Jev models, provisions its protected loopback
credential, enables native ChatGPT sharing, installs both launchd services, and
runs the end-to-end smoke test.
EOF
}

mode=install
desktop=0
case ${1:-} in
  "") ;;
  --prepare-only) mode=prepare ;;
  --desktop) desktop=1 ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac
[ "$#" -le 1 ] || { usage >&2; exit 2; }

[ -x "$router_cli" ] || {
  echo "Embedded router is missing at $router_cli." >&2
  exit 1
}

JEV_PYTHON=$(command -v python3)
export JEV_PYTHON
JEV_ENV_FILE=${JEV_ENV_FILE:-$HOME/.jev.env}
export JEV_ENV_FILE
if [ "$mode" = prepare ]; then
  python3 "$repo_dir/server/install_preflight.py" --prepare-only
else
  python3 "$repo_dir/server/install_preflight.py"
fi

if [ "$mode" = prepare ]; then
  prepare_home=$(mktemp -d "${TMPDIR:-/tmp}/jev-codex-router-prepare.XXXXXX")
  cleanup_prepare_home() {
    [ -n "${prepare_home:-}" ] && [ -d "$prepare_home" ] &&
      rm -rf -- "$prepare_home"
  }
  trap cleanup_prepare_home EXIT HUP INT TERM
  CODEX_HOME=$prepare_home \
    MODEL_ROUTER_STATE_DIR=$prepare_home/codex-router \
    CODEX_ROUTER_STATE_DIR=$prepare_home/codex-router \
    "$router_dir/bin/install" --prepare-only
  exit 0
fi

# Reject unsupported Desktop before dependency preparation or private-state writes.
# The launcher installation rechecks inside the transaction in case the app updates.
if [ "$desktop" = 1 ]; then
  python3 "$repo_dir/server/install_desktop.py" --check
fi

# Dependency preparation uses a separate home and never activates client routing.
"$repo_dir/install.sh" --prepare-only
transaction=$repo_dir/server/install_transaction.py
backup=$(python3 "$transaction" begin)
# A full root reinstall deliberately transfers checkout ownership. Authorize
# its early catalog writes only after the previous runtime is snapshotted.
export MODEL_ROUTER_ALLOW_FOREIGN_STATE=1
rollback_install() {
  result=$?
  trap - EXIT HUP INT TERM
  if [ "$result" -ne 0 ]; then
    if python3 "$transaction" restore "$backup"; then
      printf 'Installation failed; previous configuration restored. Backup: %s\n' "$backup" >&2
    else
      printf 'Installation failed; restoration needs attention. Backup: %s\n' "$backup" >&2
    fi
  fi
  exit "$result"
}
trap rollback_install EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

# Native sharing is required by Jev. Validate it before activating a live route;
# an idle --no-discovery installation cannot satisfy that contract.
node "$router_dir/src/discovery-mode.mjs" set enabled
"$router_cli" chatgpt-session enable
node "$router_dir/src/catalog.mjs" --refresh-native --bundled-native
python3 "$transaction" validate

configure_jev() {
  if "$router_cli" providers generic show jev --json >/dev/null 2>&1; then
    "$router_cli" providers generic edit jev \
      --name "Jev Router" \
      --base-url http://127.0.0.1:4319/v1 \
      --adapter openai-responses \
      --allow-private
  else
    "$router_cli" providers generic add jev \
      --name "Jev Router" \
      --base-url http://127.0.0.1:4319/v1 \
      --adapter openai-responses \
      --allow-private
  fi
  "$router_cli" providers generic enable jev

  node "$repo_dir/server/configure-model.mjs"
  node "$repo_dir/server/configure-auth.mjs"
}

if [ -f "$state_dir/enabled-providers.json" ]; then
  # Repair existing service definitions before provider commands reload them.
  "$router_dir/bin/install" --take-over-managed-router
  configure_jev
else
  # Fresh setup runs its doctor; Jev must already be ready with discovery on.
  configure_jev
  "$router_dir/install.sh" --no-provider --no-tray
fi

"$router_cli" chatgpt-session enable
"$router_cli" refresh-catalog
"$router_dir/bin/control" picker set jev/auto show
"$router_dir/bin/control" picker set jev/manual show
# The gateway registry is loaded at startup. Restart after final model/auth
# publication so advertised new routes are immediately executable.
"$router_dir/bin/control" service restart

CODEX_HOME=$codex_home CODEX_ROUTER_STATE_DIR=$state_dir \
  bash "$repo_dir/server/install-service.sh"
python3 "$repo_dir/server/smoke.py"
python3 "$transaction" validate
python3 "$transaction" validate-isolation
if [ "$desktop" = 1 ]; then
  python3 "$repo_dir/server/install_desktop.py"
fi
python3 "$transaction" commit "$backup"
trap - EXIT HUP INT TERM

printf '\nJev Codex Router is installed from %s.\n' "$repo_dir"
printf 'Official Codex remains direct. Select Jev explicitly with: codex -p jev\n'
