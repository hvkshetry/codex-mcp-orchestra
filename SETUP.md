# Detailed Setup Guide

## Prerequisites

### System Requirements
- Ubuntu/Debian Linux or WSL2 on Windows
- Python 3.9 or higher
- Node.js 18+ (for JavaScript-based MCP servers)
- Git
- 4GB+ RAM recommended
- Audio hardware (for voice features)

### Codex CLI Installation

1. **Install Codex CLI:**
```bash
# Download and install Codex
curl -fsSL https://github.com/openai/codex/releases/latest/download/install.sh | bash

# Verify installation
codex --version
```

2. **Initial Codex Configuration:**
```bash
# Initialize default configuration
codex init

# Test Codex functionality
codex "Hello, world"
```

## Understanding Codex as MCP Server and Client

### Dual Architecture

Codex CLI uniquely operates as both an MCP server and MCP client simultaneously:

#### MCP Server Mode
When you run `codex mcp`, Codex exposes itself as an MCP server:
- Listens on a specified port (e.g., 8090)
- Accepts MCP protocol requests via SSE/JSON-RPC
- Exposes Codex's AI capabilities to external clients
- Handles tool calls, prompts, and completions

#### MCP Client Mode
Simultaneously, Codex connects to other MCP servers defined in config.toml:
- Spawns subprocess for each configured MCP server
- Aggregates tools from all connected servers
- Makes these tools available within Codex sessions
- Manages lifecycle of client connections

### Configuration Structure

```toml
# ~/.codex/config.toml
name = "agent-name"
model = "gpt-4"

# Codex as MCP Client - connecting to other servers
[mcp_servers.example-tool]
command = "python"
args = ["path/to/mcp-server.py"]
env = { "API_KEY" = "..." }

[mcp_servers.another-tool]
command = "node"
args = ["another-server.js"]
```

### How It Works

1. **Startup Sequence:**
   - Launch `codex mcp` → Starts MCP server on port
   - Codex reads config.toml → Spawns MCP client connections
   - Tools from clients become available in Codex server

2. **Request Flow:**
   ```
   External Request → Codex MCP Server
                      ↓
                  Codex Core
                      ↓
              Aggregated Tools
              /      |      \
        MCP Client  Client  Client
             ↓        ↓       ↓
        External  External External
        MCP Server Server  Server
   ```

3. **Tool Resolution:**
   - External client requests tool list from Codex
   - Codex aggregates tools from all configured MCP servers
   - Returns unified tool list to client
   - Routes tool calls to appropriate MCP server

## Step-by-Step Setup

### 1. Project Structure Setup

```bash
# Create project directory
mkdir ~/codex-mcp-orchestra
cd ~/codex-mcp-orchestra

# Create required directories
mkdir -p config services mcp/logs logs temp
mkdir -p voice-automation/voices

# Clone or create the project
git init
```

### 2. Python Environment Setup

```bash
# Create virtual environment
python3 -m venv .venv

# Activate environment
source .venv/bin/activate

# Install dependencies
pip install fastapi uvicorn httpx httpx-sse aiohttp tomli pydantic
```

### 3. Configure Multiple Codex Agents

Each agent needs its own Codex configuration:

```bash
# Router Agent (General Purpose)
mkdir -p ~/.codex
cat > ~/.codex/config.toml << EOF
name = "router"
model = "gpt-4"
EOF

# Office Assistant Agent
mkdir -p ~/agents/office/.codex
cat > ~/agents/office/.codex/config.toml << EOF
name = "office-assistant"
model = "gpt-4"

[mcp_servers.graph-api]
command = "node"
args = ["/path/to/graph-mcp-server/index.js"]
env = { "CLIENT_ID" = "your-client-id" }
EOF

# Financial Analyst Agent
mkdir -p ~/agents/finance/.codex
cat > ~/agents/finance/.codex/config.toml << EOF
name = "financial-analyst"
model = "gpt-4"

[mcp_servers.market-data]
command = "python"
args = ["/path/to/market-data-mcp.py"]
EOF
```

