#!/bin/bash
#
# apply-signal-patches.sh — Idempotent signal-cli patching for nightwire
#
# Downloads signal-cli JVM edition, applies the ACI binary provisioning patch,
# and upgrades Turasa library JARs to fix sync message parsing.
#
# Usage:
#   ./scripts/apply-signal-patches.sh [INSTALL_DIR]
#
# If INSTALL_DIR is not provided, defaults to parent of the script directory.
#
# Patches applied:
#   1. ProvisioningApi class patch (fixes device linking — GH #1937)
#   2. Turasa JAR upgrade _137 → _138 (fixes sync message parsing — GH #1938)
#
# Set PATCH_REQUIRED=false below when signal-cli releases a version with both fixes.

set -e

# ---------------------------------------------------------------------------
# Configuration — update these when upstream fixes land
# ---------------------------------------------------------------------------
SIGNAL_CLI_VERSION="0.13.24"
TURASA_VERSION="2.15.3_unofficial_138"
TURASA_OLD="2.15.3_unofficial_137"
LIBSIGNAL_VERSION="0.87.0"
PATCH_VERSION="3"  # Bump when patch logic changes
PATCH_REQUIRED=true

# Turasa JARs to upgrade (groupId:artifactId)
TURASA_JARS=(
    "com.github.niccokunzmann:signal-service-java"
    "com.github.niccokunzmann:models-jvm"
    "com.github.niccokunzmann:util-jvm"
)

# Maven repository for Turasa JARs
TURASA_MAVEN="https://jitpack.io/com/github/niccokunzmann"

# ---------------------------------------------------------------------------
# Resolve install directory
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${1:-$(dirname "$SCRIPT_DIR")}"
SIGNAL_CLI_DIR="$INSTALL_DIR/signal-cli-${SIGNAL_CLI_VERSION}"
MARKER_FILE="$SIGNAL_CLI_DIR/.patched"
PATCH_SRC="$INSTALL_DIR/patches/signal-cli"

# ---------------------------------------------------------------------------
# Colors (disable if not a terminal)
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
    BLUE='\033[0;34m'; NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; NC=''
fi

info()  { echo -e "  ${GREEN}✓${NC} $*"; }
warn()  { echo -e "  ${YELLOW}!${NC} $*"; }
fail()  { echo -e "  ${RED}✗${NC} $*" >&2; }

# ---------------------------------------------------------------------------
# Idempotency check
# ---------------------------------------------------------------------------
if [ -f "$MARKER_FILE" ]; then
    current_version=$(cat "$MARKER_FILE" 2>/dev/null || echo "0")
    if [ "$current_version" = "$PATCH_VERSION" ]; then
        echo -e "${GREEN}Signal-cli patches already applied (v${PATCH_VERSION}).${NC}"
        exit 0
    fi
    echo -e "${BLUE}Patch version changed (v${current_version} → v${PATCH_VERSION}), re-applying...${NC}"
fi

# ---------------------------------------------------------------------------
# When patches are no longer needed, clean up and exit
# ---------------------------------------------------------------------------
if [ "$PATCH_REQUIRED" = false ]; then
    echo "Signal-cli patches no longer required (upstream fix available)."
    if [ -d "$SIGNAL_CLI_DIR" ]; then
        echo "  Cleaning up patched signal-cli directory..."
        rm -rf "$SIGNAL_CLI_DIR"
    fi
    exit 0
fi

echo -e "${BLUE}Applying signal-cli patches...${NC}"

# ---------------------------------------------------------------------------
# Helper: patch a JAR with ProvisioningApi classes (safe temp file usage)
# ---------------------------------------------------------------------------
patch_jar() {
    local jar_path="$1"
    local patch_src="$2"
    python3 -c "
import zipfile, sys, os, shutil, tempfile
jar = sys.argv[1]
src = sys.argv[2]
pkg = 'org/whispersystems/signalservice/api/registration'
patch_entries = {}
for cls in ['ProvisioningApi.class', 'ProvisioningApi\$NewDeviceRegistrationReturn.class']:
    cls_file = os.path.join(src, cls)
    if os.path.exists(cls_file):
        patch_entries[pkg + '/' + cls] = cls_file
jar_dir = os.path.dirname(jar)
# Write to a secure temp file, then atomically replace
fd_in, tmp_in = tempfile.mkstemp(suffix='.jar', dir=jar_dir)
os.close(fd_in)
shutil.copy2(jar, tmp_in)
fd_out, tmp_out = tempfile.mkstemp(suffix='.jar', dir=jar_dir)
os.close(fd_out)
with zipfile.ZipFile(tmp_in, 'r') as old, zipfile.ZipFile(tmp_out, 'w', zipfile.ZIP_DEFLATED) as new_jar:
    for item in old.infolist():
        if item.filename not in patch_entries:
            new_jar.writestr(item, old.read(item.filename))
    for entry, path in patch_entries.items():
        new_jar.write(path, entry)
os.remove(tmp_in)
os.replace(tmp_out, jar)  # atomic on same filesystem
" "$jar_path" "$patch_src"
}

