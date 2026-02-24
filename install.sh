#!/bin/bash
#
# sidechannel installer
# Signal + Claude AI Bot
#
# Usage: ./install.sh [--skip-signal] [--skip-systemd] [--docker] [--local]
#

set -e

# Portable sed -i (BSD/macOS sed requires backup extension arg)
sed_inplace() {
    if sed --version 2>/dev/null | grep -q GNU; then
        sed -i "$@"
    else
        sed -i '' "$@"
    fi
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
INSTALL_MODE=""

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
        --docker)
            INSTALL_MODE="docker"
            shift
            ;;
        --local)
            INSTALL_MODE="local"
            shift
            ;;
        --help|-h)
            echo "Usage: ./install.sh [options]"
            echo ""
            echo "Options:"
            echo "  --docker         Install using Docker (recommended)"
            echo "  --local          Install using local Python venv"
            echo "  --skip-signal    Skip Signal CLI REST API setup (local mode)"
            echo "  --skip-systemd   Skip systemd service installation (local mode)"
            echo "  --help, -h       Show this help message"
            exit 0
            ;;
    esac
done

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
# Install mode selection
# -----------------------------------------------------------------------------
if [ -z "$INSTALL_MODE" ]; then
    echo -e "${BLUE}How would you like to install?${NC}"
    echo ""
    echo "  1) Docker (recommended) — everything runs in containers"
    echo "  2) Local  — Python venv with optional systemd service"
    echo ""
    read -p "> " INSTALL_CHOICE
    case "$INSTALL_CHOICE" in
        1|docker|Docker)
            INSTALL_MODE="docker"
            ;;
        2|local|Local)
            INSTALL_MODE="local"
            ;;
        *)
            INSTALL_MODE="docker"
            echo -e "  Defaulting to Docker install."
            ;;
    esac
    echo ""
fi

# =============================================================================
# DOCKER INSTALL MODE
# =============================================================================
if [ "$INSTALL_MODE" = "docker" ]; then

    # -------------------------------------------------------------------------
    # Docker prerequisites
    # -------------------------------------------------------------------------
    echo -e "${BLUE}Checking prerequisites...${NC}"

    if ! command -v docker &> /dev/null; then
        echo -e "${RED}Error: Docker not found${NC}"
        echo -e "Install Docker: https://docs.docker.com/get-docker/"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} Docker"

    if ! docker info &> /dev/null; then
        echo -e "${RED}Error: Docker daemon is not running${NC}"
        echo -e "Start Docker: sudo systemctl start docker"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} Docker daemon running"

    # Check for docker compose (v2 plugin or standalone)
    if docker compose version &> /dev/null; then
        COMPOSE_CMD="docker compose"
    elif command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="docker-compose"
    else
        echo -e "${RED}Error: Docker Compose not found${NC}"
        echo -e "Install Docker Compose: https://docs.docker.com/compose/install/"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} Docker Compose"
    echo ""

    # -------------------------------------------------------------------------
    # Create directory structure
    # -------------------------------------------------------------------------
    echo -e "${BLUE}Creating directory structure...${NC}"

    mkdir -p "$INSTALL_DIR"
    mkdir -p "$CONFIG_DIR"
    mkdir -p "$DATA_DIR"
    mkdir -p "$LOGS_DIR"
    mkdir -p "$SIGNAL_DATA_DIR"

    echo -e "  ${GREEN}✓${NC} Created $INSTALL_DIR"

    # -------------------------------------------------------------------------
    # Copy source files
    # -------------------------------------------------------------------------
    echo -e "${BLUE}Copying source files...${NC}"

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

    cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"

    # Copy Docker files
    cp "$SCRIPT_DIR/Dockerfile" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/docker-compose.yml" "$INSTALL_DIR/"
    echo -e "  ${GREEN}✓${NC} Copied Docker files"

    # Copy config templates
    if [ -d "$SCRIPT_DIR/config" ]; then
        cp "$SCRIPT_DIR/config/"*.example "$CONFIG_DIR/" 2>/dev/null || true
        cp "$SCRIPT_DIR/config/CLAUDE.md" "$CONFIG_DIR/" 2>/dev/null || true
        echo -e "  ${GREEN}✓${NC} Copied config templates"
    fi

    # -------------------------------------------------------------------------
    # Interactive configuration (same prompts, with fixed sed)
    # -------------------------------------------------------------------------
    echo ""
    echo -e "${BLUE}Configuration${NC}"
    echo ""

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