### 4. Configure MCP Proxy

The mcp-proxy tool manages Codex instances as MCP servers:

```bash
# Install mcp-proxy
npm install -g @anthropic/mcp-proxy

# Create MCP servers configuration
cat > mcp/mcp-servers.json << EOF
{
  "mcpServers": {
    "router": {
      "command": "codex",
      "args": ["mcp"],
      "env": {
        "CODEX_HOME": "$HOME/.codex"
      }
    },
    "office": {
      "command": "codex",
      "args": ["mcp"],
      "env": {
        "CODEX_HOME": "$HOME/agents/office/.codex"
      }
    },
    "finance": {
      "command": "codex",
      "args": ["mcp"],
      "env": {
        "CODEX_HOME": "$HOME/agents/finance/.codex"
      }
    }
  }
}
EOF
```

### 5. Create Startup Script

```bash
cat > mcp/start-all-mcp.sh << 'EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# Start Router on port 8090
CODEX_HOME="$HOME/.codex" mcp-proxy --port=8090 -- codex mcp > "$LOG_DIR/router.log" 2>&1 &
echo $! > "$LOG_DIR/router.pid"

# Start Office Assistant on port 8081
CODEX_HOME="$HOME/agents/office/.codex" mcp-proxy --port=8081 -- codex mcp > "$LOG_DIR/office.log" 2>&1 &
echo $! > "$LOG_DIR/office.pid"

# Start Financial Analyst on port 8082
CODEX_HOME="$HOME/agents/finance/.codex" mcp-proxy --port=8082 -- codex mcp > "$LOG_DIR/finance.log" 2>&1 &
echo $! > "$LOG_DIR/finance.pid"

echo "All MCP servers started"
EOF

chmod +x mcp/start-all-mcp.sh
```

### 6. Configure Email Routing

```bash
cat > config/routing.toml << EOF
[suffixes]
office = "http://127.0.0.1:8081"
finance = "http://127.0.0.1:8082"
test = "http://127.0.0.1:8090"

[domain]
email_domain = "yourdomain.com"

[defaults]
fallback = "http://127.0.0.1:8090"

[features]
log_unknown_suffixes = true
auto_learn_suffixes = false
EOF
```

### 7. Set Environment Variables

```bash
# Add to ~/.bashrc or ~/.zshrc
export EMAIL_DOMAIN="yourdomain.com"
export CODEX_BASE_DIR="$HOME"
export CODEX_HOME="$HOME/.codex"

# Apply changes
source ~/.bashrc
```

## Testing Your Setup

### 1. Test Individual Codex Instances

```bash
# Test router agent
CODEX_HOME=~/.codex codex "What can you do?"

# Test office agent
CODEX_HOME=~/agents/office/.codex codex "List my calendar"
```

### 2. Test MCP Server Mode

```bash
# Start a single Codex as MCP server
codex mcp &

# Test SSE endpoint
curl http://localhost:8090/sse

# Kill the test server
kill %1
```

### 3. Test Full System

```bash
# Start all services
./start-all.sh

# Check service health
curl http://localhost:7000/health

# Test routing
curl -X POST http://localhost:7000/voice/command \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello", "wake_word": "router"}'
```

## Email Integration Setup

### 1. Microsoft Graph Webhook (Office 365)

```javascript
// Create webhook subscription
POST https://graph.microsoft.com/v1.0/subscriptions
{
  "changeType": "created",
  "notificationUrl": "https://your-public-url/email/route",
  "resource": "users/user@domain.com/mailFolders('inbox')/messages",
  "expirationDateTime": "2025-12-31T23:59:59Z",
  "clientState": "SecureRandomString123"
}
```

### 2. Email Transport Rules

Configure your email server to:
- Support plus addressing (user+suffix@domain.com)
- Add custom headers for routing
- Forward to webhook endpoint

