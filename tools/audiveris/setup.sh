#!/usr/bin/env bash
# ============================================================================
# Audiveris OMR -- One-time setup script
#
# Handles installation on Windows (winget), Linux (apt/deb), and macOS (brew).
# Also installs Tesseract OCR language data (required for text recognition).
#
# Usage:
#   bash tools/audiveris/setup.sh            # auto-detect OS
#   bash tools/audiveris/setup.sh --docker   # pull Docker image only
#   bash tools/audiveris/setup.sh --check    # just verify installation
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
AUDIVERIS_VERSION="5.10.2"
DOCKER_IMAGE="nirmata1/audiforge:latest"

# ANSI colours (disabled if not a terminal)
if [ -t 1 ]; then
    GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; NC=''
fi

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ---------------------------------------------------------------------------
# Detect OS
# ---------------------------------------------------------------------------
detect_os() {
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
        Linux*)                echo "linux"   ;;
        Darwin*)               echo "macos"   ;;
        *)                     echo "unknown" ;;
    esac
}

OS="$(detect_os)"

# ---------------------------------------------------------------------------
# Check: is Audiveris already installed?
# ---------------------------------------------------------------------------
check_audiveris() {
    if [ "$OS" = "windows" ]; then
        if [ -f "C:/Program Files/Audiveris/Audiveris.exe" ]; then
            local ver
            ver=$("C:/Program Files/Audiveris/Audiveris.exe" -version 2>&1 | head -5)
            info "Audiveris is installed:"
            echo "  $ver"
            return 0
        fi
    fi

    if command -v audiveris &>/dev/null; then
        info "Audiveris found on PATH: $(command -v audiveris)"
        audiveris -version 2>&1 | head -5
        return 0
    fi

    return 1
}