# Signal CLI REST API (container name resolves via Docker network)
signal_api_url: "http://signal-api:8080"

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

    echo -e "Enter your phone number in E.164 format (e.g., +15551234567):"
    read -p "> " PHONE_NUMBER

    if [ -n "$PHONE_NUMBER" ]; then
        if [[ ! "$PHONE_NUMBER" =~ ^\+[1-9][0-9]{6,14}$ ]]; then
            echo -e "${YELLOW}Warning: Phone number doesn't appear to be in E.164 format${NC}"
            read -p "Continue anyway? [y/N] " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                echo "Please re-run the installer with a valid phone number."
                exit 1
            fi
        fi
        sed_inplace "s/+1XXXXXXXXXX/$PHONE_NUMBER/" "$SETTINGS_FILE"
        echo -e "  ${GREEN}✓${NC} Phone number configured"
    fi

    ENV_FILE="$CONFIG_DIR/.env"
    if [ ! -f "$ENV_FILE" ]; then
        cat > "$ENV_FILE" << EOF
# sidechannel environment variables

# Anthropic API key (required for Claude)
ANTHROPIC_API_KEY=

# Optional: Grok API key
# GROK_API_KEY=
EOF
    fi

    echo ""
    echo -e "Enter your Anthropic API key (or press Enter to set later):"
    read -p "> " -s ANTHROPIC_KEY
    echo ""

    if [ -n "$ANTHROPIC_KEY" ]; then
        sed_inplace "s/^ANTHROPIC_API_KEY=.*/ANTHROPIC_API_KEY=$ANTHROPIC_KEY/" "$ENV_FILE"
        echo -e "  ${GREEN}✓${NC} API key configured"
    fi

    echo ""
    read -p "Enable sidechannel AI assistant (OpenAI or Grok)? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        sed_inplace "s/enabled: false/enabled: true/" "$SETTINGS_FILE"
        echo -e "Enter your Grok API key:"
        read -p "> " -s GROK_KEY
        echo ""
        if [ -n "$GROK_KEY" ]; then
            sed_inplace "s/^# GROK_API_KEY=.*/GROK_API_KEY=$GROK_KEY/" "$ENV_FILE"
            echo -e "  ${GREEN}✓${NC} Grok enabled and configured"
        fi
    fi

    # -------------------------------------------------------------------------
    # Signal device linking (Docker mode)
    # -------------------------------------------------------------------------
    echo ""
    echo -e "${BLUE}Signal Device Linking${NC}"
    echo ""

    read -p "Set up Signal device linking now? [Y/n] " -n 1 -r
    echo ""

    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        echo -e "${CYAN}Starting Signal container for device linking...${NC}"

        docker stop signal-api 2>/dev/null || true
        docker rm signal-api 2>/dev/null || true

        docker run -d \
            --name signal-api \
            --restart unless-stopped \
            -p "127.0.0.1:8080:8080" \
            -v "$SIGNAL_DATA_DIR:/home/.local/share/signal-cli" \
            -e MODE=native \
            bbernhard/signal-cli-rest-api:0.80

        echo "Waiting for container to start..."
        sleep 5

        if ! docker ps | grep -q signal-api; then
            echo -e "${RED}Error: Signal container failed to start${NC}"
            docker logs signal-api 2>&1 | tail -10
            exit 1
        fi

        echo ""
        echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║                   SIGNAL DEVICE LINKING                        ║${NC}"
        echo -e "${GREEN}╠════════════════════════════════════════════════════════════════╣${NC}"
        echo -e "${GREEN}║                                                                ║${NC}"
        echo -e "${GREEN}║  1. Open Signal on your phone                                  ║${NC}"
        echo -e "${GREEN}║  2. Go to Settings > Linked Devices                            ║${NC}"
        echo -e "${GREEN}║  3. Tap 'Link New Device'                                      ║${NC}"
        echo -e "${GREEN}║  4. Scan the QR code at the URL below                          ║${NC}"
        echo -e "${GREEN}║                                                                ║${NC}"
        echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
        echo ""
        echo "  QR code: http://127.0.0.1:8080/v1/qrcodelink?device_name=sidechannel"
        echo ""

        LINK_URI=$(curl -s "http://127.0.0.1:8080/v1/qrcodelink?device_name=sidechannel" | grep -o 'sgnl://[^"]*' 2>/dev/null || true)

        if command -v qrencode &> /dev/null && [ -n "$LINK_URI" ]; then
            echo -e "${GREEN}Terminal QR Code:${NC}"
            echo ""
            echo "$LINK_URI" | qrencode -t ANSIUTF8
            echo ""
        fi

        read -p "Press Enter after you've scanned the QR code and linked the device..."

        echo ""
        echo -e "${CYAN}Verifying device link...${NC}"
        sleep 2

        # Stop the linking container — docker compose will manage it
        docker stop signal-api 2>/dev/null || true
        docker rm signal-api 2>/dev/null || true
        echo -e "  ${GREEN}✓${NC} Signal device linked"
    fi

    # -------------------------------------------------------------------------
    # Build and start containers
    # -------------------------------------------------------------------------
    echo ""
    echo -e "${BLUE}Building and starting containers...${NC}"

    cd "$INSTALL_DIR"
    $COMPOSE_CMD build
    $COMPOSE_CMD up -d

    echo ""
    echo -e "  ${GREEN}✓${NC} Containers started"
    echo ""

    # -------------------------------------------------------------------------
    # Docker summary
    # -------------------------------------------------------------------------
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║              sidechannel installation complete!                ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "Installation directory: ${CYAN}$INSTALL_DIR${NC}"
    echo ""
    echo -e "${YELLOW}Useful commands:${NC}"
    echo ""
    echo "  View logs:          $COMPOSE_CMD -f $INSTALL_DIR/docker-compose.yml logs -f sidechannel"
    echo "  Stop:               $COMPOSE_CMD -f $INSTALL_DIR/docker-compose.yml down"
    echo "  Restart:            $COMPOSE_CMD -f $INSTALL_DIR/docker-compose.yml restart"
    echo "  Rebuild after edit: $COMPOSE_CMD -f $INSTALL_DIR/docker-compose.yml up -d --build"
    echo ""
    echo -e "Configuration: ${CYAN}$CONFIG_DIR/settings.yaml${NC}"
    echo -e "Environment:   ${CYAN}$CONFIG_DIR/.env${NC}"
    echo ""
    echo -e "${CYAN}Documentation: https://github.com/hackingdave/sidechannel${NC}"
    echo ""

    exit 0
