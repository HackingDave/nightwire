#!/bin/bash
#
# sidechannel installer
# Signal + Claude AI Bot
#
# Usage: ./install.sh [--skip-signal] [--skip-systemd] [--uninstall]
#

set -e

# Flush any buffered stdin (prevents stray Enter from skipping prompts)
flush_stdin() {
    while read -t 0.1 -n 10000 discard 2>/dev/null; do :; done
}

# Portable sed -i (BSD/macOS sed requires backup extension arg)
sed_inplace() {
    if sed --version 2>/dev/null | grep -q GNU; then
        sed -i "$@"
    else
        sed -i '' "$@"
    fi
}

# Wait for Signal bridge QR code endpoint to be ready.
# signal-cli inside the container needs time to fully initialize —
# /v1/about returns OK first, but qrcodelink may not work yet.
# The endpoint returns a PNG image on success, JSON error on failure.
# Returns 0 on success, 1 on failure. Sets QR_READY=true on success.
wait_for_qrcode() {
    local max_wait=${1:-90}
    local elapsed=0
    local qr_url="http://127.0.0.1:8080/v1/qrcodelink?device_name=sidechannel"
    QR_READY=false

    echo -ne "  Waiting for Signal bridge to initialize"

    while [ $elapsed -lt $max_wait ]; do
        # First check if container is even running
        if ! docker ps | grep -q signal-api; then
            echo ""
            return 1
        fi

        # Single GET request — check content-type from the response itself
        # Success: content-type contains "image" (PNG QR code)
        # Failure: content-type contains "json" (error like "no data to encode")
        local ctype
        ctype=$(curl -s -o /dev/null -w "%{content_type}" "$qr_url" 2>/dev/null || true)

        if echo "$ctype" | grep -qi "image"; then
            QR_READY=true
            echo ""
            return 0
        fi

        sleep 3
        elapsed=$((elapsed + 3))
        printf "."
    done

    echo ""
    return 1
}

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="${SIDECHANNEL_DIR:-$HOME/sidechannel}"
VENV_DIR="$INSTALL_DIR/venv"
CONFIG_DIR="$INSTALL_DIR/config"
DATA_DIR="$INSTALL_DIR/data"
LOGS_DIR="$INSTALL_DIR/logs"
SIGNAL_DATA_DIR="$INSTALL_DIR/signal-data"

# Flags
SKIP_SIGNAL=false
SKIP_SYSTEMD=false
UNINSTALL=false

# Parse arguments
for arg in "$@"; do
    case $arg in
        --skip-signal)
            SKIP_SIGNAL=true
            shift
            ;;
        --skip-systemd)
            SKIP_SYSTEMD=true
            shift
            ;;
        --uninstall)
            UNINSTALL=true
            shift
            ;;
        --help|-h)
            echo "Usage: ./install.sh [options]"
            echo ""
            echo "Options:"
            echo "  --skip-signal    Skip Signal pairing (configure later)"
            echo "  --skip-systemd   Skip service installation"
            echo "  --uninstall      Remove sidechannel service and containers"
            echo "  --help, -h       Show this help message"
            exit 0
            ;;
    esac
done

