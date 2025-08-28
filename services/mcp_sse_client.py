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
                tool_name="codex"  # Updated to use "codex" command
            ),
            "office": MCPServer(
                name="office",
                url="http://127.0.0.1:8081", 
                codex_home=os.path.join(base_dir, "admin", ".codex"),
                tool_name="codex"  # Updated to use "codex" command
            ),
            "analyst": MCPServer(
                name="analyst",
                url="http://127.0.0.1:8082",
                codex_home=os.path.join(base_dir, "investing", ".codex"),
                tool_name="codex-custom"  # Keeping "codex-custom" for analyst as per user request
            )
        }
        
        # Increase timeout to 10 minutes for complex MCP operations
        self.client = httpx.AsyncClient(timeout=600.0)
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
                    "cwd": os.path.expanduser("~") if server_name == "router" else os.path.join(os.path.expanduser("~"), server_name)
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
                task_complete = False
                collected_result = None
                
                # Track Codex event states
                session_configured = False
                
                # Multi-stage response collection
                reasoning_chunks = []
                message_chunks = []
                has_tool_error = False
                task_complete = False
                collected_result = None
                
                logger.info(f"Connecting to SSE endpoint: {sse_url}")
                
                # Keep reading events until task is complete or timeout
                async for event in event_source.aiter_sse():
                    
                    logger.debug(f"Received SSE event: type={event.event}, data_len={len(event.data) if event.data else 0}")
                    
                    # Check for endpoint event
                    if event.event == "endpoint" and not endpoint_url:
                        # The endpoint is sent directly as plain text, not JSON
                        endpoint_path = event.data
                        endpoint_url = urljoin(server.url, endpoint_path)
                        logger.info(f"Got endpoint URL: {endpoint_url}")
                        
                        # Track initialization request ID
                        init_request_id = self._get_next_id()
                        
                        # Initialize the session first  
                        if not await self._initialize_session_with_id(endpoint_url, init_request_id):
                            yield {
                                "type": "error",
                                "content": "Failed to initialize MCP session"
                            }
                            return
                        
                        logger.info("MCP session initialized successfully")
                        
                        # Wait for session_configured event instead of fixed sleep
                        if not session_configured:
                            config_timeout = asyncio.create_task(asyncio.sleep(2.0))
                            start_time = asyncio.get_event_loop().time()
                            while not session_configured and not config_timeout.done():
                                await asyncio.sleep(0.1)
                                if asyncio.get_event_loop().time() - start_time > 2.0:
                                    break
                        
                        # Send the actual request
                        logger.info(f"Sending prompt request with ID {prompt_request_id}")
                        response = await self.client.post(
                            endpoint_url,
                            json=request,
                            headers={"Content-Type": "application/json"}
                        )
                        
                        prompt_sent = True
                        
                        if response.status_code not in (200, 202):
                            logger.error(f"Failed to send prompt: {response.status_code} - {response.text}")
                            yield {
                                "type": "error",
                                "content": f"Failed to send message: {response.status_code} - {response.text}"
                            }
                            return
                        
                        logger.info(f"Prompt sent successfully, status: {response.status_code}")
                    
                    # Check for message events (responses)
                    elif prompt_sent and (event.event == "message" or (event.event is None and event.data)):
                        try:
                            data = json.loads(event.data)
                            
                            logger.debug(f"Parsed message data: method={data.get('method')}, id={data.get('id')}, has_result={'result' in data}")
                            
                            # Handle Codex-specific events
                            if "method" in data:
                                method = data.get("method")
                                
                                # Handle Codex events (session_configured, agent_message_delta, task_complete)
                                if method == "codex/event":
                                    params = data.get("params", {})
                                    # The event structure has msg containing the actual event
                                    msg = params.get("msg", {})
                                    event_type = msg.get("type")
                                    
                                    logger.info(f"Codex event: {event_type}")
                                    logger.debug(f"Full event params: {json.dumps(params, default=str)[:500]}")
                                    
                                    if event_type == "session_configured":
                                        session_configured = True
                                        logger.info("Codex session configured")
                                    
                                    elif event_type == "agent_message_delta":
                                        # Delta is in msg.delta not params.content
                                        content = msg.get("delta", "")
                                        if stream and content:
                                            yield {
                                                "type": "chunk",
                                                "content": content
                                            }
                                    
                                    elif event_type == "task_complete":
                                        task_complete = True
                                        # Extract the final response from last_agent_message
                                        last_agent_message = msg.get("last_agent_message", "")
                                        if last_agent_message:
                                            logger.info(f"Got task_complete with response: {last_agent_message[:100]}...")
                                            # Format the response as expected by the bridge
                                            collected_result = {
                                                "content": [{"type": "text", "text": last_agent_message}],
                                                "isError": False
                                            }
                                        else:
                                            logger.warning("task_complete received but no last_agent_message")
                                        # Mark as complete and continue to yield the result
                                
                                # Handle new schema events (method matches event type)
                                elif method == "session_configured":
                                    session_configured = True
                                    logger.info("Codex session configured (new schema)")
                                
                                # Handle converted notification events from gateway
                                elif method.startswith("notifications/"):
                                    params = data.get("params", {})
                                    event_type = params.get("type", "")
                                    
                                    if event_type == "agent_message_delta":
                                        delta = params.get("delta", "")
                                        message_chunks.append(delta)
                                        if stream and delta:
                                            yield {
                                                "type": "message",
                                                "content": delta
                                            }
                                    
                                    elif event_type in ["agent_reasoning_delta", "agent_reasoning_raw_content_delta"]:
                                        delta = params.get("delta", "")
                                        reasoning_chunks.append(delta)
                                        if stream and delta:
                                            yield {
                                                "type": "reasoning",
                                                "content": delta
                                            }
                                    
                                    elif event_type == "mcp_tool_call_end":
                                        # Check for tool errors to track retry behavior
                                        result = params.get("result", {})
                                        if isinstance(result, dict) and "error" in result:
                                            has_tool_error = True
                                            logger.info("Tool call error detected, waiting for Codex to retry...")
                                
                                elif method == "task_complete":
                                    task_complete = True
                                    # Combine all collected responses
                                    final_message = "".join(message_chunks) if message_chunks else data.get("params", {}).get("last_agent_message", "")
                                    collected_result = {
                                        "reasoning": "".join(reasoning_chunks),
                                        "message": final_message,
                                        "had_retry": has_tool_error
                                    }
                                    logger.info(f"Task complete with {len(reasoning_chunks)} reasoning chunks and {len(message_chunks)} message chunks")
                                
                                # Handle streaming notifications
                                elif method == "notifications/message":
                                    params = data.get("params", {})
                                    
                                    # Check for reasoning content (both from MCP standard and our conversion)
                                    if params.get("logger") == "reasoning" or \
                                       (isinstance(params.get("data"), dict) and params.get("data", {}).get("type") == "reasoning"):
                                        if stream:
                                            content = params.get("data", {}).get("content", "") if isinstance(params.get("data"), dict) else str(params.get("data", ""))
                                            yield {
                                                "type": "reasoning",
                                                "content": content
                                            }
                                    # Check for regular text chunks
                                    elif params.get("data", {}).get("type") == "text":
                                        if stream:
                                            yield {
                                                "type": "chunk", 
                                                "content": params.get("data", {}).get("content", "")
                                            }
                                    # Handle plain string data from our gateway
                                    elif params.get("logger") == "agent" and isinstance(params.get("data"), str):
                                        if stream:
                                            yield {
                                                "type": "chunk",
                                                "content": params.get("data", "")
                                            }
                            
                            # Check message ID to match with our prompt request
                            message_id = data.get("id")
                            
                            # Process responses matching our prompt request ID
                            if message_id == prompt_request_id:
                                # Handle different message types
                                if "result" in data:
                                    logger.info(f"Got result for request {prompt_request_id}")
                                    # Only store if we don't have a result from task_complete
                                    if collected_result is None:
                                        collected_result = data["result"]
                                    # Return result immediately when available
                                    # Don't wait for task_complete since it may be filtered by gateway
                                    if collected_result is not None:
                                        yield {
                                            "type": "result",
                                            "content": collected_result
                                        }
                                        return
                                    
                                elif "error" in data:
                                    logger.error(f"Got error for request {prompt_request_id}: {data['error']}")
                                    yield {
                                        "type": "error",
                                        "content": data.get("error", {}).get("message", str(data["error"]))
                                    }
                                    return
                            
                            # Handle streaming chunks (may not have ID)
                            elif stream and prompt_sent and not message_id:
                                # Fallback for simple chunk format
                                if "chunk" in data:
                                    yield {
                                        "type": "chunk",
                                        "content": data["chunk"]
                                    }
                                    
                        except json.JSONDecodeError as e:
                            logger.warning(f"Invalid JSON from {server_name}: {e} - Data: {event.data[:100]}")
                            continue
                    
                    # Check if we have completed and have a result
                    if task_complete and collected_result is not None:
                        logger.info("Task complete with result, yielding final response")
                        yield {
                            "type": "result",
                            "content": collected_result
                        }
                        return
                
                # If we exit the loop without a result, that's an error
                logger.error(f"SSE connection closed without receiving a complete response")
                if collected_result is not None:
                    # We have a result but didn't get task_complete - yield it anyway
                    yield {
                        "type": "result",
                        "content": collected_result
                    }
                else:
                    yield {
                        "type": "error",
                        "content": "Connection closed without receiving a response"
                    }
                            
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from {server_name}: {e.response.status_code}")
            yield {
                "type": "error",
                "content": f"HTTP {e.response.status_code}: {e.response.text}"
            }
            
        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for response from {server_name}")
            yield {
                "type": "error",
                "content": "Request timed out waiting for response"
            }
            
        except Exception as e:
            logger.error(f"Error communicating with {server_name}: {e}", exc_info=True)
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
        
        logger.info(f"Listing tools for {server_name} server")
        
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
                    
                    logger.debug(f"List tools SSE event: type={event.event}")
                    
                    # Get endpoint and initialize
                    if event.event == "endpoint" and not endpoint_url:
                        # The endpoint is sent directly as plain text, not JSON
                        endpoint_path = event.data
                        endpoint_url = urljoin(server.url, endpoint_path)
                        logger.info(f"Got endpoint for tools list: {endpoint_url}")
                        
                        # Initialize the session
                        if await self._initialize_session(endpoint_url):
                            initialized = True
                            logger.info("Session initialized for tools list")
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
                            logger.info(f"Tools list request sent, status: {response.status_code}")
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
                                    logger.info(f"Got {len(result['tools'])} tools from {server_name}")
                                    return result
                                # Otherwise might be init response, skip
                            elif "error" in data:
                                raise Exception(f"Error listing tools: {data['error']}")
                                
                        except json.JSONDecodeError:
                            logger.warning(f"Invalid JSON in tools list response")
                            continue
                            
        except Exception as e:
            logger.error(f"Error listing tools on {server_name}: {e}", exc_info=True)
            raise
    
    async def health_check(self) -> Dict[str, str]:
        """Check health of all MCP servers"""
        status = {}
        
        logger.info("Starting health check for all MCP servers")
        
        for server_name in self.servers.keys():
            try:
                logger.info(f"Checking health of {server_name} server")
                # Try to list tools as a health check
                result = await self.list_tools(server_name)
                if result and "tools" in result:
                    tool_count = len(result['tools'])
                    status[server_name] = f"healthy ({tool_count} tools)"
                    logger.info(f"{server_name}: healthy with {tool_count} tools")
                else:
                    status[server_name] = "unhealthy (no tools)"
                    logger.warning(f"{server_name}: unhealthy - no tools found")
            except asyncio.TimeoutError:
                status[server_name] = "timeout"
                logger.error(f"{server_name}: health check timeout")
            except Exception as e:
                status[server_name] = f"error: {str(e)[:50]}"
                logger.error(f"{server_name}: health check error - {e}")
        
        logger.info(f"Health check complete: {status}")
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