# Codex MCP Orchestra

A modular multi-agent system that orchestrates specialized AI agents through voice, email, and API interfaces. Built on the Codex CLI and Model Context Protocol (MCP), this system enables teams of AI coworkers with distinct capabilities and communication channels.

## Overview

Codex MCP Orchestra creates a distributed AI workforce where each agent:
- Runs as an independent Codex CLI instance with its own MCP server configuration
- Has specialized tools and context through configured MCP servers
- Responds to specific communication channels (email suffixes, voice wake words)
- Can be orchestrated through a central router for complex tasks

## Architecture

### Core Components

```
┌─────────────────────────────────────────────┐
│              Input Layer                    │
├──────────┬──────────┬───────────────────────┤
│  Voice   │  Email   │      API              │
└────┬─────┴────┬─────┴────────┬──────────────┘
     │          │              │
┌────▼──────────▼──────────────▼──────────────┐
│          Bridge Service (Port 7000)         │
│  • Session Management                       │
│  • Request Routing                          │
│  • Response Handling                        │
└────────────────┬─────────────────────────────┘
                 │
┌────────────────▼─────────────────────────────┐
│         MCP Proxy Layer                      │
├──────────┬──────────┬────────────────────────┤
│  Router  │  Agent 1 │    Agent N             │
│ (8090)   │  (8081)  │    (808N)              │
└──────────┴──────────┴────────────────────────┘
```

### Codex as MCP Server and Client

Each Codex agent in the system operates in a dual capacity:

#### As MCP Server
Each agent runs `codex mcp` to expose its capabilities as an MCP server:
```bash
codex mcp  # Starts Codex as an MCP server on configured port
```

This allows the bridge service to communicate with each agent using the MCP protocol over SSE (Server-Sent Events).

#### As MCP Client
Simultaneously, each Codex instance connects to other MCP servers configured in its `~/.codex/config.toml`:
```toml
[mcp_servers.example-tool]
command = "example-mcp-server"
args = ["--port", "9000"]
env = { "API_KEY" = "..." }
```

This dual nature allows agents to:
1. Expose their core Codex functionality to the orchestration layer
2. Leverage specialized tools from external MCP servers
3. Create a hierarchical network of capabilities

## Features

### Multi-Channel Communication
- **Email Routing**: Plus addressing (user+agent@domain.com) routes to specific agents
- **Voice Commands**: Wake word activation with natural language processing
- **REST API**: Direct programmatic access to agent capabilities
- **SSE Streaming**: Real-time responses for interactive applications

### Specialized Agents
Configure unlimited agents with unique:
- Tool sets via MCP server configurations
- Voice personalities and wake words
- Email routing rules
- Context and knowledge bases

### Example Agent: Office Assistant

The Office Assistant demonstrates a fully-configured agent with Microsoft Graph integration:

**Capabilities:**
- Email management (search, send, organize)
- Calendar operations (schedule, update, manage meetings)
- Teams integration (chats, channels, meetings)
- OneDrive/SharePoint file management
- Task management via Microsoft Planner

**MCP Server Configuration:**
```toml
# ~/.codex/config.toml for Office Assistant
name = "office-assistant"
model = "gpt-4"

[mcp_servers.office-mcp]
command = "node"
args = ["path/to/office-mcp/index.js"]

[mcp_servers.excel-mcp]
command = "npx"
args = ["--yes", "@example/excel-mcp-server"]
```

## Installation

### Prerequisites
- Linux/WSL2 environment
- Python 3.9+
- Codex CLI installed and configured
- Node.js (for JavaScript-based MCP servers)
- Audio hardware (for voice features - optional)

### Setup Steps

1. **Clone the repository with submodules**
```bash
git clone --recurse-submodules https://github.com/hvkshetry/codex-mcp-orchestra.git
cd codex-mcp-orchestra
```

2. **Create Python environment**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. **Configure Codex agents**

For each agent, create a Codex configuration directory:
```bash
# Main router
mkdir -p ~/.codex
# Configure with general MCP servers

# Specialized agents
mkdir -p ~/agents/office/.codex
# Configure with office-specific MCP servers
```

4. **Copy and customize configuration files**
```bash
cp config/routing.example.toml config/routing.toml
cp config/email_security.example.toml config/email_security.toml
cp mcp/mcp-servers.example.json mcp/mcp-servers.json
# Edit files with your settings
```

5. **Set up environment variables**
```bash
cp .env.example .env
# Edit .env with your settings
source .env  # Or use python-dotenv
```

## Configuration