# =============================================================================
# UNINSTALL MODE
# =============================================================================
if [ "$UNINSTALL" = true ]; then
    echo ""
    echo -e "${CYAN}sidechannel uninstaller${NC}"
    echo ""

    REMOVED_SOMETHING=false

    # --- Stop and disable systemd service (Linux) ---
    if [ "$(uname)" = "Linux" ] && command -v systemctl &> /dev/null; then
        SERVICE_FILE="$HOME/.config/systemd/user/sidechannel.service"
        if systemctl --user is-active sidechannel &> /dev/null || [ -f "$SERVICE_FILE" ]; then
            echo -e "${BLUE}Removing systemd service...${NC}"
            systemctl --user stop sidechannel 2>/dev/null || true
            systemctl --user disable sidechannel 2>/dev/null || true
            rm -f "$SERVICE_FILE"
            systemctl --user daemon-reload
            echo -e "  ${GREEN}✓${NC} Service stopped and removed"
            REMOVED_SOMETHING=true
        fi
    fi

    # --- Stop and remove launchd service (macOS) ---
    if [ "$(uname)" = "Darwin" ]; then
        PLIST_FILE="$HOME/Library/LaunchAgents/com.sidechannel.bot.plist"
        if [ -f "$PLIST_FILE" ]; then
            echo -e "${BLUE}Removing launchd service...${NC}"
            launchctl unload "$PLIST_FILE" 2>/dev/null || true
            rm -f "$PLIST_FILE"
            echo -e "  ${GREEN}✓${NC} Service stopped and removed"
            REMOVED_SOMETHING=true
        fi
    fi

    # --- Stop Docker containers ---
    # Checks for legacy "sidechannel" container from older Docker installs
    if command -v docker &> /dev/null; then
        for CONTAINER in signal-api sidechannel; do
            if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
                echo -e "${BLUE}Stopping Docker container: ${CONTAINER}...${NC}"
                docker stop "$CONTAINER" 2>/dev/null || true
                docker rm "$CONTAINER" 2>/dev/null || true
                echo -e "  ${GREEN}✓${NC} Container $CONTAINER removed"
                REMOVED_SOMETHING=true
            fi
        done
    fi

    # --- Remove install directory (with confirmation) ---
    if [ -d "$INSTALL_DIR" ]; then
        echo ""
        echo -e "${YELLOW}The install directory contains your configuration and data:${NC}"
        echo -e "  ${CYAN}$INSTALL_DIR${NC}"
        echo ""
        echo "  This includes settings.yaml, .env (API keys), Signal data,"
        echo "  and any plugin data."
        echo ""
        read -p "Remove install directory? [y/N] " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$INSTALL_DIR"
            echo -e "  ${GREEN}✓${NC} Removed $INSTALL_DIR"
            REMOVED_SOMETHING=true
        else
            echo "  Kept $INSTALL_DIR"
        fi
    fi

    if [ "$REMOVED_SOMETHING" = true ]; then
        echo ""
        echo -e "${GREEN}sidechannel has been uninstalled.${NC}"
    else
        echo -e "${YELLOW}Nothing to uninstall.${NC} No service, containers, or install directory found."
        echo ""
        echo "  Expected install dir: $INSTALL_DIR"
        echo "  Set SIDECHANNEL_DIR if installed elsewhere."
    fi
    echo ""
    exit 0
fi

# Banner
echo -e "${CYAN}"
cat << 'EOF'
     _     _           _                            _
 ___(_) __| | ___  ___| |__   __ _ _ __  _ __   ___| |
/ __| |/ _` |/ _ \/ __| '_ \ / _` | '_ \| '_ \ / _ \ |
\__ \ | (_| |  __/ (__| | | | (_| | | | | | | |  __/ |
|___/_|\__,_|\___|\___|_| |_|\__,_|_| |_|_| |_|\___|_|

EOF
echo -e "${NC}"
echo -e "${GREEN}Signal + Claude AI Bot Installer${NC}"
echo ""

# -----------------------------------------------------------------------------
# Prerequisite checks
# -----------------------------------------------------------------------------
echo -e "${BLUE}Checking prerequisites...${NC}"

# Python 3.10+
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
    if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 10 ]); then
        echo -e "${RED}Error: Python 3.10+ required (found $PYTHON_VERSION)${NC}"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} Python $PYTHON_VERSION"
else
    echo -e "${RED}Error: Python 3 not found${NC}"
    exit 1
fi

# Claude CLI
if command -v claude &> /dev/null; then
    echo -e "  ${GREEN}✓${NC} Claude CLI"
elif [ -f "$HOME/.local/bin/claude" ]; then
    echo -e "  ${GREEN}✓${NC} Claude CLI ($HOME/.local/bin/claude)"
