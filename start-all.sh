#!/bin/bash
#
# AI Automation System Startup Script
# Starts all MCP servers and bridge service with health checks
#

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Directories
AI_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_DIR="${AI_HOME}/mcp"
VENV_DIR="${AI_HOME}/.venv"
LOG_DIR="${AI_HOME}/logs"

# Create log directory if it doesn't exist
mkdir -p "${LOG_DIR}"

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

# Function to check if a service is healthy
check_health() {
    local url=$1
    local name=$2
    local max_attempts=30
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        if curl -s -f "${url}/health" > /dev/null 2>&1; then
            log_info "${name} is healthy"
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 1
    done
    
    log_error "${name} failed health check after ${max_attempts} seconds"
    return 1
}

# Function to check if port is in use
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        return 0  # Port is in use
    else
        return 1  # Port is free
    fi
}

# Main startup sequence
main() {
    log_info "Starting AI Automation System..."
    
    # Step 1: Check for conflicting services
    log_info "Checking for port conflicts..."
    
    if check_port 8080; then
        log_warn "Port 8080 is in use (likely WhatsApp bridge)"
    fi
    
    if check_port 7000; then
        log_warn "Port 7000 already in use, stopping old bridge..."
        pkill -f "python services/bridge.py" || true
        sleep 2
    fi
    
    # Step 2: Start MCP servers
    log_info "Starting MCP servers..."
    cd "${MCP_DIR}"
    
    if [ -f "start-all-mcp.sh" ]; then
        ./start-all-mcp.sh >> "${LOG_DIR}/mcp-servers.log" 2>&1 &
        log_info "MCP servers starting..."
        sleep 5  # Give them time to initialize
    else
        log_error "MCP startup script not found!"
        exit 1
    fi
    
    # Step 3: Verify MCP servers are running
    log_info "Verifying MCP servers..."
    
    if ! check_port 8090; then
        log_error "Router MCP (8090) not running!"
        exit 1
    fi
    
    if ! check_port 8081; then
        log_error "Office MCP (8081) not running!"
        exit 1
    fi
    
    if ! check_port 8082; then
        log_error "Analyst MCP (8082) not running!"
        exit 1
    fi
    
    log_info "All MCP servers are running"
    
    # Step 4: Start Whisper service (for voice transcription)
    log_info "Starting Whisper transcription service..."
    cd "${AI_HOME}"
    
    # Activate virtual environment and start whisper
    source "${VENV_DIR}/bin/activate"
    nohup python services/whisper_service.py >> "${LOG_DIR}/whisper.log" 2>&1 &
    WHISPER_PID=$!
    
    log_info "Whisper service started with PID ${WHISPER_PID}"
    echo ${WHISPER_PID} > "${LOG_DIR}/whisper.pid"
    
    # Give it a moment to start
    sleep 2
    
    # Step 5: Start bridge service
    log_info "Starting bridge service..."
    
    nohup python services/bridge.py >> "${LOG_DIR}/bridge.log" 2>&1 &
    BRIDGE_PID=$!
    
    log_info "Bridge service started with PID ${BRIDGE_PID}"
    echo ${BRIDGE_PID} > "${LOG_DIR}/bridge.pid"
    
    # Step 6: Wait for services to be healthy
    sleep 3
    
    # Check Whisper service
    if curl -s -f "http://localhost:7001/health" > /dev/null 2>&1; then
        log_info "Whisper service is healthy"
    else
        log_warn "Whisper service not responding (voice transcription unavailable)"
    fi
    if check_health "http://localhost:7000" "Bridge service"; then
        log_info "Bridge service is healthy"
    else
        log_error "Bridge service failed to start!"
        exit 1
    fi
    
    # Step 6: Show service status
    log_info "=== Service Status ==="
    
    # Get health status
    HEALTH=$(curl -s http://localhost:7000/health 2>/dev/null || echo "{}")
    
    if [ -n "$HEALTH" ]; then
        echo "$HEALTH" | python3 -m json.tool
    fi
    
    # Step 7: Show available endpoints
    log_info "=== Available Endpoints ==="
    echo "  Bridge API: http://localhost:7000"
    echo "  - POST /voice/command - Handle voice commands"
    echo "  - POST /email/notification - Handle email webhooks"
    echo "  - GET /health - Health check"
    echo "  - GET /sessions - List active sessions"
    echo "  - GET /servers - List MCP servers"
    echo ""
    echo "  Whisper ASR: http://localhost:7001"
    echo "  - POST /transcribe - Transcribe audio to text"
    echo "  - GET /health - Service health"
    echo ""
    echo "  MCP Servers:"
    echo "  - Router: http://localhost:8090"
    echo "  - Office: http://localhost:8081"
    echo "  - Analyst: http://localhost:8082"
    
    log_info "=== Startup Complete ==="
    log_info "All services are running. Check logs in ${LOG_DIR}"
    
    # Optional: tail logs for monitoring
    if [ "$1" == "--follow" ]; then
        log_info "Following bridge logs (Ctrl+C to exit)..."
        tail -f "${LOG_DIR}/bridge.log"
    fi
}

# Run main function
main "$@"