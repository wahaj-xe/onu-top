#!/usr/bin/env bash
# ==============================================================================
# onu-top Automated Installer for macOS (Apple Silicon M1/M2/M3/M4 & Intel) & Linux
# Execution:
#   curl -fsSL https://raw.githubusercontent.com/wahaj-xe/onu-top/main/install.sh | bash
# ==============================================================================

set -e

OS="$(uname -s)"
ARCH="$(uname -m)"

echo ""
echo "+--------------------------------------------------------------+"
if [ "$OS" = "Darwin" ]; then
    if [ "$ARCH" = "arm64" ]; then
        echo "|       onu-top Installer (Apple Silicon macOS - arm64)        |"
    else
        echo "|            onu-top Installer (macOS - x86_64)                |"
    fi
else
    echo "|                onu-top Installer (Linux / Unix)              |"
fi
echo "|         Lightweight btop-style Live Performance Dashboard    |"
echo "+--------------------------------------------------------------+"
echo ""

# ------------------------------------------------------------------------------
# 1. Check Prerequisites: Python 3.8+
# ------------------------------------------------------------------------------
echo "[1/4] Checking Python 3 prerequisite..."
PYTHON_BIN=""

for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ -n "$MAJOR" ] && [ -n "$MINOR" ] && [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 8 ]; then
            PYTHON_BIN="$cmd"
            echo "  [OK] Python found: $cmd ($VER)"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "  [!] Python 3 is required to run onu-top, but was not detected."
    read -p "  Would you like this script to automatically install Python now? [Y/n]: " -r DO_INSTALL </dev/tty || DO_INSTALL="Y"
    DO_INSTALL=${DO_INSTALL:-Y}
    if [[ "$DO_INSTALL" =~ ^[Yy]$ ]]; then
        echo "  [+] Starting automated Python 3 installation..."
        if [ "$OS" = "Darwin" ]; then
            if command -v brew >/dev/null 2>&1; then
                echo "      Installing Python 3 via Homebrew..."
                brew install python3
                PYTHON_BIN="python3"
            else
                echo "      Homebrew not found. Downloading official macOS Universal Python installer..."
                PKG_URL="https://www.python.org/ftp/python/3.12.3/python-3.12.3-macos11.pkg"
                curl -fsSL "$PKG_URL" -o /tmp/python-3.12.pkg
                echo "      Running macOS installer (administrator password may be required)..."
                sudo installer -pkg /tmp/python-3.12.pkg -target /
                rm -f /tmp/python-3.12.pkg
                PYTHON_BIN="/usr/local/bin/python3"
            fi
        else
            # Linux
            if command -v apt-get >/dev/null 2>&1; then
                sudo apt-get update && sudo apt-get install -y python3
                PYTHON_BIN="python3"
            elif command -v dnf >/dev/null 2>&1; then
                sudo dnf install -y python3
                PYTHON_BIN="python3"
            elif command -v pacman >/dev/null 2>&1; then
                sudo pacman -Sy --noconfirm python
                PYTHON_BIN="python3"
            else
                echo "  [X] Package manager not recognized. Please install Python 3 manually."
                exit 1
            fi
        fi
        echo "  [OK] Python installed successfully!"
    else
        echo "------------------------------------------------------------"
        echo "  PREREQUISITE REQUIRED:"
        echo "  Please install Python 3.9+ manually:"
        echo "    * macOS: brew install python3"
        echo "    * Download: https://www.python.org/downloads/"
        echo "------------------------------------------------------------"
        exit 1
    fi
fi

# ------------------------------------------------------------------------------
# 2. Setup Target Directory
# ------------------------------------------------------------------------------
echo "[2/4] Setting up installation directory..."
INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"
echo "  Directory: $INSTALL_DIR"

TARGET_SCRIPT="$INSTALL_DIR/huawei_ont_top.py"
REPO_URL="https://raw.githubusercontent.com/wahaj-xe/onu-top/main/huawei_ont_top.py"

echo "  Downloading huawei_ont_top.py from GitHub..."
curl -fsSL "$REPO_URL" -o "$TARGET_SCRIPT"
chmod +x "$TARGET_SCRIPT"
echo "  [OK] huawei_ont_top.py installed."

# ------------------------------------------------------------------------------
# 3. Create Launcher Shim & Configure PATH
# ------------------------------------------------------------------------------
echo "[3/4] Configuring command launcher and PATH..."
LAUNCHER="$INSTALL_DIR/onu-top"
cat << 'EOF' > "$LAUNCHER"
#!/usr/bin/env sh
DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$DIR/huawei_ont_top.py" "$@"
EOF
chmod +x "$LAUNCHER"

# Add ~/.local/bin to shell profiles if missing
for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
    if [ -f "$rc" ]; then
        if ! grep -q '\.local/bin' "$rc"; then
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$rc"
        fi
    fi
done
export PATH="$HOME/.local/bin:$PATH"
echo "  [OK] Created launcher '$LAUNCHER'."

# ------------------------------------------------------------------------------
# 4. Completion & Verification
# ------------------------------------------------------------------------------
echo "[4/4] Finalizing..."
echo ""
echo "================================================================"
echo "  SUCCESS: onu-top is installed and ready to use!"
echo "================================================================"
echo ""
echo "  To run it, open any terminal and type:"
echo "      onu-top"
echo ""
echo "  Important Prerequisites Reminder:"
echo "   * Ensure Telnet access is enabled on your Huawei ONT"
echo "     (Web GUI: Security / Maintenance -> Device Access Control)"
echo "   * Have your ONT IP (e.g. 192.168.18.1), Telnet user, and password ready."
echo ""

if [ -t 0 ] || [ -c /dev/tty ]; then
    read -p "Would you like to launch onu-top now? [Y/n]: " -r RUN_NOW </dev/tty || RUN_NOW="n"
    RUN_NOW=${RUN_NOW:-Y}
    if [[ "$RUN_NOW" =~ ^[Yy]$ ]]; then
        exec "$LAUNCHER"
    fi
fi