else
    echo -e "  ${YELLOW}!${NC} Claude CLI not found"
    echo -e "    sidechannel requires Claude CLI for code commands (/ask, /do, /complex)."
    echo -e "    Install: ${CYAN}https://docs.anthropic.com/en/docs/claude-code${NC}"
    read -p "    Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Docker (required for Signal bridge — one small container)
DOCKER_OK=false
if [ "$SKIP_SIGNAL" = true ]; then
    DOCKER_OK=true  # Don't need Docker if skipping Signal
elif command -v docker &> /dev/null; then
    if docker info &> /dev/null; then
        echo -e "  ${GREEN}✓${NC} Docker"
        DOCKER_OK=true
    else
        echo -e "  ${YELLOW}!${NC} Docker installed but not running"
        echo ""
        if [ "$(uname)" = "Darwin" ]; then
            echo -e "    Start Docker Desktop: ${CYAN}open -a Docker${NC}"
        else
            echo -e "    Start Docker: ${CYAN}sudo systemctl start docker${NC}"
        fi
        echo ""
        echo "    1) Wait — I'll start Docker now"
        echo "    2) Skip Signal setup for now"
        echo ""
        read -p "    > " DOCKER_WAIT_CHOICE
        echo ""
        if [ "$DOCKER_WAIT_CHOICE" = "2" ]; then
            SKIP_SIGNAL=true
            DOCKER_OK=true
        else
            flush_stdin
            read -p "    Press Enter when Docker is running..."
            echo ""
            echo -e "    Waiting for Docker..."
            TRIES=0
            while [ $TRIES -lt 30 ]; do
                if docker info &> /dev/null; then
                    break
                fi
                sleep 2
                TRIES=$((TRIES + 1))
            done
            if docker info &> /dev/null; then
                echo -e "  ${GREEN}✓${NC} Docker is running"
                DOCKER_OK=true
            else
                echo -e "  ${YELLOW}Docker still not ready.${NC} Skipping Signal setup."
                SKIP_SIGNAL=true
                DOCKER_OK=true
            fi
        fi
    fi
else
    echo -e "  ${YELLOW}!${NC} Docker not found"
    echo ""
    echo "    sidechannel needs one small Docker container for Signal messaging."
    echo ""
    if [ "$(uname)" = "Darwin" ]; then
        echo -e "    Install Docker Desktop: ${CYAN}https://docs.docker.com/desktop/install/mac-install/${NC}"
    elif command -v apt-get &> /dev/null; then
        read -p "    Install Docker now? [Y/n] " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            echo -e "  ${CYAN}Installing Docker...${NC}"
            sudo apt-get update -qq && sudo apt-get install -y -qq docker.io > /dev/null
            sudo usermod -aG docker "$USER" 2>/dev/null || true
            sudo systemctl start docker 2>/dev/null || true
            sudo systemctl enable docker 2>/dev/null || true
            if docker info &> /dev/null; then
                echo -e "  ${GREEN}✓${NC} Docker installed"
                DOCKER_OK=true
            else
                echo -e "  ${YELLOW}!${NC} Docker installed but may need a re-login for group permissions"
                echo "    Run: ${CYAN}newgrp docker${NC} then re-run this installer"
                exit 1
            fi
        fi
    elif command -v dnf &> /dev/null; then
        read -p "    Install Docker now? [Y/n] " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            echo -e "  ${CYAN}Installing Docker...${NC}"
            sudo dnf install -y -q docker > /dev/null
            sudo usermod -aG docker "$USER" 2>/dev/null || true
            sudo systemctl start docker 2>/dev/null || true
            sudo systemctl enable docker 2>/dev/null || true
            if docker info &> /dev/null; then
                echo -e "  ${GREEN}✓${NC} Docker installed"
                DOCKER_OK=true
            else
                echo -e "  ${YELLOW}!${NC} Docker installed but may need a re-login for group permissions"
                echo "    Run: ${CYAN}newgrp docker${NC} then re-run this installer"
                exit 1
            fi
        fi
    else
        echo -e "    Install Docker: ${CYAN}https://docs.docker.com/get-docker/${NC}"
    fi

    if [ "$DOCKER_OK" = false ]; then
        echo ""
        read -p "    Skip Signal setup and continue? [y/N] " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            SKIP_SIGNAL=true
            DOCKER_OK=true
        else
            echo ""
            echo "  Install Docker, then re-run this installer."
            exit 1
        fi
    fi