fi

# =============================================================================
# LOCAL INSTALL MODE
# =============================================================================

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

# Docker (for Signal CLI REST API)
if [ "$SKIP_SIGNAL" = false ]; then
    if command -v docker &> /dev/null; then
        echo -e "  ${GREEN}✓${NC} Docker"
        # Check Docker daemon is running
        if ! docker info &> /dev/null; then
            echo -e "${YELLOW}Warning: Docker daemon is not running.${NC}"
            echo -e "Start Docker: sudo systemctl start docker"
            read -p "Continue anyway? [y/N] " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    else
        echo -e "${YELLOW}Warning: Docker not found. Signal CLI REST API requires Docker.${NC}"
        echo -e "Install Docker: https://docs.docker.com/get-docker/"
        read -p "Continue without Signal setup? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
        SKIP_SIGNAL=true
    fi
fi

# Claude CLI
if command -v claude &> /dev/null; then
    echo -e "  ${GREEN}✓${NC} Claude CLI"
elif [ -f "$HOME/.local/bin/claude" ]; then
    echo -e "  ${GREEN}✓${NC} Claude CLI ($HOME/.local/bin/claude)"
else
    echo -e "${YELLOW}Warning: Claude CLI not found in PATH${NC}"
    echo -e "Install Claude: https://docs.anthropic.com/en/docs/claude-code"
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
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

# Copy config templates
if [ -d "$SCRIPT_DIR/config" ]; then
    cp "$SCRIPT_DIR/config/"*.example "$CONFIG_DIR/" 2>/dev/null || true
    cp "$SCRIPT_DIR/config/CLAUDE.md" "$CONFIG_DIR/" 2>/dev/null || true
    echo -e "  ${GREEN}✓${NC} Copied config templates"
fi

# Copy requirements
cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"

# -----------------------------------------------------------------------------
# Create virtual environment
# -----------------------------------------------------------------------------
echo -e "${BLUE}Setting up Python virtual environment...${NC}"

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
echo -e "Enter your phone number in E.164 format (e.g., +15551234567):"
read -p "> " PHONE_NUMBER

