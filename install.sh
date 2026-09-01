#!/bin/sh
#
# SuperQode one-line installer for macOS, Linux, and WSL:
#
#   curl -fsSL https://superqode.dev/install.sh | sh
#
# The script installs uv when it is missing, then uses uv to install SuperQode
# from PyPI in an isolated tool environment. It never uses sudo.

set -eu

UV_INSTALLER_URL="${SUPERQODE_UV_INSTALLER_URL:-https://astral.sh/uv/install.sh}"
SUPERQODE_EXTRAS_VALUE="${SUPERQODE_EXTRAS:-}"
SUPERQODE_VERSION_VALUE="${SUPERQODE_VERSION:-}"
LITELLM_CONSTRAINT="litellm<1.92"

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

install_uv() {
    printf '%s\n' "SuperQode uses uv to manage an isolated Python environment."
    printf '%s\n' "uv was not found, so the official Astral uv installer will run now."
    printf '%s\n' "Installer source: ${UV_INSTALLER_URL}"

    if command -v curl >/dev/null 2>&1; then
        curl -LsSf "$UV_INSTALLER_URL" | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- "$UV_INSTALLER_URL" | sh
    else
        printf '%s\n' "Error: installing uv requires curl or wget." >&2
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

printf '%s\n' "Installing ${package_spec} from PyPI with ${uv_bin}..."
"$uv_bin" tool install \
    --no-config \
    --upgrade \
    --force \
    --with "$LITELLM_CONSTRAINT" \
    "$package_spec"

tool_bin="$("$uv_bin" tool dir --bin --no-config)"
superqode_bin="${tool_bin}/superqode"
sq_bin="${tool_bin}/sq"

if [ ! -x "$superqode_bin" ]; then
    printf '%s\n' \
        "Error: SuperQode was installed but ${superqode_bin} was not found." \
        >&2
    exit 1
fi

"$superqode_bin" --version

if [ ! -x "$sq_bin" ]; then
    printf '%s\n' "Error: the expected short command ${sq_bin} was not found." >&2
    exit 1
fi

"$sq_bin" --version
printf '%s\n' "SuperQode is installed. Run: superqode"
printf '%s\n' "Short command: sq"
printf '%s\n' "Upgrade later by running this installer again."
printf '%s\n' "Uninstall with: ${uv_bin} tool uninstall superqode"

case ":${PATH}:" in
    *":${tool_bin}:"*) ;;
    *)
        printf '%s\n' \
            "Restart your shell if 'superqode' is not found; ${tool_bin} must be on PATH."
        ;;
esac