fi

echo ""

# -----------------------------------------------------------------------------
# Create directory structure
# -----------------------------------------------------------------------------
echo -e "${BLUE}Creating directory structure...${NC}"

mkdir -p "$INSTALL_DIR"
mkdir -p "$CONFIG_DIR"
mkdir -p "$DATA_DIR"
mkdir -p "$LOGS_DIR"
mkdir -p "$SIGNAL_DATA_DIR"

echo -e "  ${GREEN}✓${NC} Created $INSTALL_DIR"

# -----------------------------------------------------------------------------
# Copy source files
# -----------------------------------------------------------------------------
echo -e "${BLUE}Copying source files...${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Copy Python package
if [ -d "$SCRIPT_DIR/sidechannel" ]; then
    cp -r "$SCRIPT_DIR/sidechannel" "$INSTALL_DIR/"
    echo -e "  ${GREEN}✓${NC} Copied sidechannel package"
else
    echo -e "${RED}Error: sidechannel package not found in $SCRIPT_DIR${NC}"
    exit 1
fi

# Copy plugins if present
if [ -d "$SCRIPT_DIR/plugins" ]; then
    cp -r "$SCRIPT_DIR/plugins" "$INSTALL_DIR/"
    echo -e "  ${GREEN}✓${NC} Copied plugins"
fi

# Copy config templates
if [ -d "$SCRIPT_DIR/config" ]; then
    cp "$SCRIPT_DIR/config/"*.example "$CONFIG_DIR/" 2>/dev/null || true
    cp "$SCRIPT_DIR/config/CLAUDE.md" "$CONFIG_DIR/" 2>/dev/null || true
    echo -e "  ${GREEN}✓${NC} Copied config templates"
fi

# Copy requirements
cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"

# Copy docker-compose for Signal bridge
cp "$SCRIPT_DIR/docker-compose.yml" "$INSTALL_DIR/" 2>/dev/null || true

# -----------------------------------------------------------------------------
# Create virtual environment
# -----------------------------------------------------------------------------
echo -e "${BLUE}Setting up Python environment...${NC}"

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo -e "  ${GREEN}✓${NC} Virtual environment created"
fi

source "$VENV_DIR/bin/activate"

if "$VENV_DIR/bin/pip" freeze 2>/dev/null | grep -q aiohttp; then
    echo -e "  ${GREEN}✓${NC} Dependencies already installed"
else
    pip install --upgrade pip -q
    pip install -r "$INSTALL_DIR/requirements.txt" -q
    echo -e "  ${GREEN}✓${NC} Dependencies installed"
fi

# -----------------------------------------------------------------------------
# Interactive configuration
# -----------------------------------------------------------------------------
echo ""
echo -e "${BLUE}Configuration${NC}"
echo ""

# Create settings.yaml from template
SETTINGS_FILE="$CONFIG_DIR/settings.yaml"
if [ ! -f "$SETTINGS_FILE" ]; then
    if [ -f "$CONFIG_DIR/settings.yaml.example" ]; then
        cp "$CONFIG_DIR/settings.yaml.example" "$SETTINGS_FILE"
    else
        cat > "$SETTINGS_FILE" << 'YAML'
# sidechannel configuration

# Phone numbers authorized to use the bot (E.164 format)
allowed_numbers:
  - "+1XXXXXXXXXX"  # Replace with your number

