#!/bin/sh
#
# SuperQode one-line installer for macOS, Linux, and WSL:
#
#   curl -fsSL https://superqode.dev/install.sh | sh
#
# The script installs uv when it is missing, then uses uv to install SuperQode
# from PyPI in an isolated tool environment. It never uses sudo.
#
# Package manager output is captured to a log rather than printed. A wall of
# several hundred resolved Python dependencies reads like something has gone
# wrong, so the log is shown only when a step actually fails. Set
# SUPERQODE_INSTALL_VERBOSE=1 to stream it instead.

set -eu

UV_INSTALLER_URL="${SUPERQODE_UV_INSTALLER_URL:-https://astral.sh/uv/install.sh}"
SUPERQODE_EXTRAS_VALUE="${SUPERQODE_EXTRAS:-}"
SUPERQODE_VERSION_VALUE="${SUPERQODE_VERSION:-}"
SUPERQODE_VERBOSE="${SUPERQODE_INSTALL_VERBOSE:-0}"
LITELLM_CONSTRAINT="litellm<1.92"

# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------

ESC=$(printf '\033')
FANCY=0
UTF8=0

case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
    *UTF-8*|*utf-8*|*UTF8*|*utf8*) UTF8=1 ;;
esac

if [ -t 1 ] && [ "$SUPERQODE_VERBOSE" = "0" ] && [ -z "${NO_COLOR:-}" ]; then
    case "${TERM:-dumb}" in
        dumb|"") ;;
        *) FANCY=1 ;;
    esac
fi

TRUECOLOR=0
case "${COLORTERM:-}" in
    truecolor|24bit) TRUECOLOR=1 ;;
esac

# G1 to G6 are sampled straight off assets/superqode-logo.png, where the mark
# ramps violet to magenta to red to amber. Terminals that report 24-bit colour
# get those values exactly; the rest get the closest 256-colour cube entries.
if [ "$FANCY" = "1" ]; then
    C_RESET="${ESC}[0m"
    C_BOLD="${ESC}[1m"
    C_DIM="${ESC}[2m"
    C_TEXT="${ESC}[38;5;252m"
    C_TRACK="${ESC}[38;5;238m"
    C_GREEN="${ESC}[38;5;42m"
    if [ "$TRUECOLOR" = "1" ]; then
        C_G1="${ESC}[38;2;121;32;232m"
        C_G2="${ESC}[38;2;172;28;207m"
        C_G3="${ESC}[38;2;218;22;153m"
        C_G4="${ESC}[38;2;254;24;86m"
        C_G5="${ESC}[38;2;254;107;5m"
        C_G6="${ESC}[38;2;255;163;0m"
    else
        C_G1="${ESC}[38;5;92m"
        C_G2="${ESC}[38;5;128m"
        C_G3="${ESC}[38;5;162m"
        C_G4="${ESC}[38;5;197m"
        C_G5="${ESC}[38;5;202m"
        C_G6="${ESC}[38;5;214m"
    fi
else
    C_RESET=""
    C_BOLD=""
    C_DIM=""
    C_TEXT=""
    C_TRACK=""
    C_GREEN=""
    C_G1=""
    C_G2=""
    C_G3=""
    C_G4=""
    C_G5=""
    C_G6=""
fi

if [ "$UTF8" = "1" ]; then
    GL_FULL="█"
    GL_MED="▓"
    GL_LOW="░"
    GL_TICK="✓"
    GL_DOT="•"
else
    GL_FULL="#"
    GL_MED="="
    GL_LOW="-"
    GL_TICK="OK"
    GL_DOT="*"
fi

COLUMNS_AVAILABLE="${COLUMNS:-}"
if [ -z "$COLUMNS_AVAILABLE" ] && command -v tput >/dev/null 2>&1; then
    COLUMNS_AVAILABLE=$(tput cols 2>/dev/null || printf '80')
fi
if [ -z "$COLUMNS_AVAILABLE" ]; then
    COLUMNS_AVAILABLE=80