### Email Routing (config/routing.toml)
```toml
[suffixes]
office = "http://127.0.0.1:8081"
finance = "http://127.0.0.1:8082"

[domain]
email_domain = "your-domain.com"

[defaults]
fallback = "http://127.0.0.1:8090"
```

### MCP Servers (mcp/mcp-servers.json)
```json
{
  "mcpServers": {
    "agent-name": {
      "command": "codex-custom",
      "args": ["mcp"],
      "env": {
        "CODEX_HOME": "${HOME}/agents/agent-name/.codex"
      }
    }
  }
}
```

### Voice Configuration
```toml
[wake]
phrase = "hey assistant"

[mcp]
endpoint = "http://127.0.0.1:8090/sse"
```

## Usage

### Starting the System

**Quick Start:**
```bash
./start-all.sh
```

**Manual Start:**
```bash
# Start MCP servers
cd mcp
./start-all-mcp.sh

# Start bridge service
source .venv/bin/activate
python services/bridge.py
```

### Communication Methods

**Email:**
Send emails to configured addresses:
- `user+office@domain.com` → Office Assistant
- `user+finance@domain.com` → Financial Analyst
- `user@domain.com` → General Router

**Voice:**

The voice-automation submodule provides natural voice interaction:

1. **Start voice service:**
```bash
cd voice-automation
python voice_router.py
```

2. **Interaction flow:**
   - Say the wake word: "Deep Thought"
   - Speak your request
   - System transcribes and routes to appropriate agent
   - Receive spoken response

3. **Voice models:**
   - Download required models to `voice-automation/voices/`
   - Configure paths in `voice_config.toml`

**API:**
```python
import requests

response = requests.post('http://localhost:7000/voice/command', json={
    'text': 'Schedule a meeting for tomorrow at 3pm',
    'wake_word': 'office'
})
```

## Adding New Agents

1. **Create Codex configuration:**
```bash
mkdir -p ~/agents/new-agent/.codex
# Configure config.toml with MCP servers
```

2. **Update MCP configuration:**
```json
// mcp/mcp-servers.json
"new-agent": {
  "command": "codex-custom",
  "args": ["mcp"],
  "env": {
    "CODEX_HOME": "${HOME}/agents/new-agent/.codex"
  }
}
```

3. **Configure routing:**
```toml
# config/routing.toml
[suffixes]
newagent = "http://127.0.0.1:8086"
```

4. **Restart services:**
```bash
./start-all.sh
```

## MCP Server Development

To create custom MCP servers for your agents:

1. **Follow MCP specification:**
   - Implement JSON-RPC 2.0 protocol
   - Support initialize, list_tools, call_tool methods
   - Use stdio or SSE transport

2. **Configure in Codex:**
```toml
[mcp_servers.custom-tool]
command = "python"
args = ["path/to/custom-mcp-server.py"]
env = { "CONFIG" = "value" }
```

3. **Test integration:**
```bash
codex mcp  # Start Codex as MCP server
# In another terminal
curl http://localhost:8090/sse  # Test SSE endpoint
```

## Architecture Deep Dive

### Session Management
The bridge service maintains stateful sessions across interactions, preserving context for multi-turn conversations.

### Request Routing
Intelligent routing based on:
- Email suffixes and headers
- Voice wake words and keyword detection
- API endpoint selection

### Tool Aggregation
Each Codex agent aggregates tools from:
- Core Codex functionality
- Configured MCP servers
- Custom integrations

## Security Considerations

- Run services on localhost by default
- Use environment variables for sensitive configuration
- Implement rate limiting for email processing
- Validate webhook signatures for external integrations
- Regular security audits of MCP server connections

## Troubleshooting

### Check Service Status
```bash
./verify-ports.sh  # Check if services are running
```

### View Logs
```bash
tail -f logs/bridge.log
tail -f mcp/logs/agent-name.log
```

### Common Issues

**Port Already in Use:**
```bash
lsof -i :PORT_NUMBER
kill -9 PID
```

**MCP Connection Failed:**
- Verify Codex configuration
- Check MCP server is running
- Review logs for connection errors

**Email Routing Issues:**
- Confirm domain configuration
- Check webhook setup
- Verify plus addressing enabled

## Contributing

1. Fork the repository
2. Create a feature branch
3. Test with multiple agents
4. Submit a pull request

## License

MIT License - See LICENSE file for details

## Acknowledgments

Built on:
- [Codex CLI](https://github.com/openai/codex) - AI-powered development assistant
- Model Context Protocol (MCP) - Standardized AI tool integration
- FastAPI - High-performance web framework
- Microsoft Graph API - Office 365 integration