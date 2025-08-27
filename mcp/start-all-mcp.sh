#!/bin/bash
# Multi-Specialist MCP Server Launcher
# Starts all MCP servers on different ports for direct access

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Multi-Specialist MCP Server Launcher        ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# Function to check if a port is in use
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        return 0  # Port is in use
    else
        return 1  # Port is free
    fi
}

# Function to start an MCP server
start_mcp_server() {
    local name=$1
    local port=$2
    local codex_home=$3
    local command=${4:-"codex-custom"}
    
    echo -e "${YELLOW}Starting $name on port $port...${NC}"
    
    # Check if port is already in use
    if check_port $port; then
        echo -e "${RED}✗ Port $port is already in use!${NC}"
        return 1
    fi
    
    # Start the MCP server with gateway filter
    CODEX_HOME="$codex_home" mcp-proxy --port=$port -- \
        python3 "$SCRIPT_DIR/codex-mcp-gateway.py" $command mcp \
        > "$LOG_DIR/${name}.log" 2>&1 &
    
    local pid=$!
    echo $pid > "$LOG_DIR/${name}.pid"
    
    # Wait a moment and check if it started successfully
    sleep 2
    if kill -0 $pid 2>/dev/null; then
        echo -e "${GREEN}✓ $name started (PID: $pid)${NC}"
        echo -e "  Endpoint: http://127.0.0.1:$port/sse"
        return 0
    else
        echo -e "${RED}✗ Failed to start $name${NC}"
        return 1
    fi
}

# Function to stop all MCP servers
stop_all() {
    echo -e "${YELLOW}Stopping all MCP servers...${NC}"
    
    for pidfile in "$LOG_DIR"/*.pid; do
        if [ -f "$pidfile" ]; then
            pid=$(cat "$pidfile")
            name=$(basename "$pidfile" .pid)
            if kill -0 $pid 2>/dev/null; then
                kill $pid
                echo -e "${GREEN}✓ Stopped $name (PID: $pid)${NC}"
            fi
            rm -f "$pidfile"
        fi
    done
}

# Function to show status
show_status() {
    echo -e "${BLUE}MCP Server Status:${NC}"
    echo ""
    
    local any_running=false
    
    # Check each expected server
    for server in "office-assistant:8081" "openbb-analyst:8082" "router:8080"; do
        IFS=':' read -r name port <<< "$server"
        pidfile="$LOG_DIR/${name}.pid"
        
        if [ -f "$pidfile" ]; then
            pid=$(cat "$pidfile")
            if kill -0 $pid 2>/dev/null; then
                echo -e "${GREEN}✓ $name${NC} - Running (PID: $pid) on port $port"
                any_running=true
            else
                echo -e "${RED}✗ $name${NC} - Stopped (stale PID file)"
                rm -f "$pidfile"
            fi
        else
            echo -e "${RED}✗ $name${NC} - Not running"
        fi
    done
    
    if ! $any_running; then
        echo ""
        echo -e "${YELLOW}No MCP servers are currently running.${NC}"
    fi
}

# Main command handling
case "${1:-start}" in
    start)
        echo "Starting all MCP servers..."
        echo ""
        
        # Start Office Assistant on port 8081 (using codex)
        start_mcp_server "office-assistant" 8081 "${OFFICE_AGENT_HOME:-$HOME/admin/.codex}" "codex"
        
        # Start OpenBB Analyst on port 8082 (keeping codex-custom)
        start_mcp_server "openbb-analyst" 8082 "${FINANCE_AGENT_HOME:-$HOME/investing/.codex}" "codex-custom"
        
        # Start Router on port 8090 (using codex)
        start_mcp_server "router" 8090 "${ROUTER_AGENT_HOME:-$HOME/.codex}" "codex"
        
        echo ""
        echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
        echo -e "${GREEN}All MCP servers started!${NC}"
        echo ""
        echo "Direct Access Endpoints:"
        echo "  • Office Assistant: http://127.0.0.1:8081/sse"
        echo "  • Financial Analyst: http://127.0.0.1:8082/sse"
        echo "  • Router (fallback): http://127.0.0.1:8090/sse"
        echo ""
        echo "Voice Wake Words:"
        echo "  • 'Hey Office' → Office Assistant"
        echo "  • 'Hey Analyst' → Financial Analyst"
        echo "  • 'Hey Assistant' → Router"
        echo ""
        echo "Logs: $LOG_DIR/"
        echo ""
        echo "To stop all servers: $0 stop"
        ;;
        
    stop)
        stop_all
        ;;
        
    restart)
        stop_all
        sleep 2
        exec "$0" start
        ;;
        
    status)
        show_status
        ;;
        
    logs)
        # Show recent logs
        server=${2:-all}
        if [ "$server" = "all" ]; then
            echo "Recent logs from all servers:"
            for logfile in "$LOG_DIR"/*.log; do
                if [ -f "$logfile" ]; then
                    name=$(basename "$logfile" .log)
                    echo ""
                    echo -e "${BLUE}=== $name ===${NC}"
                    tail -n 20 "$logfile"
                fi
            done
        else
            logfile="$LOG_DIR/${server}.log"
            if [ -f "$logfile" ]; then
                tail -f "$logfile"
            else
                echo "No log file found for: $server"
            fi
        fi
        ;;
        
    *)
        echo "Usage: $0 {start|stop|restart|status|logs [server-name]}"
        echo ""
        echo "Commands:"
        echo "  start   - Start all MCP servers"
        echo "  stop    - Stop all MCP servers"
        echo "  restart - Restart all MCP servers"
        echo "  status  - Show status of all servers"
        echo "  logs    - Show recent logs (optionally specify server name)"
        echo ""
        echo "Examples:"
        echo "  $0 start"
        echo "  $0 status"
        echo "  $0 logs office-assistant"
        exit 1
        ;;
esac