# Signal CLI REST API
signal_api_url: "http://127.0.0.1:8080"

# Memory System
memory:
  session_timeout: 30
  max_context_tokens: 1500

# Autonomous Tasks
autonomous:
  enabled: true
  poll_interval: 30
  quality_gates: true

# Optional: sidechannel AI assistant (OpenAI or Grok)
sidechannel_assistant:
  enabled: false
YAML
    fi
fi

# Get phone number
echo -e "  Enter your phone number (e.g., +15551234567):"
read -p "  > " PHONE_NUMBER

if [ -n "$PHONE_NUMBER" ]; then
    if [[ ! "$PHONE_NUMBER" =~ ^\+[1-9][0-9]{6,14}$ ]]; then
        echo -e "  ${YELLOW}Warning: doesn't look like E.164 format (e.g., +15551234567)${NC}"
        read -p "  Continue anyway? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "  Please re-run the installer with a valid phone number."
            exit 1
        fi
    fi
    sed_inplace "s/+1XXXXXXXXXX/$PHONE_NUMBER/" "$SETTINGS_FILE"
    echo -e "  ${GREEN}✓${NC} Phone number set"
fi

# Create .env file
ENV_FILE="$CONFIG_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" << EOF
# sidechannel environment variables

# Optional: OpenAI API key (for sidechannel AI assistant)
# OPENAI_API_KEY=

# Optional: Grok API key (for sidechannel AI assistant)
# GROK_API_KEY=
EOF
fi

# Optional AI assistant
echo ""
read -p "  Enable AI assistant (OpenAI or Grok)? [y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sed_inplace "s/enabled: false/enabled: true/" "$SETTINGS_FILE"
    echo ""
    echo "    Which provider? (1) OpenAI  (2) Grok"
    read -p "    > " PROVIDER_CHOICE
    echo ""
    if [ "$PROVIDER_CHOICE" = "1" ]; then
        echo -e "  Enter your OpenAI API key:"
        read -p "  > " -s OPENAI_KEY
        echo ""
        if [ -n "$OPENAI_KEY" ]; then
            sed_inplace "s/^# OPENAI_API_KEY=.*/OPENAI_API_KEY=$OPENAI_KEY/" "$ENV_FILE"
            echo -e "  ${GREEN}✓${NC} OpenAI configured"
        fi
    else
        echo -e "  Enter your Grok API key:"
        read -p "  > " -s GROK_KEY
        echo ""
        if [ -n "$GROK_KEY" ]; then
            sed_inplace "s/^# GROK_API_KEY=.*/GROK_API_KEY=$GROK_KEY/" "$ENV_FILE"
            echo -e "  ${GREEN}✓${NC} Grok configured"
        fi
    fi
fi

# -----------------------------------------------------------------------------
# Signal Pairing — automatic, no choices
# -----------------------------------------------------------------------------
SIGNAL_PAIRED=false

