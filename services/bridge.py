#!/usr/bin/env python3
"""
Windows-WSL Bridge Service
Handles communication between Windows voice capture and WSL MCP servers
"""

import asyncio
import json
import logging
import os
import aiohttp
from typing import Dict, Any, Optional, Set
from pathlib import Path
from datetime import datetime, timedelta

import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

# Add current directory to path for imports
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import SSE client
from mcp_sse_client import get_mcp_client, close_mcp_client

# Import session manager and voice config
from session_manager import get_session_manager, process_with_session, record_response
from config.voice_personalities import (
    get_agent_voice, get_agent_from_keywords, 
    get_handoff_message, get_email_announcement
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Windows-WSL Bridge Service")

# MCP server configuration is now in mcp_sse_client.py

# Whisper service endpoint
WHISPER_SERVICE = "http://127.0.0.1:7001"

class VoiceRequest(BaseModel):
    """Voice command request"""
    audio_data: Optional[str] = None  # Base64 encoded audio
    text: Optional[str] = None  # Pre-transcribed text
    wake_word: str = "router"  # Which specialist to route to
    session_id: Optional[str] = None
    stream: bool = False  # Whether to stream responses
    two_stage_mode: bool = False  # Whether using two-stage wake detection
    enable_tts: bool = True  # Whether to call TTS service

class MCPMessage(BaseModel):
    """MCP protocol message"""
    jsonrpc: str = "2.0"
    method: str
    params: Dict[str, Any]
    id: Optional[int] = None

class EmailNotification(BaseModel):
    """Graph API email notification"""
    changeType: str
    clientState: str
    resource: str
    subscriptionId: str
    tenantId: str

# Import email router
try:
    from email_router import get_router
    email_router_available = True
except ImportError:
    logger.warning("Email router not available")
    email_router_available = False

# Idempotency tracking
processed_message_ids: Set[str] = set()
idempotency_window = timedelta(hours=24)  # Keep IDs for 24 hours
last_cleanup = datetime.now()

async def send_to_mcp(server: str, prompt: str, stream: bool = False, 
                      context: Optional[str] = None) -> Dict[str, Any]:
    """
    Send a prompt to an MCP server via SSE with context
    
    Args:
        server: Server name (router, office, analyst)
        prompt: The prompt to send
        stream: Whether to stream responses
        context: Optional conversation context
    
    Returns:
        Response from the MCP server (or generator for streaming)
    """
    try:
        # Include context in prompt if provided
        full_prompt = prompt
        if context:
            full_prompt = f"Previous context:\n{context}\n\nCurrent request: {prompt}"
        
        async with get_mcp_client() as client:
            if stream:
                # Return async generator for streaming
                return client.send_prompt(server, full_prompt, stream=True)
            else:
                # Collect full response
                full_response = None
                async for chunk in client.send_prompt(server, full_prompt, stream=False):
                    if chunk["type"] == "result":
                        full_response = chunk["content"]
                    elif chunk["type"] == "error":
                        logger.error(f"MCP error from {server}: {chunk['content']}")
                        raise HTTPException(
                            status_code=500,
                            detail=f"MCP error: {chunk['content']}"
                        )
                
                if full_response is None:
                    raise HTTPException(
                        status_code=500,
                        detail="No response from MCP server"
                    )
                
                return {"result": full_response}
                
    except Exception as e:
        logger.error(f"Error communicating with MCP {server}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"MCP communication error: {str(e)}"
        )

async def transcribe_audio(audio_base64: str) -> str:
    """
    Send audio to Whisper service for transcription
    
    Args:
        audio_base64: Base64 encoded audio data
    
    Returns:
        Transcribed text
    """
    import base64
    import tempfile
    import os
    
    # Send base64 audio directly to Whisper service
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{WHISPER_SERVICE}/transcribe",
                json={"audio_data": audio_base64},
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result["transcription"]
                else:
                    error_text = await response.text()
                    raise HTTPException(
                        status_code=response.status,
                        detail=f"Whisper error: {error_text}"
                    )
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

@app.post("/voice/command")
async def handle_voice_command(request: VoiceRequest):
    """
    Handle voice command from Windows with session management and multi-voice support
    
    1. Transcribe audio if needed
    2. Detect target agent (two-stage if enabled)
    3. Route to appropriate MCP server with context
    4. Return response with voice personality
    """
    try:
        # Get text (transcribe if needed)
        if request.text:
            prompt = request.text
            logger.info(f"Using pre-transcribed text: {prompt}")
        elif request.audio_data:
            logger.info("Transcribing audio...")
            prompt = await transcribe_audio(request.audio_data)
            logger.info(f"Transcribed: {prompt}")
        else:
            raise HTTPException(
                status_code=400,
                detail="Either text or audio_data must be provided"
            )
        
        # Determine which server to use
        if request.two_stage_mode:
            # Detect agent from keywords in the prompt
            server = get_agent_from_keywords(prompt)
            logger.info(f"Two-stage detection: routing to {server}")
        else:
            # Use explicit wake word mapping
            server_map = {
                "router": "router",
                "assistant": "router",
                "deep thought": "router",
                "office": "office",
                "hey office": "office",
                "analyst": "analyst",
                "hey analyst": "analyst",
                "procurement": "procurement",
                "engineering": "engineering",
                "accounting": "accounting"
            }
            server = server_map.get(request.wake_word.lower(), "router")
            
        logger.info(f"Routing to {server} server")
        
        # Process with session management
        session_id = request.session_id or f"voice_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        session_info = await process_with_session(session_id, prompt, server, "voice")
        
        # Get voice personality for this agent
        voice_config = get_agent_voice(server)
        
        # Send to MCP server with context
        if request.stream:
            # Stream responses back
            async def generate():
                async for chunk in await send_to_mcp(server, prompt, stream=True, context=session_info["context"]):
                    data = json.dumps({
                        "type": chunk["type"],
                        "content": chunk["content"],
                        "server": server,
                        "session_id": session_id,
                        "voice": voice_config["voice"]
                    })
                    yield f"data: {data}\n\n"
            
            return StreamingResponse(
                generate(),
                media_type="text/event-stream"
            )
        else:
            # Non-streaming response
            response = await send_to_mcp(server, prompt, stream=False, context=session_info["context"])
            
            # Extract the actual response text
            response_text = ""
            if "result" in response:
                result = response["result"]
                if isinstance(result, dict) and "content" in result:
                    response_text = result["content"][0]["text"]
            else:
                response_text = str(response)
            
            # Record response in session
            await record_response(session_id, response_text, server)
            
            # Return with voice configuration
            return JSONResponse(content={
                "response": response_text,
                "server": server,
                "session_id": session_id,
                "voice": voice_config["voice"],
                "voice_config": {
                    "speed": voice_config["speed"],
                    "pitch": voice_config["pitch"]
                }
            })
        
    except Exception as e:
        logger.error(f"Error handling voice command: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/email/notification")
async def validate_webhook(validation_token: Optional[str] = None):
    """
    Validate Graph API webhook subscription
    Microsoft sends a GET request with validationToken to verify endpoint
    """
    if validation_token:
        logger.info(f"Validating webhook with token: {validation_token[:20]}...")
        return validation_token
    
    raise HTTPException(status_code=400, detail="No validation token provided")

@app.post("/email/notification")
async def handle_email_notification(notification: Dict[str, Any]):
    """
    Handle email notification webhook
    Routes to office-assistant for processing
    """
    try:
        # Extract relevant information
        change_type = notification.get("changeType", "")
        resource = notification.get("resource", "")
        
        # Build prompt for office assistant
        prompt = f"Process email notification: {change_type} on {resource}"
        
        # Send to office MCP server
        response = await send_to_mcp("office", prompt)
        
        return JSONResponse(content={
            "status": "processed",
            "response": response
        })
        
    except Exception as e:
        logger.error(f"Error handling email notification: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """
    Health check endpoint
    Also checks connectivity to MCP servers
    """
    status = {"status": "healthy", "servers": {}}
    
    # Check MCP servers via SSE client
    try:
        async with get_mcp_client() as client:
            server_status = await client.health_check()
            status["servers"] = server_status
    except Exception as e:
        logger.error(f"Error checking MCP health: {e}")
        status["servers"] = {"error": str(e)}
    
    # Check Whisper service
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{WHISPER_SERVICE}/health", timeout=2) as response:
                if response.status == 200:
                    status["whisper"] = "healthy"
                else:
                    status["whisper"] = "unhealthy"
    except:
        status["whisper"] = "unreachable"
    
    return status

@app.get("/servers")
async def list_servers():
    """
    List available MCP servers and their endpoints
    """
    servers = {}
    async with get_mcp_client() as client:
        for name, server in client.servers.items():
            servers[name] = f"SSE connection to {server.url}"
    
    return {
        "servers": servers,
        "whisper": WHISPER_SERVICE,
        "wake_words": {
            "router": ["router", "assistant", "deep thought"],
            "office": ["office", "hey office"],
            "analyst": ["analyst", "hey analyst"]
        }
    }

@app.post("/email/route")
async def handle_email_route(request: Request):
    """
    Handle email routing from Graph API webhook
    Implements idempotency and suffix-based routing
    """
    global processed_message_ids, last_cleanup
    
    # Clean up old message IDs periodically
    if datetime.now() - last_cleanup > timedelta(hours=1):
        processed_message_ids.clear()
        last_cleanup = datetime.now()
        logger.info("Cleared processed message ID cache")
    
    try:
        # Parse webhook notification
        body = await request.json()
        
        # Handle validation request
        if "validationToken" in request.query_params:
            return request.query_params["validationToken"]
        
        # Process notifications
        notifications = body.get("value", [])
        results = []
        
        for notification in notifications:
            resource = notification.get("resource", "")
            change_type = notification.get("changeType", "")
            
            # Extract message ID from resource path
            # Format: users/{id}/messages/{messageId}
            parts = resource.split("/")
            if len(parts) >= 4 and parts[2] == "messages":
                message_id = parts[3]
                
                # Check idempotency
                if message_id in processed_message_ids:
                    logger.info(f"Skipping duplicate message: {message_id}")
                    continue
                
                # Mark as processed
                processed_message_ids.add(message_id)
                
                # Get message details from Graph API
                # This would need the Office MCP server's auth token
                # For now, we'll parse from notification
                
                if email_router_available:
                    router = get_router()
                    
                    # Mock message object for router
                    # In production, fetch from Graph API
                    mock_message = {
                        "id": message_id,
                        "toRecipients": [],
                        "ccRecipients": [],
                        "internetMessageHeaders": []
                    }
                    
                    # Route the message
                    routing = router.route_email(mock_message)
                    
                    logger.info(f"Routed message {message_id}: {routing['reason']}")
                    
                    # Forward to MCP server
                    # TODO: Actually call the MCP endpoint
                    results.append({
                        "messageId": message_id,
                        "routing": routing,
                        "status": "routed"
                    })
                else:
                    results.append({
                        "messageId": message_id,
                        "status": "router_unavailable"
                    })
        
        return JSONResponse(content={
            "processed": len(results),
            "results": results
        })
    
    except Exception as e:
        logger.error(f"Error handling email route: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/email/status")
async def email_status():
    """
    Get email routing status
    """
    return {
        "router_available": email_router_available,
        "processed_count": len(processed_message_ids),
        "last_cleanup": last_cleanup.isoformat()
    }

@app.get("/sessions")
async def get_sessions():
    """
    Get all active sessions
    """
    manager = get_session_manager()
    return {
        "sessions": manager.get_active_sessions()
    }

@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """
    Get details of a specific session
    """
    manager = get_session_manager()
    summary = manager.get_session_summary(session_id)
    
    if not summary:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return summary

@app.post("/sessions/{session_id}/handoff")
async def handoff_session(session_id: str, target_agent: str, context: Optional[str] = None):
    """
    Hand off a session to a different agent
    """
    manager = get_session_manager()
    session = manager.handoff_session(session_id, target_agent, context)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get handoff message with voice
    handoff_msg = get_handoff_message(session.current_agent, target_agent)
    old_voice = get_agent_voice(session.current_agent)["voice"]
    new_voice = get_agent_voice(target_agent)["voice"]
    
    return {
        "session_id": session_id,
        "handoff_message": handoff_msg,
        "old_agent": session.current_agent,
        "new_agent": target_agent,
        "old_voice": old_voice,
        "new_voice": new_voice
    }

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up SSE connections on shutdown"""
    await close_mcp_client()
    logger.info("Closed all MCP connections")

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",  # Listen on all interfaces for Windows access
        port=7000,
        log_level="info"
    )