if [ -n "$PHONE_NUMBER" ]; then
    # Validate E.164 format
    if [[ ! "$PHONE_NUMBER" =~ ^\+[1-9][0-9]{6,14}$ ]]; then
        echo -e "${YELLOW}Warning: Phone number doesn't appear to be in E.164 format (e.g., +15551234567)${NC}"
        read -p "Continue anyway? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Please re-run the installer with a valid phone number."
            exit 1
        fi
    fi
    # Update settings.yaml with phone number
    sed_inplace "s/+1XXXXXXXXXX/$PHONE_NUMBER/" "$SETTINGS_FILE"
    echo -e "  ${GREEN}✓${NC} Phone number configured"
fi

# Create .env file
ENV_FILE="$CONFIG_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" << EOF
# sidechannel environment variables

# Anthropic API key (required for Claude)
ANTHROPIC_API_KEY=

# Optional: Grok API key
# GROK_API_KEY=
EOF
fi

echo ""
echo -e "Enter your Anthropic API key (or press Enter to set later):"
read -p "> " -s ANTHROPIC_KEY
echo ""

if [ -n "$ANTHROPIC_KEY" ]; then
    sed_inplace "s/^ANTHROPIC_API_KEY=.*/ANTHROPIC_API_KEY=$ANTHROPIC_KEY/" "$ENV_FILE"
    echo -e "  ${GREEN}✓${NC} API key configured"
fi

# Ask about Grok
echo ""
read -p "Enable sidechannel AI assistant (OpenAI or Grok)? [y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sed_inplace "s/enabled: false/enabled: true/" "$SETTINGS_FILE"
    echo -e "Enter your Grok API key:"
    read -p "> " -s GROK_KEY
    echo ""
    if [ -n "$GROK_KEY" ]; then
        sed_inplace "s/^# GROK_API_KEY=.*/GROK_API_KEY=$GROK_KEY/" "$ENV_FILE"
        echo -e "  ${GREEN}✓${NC} Grok enabled and configured"
    fi
fi