fi
case "$COLUMNS_AVAILABLE" in
    ''|*[!0-9]*) COLUMNS_AVAILABLE=80 ;;
esac

BAR_WIDTH=28
if [ "$COLUMNS_AVAILABLE" -lt 60 ]; then
    BAR_WIDTH=14
fi

# A frame wider than the terminal wraps, and the carriage return then only
# rewinds the last screen line, so the repaint leaves debris behind. Short
# captions keep every frame on one line.
LABEL_START="Setting up an isolated environment"
LABEL_FETCH="Downloading components"
LABEL_BUILD="Installing components"
LABEL_LINK="Linking commands"
LABEL_UV="Setting up the installer"
if [ "$COLUMNS_AVAILABLE" -lt 72 ]; then
    LABEL_START="Setting up"
    LABEL_FETCH="Downloading"
    LABEL_BUILD="Installing"
    LABEL_LINK="Linking"
fi

# A tenth of a second keeps the sweep smooth. Some minimal /bin/sleep builds
# only accept whole seconds, so fall back rather than erroring on every frame.
TICK=0.1
if ! sleep 0.1 >/dev/null 2>&1; then
    TICK=1
fi

WORK_DIR=""
CURSOR_HIDDEN=0

cleanup() {
    if [ "$CURSOR_HIDDEN" = "1" ]; then
        printf '%s[?25h' "$ESC"
        CURSOR_HIDDEN=0
    fi
    if [ -n "$WORK_DIR" ] && [ -d "$WORK_DIR" ]; then
        rm -rf "$WORK_DIR"
    fi
}

trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

WORK_DIR=$(mktemp -d 2>/dev/null || printf '%s' "${TMPDIR:-/tmp}/superqode-install.$$")
mkdir -p "$WORK_DIR"
STEP_LOG="${WORK_DIR}/step.log"
STEP_STATUS="${WORK_DIR}/step.status"

say() {
    printf '%s\n' "$1"
}

note() {
    if [ "$FANCY" = "1" ]; then
        printf '  %s%s%s %s%s%s\n' "$C_G3" "$GL_DOT" "$C_RESET" "$C_TEXT" "$1" "$C_RESET"
    else
        printf '%s\n' "$1"
    fi
}

clear_line() {
    printf '\r%s[2K' "$ESC"
}

# Build one frame of an indeterminate sweep. Real percentages are not available
# from the package manager, so the bar reports that work is moving rather than
# claiming a position it does not know.
render_bar() {
    rb_pos=$1
    rb_i=0
    rb_out=""
    while [ "$rb_i" -lt "$BAR_WIDTH" ]; do
        rb_d=$(( rb_pos - rb_i ))
        if [ "$rb_d" -lt 0 ]; then
            rb_d=$(( 0 - rb_d ))
        fi
        if [ "$rb_d" -eq 0 ]; then
            rb_out="${rb_out}${C_G6}${GL_FULL}"
        elif [ "$rb_d" -eq 1 ]; then
            rb_out="${rb_out}${C_G5}${GL_FULL}"
        elif [ "$rb_d" -le 3 ]; then
            rb_out="${rb_out}${C_G4}${GL_FULL}"
        elif [ "$rb_d" -le 5 ]; then
            rb_out="${rb_out}${C_G2}${GL_MED}"
        else
            rb_out="${rb_out}${C_TRACK}${GL_LOW}"
        fi
        rb_i=$(( rb_i + 1 ))
    done
    printf '%s%s' "$rb_out" "$C_RESET"
}

# Describe the phase from what the package manager has actually logged, so the
# caption tracks real progress instead of cycling through invented stages.
phase_label() {
    pl_default=$1
    if [ ! -s "$STEP_LOG" ]; then
        printf '%s' "$pl_default"
        return
    fi
    if grep -q 'Installed' "$STEP_LOG" 2>/dev/null; then
        printf '%s' "$LABEL_LINK"
    elif grep -q 'Prepared' "$STEP_LOG" 2>/dev/null; then
        printf '%s' "$LABEL_BUILD"
    elif grep -q 'Resolved' "$STEP_LOG" 2>/dev/null; then
        pl_count=$(grep -o 'Resolved [0-9]* package' "$STEP_LOG" 2>/dev/null | head -n 1 | tr -dc '0-9')
        if [ -n "$pl_count" ] && [ "$COLUMNS_AVAILABLE" -ge 72 ]; then
            printf 'Downloading %s components' "$pl_count"
        else
            printf '%s' "$LABEL_FETCH"
        fi
    else
        printf '%s' "$pl_default"
    fi
}

