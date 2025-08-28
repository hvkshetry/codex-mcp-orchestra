#!/usr/bin/env python3
"""
codex-mcp-gateway.py - Robust gateway process for Codex MCP
- Spawns codex subprocess with proper signal handling  
- Filters stdout: removes banners, converts events
- Preserves stderr and exit codes
- Streams reasoning tokens for TTS
"""
import asyncio
import sys
import signal
import json
import os
from pathlib import Path

BANNER_HINTS = ("MCP Doc Forge Server", "Server is running", "Starting", "Listening")

class CodexGateway:
    def __init__(self, codex_cmd: str, args: list):
        self.codex_cmd = codex_cmd
        self.args = args
        self.process = None
        self.exit_code = 0
        
    async def start(self):
        """Start codex subprocess and handle I/O"""
        # Start codex process
        self.process = await asyncio.create_subprocess_exec(
            self.codex_cmd,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ
        )
        
        # Set up signal handlers
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda s, f: asyncio.create_task(self.shutdown(s)))
        
        # Start I/O tasks
        await asyncio.gather(
            self.forward_stdin(),
            self.filter_stdout(),
            self.forward_stderr(),
            return_exceptions=True
        )
        
        # Wait for process to exit
        self.exit_code = await self.process.wait()
        
    async def forward_stdin(self):
        """Forward stdin to codex process"""
        try:
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)
            
            while True:
                line = await reader.readline()
                if not line:
                    break
                self.process.stdin.write(line)
                await self.process.stdin.drain()
        except Exception as e:
            print(f"[gateway] stdin error: {e}", file=sys.stderr)
    
    async def filter_stdout(self):
        """Filter codex stdout and forward to our stdout"""
        try:
            async for line in self.process.stdout:
                line_str = line.decode('utf-8').strip()
                
                # Skip banners and non-JSON
                if not line_str or (not line_str.startswith("{") and not line_str.startswith("[")):
                    if any(hint in line_str for hint in BANNER_HINTS):
                        print(f"[gateway] dropped banner: {line_str!r}", file=sys.stderr)
                    continue
                
                try:
                    obj = json.loads(line_str)
                    
                    # Convert codex/event to notifications/message
                    if obj.get("method") == "codex/event":
                        converted = self.convert_event(obj)
                        if converted is None:
                            continue
                        obj = converted
                    
                    # Emit filtered JSON
                    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
                    sys.stdout.flush()
                    
                except json.JSONDecodeError:
                    print(f"[gateway] invalid JSON: {line_str!r}", file=sys.stderr)
                    
        except Exception as e:
            print(f"[gateway] stdout error: {e}", file=sys.stderr)
    
    def convert_event(self, obj):
        """Convert codex/event to MCP notifications/message format"""
        params = obj.get("params", {})
        msg = params.get("msg", {})
        event_type = msg.get("type")
        
        # Silent internal events
        if event_type == "session_configured":
            return None
            
        # Preserve event types for proper multi-stage handling
        # Agent message streaming
        elif event_type == "agent_message_delta":
            return {
                "jsonrpc": "2.0",
                "method": f"notifications/{event_type}",
                "params": {
                    "type": event_type,
                    "delta": msg.get("delta", "")
                }
            }
        
        # Reasoning streaming (for TTS)
        elif event_type in ["agent_reasoning_delta", "agent_reasoning_raw_content_delta"]:
            return {
                "jsonrpc": "2.0",
                "method": f"notifications/{event_type}",
                "params": {
                    "type": event_type,
                    "delta": msg.get("delta", "")
                }
            }
        
        # Tool call events - pass through but marked
        elif event_type in ["mcp_tool_call_begin", "mcp_tool_call_end"]:
            return {
                "jsonrpc": "2.0",
                "method": f"notifications/{event_type}",
                "params": msg
            }
        
        # Task completion - preserve original structure
        elif event_type == "task_complete":
            return obj  # Pass through unchanged for proper handling
        
        # Other events as structured data
        else:
            return {
                "jsonrpc": "2.0",
                "method": "notifications/message",
                "params": {
                    "level": "info",
                    "data": msg,
                    "logger": "codex"
                }
            }
    
    async def forward_stderr(self):
        """Forward stderr to log file"""
        try:
            log_path = "/tmp/codex-mcp-stderr.log"
            with open(log_path, "a") as log:
                async for line in self.process.stderr:
                    log.write(line.decode('utf-8'))
                    log.flush()
        except Exception as e:
            print(f"[gateway] stderr error: {e}", file=sys.stderr)
    
    async def shutdown(self, signum):
        """Clean shutdown on signal"""
        if self.process:
            self.process.terminate()
            await asyncio.sleep(0.5)
            if self.process.returncode is None:
                self.process.kill()

async def main():
    if len(sys.argv) < 2:
        print("Usage: codex-mcp-gateway.py <codex-cmd> [args...]", file=sys.stderr)
        sys.exit(1)
    
    gateway = CodexGateway(sys.argv[1], sys.argv[2:])
    await gateway.start()
    sys.exit(gateway.exit_code)

if __name__ == "__main__":
    asyncio.run(main())