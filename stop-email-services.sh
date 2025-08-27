#!/bin/bash
# Stop Email Automation Services

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Stopping AI Email Automation Services..."
echo "========================================"

# Function to stop a service
stop_service() {
    local name=$1
    local pidfile="logs/${name}.pid"
    
    if [ -f "$pidfile" ]; then
        pid=$(cat "$pidfile")
        if kill -0 $pid 2>/dev/null; then
            echo "Stopping $name (PID: $pid)..."
            kill $pid
            rm -f "$pidfile"
        else
            echo "$name not running (stale PID file)"
            rm -f "$pidfile"
        fi
    else
        echo "$name not running"
    fi
}

# Stop services
stop_service "bridge"
stop_service "whisper"

echo ""
echo "All services stopped."