if [ "$SKIP_SIGNAL" = false ]; then
    echo ""
    echo -e "${BLUE}Signal Pairing${NC}"
    echo ""

    # Start Signal bridge container
    mkdir -p "$SIGNAL_DATA_DIR"

    echo -e "  Starting Signal bridge..."

    # Ask about remote access for QR code scanning
    SIGNAL_BIND="127.0.0.1"
    REMOTE_MODE=false
    if [ -n "$SSH_CONNECTION" ]; then
        echo -e "  ${YELLOW}Remote session detected.${NC}"
        echo ""
    fi
    read -p "  Will you scan the QR code from another device (e.g., SSH'd in)? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        REMOTE_MODE=true
        SIGNAL_BIND="0.0.0.0"
        echo -e "  Signal bridge will be temporarily exposed on all interfaces."
        echo -e "  It will be locked to localhost after pairing."
        echo ""
    fi

    if [ "$SKIP_SIGNAL" = false ]; then
        docker stop signal-api 2>/dev/null || true
        docker rm signal-api 2>/dev/null || true

        docker run -d \
            --name signal-api \
            --restart unless-stopped \
            -p "$SIGNAL_BIND:8080:8080" \
            -v "$SIGNAL_DATA_DIR:/home/.local/share/signal-cli" \
            -e MODE=native \
            bbernhard/signal-cli-rest-api:latest

        if ! docker ps | grep -q signal-api; then
            echo -e "  ${RED}Signal bridge failed to start${NC}"
            docker logs signal-api 2>&1 | tail -5
            echo ""
            echo -e "  You can re-run the installer later to set up Signal."
        elif wait_for_qrcode 90; then
            echo ""
            echo -e "  ${GREEN}✓${NC} Signal bridge ready"
            echo ""

            # --- Device linking ---
            echo -e "  ${GREEN}Link your phone to sidechannel:${NC}"
            echo ""
            echo "    1. Open this URL in your browser to see the QR code:"
            echo ""
            if [ "$REMOTE_MODE" = true ]; then
                SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
                [ -z "$SERVER_IP" ] && SERVER_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "<your-server-ip>")
                echo -e "       ${CYAN}http://${SERVER_IP}:8080/v1/qrcodelink?device_name=sidechannel${NC}"
            else
                echo -e "       ${CYAN}http://127.0.0.1:8080/v1/qrcodelink?device_name=sidechannel${NC}"
            fi
            echo ""
            echo "    2. Open Signal on your phone"
            echo "    3. Settings > Linked Devices > Link New Device"
            echo "    4. Scan the QR code from your browser"
            echo ""
            flush_stdin
            read -p "  Press Enter after scanning the QR code..."

            echo ""
            echo -e "  Verifying link..."
            sleep 3

            ACCOUNTS=$(curl -s "http://127.0.0.1:8080/v1/accounts" 2>/dev/null)
            if echo "$ACCOUNTS" | grep -q "+"; then
                LINKED_NUMBER=$(echo "$ACCOUNTS" | grep -o '+[0-9]*' | head -1)
                echo -e "  ${GREEN}✓${NC} Device linked: $LINKED_NUMBER"

                if [ "$LINKED_NUMBER" != "$PHONE_NUMBER" ] && [ -n "$LINKED_NUMBER" ]; then
                    sed_inplace "s/$PHONE_NUMBER/$LINKED_NUMBER/" "$SETTINGS_FILE" 2>/dev/null || true
                fi
                SIGNAL_PAIRED=true
            else
                echo -e "  ${YELLOW}Could not verify link.${NC}"
                echo -e "  Check: ${CYAN}http://127.0.0.1:8080/v1/accounts${NC}"
                echo ""
                echo "  You may need to wait a moment and try scanning again."
                flush_stdin
                read -p "  Retry verification? [Y/n] " -n 1 -r
                echo ""
                if [[ ! $REPLY =~ ^[Nn]$ ]]; then
                    sleep 3
                    ACCOUNTS=$(curl -s "http://127.0.0.1:8080/v1/accounts" 2>/dev/null)
                    if echo "$ACCOUNTS" | grep -q "+"; then
                        LINKED_NUMBER=$(echo "$ACCOUNTS" | grep -o '+[0-9]*' | head -1)
                        echo -e "  ${GREEN}✓${NC} Device linked: $LINKED_NUMBER"
                        if [ "$LINKED_NUMBER" != "$PHONE_NUMBER" ] && [ -n "$LINKED_NUMBER" ]; then
                            sed_inplace "s/$PHONE_NUMBER/$LINKED_NUMBER/" "$SETTINGS_FILE" 2>/dev/null || true
                        fi
                        SIGNAL_PAIRED=true
                    else
                        echo -e "  ${YELLOW}Still not verified. You can pair later via:${NC}"
                        echo -e "    ${CYAN}http://127.0.0.1:8080/v1/qrcodelink?device_name=sidechannel${NC}"
                    fi
                fi
            fi
        else
            echo ""
            echo -e "  ${YELLOW}Signal bridge is taking too long to initialize.${NC}"
            echo ""
            echo "  This can happen on first run. Try these troubleshooting steps:"
            echo "    1. Check container logs: docker logs signal-api"
            echo "    2. Restart the container: docker restart signal-api"
            echo "    3. Wait a minute, then open in browser:"
            echo -e "       ${CYAN}http://127.0.0.1:8080/v1/qrcodelink?device_name=sidechannel${NC}"
            echo ""
            echo "  The install will continue — you can pair later."

            # Lock down to localhost if remote mode was used
            if [ "$REMOTE_MODE" = true ]; then
                echo -e "  Securing Signal bridge to localhost..."
                docker stop signal-api 2>/dev/null || true
                docker rm signal-api 2>/dev/null || true

                docker run -d \
                    --name signal-api \
                    --restart unless-stopped \
                    -p 127.0.0.1:8080:8080 \
                    -v "$SIGNAL_DATA_DIR:/home/.local/share/signal-cli" \
                    -e MODE=native \
                    bbernhard/signal-cli-rest-api:latest

                sleep 3
                if docker ps | grep -q signal-api; then
                    echo -e "  ${GREEN}✓${NC} Signal bridge secured (localhost only)"
                fi
            fi
        fi
    fi