## Voice Setup (Optional)

### 1. Install Voice Dependencies

```bash
pip install SpeechRecognition pyaudio pyttsx3
pip install faster-whisper openai-whisper
```

### 2. Download Voice Models

```bash
# Download wake word models
cd voice-automation/voices
wget https://github.com/rhasspy/piper/releases/download/v1.0/en_GB-alan-medium.onnx
```

### 3. Configure Voice Settings

```bash
cat > voice-automation/voice_config.toml << EOF
[wake]
phrase = "hey assistant"

[asr]
model = "small"
language = "en"

[tts]
piper_voice = "voices/en_GB-alan-medium.onnx"
speech_rate = 0.9

[mcp]
endpoint = "http://127.0.0.1:8090/sse"
timeout = 60
EOF
```

## Creating Custom MCP Servers

### Python MCP Server Template

```python
#!/usr/bin/env python3
import sys
import json

class CustomMCPServer:
    def handle_request(self, request):
        method = request.get("method")
        
        if method == "initialize":
            return {
                "protocolVersion": "0.1.0",
                "capabilities": {"tools": {}}
            }
        elif method == "tools/list":
            return {
                "tools": [
                    {
                        "name": "custom_tool",
                        "description": "Custom tool description",
                        "inputSchema": {
                            "type": "object",
                            "properties": {}
                        }
                    }
                ]
            }
        elif method == "tools/call":
            # Implement tool logic
            return {"result": "Tool executed"}

if __name__ == "__main__":
    server = CustomMCPServer()
    # Implement stdio JSON-RPC handling
```

### Integrating Custom MCP Server

1. Add to Codex config:
```toml
[mcp_servers.custom]
command = "python"
args = ["/path/to/custom-mcp-server.py"]
```

2. Restart Codex agent:
```bash
# Stop existing
pkill -f "codex mcp"

# Restart
./mcp/start-all-mcp.sh
```

## Monitoring and Maintenance

### Log Locations
- Bridge service: `logs/bridge.log`
- MCP servers: `mcp/logs/*.log`
- System: `logs/systemd.log`

### Health Checks
```bash
# Create health check script
cat > check-health.sh << 'EOF'
#!/bin/bash
echo "Checking service health..."

# Check bridge
curl -s http://localhost:7000/health | jq .

# Check MCP servers
for port in 8090 8081 8082; do
  echo "Port $port: $(curl -s -o /dev/null -w "%{http_code}" http://localhost:$port/sse)"
done
EOF

chmod +x check-health.sh
```

### Troubleshooting Commands
```bash
# View all running services
ps aux | grep -E "(codex|mcp-proxy|python.*bridge)"

# Check port usage
netstat -tulpn | grep -E "(7000|808[0-9])"

# Tail all logs
tail -f logs/*.log mcp/logs/*.log

# Restart everything
pkill -f "codex mcp"
pkill -f "python.*bridge"
./start-all.sh
```

## Security Best Practices

1. **Use environment variables for secrets:**
```bash
# .env file (excluded from git)
GRAPH_CLIENT_ID=xxx
GRAPH_CLIENT_SECRET=xxx
API_KEY=xxx
```

2. **Restrict network access:**
```bash
# Only allow localhost connections
iptables -A INPUT -p tcp --dport 7000:8090 -s 127.0.0.1 -j ACCEPT
iptables -A INPUT -p tcp --dport 7000:8090 -j DROP
```

3. **Regular updates:**
```bash
# Update Codex CLI
codex update

# Update dependencies
pip install --upgrade -r requirements.txt
```

## Next Steps

1. Customize agents with specialized MCP servers
2. Implement authentication for production
3. Set up monitoring and alerting
4. Create agent-specific knowledge bases
5. Develop custom tools for your use cases

For more information, see:
- [Codex Documentation](https://github.com/openai/codex)
- [MCP Specification](https://github.com/anthropics/mcp)
- Main README.md for usage examples