# ---------------------------------------------------------------------------
# Step 1: Download signal-cli JVM edition
# ---------------------------------------------------------------------------
if [ ! -f "$SIGNAL_CLI_DIR/bin/signal-cli" ]; then
    os_name="Linux"
    case "$(uname)" in
        Darwin) os_name="macOS" ;;
    esac

    echo -ne "  Downloading signal-cli ${SIGNAL_CLI_VERSION}..."
    if ! curl -sfL "https://github.com/AsamK/signal-cli/releases/download/v${SIGNAL_CLI_VERSION}/signal-cli-${SIGNAL_CLI_VERSION}-${os_name}.tar.gz" \
        | tar xz -C "$INSTALL_DIR/" 2>/dev/null; then
        fail "Failed to download signal-cli"
        exit 1
    fi
    echo -e " ${GREEN}done${NC}"
fi
info "signal-cli ${SIGNAL_CLI_VERSION}"

# ---------------------------------------------------------------------------
# Step 2: Download native library for this architecture
# ---------------------------------------------------------------------------
ARCH=$(uname -m)
lib_ext="so"
case "$ARCH" in
    aarch64)       LIB_ARCH="arm64" ;;
    arm64)         LIB_ARCH="arm64"; [ "$(uname)" = "Darwin" ] && lib_ext="dylib" ;;
    x86_64|amd64)  LIB_ARCH="amd64" ;;
    *)
        fail "Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

lib_path="$SIGNAL_CLI_DIR/lib/libsignal_jni.${lib_ext}"
if [ ! -f "$lib_path" ] || ([ "$(uname)" = "Linux" ] && [ "$LIB_ARCH" = "arm64" ]); then
    echo -ne "  Downloading native library (${LIB_ARCH})..."
    if ! curl -sfL "https://raw.githubusercontent.com/bbernhard/signal-cli-rest-api/master/ext/libraries/libsignal-client/v${LIBSIGNAL_VERSION}/${LIB_ARCH}/libsignal_jni.${lib_ext}" \
        -o "$lib_path" 2>/dev/null; then
        fail "Failed to download native library"
        exit 1
    fi
    echo -e " ${GREEN}done${NC}"
fi
info "Native library (${LIB_ARCH})"

# ---------------------------------------------------------------------------
# Step 3: Upgrade Turasa JARs (_137 → _138) — do this BEFORE patching
# ---------------------------------------------------------------------------
lib_dir="$SIGNAL_CLI_DIR/lib"
needs_jar_upgrade=false

for spec in "${TURASA_JARS[@]}"; do
    artifact=$(echo "$spec" | cut -d: -f2)
    old_jar="$lib_dir/${artifact}-${TURASA_OLD}.jar"
    new_jar="$lib_dir/${artifact}-${TURASA_VERSION}.jar"

    if [ -f "$old_jar" ] && [ ! -f "$new_jar" ]; then
        needs_jar_upgrade=true
        break
    fi
done

if [ "$needs_jar_upgrade" = true ]; then
    echo -ne "  Upgrading Turasa JARs (${TURASA_OLD} → ${TURASA_VERSION})..."

    for spec in "${TURASA_JARS[@]}"; do
        artifact=$(echo "$spec" | cut -d: -f2)
        old_jar="$lib_dir/${artifact}-${TURASA_OLD}.jar"
        new_jar="$lib_dir/${artifact}-${TURASA_VERSION}.jar"

        if [ -f "$old_jar" ] && [ ! -f "$new_jar" ]; then
            url="${TURASA_MAVEN}/${artifact}/${TURASA_VERSION}/${artifact}-${TURASA_VERSION}.jar"
            if ! curl -sfL "$url" -o "$new_jar" 2>/dev/null; then
                fail "Failed to download ${artifact}-${TURASA_VERSION}.jar"
                exit 1
            fi

            # Keep old JAR as backup
            mv "$old_jar" "${old_jar}.old" 2>/dev/null || true
        fi
    done

    echo -e " ${GREEN}done${NC}"
fi
info "Turasa JARs at ${TURASA_VERSION}"

# ---------------------------------------------------------------------------
# Step 4: Apply ProvisioningApi class patch to the final JAR
# ---------------------------------------------------------------------------
final_jar="$lib_dir/signal-service-java-${TURASA_VERSION}.jar"
if [ ! -f "$final_jar" ]; then
    # Fallback: patch the old JAR if upgrade didn't happen (shouldn't normally occur)
    final_jar="$lib_dir/signal-service-java-${TURASA_OLD}.jar"
fi

if [ -f "$PATCH_SRC/ProvisioningApi.class" ] && [ -f "$final_jar" ]; then
    echo -ne "  Applying ProvisioningApi patch..."
    patch_jar "$final_jar" "$PATCH_SRC"
    echo -e " ${GREEN}done${NC}"
else
    warn "Patch files not found — provisioning patch not applied"
fi

# ---------------------------------------------------------------------------
# Step 5: Update classpath in signal-cli launcher script
# ---------------------------------------------------------------------------
launcher="$SIGNAL_CLI_DIR/bin/signal-cli"
if grep -q "$TURASA_OLD" "$launcher" 2>/dev/null; then
    echo -ne "  Updating classpath references..."
    sed -i "s/${TURASA_OLD}/${TURASA_VERSION}/g" "$launcher"
    echo -e " ${GREEN}done${NC}"
fi
info "Classpath updated"

# ---------------------------------------------------------------------------
# Write marker file
# ---------------------------------------------------------------------------
echo "$PATCH_VERSION" > "$MARKER_FILE"
info "Patches applied successfully (v${PATCH_VERSION})"
