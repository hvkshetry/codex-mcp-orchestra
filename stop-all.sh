#!/bin/bash
#
# AI Automation System Stop Script
# Stops all services gracefully
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Directories
AI_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${AI_HOME}/logs"

# Function to print colored messages
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to stop a service by PID file
stop_service() {
    local service_name=$1
    local pid_file="${LOG_DIR}/${service_name}.pid"
    
    if [ -f "$pid_file" ]; then
        PID=$(cat "$pid_file")
        if kill -0 $PID 2>/dev/null; then
            kill $PID
            log_info "Stopped ${service_name} (PID: $PID)"
            rm -f "$pid_file"
        else
            log_warn "${service_name} PID file exists but process not running"
            rm -f "$pid_file"
        fi
    else
        log_warn "${service_name} not running (no PID file)"
    fi
}

# Main stop sequence
main() {
    log_info "Stopping AI Automation System..."
    
    # Stop bridge service
    stop_service "bridge"
    pkill -f "python services/bridge.py" 2>/dev/null || true
    
    # Stop whisper service
    stop_service "whisper"
    pkill -f "python services/whisper_service.py" 2>/dev/null || true
    
    # Stop MCP servers
    cd "${AI_HOME}/mcp"
    if [ -f "logs/router.pid" ]; then
        stop_service "../mcp/logs/router"
    fi
    if [ -f "logs/office-assistant.pid" ]; then
        stop_service "../mcp/logs/office-assistant"
    fi
    if [ -f "logs/openbb-analyst.pid" ]; then
        stop_service "../mcp/logs/openbb-analyst"
    fi
    
    # Kill any remaining mcp-proxy or codex processes
    pkill -f "mcp-proxy" 2>/dev/null || true
    pkill -f "codex-custom" 2>/dev/null || true
    pkill -f "codex mcp" 2>/dev/null || true
    
    log_info "All services stopped"
    
    # Clean up any stale PID files
    rm -f "${LOG_DIR}"/*.pid
    rm -f "${AI_HOME}/mcp/logs"/*.pid
    
    log_info "=== Shutdown Complete ==="
}

# Run main function
main "$@"