animate() {
    an_label=$1
    an_frame=0
    an_period=$(( (BAR_WIDTH - 1) * 2 ))
    while [ ! -f "$STEP_STATUS" ]; do
        if [ "$FANCY" = "1" ]; then
            an_p=$(( an_frame % an_period ))
            if [ "$an_p" -ge "$BAR_WIDTH" ]; then
                an_pos=$(( an_period - an_p ))
            else
                an_pos=$an_p
            fi
            printf '\r  %s  %s%s%s' \
                "$(render_bar "$an_pos")" "$C_TEXT" "$(phase_label "$an_label")" "$C_RESET"
            printf '%s[K' "$ESC"
        fi
        an_frame=$(( an_frame + 1 ))
        sleep "$TICK"
    done
    if [ "$FANCY" = "1" ]; then
        clear_line
    fi
}

# Run one step with its output captured. A status file rather than `kill -0`
# ends the wait: a finished child stays killable as a zombie until it is
# reaped, which would spin the animation forever.
run_step() {
    rs_label=$1
    shift
    rm -f "$STEP_STATUS"
    : > "$STEP_LOG"

    if [ "$SUPERQODE_VERBOSE" = "1" ]; then
        say "$rs_label..."
        "$@"
        return $?
    fi

    (
        if "$@" >"$STEP_LOG" 2>&1; then
            printf '0' >"${STEP_STATUS}.tmp"
        else
            printf '%s' "$?" >"${STEP_STATUS}.tmp"
        fi
        mv "${STEP_STATUS}.tmp" "$STEP_STATUS"
    ) &
    rs_pid=$!

    if [ "$FANCY" = "1" ]; then
        printf '%s[?25l' "$ESC"
        CURSOR_HIDDEN=1
    fi
    animate "$rs_label"
    if [ "$FANCY" = "1" ]; then
        printf '%s[?25h' "$ESC"
        CURSOR_HIDDEN=0
    fi

    wait "$rs_pid" 2>/dev/null || true
    rs_rc=$(cat "$STEP_STATUS" 2>/dev/null || printf '1')
    case "$rs_rc" in
        ''|*[!0-9]*) rs_rc=1 ;;
    esac
    return "$rs_rc"
}

step_failed() {
    sf_label=$1
    printf '%s\n' "Error: ${sf_label} failed." >&2
    if [ -s "$STEP_LOG" ]; then
        printf '%s\n' "Output:" >&2
        cat "$STEP_LOG" >&2
    fi
}

banner() {
    if [ "$FANCY" != "1" ]; then
        return
    fi
    printf '\n'
    if [ "$UTF8" = "1" ]; then
        printf '      %s▪%s  %s▪%s\n' "$C_G5" "$C_RESET" "$C_G6" "$C_RESET"
        printf '  %s╭──────────╮%s %s▪%s\n' "$C_G1" "$C_RESET" "$C_G5" "$C_RESET"
        printf '  %s│%s %s●%s %s●%s %s●%s    %s│%s\n' \
            "$C_G1" "$C_RESET" "$C_G2" "$C_RESET" "$C_G3" "$C_RESET" \
            "$C_G4" "$C_RESET" "$C_G2" "$C_RESET"
        printf '  %s│%s  %s❯%s %s▁▁▁%s   %s│%s\n' \
            "$C_G2" "$C_RESET" "$C_G3" "$C_RESET" "$C_G4" "$C_RESET" \
            "$C_G3" "$C_RESET"
        printf '  %s╰──────────╯%s\n\n' "$C_G3" "$C_RESET"
    fi
    printf '  %s%sSuperQode%s\n' "$C_BOLD" "$C_G3" "$C_RESET"
    printf '  %sthe harness interoperability layer for coding agents.%s\n' \
        "$C_TEXT" "$C_RESET"
    printf '  %sAgent to Agent communication over ACP, A2A and UHP%s\n\n' \
        "$C_DIM" "$C_RESET"
}

