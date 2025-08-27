#!/bin/bash
# Start Email Automation Services

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtual environment
source .venv/bin/activate

echo "Starting AI Email Automation Services..."
echo "========================================"

# Function to start a service
start_service() {
    local name=$1
    local script=$2
    local port=$3
    
    echo "Starting $name on port $port..."
    python3 services/$script > logs/${name}.log 2>&1 &
    echo $! > logs/${name}.pid
    echo "  PID: $(cat logs/${name}.pid)"
}

# Create logs directory
mkdir -p logs

# Start services
echo ""
echo "1. Starting Bridge Service (includes email routing)..."
start_service "bridge" "bridge.py" "7000"

echo ""
echo "2. Starting Whisper Transcription Service..."
start_service "whisper" "whisper_service.py" "7001"

echo ""
echo "Services started!"
echo ""
echo "Email routing endpoints:"
echo "  Bridge (with email): http://127.0.0.1:7000"
echo "  - POST /email/route - Graph webhook endpoint"
echo "  - GET /email/status - Check routing status"
echo ""
echo "Test the router:"
echo "  curl http://127.0.0.1:7000/email/status"
echo ""
echo "Logs: $SCRIPT_DIR/logs/"
echo ""
echo "To stop services: ./stop-email-services.sh"