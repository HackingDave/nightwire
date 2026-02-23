#!/bin/bash
#
# sidechannel installer
# Signal + Claude AI Bot
#
# Usage: ./install.sh [--skip-signal] [--skip-systemd]
#

set -e

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
        --help|-h)
            echo "Usage: ./install.sh [options]"
            echo ""
            echo "Options:"
            echo "  --skip-signal    Skip Signal CLI REST API setup"
            echo "  --skip-systemd   Skip systemd service installation"
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

python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

pip install --upgrade pip -q
pip install -r "$INSTALL_DIR/requirements.txt" -q

echo -e "  ${GREEN}✓${NC} Virtual environment created"
echo -e "  ${GREEN}✓${NC} Dependencies installed"

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
    sed -i "s/+1XXXXXXXXXX/$PHONE_NUMBER/" "$SETTINGS_FILE"
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
    sed -i "s/^ANTHROPIC_API_KEY=.*/ANTHROPIC_API_KEY=$ANTHROPIC_KEY/" "$ENV_FILE"
    echo -e "  ${GREEN}✓${NC} API key configured"
fi

# Ask about Grok
echo ""
read -p "Enable sidechannel AI assistant (OpenAI or Grok)? [y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sed -i "s/enabled: false/enabled: true/" "$SETTINGS_FILE"
    echo -e "Enter your Grok API key:"
    read -p "> " -s GROK_KEY
    echo ""
    if [ -n "$GROK_KEY" ]; then
        sed -i "s/^# GROK_API_KEY=.*/GROK_API_KEY=$GROK_KEY/" "$ENV_FILE"
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
        # Pull the Docker image
        echo -e "${CYAN}Pulling Signal CLI REST API image...${NC}"
        docker pull bbernhard/signal-cli-rest-api:0.80

        # Start container for linking
        echo ""
        echo -e "${CYAN}Starting Signal container for device linking...${NC}"

        # Stop any existing container
        docker stop signal-api 2>/dev/null || true
        docker rm signal-api 2>/dev/null || true

        # Start new container
        docker run -d \
            --name signal-api \
            --restart unless-stopped \
            -p 8080:8080 \
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
        echo -e "${GREEN}║  4. A QR code will appear below - scan it with your phone      ║${NC}"
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
            echo ""
            echo "To link manually, visit: http://127.0.0.1:8080/v1/qrcodelink?device_name=sidechannel"
            echo "Or use the Signal CLI REST API Swagger UI at: http://127.0.0.1:8080/swagger/index.html"
        fi

        # Try to display QR code if qrencode is available
        if command -v qrencode &> /dev/null; then
            # Get the link URI
            LINK_URI=$(curl -s "http://127.0.0.1:8080/v1/qrcodelink?device_name=sidechannel" | grep -o 'sgnl://[^"]*' 2>/dev/null || true)
            if [ -n "$LINK_URI" ]; then
                echo "$LINK_URI" | qrencode -t ANSIUTF8
            fi
        else
            echo ""
            echo -e "${YELLOW}Tip: Install 'qrencode' to display QR codes in terminal:${NC}"
            echo "  sudo apt install qrencode  # Debian/Ubuntu"
            echo "  brew install qrencode      # macOS"
            echo ""
            echo "For now, open this URL in a browser to see the QR code:"
            echo -e "${CYAN}http://127.0.0.1:8080/v1/qrcodelink?device_name=sidechannel${NC}"
        fi

        echo ""
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
                sed -i "s/$PHONE_NUMBER/$LINKED_NUMBER/" "$SETTINGS_FILE" 2>/dev/null || true
            fi
        else
            echo -e "${YELLOW}Warning: Could not verify device link${NC}"
            echo "Check http://127.0.0.1:8080/v1/accounts to verify"
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