# The wordmark is 77 columns wide, so narrow terminals get the compact mark.
logo() {
    if [ "$FANCY" != "1" ]; then
        return
    fi
    if [ "$UTF8" != "1" ] || [ "$COLUMNS_AVAILABLE" -lt 80 ]; then
        printf '\n  %s%sSuperQode%s\n\n' "$C_BOLD" "$C_G3" "$C_RESET"
        return
    fi
    printf '\n'
    printf '%s' "$C_G1"
    printf '%s\n' '  ███████╗██╗   ██╗██████╗ ███████╗██████╗  ██████╗  ██████╗ ██████╗ ███████╗'
    printf '%s' "$C_G2"
    printf '%s\n' '  ██╔════╝██║   ██║██╔══██╗██╔════╝██╔══██╗██╔═══██╗██╔═══██╗██╔══██╗██╔════╝'
    printf '%s' "$C_G3"
    printf '%s\n' '  ███████╗██║   ██║██████╔╝█████╗  ██████╔╝██║   ██║██║   ██║██║  ██║█████╗  '
    printf '%s' "$C_G4"
    printf '%s\n' '  ╚════██║██║   ██║██╔═══╝ ██╔══╝  ██╔══██╗██║▄▄ ██║██║   ██║██║  ██║██╔══╝  '
    printf '%s' "$C_G5"
    printf '%s\n' '  ███████║╚██████╔╝██║     ███████╗██║  ██║╚██████╔╝╚██████╔╝██████╔╝███████╗'
    printf '%s' "$C_G6"
    printf '%s\n' '  ╚══════╝ ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═╝ ╚══▀▀═╝  ╚═════╝ ╚═════╝ ╚══════╝'
    printf '%s\n' "$C_RESET"
}

# ---------------------------------------------------------------------------
# Discovery and validation
# ---------------------------------------------------------------------------

find_uv() {
    if command -v uv >/dev/null 2>&1; then
        command -v uv
        return
    fi

    if [ -n "${UV_INSTALL_DIR:-}" ] && [ -x "${UV_INSTALL_DIR}/uv" ]; then
        printf '%s\n' "${UV_INSTALL_DIR}/uv"
        return
    fi

    if [ -n "${XDG_BIN_HOME:-}" ] && [ -x "${XDG_BIN_HOME}/uv" ]; then
        printf '%s\n' "${XDG_BIN_HOME}/uv"
        return
    fi

    if [ -n "${HOME:-}" ]; then
        for candidate in "${HOME}/.local/bin/uv" "${HOME}/.cargo/bin/uv"; do
            if [ -x "$candidate" ]; then
                printf '%s\n' "$candidate"
                return
            fi
        done
    fi

    return 1
}

fetch_uv() {
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf "$UV_INSTALLER_URL" | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- "$UV_INSTALLER_URL" | sh
    else
        printf '%s\n' "Error: installing uv requires curl or wget." >&2
        exit 1
    fi
}

install_uv() {
    note "SuperQode keeps its tools in an isolated environment, managed by uv."
    note "uv was not found, so the official Astral uv installer will run now."
    note "Installer source: ${UV_INSTALLER_URL}"

    if ! run_step "$LABEL_UV" fetch_uv; then
        step_failed "setting up the installer"
        exit 1
    fi
}

validate_options() {
    case "$SUPERQODE_EXTRAS_VALUE" in
        *[!A-Za-z0-9,_-]*)
            printf '%s\n' \
                "Error: SUPERQODE_EXTRAS may contain only letters, numbers, commas, '_' and '-'." \
                >&2
            exit 1
            ;;
    esac
    case "$SUPERQODE_VERSION_VALUE" in
        *[!A-Za-z0-9._+!-]*)
            printf '%s\n' "Error: SUPERQODE_VERSION contains unsupported characters." >&2
            exit 1
            ;;
    esac
}

