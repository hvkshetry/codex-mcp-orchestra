# MCP Multi-Stage Response Handling

## Overview

This document describes the implementation of multi-stage response handling for the MCP SSE system, enabling proper error recovery, reasoning streaming, and TTS integration.

## Problem Statement

The original implementation had several issues:
1. **Non-JSON banners** from MCP servers crashed the SSE client
2. **Event format mismatch** - Codex emits `codex/event` format, not MCP-compliant notifications
3. **No multi-stage support** - System couldn't handle reasoning → tool call → error → retry flows
4. **TTS timeout issues** - Long-running operations (30-60s+) cause Windows TTS to timeout

## Solution Architecture

### 1. Gateway Process (`mcp/codex-mcp-gateway.py`)

Filters and translates Codex output to MCP-compliant format:

- **Banner Filtering**: Removes non-JSON lines like "MCP Doc Forge Server is running"
- **Event Translation**: Converts `codex/event` to `notifications/*` format
- **Event Type Preservation**: Maintains event types for proper multi-stage handling

Key event types:
- `agent_reasoning_delta` - LLM reasoning chunks (streamed to TTS)
- `agent_message_delta` - Final response chunks  
- `mcp_tool_call_begin/end` - Tool execution events
- `task_complete` - Conversation complete

### 2. MCP SSE Client (`services/mcp_sse_client.py`)

Enhanced to collect multi-stage responses:

```python
# Collects reasoning and message chunks separately
reasoning_chunks = []
message_chunks = []
has_tool_error = False

# Returns structured response with both components
return {
    "type": "result",
    "content": final_response,
    "reasoning": reasoning_chunks,  # For TTS "thinking out loud"
    "message": message_chunks        # Final answer
}
```

### 3. Bridge Service (`services/bridge.py`)

Handles multi-part responses with TTS-friendly formatting:

- **Non-streaming**: Includes optional `reasoning` field with faster voice config
- **Streaming**: Sends reasoning chunks in real-time for immediate TTS synthesis
- **Voice Configuration**: Reasoning at 1.2x speed, 0.95x pitch for differentiation

## Known Issues & Limitations

### 1. Long Processing Times

Complex operations take significant time:
- Email search: 30-60 seconds
- Teams calendar queries: 60+ seconds
- Multiple tool calls: Can exceed 2-3 minutes

### 2. TTS Timeout Challenges

Windows TTS expects quick responses (<5 seconds typical):
- Long silence creates poor user experience
- No feedback during processing
- Potential connection timeouts

### 3. Streaming Limitations

Current SSE implementation has challenges:
- Reasoning chunks not consistently available from Codex
- Streaming mode can timeout on complex queries
- No heartbeat mechanism for long operations

## Production Recommendations

### 1. Immediate Acknowledgment Pattern

```python
# Send immediately to TTS
"Searching your emails for action items..."

# Stream reasoning chunks as available
"[REASONING]: Looking through recent messages..."

# Send final response
"Found 3 action items: ..."
```

### 2. WebSocket Upgrade

Replace SSE with WebSocket for:
- Bidirectional communication
- Better timeout handling
- Real-time progress updates
- Heartbeat/keepalive support

### 3. Job Queue Architecture

For operations >10 seconds:
1. Return job ID immediately
2. Process in background
3. Stream results progressively
4. Allow status checking

### 4. TTS Integration Improvements

- Set client timeout to 60+ seconds
- Implement chunked responses for long text
- Add "still working" periodic updates
- Use different voice speeds for reasoning vs. response

## Testing Results

### Successful Tests
- Simple queries (<5s): ✅ Working well
- Email search (30-60s): ✅ Returns results but no reasoning
- Teams calendar (60s+): ✅ Works with extended timeout

### Failed/Timeout Tests
- Streaming with reasoning: ⚠️ Inconsistent, often timeouts
- Multi-tool workflows: ⚠️ Can exceed 2-3 minutes
- Error retry flows: ⚠️ Validation errors with whatsapp-mcp

## Configuration Changes

### Start Script (`mcp/start-all-mcp.sh`)
Now uses gateway wrapper for office-assistant:
```bash
python3 "$SCRIPT_DIR/codex-mcp-gateway.py" codex mcp
```

### Environment Requirements
- `CODEX_HOME` must be set and passed to subprocess
- Python `.venv` required for aiohttp and other dependencies
- Increased timeouts in client and bridge (60-600 seconds)

## Future Enhancements

1. **Progressive Response Streaming**
   - Implement sentence-level chunking
   - Add natural pauses between thoughts
   - Support interruption/cancellation

2. **Caching Layer**
   - Cache common queries
   - Pre-warm frequent operations
   - Reduce response times

3. **Fallback Mechanisms**
   - Timeout with partial results
   - Graceful degradation
   - Error summaries for TTS

## Related Files

- `/home/hvksh/ai-automation/mcp/codex-mcp-gateway.py` - Gateway process
- `/home/hvksh/ai-automation/services/mcp_sse_client.py` - SSE client with multi-stage support
- `/home/hvksh/ai-automation/services/bridge.py` - Bridge with response formatting
- `/home/hvksh/ai-automation/mcp/start-all-mcp.sh` - Updated startup script