# -----------------------------------------------------------------------------
# Signal CLI REST API Setup
# -----------------------------------------------------------------------------
if [ "$SKIP_SIGNAL" = false ]; then
    echo ""
    echo -e "${BLUE}Signal CLI REST API Setup${NC}"
    echo ""
    echo "sidechannel uses Signal CLI REST API to send/receive messages."
    echo "This runs as a Docker container on port 8080."
    echo ""

    read -p "Set up Signal CLI REST API now? [Y/n] " -n 1 -r
    echo ""

    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        # Check if this is a remote/headless deployment
        REMOTE_MODE=false
        SIGNAL_BIND="127.0.0.1"

        echo ""
        echo -e "Is this a ${YELLOW}remote/headless${NC} server (e.g., VPS, cloud instance)?"
        echo "If yes, the QR code will be made available over the network so you"
        echo "can access it from your local browser to pair your phone."
        echo ""
        read -p "Remote deployment? [y/N] " -n 1 -r
        echo ""

        if [[ $REPLY =~ ^[Yy]$ ]]; then
            REMOTE_MODE=true
            SIGNAL_BIND="0.0.0.0"
            echo ""
            echo -e "${RED}╔════════════════════════════════════════════════════════════════╗${NC}"
            echo -e "${RED}║                    ⚠  SECURITY WARNING  ⚠                     ║${NC}"
            echo -e "${RED}╠════════════════════════════════════════════════════════════════╣${NC}"
            echo -e "${RED}║                                                                ║${NC}"
            echo -e "${RED}║  The Signal API will be temporarily bound to 0.0.0.0:8080      ║${NC}"
            echo -e "${RED}║  This means it is accessible from ANY network interface.       ║${NC}"
            echo -e "${RED}║                                                                ║${NC}"
            echo -e "${RED}║  After device linking completes, the container will be          ║${NC}"
            echo -e "${RED}║  restarted on 127.0.0.1 (localhost only).                      ║${NC}"
            echo -e "${RED}║                                                                ║${NC}"
            echo -e "${RED}║  Make sure your firewall only allows trusted IPs on port 8080. ║${NC}"
            echo -e "${RED}║                                                                ║${NC}"
            echo -e "${RED}╚════════════════════════════════════════════════════════════════╝${NC}"
            echo ""
            read -p "Continue with remote mode? [y/N] " -n 1 -r
            echo ""
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                REMOTE_MODE=false
                SIGNAL_BIND="127.0.0.1"
                echo "Falling back to localhost-only mode."
            fi
        fi

        # Pull the Docker image
        echo -e "${CYAN}Pulling Signal CLI REST API image...${NC}"
        docker pull bbernhard/signal-cli-rest-api:0.80

        # Start container for linking
        echo ""
        echo -e "${CYAN}Starting Signal container for device linking...${NC}"

        # Stop any existing container
        docker stop signal-api 2>/dev/null || true
        docker rm signal-api 2>/dev/null || true

        # Start new container (bind address depends on remote mode)
        docker run -d \
            --name signal-api \
            --restart unless-stopped \
            -p "$SIGNAL_BIND:8080:8080" \
            -v "$SIGNAL_DATA_DIR:/home/.local/share/signal-cli" \
            -e MODE=native \
            bbernhard/signal-cli-rest-api:0.80

        # Wait for container to start
        echo "Waiting for container to start..."
        sleep 5

        # Check if container is running
        if ! docker ps | grep -q signal-api; then
            echo -e "${RED}Error: Signal container failed to start${NC}"
            docker logs signal-api 2>&1 | tail -10
            exit 1
        fi

        echo ""
        echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║                   SIGNAL DEVICE LINKING                        ║${NC}"
        echo -e "${GREEN}╠════════════════════════════════════════════════════════════════╣${NC}"
        echo -e "${GREEN}║                                                                ║${NC}"
        echo -e "${GREEN}║  1. Open Signal on your phone                                  ║${NC}"
        echo -e "${GREEN}║  2. Go to Settings > Linked Devices                            ║${NC}"
        echo -e "${GREEN}║  3. Tap 'Link New Device'                                      ║${NC}"
        echo -e "${GREEN}║  4. Scan the QR code (see options below)                        ║${NC}"
        echo -e "${GREEN}║                                                                ║${NC}"
        echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
        echo ""

        # Request QR code link
        echo -e "${CYAN}Requesting device link...${NC}"
        echo ""

        # Generate QR code
        LINK_RESPONSE=$(curl -s -X GET "http://127.0.0.1:8080/v1/qrcodelink?device_name=sidechannel" 2>/dev/null)

        if echo "$LINK_RESPONSE" | grep -q "error"; then
            echo -e "${YELLOW}Note: QR code generation requires terminal QR display.${NC}"
        fi

        # Try to display QR code in terminal if qrencode is available
        LINK_URI=$(curl -s "http://127.0.0.1:8080/v1/qrcodelink?device_name=sidechannel" | grep -o 'sgnl://[^"]*' 2>/dev/null || true)

        if command -v qrencode &> /dev/null && [ -n "$LINK_URI" ]; then
            echo -e "${GREEN}Terminal QR Code:${NC}"
            echo ""
            echo "$LINK_URI" | qrencode -t ANSIUTF8
            echo ""
        fi

        # Save QR code as PNG image file
        QR_IMAGE="$INSTALL_DIR/qrcode-link.png"
        if command -v qrencode &> /dev/null && [ -n "$LINK_URI" ]; then
            echo "$LINK_URI" | qrencode -t PNG -o "$QR_IMAGE" -s 10
            echo -e "${GREEN}QR code saved to:${NC} $QR_IMAGE"
            echo "  Download it with: scp $(whoami)@$(hostname):$QR_IMAGE ."
            echo ""
        fi

        # Remote access instructions
        if [ "$REMOTE_MODE" = true ]; then
            # Detect the server's public/external IP
            SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
            if [ -z "$SERVER_IP" ]; then
                SERVER_IP="<your-server-ip>"
            fi

            echo -e "${CYAN}Remote QR Code Access:${NC}"
            echo ""
            echo "  Open this URL in your local browser to view the QR code:"
            echo -e "  ${CYAN}http://${SERVER_IP}:8080/v1/qrcodelink?device_name=sidechannel${NC}"
            echo ""
            echo "  Or use the Swagger UI:"
            echo -e "  ${CYAN}http://${SERVER_IP}:8080/swagger/index.html${NC}"
            echo ""
        else
            echo "  Local browser: http://127.0.0.1:8080/v1/qrcodelink?device_name=sidechannel"
            echo ""
        fi

        if ! command -v qrencode &> /dev/null; then
            echo -e "${YELLOW}Tip: Install 'qrencode' for terminal QR display and PNG export:${NC}"
            echo "  sudo apt install qrencode  # Debian/Ubuntu"
            echo "  brew install qrencode      # macOS"
            echo ""
        fi

        read -p "Press Enter after you've scanned the QR code and linked the device..."

        # Verify linking
        echo ""
        echo -e "${CYAN}Verifying device link...${NC}"
        sleep 2

        ACCOUNTS=$(curl -s "http://127.0.0.1:8080/v1/accounts" 2>/dev/null)
        if echo "$ACCOUNTS" | grep -q "+"; then
            LINKED_NUMBER=$(echo "$ACCOUNTS" | grep -o '+[0-9]*' | head -1)
            echo -e "  ${GREEN}✓${NC} Device linked successfully: $LINKED_NUMBER"

            # Update settings with linked number if different
            if [ "$LINKED_NUMBER" != "$PHONE_NUMBER" ] && [ -n "$LINKED_NUMBER" ]; then
                sed_inplace "s/$PHONE_NUMBER/$LINKED_NUMBER/" "$SETTINGS_FILE" 2>/dev/null || true
            fi
        else
            echo -e "${YELLOW}Warning: Could not verify device link${NC}"
            echo "Check http://127.0.0.1:8080/v1/accounts to verify"
        fi

        # If remote mode was used, restart container on localhost only
        if [ "$REMOTE_MODE" = true ]; then
            echo ""
            echo -e "${CYAN}Switching Signal API to localhost-only (securing)...${NC}"
            docker stop signal-api 2>/dev/null || true
            docker rm signal-api 2>/dev/null || true

            docker run -d \
                --name signal-api \
                --restart unless-stopped \
                -p 127.0.0.1:8080:8080 \
                -v "$SIGNAL_DATA_DIR:/home/.local/share/signal-cli" \
                -e MODE=native \
                bbernhard/signal-cli-rest-api:0.80

            sleep 3
            if docker ps | grep -q signal-api; then
                echo -e "  ${GREEN}✓${NC} Signal API now bound to 127.0.0.1 only"
            else
                echo -e "${RED}Error: Failed to restart Signal container on localhost${NC}"
            fi
        fi

        # Clean up QR code image
        if [ -f "$QR_IMAGE" ]; then
            rm -f "$QR_IMAGE"
            echo -e "  ${GREEN}✓${NC} QR code image cleaned up"
        fi

        echo -e "  ${GREEN}✓${NC} Signal CLI REST API configured"
    fi