validate_options

banner

uv_bin="$(find_uv || true)"
if [ -z "$uv_bin" ]; then
    install_uv
    uv_bin="$(find_uv || true)"
fi

if [ -z "$uv_bin" ]; then
    printf '%s\n' "Error: uv was installed but its executable could not be found." >&2
    printf '%s\n' "Open a new terminal and run: uv tool install superqode" >&2
    exit 1
fi

package_spec="superqode"
if [ -n "$SUPERQODE_EXTRAS_VALUE" ]; then
    package_spec="${package_spec}[${SUPERQODE_EXTRAS_VALUE}]"
fi
if [ -n "$SUPERQODE_VERSION_VALUE" ]; then
    package_spec="${package_spec}==${SUPERQODE_VERSION_VALUE}"
fi

install_message="Installing SuperQode"
if [ -n "$SUPERQODE_VERSION_VALUE" ]; then
    install_message="${install_message} ${SUPERQODE_VERSION_VALUE}"
fi
if [ -n "$SUPERQODE_EXTRAS_VALUE" ]; then
    install_message="${install_message} with extras: ${SUPERQODE_EXTRAS_VALUE}"
fi
note "$install_message"

if ! run_step "$LABEL_START" \
    "$uv_bin" tool install \
        --no-config \
        --upgrade \
        --force \
        --with "$LITELLM_CONSTRAINT" \
        "$package_spec"; then
    step_failed "installing SuperQode"
    exit 1
fi

tool_bin="$("$uv_bin" tool dir --bin --no-config)"
superqode_bin="${tool_bin}/superqode"
sq_bin="${tool_bin}/sq"

if [ ! -x "$superqode_bin" ]; then
    printf '%s\n' \
        "Error: SuperQode was installed but ${superqode_bin} was not found." \
        >&2
    exit 1
fi

if [ ! -x "$sq_bin" ]; then
    printf '%s\n' "Error: the expected short command ${sq_bin} was not found." >&2
    exit 1
fi

superqode_version="$("$superqode_bin" --version)"
sq_version="$("$sq_bin" --version)"

logo

if [ "$FANCY" = "1" ]; then
    printf '  %s%s%s %s%s%s\n' \
        "$C_GREEN" "$GL_TICK" "$C_RESET" "$C_TEXT" "$superqode_version" "$C_RESET"
    printf '  %s%s%s %s%s%s\n\n' \
        "$C_GREEN" "$GL_TICK" "$C_RESET" "$C_TEXT" "$sq_version" "$C_RESET"
    printf '  %s%s%s\n' "$C_BOLD" "SuperQode is installed. Run: superqode" "$C_RESET"
    printf '  %sShort command:%s %s%ssq%s\n\n' \
        "$C_DIM" "$C_RESET" "$C_BOLD" "$C_G6" "$C_RESET"
    printf '  %sUpgrade later by running this installer again.%s\n' "$C_DIM" "$C_RESET"
    printf '  %sUninstall with: %s tool uninstall superqode%s\n\n' \
        "$C_DIM" "$uv_bin" "$C_RESET"
else
    say "$superqode_version"
    say "$sq_version"
    say "SuperQode is installed. Run: superqode"
    say "Short command: sq"
    say "Upgrade later by running this installer again."
    say "Uninstall with: ${uv_bin} tool uninstall superqode"
fi

case ":${PATH}:" in
    *":${tool_bin}:"*) ;;
    *)
        if [ "$FANCY" = "1" ]; then
            printf '  %sRestart your shell if '"'"'superqode'"'"' is not found; %s must be on PATH.%s\n\n' \
                "$C_G6" "$tool_bin" "$C_RESET"
        else
            printf '%s\n' \
                "Restart your shell if 'superqode' is not found; ${tool_bin} must be on PATH."
        fi
        ;;
esac