fi

# -----------------------------------------------------------------------------
# Auto-start service
# -----------------------------------------------------------------------------
INSTALLED_SERVICE=false
STARTED_SERVICE=false

# Create run script (always, as a fallback)
RUN_SCRIPT="$INSTALL_DIR/run.sh"
cat > "$RUN_SCRIPT" << EOF
#!/bin/bash
# Start sidechannel
cd "$INSTALL_DIR"
source "$VENV_DIR/bin/activate"
source "$CONFIG_DIR/.env"
python -m sidechannel
EOF
chmod +x "$RUN_SCRIPT"

if [ "$SKIP_SYSTEMD" = false ]; then
    echo ""

    if [ "$(uname)" = "Linux" ] && command -v systemctl &> /dev/null; then
        # --- Linux: systemd service ---
        read -p "Start sidechannel as a service (auto-starts on boot)? [Y/n] " -n 1 -r
        echo ""

        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            SERVICE_FILE="$HOME/.config/systemd/user/sidechannel.service"
            mkdir -p "$HOME/.config/systemd/user"

            cat > "$SERVICE_FILE" << EOF
[Unit]
Description=sidechannel - Signal Claude Bot
After=network.target docker.service

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=$CONFIG_DIR/.env
ExecStart=$VENV_DIR/bin/python -m sidechannel
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF

            systemctl --user daemon-reload
            systemctl --user enable sidechannel
            loginctl enable-linger "$USER" 2>/dev/null || true

            INSTALLED_SERVICE=true
            echo -e "  ${GREEN}✓${NC} Service installed and enabled"

            # Start it now
            systemctl --user start sidechannel 2>/dev/null
            sleep 2
            if systemctl --user is-active sidechannel &>/dev/null; then
                echo -e "  ${GREEN}✓${NC} sidechannel is running!"
                STARTED_SERVICE=true
            else
                echo -e "  ${YELLOW}Service installed but not started yet.${NC}"
                echo -e "  Start with: ${CYAN}systemctl --user start sidechannel${NC}"
            fi
        fi

    elif [ "$(uname)" = "Darwin" ]; then
        # --- macOS: launchd plist ---
        read -p "Start sidechannel as a service (auto-starts on login)? [Y/n] " -n 1 -r
        echo ""

        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            PLIST_DIR="$HOME/Library/LaunchAgents"
            PLIST_FILE="$PLIST_DIR/com.sidechannel.bot.plist"
            mkdir -p "$PLIST_DIR"

            cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.sidechannel.bot</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV_DIR/bin/python</string>
        <string>-m</string>
        <string>sidechannel</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOGS_DIR/sidechannel.log</string>
    <key>StandardErrorPath</key>
    <string>$LOGS_DIR/sidechannel.err</string>