fi

# -----------------------------------------------------------------------------
# Systemd service
# -----------------------------------------------------------------------------
if [ "$SKIP_SYSTEMD" = false ]; then
    echo ""
    echo -e "${BLUE}Systemd Service Setup${NC}"
    echo ""

    read -p "Install sidechannel as a systemd service? [Y/n] " -n 1 -r
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

        echo -e "  ${GREEN}✓${NC} Service installed"
        echo ""
        echo "To start sidechannel:"
        echo "  systemctl --user start sidechannel"
        echo ""
        echo "To enable on boot:"
        echo "  systemctl --user enable sidechannel"
        echo "  loginctl enable-linger $USER"
    fi
fi

# -----------------------------------------------------------------------------
# Create run script
# -----------------------------------------------------------------------------
RUN_SCRIPT="$INSTALL_DIR/run.sh"
cat > "$RUN_SCRIPT" << EOF
#!/bin/bash
# Start sidechannel manually

cd "$INSTALL_DIR"
source "$VENV_DIR/bin/activate"
source "$CONFIG_DIR/.env"

python -m sidechannel
EOF
chmod +x "$RUN_SCRIPT"

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              sidechannel installation complete!                ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Installation directory: ${CYAN}$INSTALL_DIR${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo ""
echo "1. Review configuration:"
echo "   $CONFIG_DIR/settings.yaml"
echo "   $CONFIG_DIR/.env"
echo ""
echo "2. Start sidechannel:"
echo "   $RUN_SCRIPT"
echo ""
echo "3. Or use systemd:"
echo "   systemctl --user start sidechannel"
echo ""
echo "4. Send a message to your Signal number:"
echo "   /help - Show available commands"
echo ""
echo -e "${CYAN}Documentation: https://github.com/hackingdave/sidechannel${NC}"
echo ""