# ---------------------------------------------------------------------------
# Check: is Java 17+ available?
# ---------------------------------------------------------------------------
check_java() {
    local java_cmd="java"

    # Try JAVA_HOME first
    if [ -n "${JAVA_HOME:-}" ] && [ -f "$JAVA_HOME/bin/java" ]; then
        java_cmd="$JAVA_HOME/bin/java"
    fi

    # Try known Windows path
    if [ "$OS" = "windows" ] && [ -f "C:/Program Files/Microsoft/jdk-17.0.18.8-hotspot/bin/java" ]; then
        java_cmd="C:/Program Files/Microsoft/jdk-17.0.18.8-hotspot/bin/java"
    fi

    if "$java_cmd" -version 2>&1 | grep -q 'version "1[7-9]\|version "2[0-9]'; then
        info "Java 17+ found: $("$java_cmd" -version 2>&1 | head -1)"
        return 0
    else
        warn "Java 17+ not detected. Audiveris requires Java 17 or later."
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Install Tesseract OCR language data (needed for text recognition)
# ---------------------------------------------------------------------------
install_tessdata() {
    info "Checking Tesseract OCR language data..."

    # Audiveris bundles Tesseract but needs language trained data.
    # The tessdata files go in the user's Audiveris config folder.
    local tessdata_dir

    if [ "$OS" = "windows" ]; then
        tessdata_dir="$APPDATA/AudiverisLtd/audiveris/config/tessdata"
    elif [ "$OS" = "macos" ]; then
        tessdata_dir="$HOME/Library/Application Support/AudiverisLtd/audiveris/config/tessdata"
    else
        tessdata_dir="$HOME/.config/AudiverisLtd/audiveris/config/tessdata"
    fi

    mkdir -p "$tessdata_dir"

    # Download English trained data if missing
    if [ ! -f "$tessdata_dir/eng.traineddata" ]; then
        info "Downloading Tesseract English language data..."
        local url="https://github.com/tesseract-ocr/tessdata_best/raw/main/eng.traineddata"
        if command -v curl &>/dev/null; then
            curl -L -o "$tessdata_dir/eng.traineddata" "$url"
        elif command -v wget &>/dev/null; then
            wget -O "$tessdata_dir/eng.traineddata" "$url"
        else
            warn "Neither curl nor wget available. Download manually:"
            warn "  $url -> $tessdata_dir/eng.traineddata"
            return 1
        fi
        info "Tesseract eng.traineddata installed at: $tessdata_dir"
    else
        info "Tesseract eng.traineddata already present."
    fi
}

# ---------------------------------------------------------------------------
# Install Audiveris
# ---------------------------------------------------------------------------
install_audiveris_windows() {
    info "Installing Audiveris on Windows..."

    if command -v winget &>/dev/null; then
        info "Using winget..."
        winget install Audiveris --accept-package-agreements --accept-source-agreements || true
    else
        local msi_url="https://github.com/Audiveris/audiveris/releases/download/${AUDIVERIS_VERSION}/Audiveris-${AUDIVERIS_VERSION}-windows-x86_64.msi"
        info "winget not found. Download the installer manually:"
        info "  $msi_url"
        info "Or install via scoop: scoop bucket add extras && scoop install audiveris"
        return 1
    fi
}

install_audiveris_linux() {
    info "Installing Audiveris on Linux..."

    # Detect Ubuntu version for correct .deb
    local ubuntu_ver
    ubuntu_ver=$(lsb_release -rs 2>/dev/null || echo "22.04")
    local deb_tag="ubuntu22.04"
    if [[ "$ubuntu_ver" == 24.* ]]; then
        deb_tag="ubuntu24.04"
    fi

    local deb_url="https://github.com/Audiveris/audiveris/releases/download/${AUDIVERIS_VERSION}/Audiveris-${AUDIVERIS_VERSION}-${deb_tag}-x86_64.deb"
    local deb_file="/tmp/audiveris-${AUDIVERIS_VERSION}.deb"

    info "Downloading: $deb_url"
    curl -L -o "$deb_file" "$deb_url"

    info "Installing .deb package (may require sudo)..."
    sudo dpkg -i "$deb_file" || sudo apt-get install -f -y
    rm -f "$deb_file"
}

install_audiveris_macos() {
    info "Installing Audiveris on macOS..."
    local dmg_url
    if [ "$(uname -m)" = "arm64" ]; then
        dmg_url="https://github.com/Audiveris/audiveris/releases/download/${AUDIVERIS_VERSION}/Audiveris-${AUDIVERIS_VERSION}-macosx-arm64.dmg"
    else
        dmg_url="https://github.com/Audiveris/audiveris/releases/download/${AUDIVERIS_VERSION}/Audiveris-${AUDIVERIS_VERSION}-macosx-x86_64.dmg"
    fi
    info "Download the installer:"
    info "  $dmg_url"
    info "Then drag Audiveris to /Applications."
}

# ---------------------------------------------------------------------------
# Docker fallback
# ---------------------------------------------------------------------------
setup_docker() {
    info "Setting up Docker-based Audiveris (Audiforge)..."
    if ! command -v docker &>/dev/null; then
        error "Docker is not installed. Install Docker Desktop first."
        return 1
    fi

    info "Pulling $DOCKER_IMAGE ..."
    docker pull "$DOCKER_IMAGE"
    info "Docker image ready. Use:  python convert.py --docker <input.pdf>"
}

# ---------------------------------------------------------------------------
# Create output directories
# ---------------------------------------------------------------------------
create_dirs() {
    mkdir -p "$REPO_ROOT/results/audiveris"
    info "Output directory ready: $REPO_ROOT/results/audiveris"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    echo "============================================"
    echo " Audiveris OMR Setup"
    echo " OS: $OS | Target version: $AUDIVERIS_VERSION"
    echo "============================================"
    echo ""

    # Parse args
    local mode="install"
    for arg in "$@"; do
        case "$arg" in
            --docker) mode="docker" ;;
            --check)  mode="check"  ;;
            --help|-h)
                echo "Usage: $0 [--check|--docker|--help]"
                exit 0
                ;;
        esac
    done

    # Check-only mode
    if [ "$mode" = "check" ]; then
        check_java || true
        check_audiveris || warn "Audiveris not found."
        exit 0
    fi

    # Docker-only mode
    if [ "$mode" = "docker" ]; then
        setup_docker
        create_dirs
        info "Done! Docker setup complete."
        exit 0
    fi

    # Full install
    check_java || warn "Install Java 17+ before running Audiveris."

    if check_audiveris; then
        info "Audiveris already installed -- skipping installation."
    else
        case "$OS" in
            windows) install_audiveris_windows ;;
            linux)   install_audiveris_linux   ;;
            macos)   install_audiveris_macos   ;;
            *)       error "Unsupported OS: $OS. Use --docker mode."; exit 1 ;;
        esac
    fi

    install_tessdata
    create_dirs

    echo ""
    info "Setup complete! Run a test conversion with:"
    info "  python tools/audiveris/convert.py test-scores/mozart-eine-kleine-viola.pdf"
    echo ""
}

main "$@"