</dict>
</plist>
EOF

            INSTALLED_SERVICE=true
            echo -e "  ${GREEN}✓${NC} Service installed"

            # Load .env into the plist environment
            if [ -f "$ENV_FILE" ]; then
                while IFS='=' read -r key value; do
                    [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
                    # Strip surrounding whitespace
                    key=$(echo "$key" | xargs)
                    value=$(echo "$value" | xargs)
                    [ -n "$value" ] && launchctl setenv "$key" "$value" 2>/dev/null || true
                done < "$ENV_FILE"
            fi

            launchctl unload "$PLIST_FILE" 2>/dev/null || true
            launchctl load "$PLIST_FILE" 2>/dev/null

            sleep 2
            if launchctl list | grep -q com.sidechannel.bot; then
                echo -e "  ${GREEN}✓${NC} sidechannel is running!"
                STARTED_SERVICE=true
            else
                echo -e "  ${YELLOW}Service installed but not started yet.${NC}"
                echo -e "  Start with: ${CYAN}launchctl load $PLIST_FILE${NC}"
            fi
        fi
    fi
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo ""
if [ "$SIGNAL_PAIRED" = true ] && [ "$STARTED_SERVICE" = true ]; then
    # Everything worked — clean success
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                  sidechannel is ready!                         ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  Send a message to ${CYAN}${LINKED_NUMBER:-your Signal number}${NC} to test!"
    echo -e "  Try: ${CYAN}/help${NC}"
    echo ""
    if [ "$(uname)" = "Linux" ]; then
        echo -e "  View logs:  ${CYAN}journalctl --user -u sidechannel -f${NC}"
        echo -e "  Stop:       ${CYAN}systemctl --user stop sidechannel${NC}"
        echo -e "  Restart:    ${CYAN}systemctl --user restart sidechannel${NC}"
    elif [ "$(uname)" = "Darwin" ]; then
        echo -e "  View logs:  ${CYAN}tail -f $LOGS_DIR/sidechannel.log${NC}"
        echo -e "  Stop:       ${CYAN}launchctl unload ~/Library/LaunchAgents/com.sidechannel.bot.plist${NC}"
        echo -e "  Restart:    ${CYAN}launchctl unload ~/Library/LaunchAgents/com.sidechannel.bot.plist && launchctl load ~/Library/LaunchAgents/com.sidechannel.bot.plist${NC}"
    fi
else
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║              sidechannel installation complete!                ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  Install dir: ${CYAN}$INSTALL_DIR${NC}"
    echo -e "  Config:      ${CYAN}$CONFIG_DIR/settings.yaml${NC}"

    # Only show remaining steps
    STEP=1

    if ! command -v claude &> /dev/null && ! [ -f "$HOME/.local/bin/claude" ]; then
        echo ""
        echo -e "  ${STEP}. Install Claude CLI: ${CYAN}https://docs.anthropic.com/en/docs/claude-code${NC}"
        STEP=$((STEP + 1))
    fi

    if [ "$SIGNAL_PAIRED" = false ] && [ "$SKIP_SIGNAL" = true ]; then
        echo ""
        echo "  $STEP. Set up Signal (re-run installer without --skip-signal)"
        STEP=$((STEP + 1))
    fi

    if [ "$STARTED_SERVICE" = false ]; then
        echo ""
        echo -e "  $STEP. Start sidechannel: ${CYAN}$RUN_SCRIPT${NC}"
        STEP=$((STEP + 1))
    fi

    echo ""
    echo -e "  Send a test message on Signal: ${CYAN}/help${NC}"
fi

echo ""
echo -e "  Config:  ${CYAN}$CONFIG_DIR/settings.yaml${NC}"
echo -e "  Docs:    ${CYAN}https://github.com/hackingdave/sidechannel${NC}"
echo ""
