#!/usr/bin/env python3
"""
MCP SSE Client Module
Manages SSE connections to MCP servers via mcp-proxy
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timedelta
import os
import httpx
from httpx_sse import aconnect_sse, ServerSentEvent
from contextlib import asynccontextmanager
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

@dataclass
class MCPServer:
    """MCP Server configuration"""
    name: str
    url: str
    codex_home: str
    tool_name: str  # Tool name for this server (e.g., "codex")

@dataclass
class SSESession:
    """SSE session information"""
    endpoint_url: str  # The POST endpoint with session_id
    event_source: Any  # SSE connection
    created_at: datetime

class MCPSSEClient:
    """
    Manages SSE connections to MCP servers via mcp-proxy
    Implements the MCP protocol over SSE transport
    """
    
    def __init__(self):
        # Get base directory from environment or use default
        base_dir = os.environ.get('CODEX_BASE_DIR', os.path.expanduser('~'))
        
        self.servers = {
            "router": MCPServer(
                name="router",
                url="http://127.0.0.1:8090",
                codex_home=os.path.join(base_dir, ".codex"),
                tool_name="codex"
            ),
            "office": MCPServer(
                name="office",
                url="http://127.0.0.1:8081", 
                codex_home=os.path.join(base_dir, "admin", ".codex"),
                tool_name="codex"  # office-assistant uses "codex" tool
            ),
            "analyst": MCPServer(
                name="analyst",
                url="http://127.0.0.1:8082",
                codex_home=os.path.join(base_dir, "finance", ".codex"),
                tool_name="codex"  # analyst-assistant uses "codex" tool  
            )
        }
        
        self.client = httpx.AsyncClient(timeout=30.0)
        self._message_id = 1
        self.sessions: Dict[str, SSESession] = {}
        
    def _get_next_id(self) -> int:
        """Get next message ID for JSON-RPC"""
        current = self._message_id
        self._message_id += 1
        return current
    
    async def _get_endpoint_from_sse(self, server_name: str) -> str:
        """
        Connect to SSE and get the endpoint URL for messages
        
        Returns:
            The endpoint URL containing session_id for POST messages
        """
        if server_name not in self.servers:
            raise ValueError(f"Unknown server: {server_name}")
        
        server = self.servers[server_name]
        sse_url = f"{server.url}/sse"
        
        # Connect to SSE and listen for endpoint event
        async with aconnect_sse(
            self.client,
            "GET",
            sse_url,
            headers={"Accept": "text/event-stream"}
        ) as event_source:
            
            # Listen for the first event which should be "endpoint"
            async for event in event_source.aiter_sse():
                if event.event == "endpoint":
                    # The endpoint is sent directly as plain text, not JSON
                    endpoint_path = event.data
                    
                    # Build full URL
                    if endpoint_path.startswith("http"):
                        return endpoint_path
                    else:
                        # Relative path, combine with server URL
                        return urljoin(server.url, endpoint_path)
            
        # If we get here, no endpoint was received
        # Fall back to default pattern
        import uuid
        session_id = str(uuid.uuid4())
        return f"{server.url}/messages/?session_id={session_id}"
    
    async def send_prompt(self, server_name: str, prompt: str, 
                          stream: bool = False) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Send a prompt to an MCP server via SSE
        
        Args:
            server_name: Name of the server (router, office, analyst)
            prompt: The prompt to send
            stream: Whether to stream responses
            
        Yields:
            Response chunks from the MCP server
        """
        if server_name not in self.servers:
            raise ValueError(f"Unknown server: {server_name}")
        
        server = self.servers[server_name]
        
        # Track the request ID for matching responses
        prompt_request_id = self._get_next_id()
        
        # Build the MCP request following JSON-RPC format
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": server.tool_name,
                "arguments": {
                    "prompt": prompt,
                    "cwd": "/home/hvksh" if server_name == "router" else f"/home/hvksh/{server_name}"
                }
            },
            "id": prompt_request_id
        }
        
        try:
            # Establish SSE connection and get endpoint
            sse_url = f"{server.url}/sse"
            
            async with aconnect_sse(
                self.client,
                "GET",
                sse_url,
                headers={"Accept": "text/event-stream"}
            ) as event_source:
                
                # Variable to store endpoint URL
                endpoint_url = None
                init_request_id = None
                prompt_sent = False
                
                # Read events until we get endpoint or can send message
                async for event in event_source.aiter_sse():
                    
                    # Check for endpoint event
                    if event.event == "endpoint" and not endpoint_url:
                        # The endpoint is sent directly as plain text, not JSON
                        endpoint_path = event.data
                        endpoint_url = urljoin(server.url, endpoint_path)
                        
                        # Track initialization request ID
                        init_request_id = self._get_next_id()
                        
                        # Initialize the session first  
                        if not await self._initialize_session_with_id(endpoint_url, init_request_id):
                            yield {
                                "type": "error",
                                "content": "Failed to initialize MCP session"
                            }
                            return
                        
                        # Wait for initialization to complete
                        await asyncio.sleep(0.5)
                        
                        # Send the actual request
                        response = await self.client.post(
                            endpoint_url,
                            json=request,
                            headers={"Content-Type": "application/json"}
                        )
                        
                        prompt_sent = True
                        
                        if response.status_code not in (200, 202):
                            yield {
                                "type": "error",
                                "content": f"Failed to send message: {response.status_code} - {response.text}"
                            }
                            return
                    
                    # Check for message events (responses)
                    elif event.event == "message" or (event.event is None and event.data):
                        try:
                            data = json.loads(event.data)
                            
                            # Check message ID to match with our prompt request
                            message_id = data.get("id")
                            
                            # Only process responses matching our prompt request ID
                            if message_id == prompt_request_id:
                                # Handle different message types
                                if "result" in data:
                                    yield {
                                        "type": "result",
                                        "content": data["result"]
                                    }
                                    return
                                    
                                elif "error" in data:
                                    yield {
                                        "type": "error",
                                        "content": data.get("error", {}).get("message", str(data["error"]))
                                    }
                                    return
                            
                            # Handle streaming chunks (may not have ID)
                            elif stream and "chunk" in data and prompt_sent:
                                yield {
                                    "type": "chunk",
                                    "content": data["chunk"]
                                }
                                    
                        except json.JSONDecodeError as e:
                            logger.warning(f"Invalid JSON from {server_name}: {e} - Data: {event.data}")
                            continue
                
                # If no endpoint was found, try default pattern
                if not endpoint_url:
                    endpoint_url = f"{server.url}/messages/"
                    response = await self.client.post(
                        endpoint_url,
                        json=request,
                        headers={"Content-Type": "application/json"}
                    )
                    
                    if response.status_code == 400:
                        # Try with a session_id
                        import uuid
                        endpoint_url = f"{server.url}/messages/?session_id={uuid.uuid4()}"
                        response = await self.client.post(
                            endpoint_url,
                            json=request,
                            headers={"Content-Type": "application/json"}
                        )
                    
                    if response.status_code != 200:
                        yield {
                            "type": "error",
                            "content": f"Failed to send message: {response.status_code} - {response.text}"
                        }
                            
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from {server_name}: {e.response.status_code}")
            yield {
                "type": "error",
                "content": f"HTTP {e.response.status_code}: {e.response.text}"
            }
            
        except Exception as e:
            logger.error(f"Error communicating with {server_name}: {e}")
            yield {
                "type": "error", 
                "content": str(e)
            }
    
    async def _initialize_session_with_id(self, endpoint_url: str, init_id: int) -> bool:
        """
        Send initialization sequence to MCP server with specific ID
        
        Returns:
            True if initialization succeeded
        """
        try:
            # Send initialize request
            init_request = {
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "0.1.0",
                    "capabilities": {
                        "tools": {},
                        "prompts": {},
                        "resources": {}
                    },
                    "clientInfo": {
                        "name": "bridge-client",
                        "version": "1.0.0"
                    }
                },
                "id": init_id
            }
            
            response = await self.client.post(
                endpoint_url,
                json=init_request,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code not in (200, 202):
                return False
            
            # Send initialized notification
            initialized_notif = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {}
            }
            
            response = await self.client.post(
                endpoint_url,
                json=initialized_notif,
                headers={"Content-Type": "application/json"}
            )
            
            return response.status_code in (200, 202)
            
        except Exception as e:
            logger.error(f"Failed to initialize session: {e}")
            return False
    
    async def _initialize_session(self, endpoint_url: str) -> bool:
        """
        Send initialization sequence to MCP server
        
        Returns:
            True if initialization succeeded
        """
        try:
            # Send initialize request
            init_request = {
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "0.1.0",
                    "capabilities": {
                        "tools": {},
                        "prompts": {},
                        "resources": {}
                    },
                    "clientInfo": {
                        "name": "bridge-client",
                        "version": "1.0.0"
                    }
                },
                "id": self._get_next_id()
            }
            
            response = await self.client.post(
                endpoint_url,
                json=init_request,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code not in (200, 202):
                return False
            
            # Send initialized notification
            initialized_notif = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {}
            }
            
            response = await self.client.post(
                endpoint_url,
                json=initialized_notif,
                headers={"Content-Type": "application/json"}
            )
            
            return response.status_code in (200, 202)
            
        except Exception as e:
            logger.error(f"Failed to initialize session: {e}")
            return False
    
    async def list_tools(self, server_name: str) -> Dict[str, Any]:
        """
        List available tools on an MCP server
        
        Args:
            server_name: Name of the server
            
        Returns:
            List of available tools
        """
        if server_name not in self.servers:
            raise ValueError(f"Unknown server: {server_name}")
        
        server = self.servers[server_name]
        
        # Build tools/list request
        request = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},  # Empty params object required
            "id": self._get_next_id()
        }
        
        try:
            sse_url = f"{server.url}/sse"
            
            async with aconnect_sse(
                self.client,
                "GET",
                sse_url,
                headers={"Accept": "text/event-stream"}
            ) as event_source:
                
                endpoint_url = None
                initialized = False
                request_sent = False
                
                async for event in event_source.aiter_sse():
                    
                    # Get endpoint and initialize
                    if event.event == "endpoint" and not endpoint_url:
                        # The endpoint is sent directly as plain text, not JSON
                        endpoint_path = event.data
                        endpoint_url = urljoin(server.url, endpoint_path)
                        
                        # Initialize the session
                        if await self._initialize_session(endpoint_url):
                            initialized = True
                            # Wait a bit for initialization to complete
                            await asyncio.sleep(0.5)
                            
                            # Send the actual request
                            response = await self.client.post(
                                endpoint_url,
                                json=request,
                                headers={"Content-Type": "application/json"}
                            )
                            request_sent = True
                            
                            if response.status_code not in (200, 202):
                                raise Exception(f"Failed to send message: {response.status_code}")
                        else:
                            raise Exception("Failed to initialize session")
                    
                    # Read response
                    elif request_sent and (event.event == "message" or (event.event is None and event.data)):
                        try:
                            data = json.loads(event.data)
                            
                            # Skip initialization responses
                            if "result" in data:
                                # Check if this is the tools response (not init response)
                                result = data["result"]
                                if "tools" in result:
                                    return result
                                # Otherwise might be init response, skip
                            elif "error" in data:
                                raise Exception(f"Error listing tools: {data['error']}")
                                
                        except json.JSONDecodeError:
                            continue
                            
        except Exception as e:
            logger.error(f"Error listing tools on {server_name}: {e}")
            raise
    
    async def health_check(self) -> Dict[str, str]:
        """Check health of all MCP servers"""
        status = {}
        
        for server_name in self.servers.keys():
            try:
                # Try to list tools as a health check
                result = await self.list_tools(server_name)
                if result and "tools" in result:
                    status[server_name] = f"healthy ({len(result['tools'])} tools)"
                else:
                    status[server_name] = "unhealthy (no tools)"
            except asyncio.TimeoutError:
                status[server_name] = "timeout"
            except Exception as e:
                status[server_name] = f"error: {str(e)[:50]}"
        
        return status
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()

# Singleton instance
_client_instance: Optional[MCPSSEClient] = None

@asynccontextmanager
async def get_mcp_client():
    """Get or create the singleton MCP SSE client"""
    global _client_instance
    
    if _client_instance is None:
        _client_instance = MCPSSEClient()
    
    try:
        yield _client_instance
    finally:
        # Keep client alive for connection reuse
        pass

async def close_mcp_client():
    """Close the singleton MCP client"""
    global _client_instance
    if _client_instance:
        await _client_instance.close()
        _client_instance = None