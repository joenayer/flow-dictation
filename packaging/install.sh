#!/bin/sh
# Install (or uninstall) flow-linux: editable venv, systemd --user unit, autostart.
# Does not download STT models.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
UNIT_DIR="$CONFIG_HOME/systemd/user"
UNIT_PATH="$UNIT_DIR/flow-linux.service"
AUTOSTART_DIR="$CONFIG_HOME/autostart"
DESKTOP_PATH="$AUTOSTART_DIR/flow-linux.desktop"
VENV_PY="$REPO_ROOT/.venv/bin/python"
SERVICE_TEMPLATE="$SCRIPT_DIR/flow-linux.service"

usage() {
    cat <<'EOF'
Usage: install.sh [--help] [--uninstall] [--purge]

Install flow-linux into ./.venv and enable the systemd --user unit
(the single launcher at login). Does not download STT models;
after install run: scripts/fetch_models.sh

  --uninstall   Disable the user unit and remove unit files.
                Repo and models are kept.
  --purge       Also remove models/, .venv, and ~/.config/flow-linux.
  --help        Show this help.
EOF
}

do_uninstall() {
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user disable --now flow-linux.service >/dev/null 2>&1 || true
        systemctl --user daemon-reload >/dev/null 2>&1 || true
    fi
    rm -f "$UNIT_PATH" "$DESKTOP_PATH"
    echo "flow-linux unit and autostart removed."
}

systemd_exec_escape() {
    # ExecStart accepts a quoted argument. Escape quotes/backslashes and
    # double percent signs to prevent unit specifier expansion.
    printf '%s' "$1" | sed \
        -e 's/\\/\\\\/g' \
        -e 's/"/\\"/g' \
        -e 's/%/%%/g'
}

systemd_workdir_escape() {
    # WorkingDirectory receives the full value, including interior spaces.
    # Escape percent signs only, so unit specifier expansion leaves them literal.
    printf '%s' "$1" | sed -e 's/%/%%/g'
}

escape_sed_replacement() {
    # The template substitution uses | as its delimiter.
    printf '%s' "$1" | sed 's/[\\&|]/\\&/g'
}

write_service_unit() {
    if [ ! -r "$SERVICE_TEMPLATE" ]; then
        echo "install.sh: service template not found: $SERVICE_TEMPLATE" >&2
        exit 1
    fi

    _exec_path=$(systemd_exec_escape "$VENV_PY")
    _exec_path=$(printf '%s' "$_exec_path" | sed -e 's/\$/$$/g')
    _work_dir=$(systemd_workdir_escape "$REPO_ROOT")
    _exec_path=$(escape_sed_replacement "\"${_exec_path}\"")
    _work_dir=$(escape_sed_replacement "$_work_dir")
    sed \
        -e "s|@FLOW_EXECSTART@|$_exec_path|g" \
        -e "s|@FLOW_WORKDIR@|$_work_dir|g" \
        "$SERVICE_TEMPLATE" > "$UNIT_PATH"
}

do_purge() {
    do_uninstall
    rm -rf "$REPO_ROOT/models" "$REPO_ROOT/.venv" "$CONFIG_HOME/flow-linux"
    echo "Purged models/, .venv, and $CONFIG_HOME/flow-linux. Repo source kept."
}

do_install() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo "install.sh: python3 is required" >&2
        exit 1
    fi

    if command -v uv >/dev/null 2>&1; then
        if [ ! -x "$VENV_PY" ]; then
            uv venv "$REPO_ROOT/.venv"
        fi
        uv pip install --python "$VENV_PY" -e "$REPO_ROOT"
    else
        if [ ! -x "$VENV_PY" ]; then
            python3 -m venv "$REPO_ROOT/.venv"
        fi
        "$REPO_ROOT/.venv/bin/pip" install -e "$REPO_ROOT"
    fi

    mkdir -p "$UNIT_DIR"
    write_service_unit
    # Single launcher is the systemd unit; a desktop entry too would
    # start a second copy at login (double hotkeys, double memory).
    rm -f "$DESKTOP_PATH"

    if ! command -v systemctl >/dev/null 2>&1; then
        echo "install.sh: systemctl not found; unit copied to $UNIT_PATH but not enabled" >&2
        exit 1
    fi
    systemctl --user daemon-reload
    systemctl --user enable --now flow-linux.service

    echo "Installed. Next step (models are NOT downloaded by this script):"
    echo "  $REPO_ROOT/scripts/fetch_models.sh"
}

UNINSTALL=0
PURGE=0
for arg in "$@"; do
    case "$arg" in
        --help|-h)
            usage
            exit 0
            ;;
        --uninstall)
            UNINSTALL=1
            ;;
        --purge)
            PURGE=1
            ;;
        *)
            echo "install.sh: unknown argument: $arg" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [ "$PURGE" -eq 1 ]; then
    do_purge
    exit 0
fi
if [ "$UNINSTALL" -eq 1 ]; then
    do_uninstall
    exit 0
fi
do_install
