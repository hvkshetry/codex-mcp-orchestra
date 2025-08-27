#!/usr/bin/env python3
"""
Session Manager for Multi-Agent System
Manages conversation sessions across voice and email channels with voice personality persistence
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from pathlib import Path
import uuid

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class ConversationTurn:
    """A single turn in a conversation"""
    timestamp: datetime
    role: str  # "user" or "assistant"
    content: str
    agent: str
    voice_used: Optional[str] = None

@dataclass 
class ConversationSession:
    """A conversation session with context and voice personality"""
    session_id: str
    channel: str  # "voice", "email", or "hybrid"
    current_agent: str
    voice_personality: str
    context: List[ConversationTurn] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    
    def add_turn(self, role: str, content: str, agent: str, voice: Optional[str] = None):
        """Add a conversation turn"""
        turn = ConversationTurn(
            timestamp=datetime.now(),
            role=role,
            content=content,
            agent=agent,
            voice_used=voice
        )
        self.context.append(turn)
        self.last_active = datetime.now()
    
    def get_context_string(self, max_turns: int = 10) -> str:
        """Get recent context as a formatted string"""
        recent_turns = self.context[-max_turns:]
        context_str = ""
        
        for turn in recent_turns:
            role_label = "User" if turn.role == "user" else f"{turn.agent.title()}"
            context_str += f"{role_label}: {turn.content}\n"
        
        return context_str
    
    def is_expired(self, timeout_minutes: int = 30) -> bool:
        """Check if session has expired"""
        return datetime.now() - self.last_active > timedelta(minutes=timeout_minutes)

class SessionManager:
    """Manages all conversation sessions"""
    
    def __init__(self, session_timeout_minutes: int = 30):
        self.sessions: Dict[str, ConversationSession] = {}
        self.session_timeout = session_timeout_minutes
        self.session_file = Path("/tmp/ai_sessions.json")
        self._load_sessions()
        
        # Start cleanup task
        asyncio.create_task(self._cleanup_expired_sessions())
    
    def _load_sessions(self):
        """Load sessions from persistent storage"""
        if self.session_file.exists():
            try:
                with open(self.session_file, 'r') as f:
                    data = json.load(f)
                    # Reconstruct sessions from JSON
                    for session_id, session_data in data.items():
                        # Convert timestamps
                        session_data['created_at'] = datetime.fromisoformat(session_data['created_at'])
                        session_data['last_active'] = datetime.fromisoformat(session_data['last_active'])
                        
                        # Reconstruct conversation turns
                        turns = []
                        for turn_data in session_data.get('context', []):
                            turn_data['timestamp'] = datetime.fromisoformat(turn_data['timestamp'])
                            turns.append(ConversationTurn(**turn_data))
                        session_data['context'] = turns
                        
                        # Create session
                        session = ConversationSession(**session_data)
                        if not session.is_expired(self.session_timeout):
                            self.sessions[session_id] = session
                            
                logger.info(f"Loaded {len(self.sessions)} active sessions")
            except Exception as e:
                logger.error(f"Error loading sessions: {e}")
    
    def _save_sessions(self):
        """Save sessions to persistent storage"""
        try:
            data = {}
            for session_id, session in self.sessions.items():
                # Convert to JSON-serializable format
                session_dict = asdict(session)
                session_dict['created_at'] = session.created_at.isoformat()
                session_dict['last_active'] = session.last_active.isoformat()
                
                # Convert conversation turns
                for turn in session_dict['context']:
                    turn['timestamp'] = turn['timestamp'].isoformat()
                
                data[session_id] = session_dict
            
            with open(self.session_file, 'w') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Error saving sessions: {e}")
    
    async def _cleanup_expired_sessions(self):
        """Periodically clean up expired sessions"""
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                
                expired = []
                for session_id, session in self.sessions.items():
                    if session.is_expired(self.session_timeout):
                        expired.append(session_id)
                
                for session_id in expired:
                    logger.info(f"Removing expired session: {session_id}")
                    del self.sessions[session_id]
                
                if expired:
                    self._save_sessions()
                    
            except Exception as e:
                logger.error(f"Error in session cleanup: {e}")
    
    def create_session(self, session_id: Optional[str] = None, 
                      channel: str = "voice",
                      agent: str = "router",
                      voice: Optional[str] = None) -> ConversationSession:
        """Create a new conversation session"""
        if not session_id:
            session_id = str(uuid.uuid4())
        
        # Import voice config
        from config.voice_personalities import get_agent_voice
        
        # Get voice personality for agent
        if not voice:
            voice_config = get_agent_voice(agent)
            voice = voice_config["voice"]
        
        session = ConversationSession(
            session_id=session_id,
            channel=channel,
            current_agent=agent,
            voice_personality=voice
        )
        
        self.sessions[session_id] = session
        self._save_sessions()
        
        logger.info(f"Created session {session_id} for {agent} on {channel}")
        return session
    
    def get_session(self, session_id: str) -> Optional[ConversationSession]:
        """Get an existing session"""
        session = self.sessions.get(session_id)
        
        if session and not session.is_expired(self.session_timeout):
            session.last_active = datetime.now()
            return session
        
        return None
    
    def get_or_create_session(self, session_id: str, 
                             channel: str = "voice",
                             agent: str = "router") -> ConversationSession:
        """Get existing session or create new one"""
        session = self.get_session(session_id)
        
        if not session:
            session = self.create_session(session_id, channel, agent)
        
        return session
    
    def handoff_session(self, session_id: str, 
                       new_agent: str,
                       handoff_context: Optional[str] = None) -> Optional[ConversationSession]:
        """Hand off a session to a different agent"""
        session = self.get_session(session_id)
        
        if not session:
            logger.warning(f"Session {session_id} not found for handoff")
            return None
        
        # Import voice config
        from config.voice_personalities import get_agent_voice, get_handoff_message
        
        # Record handoff in context
        handoff_msg = get_handoff_message(session.current_agent, new_agent)
        session.add_turn("assistant", handoff_msg, session.current_agent, session.voice_personality)
        
        # Update agent and voice
        old_agent = session.current_agent
        session.current_agent = new_agent
        
        voice_config = get_agent_voice(new_agent)
        session.voice_personality = voice_config["voice"]
        
        # Add handoff context if provided
        if handoff_context:
            intro = f"I see you need help with {handoff_context}"
            session.add_turn("assistant", intro, new_agent, session.voice_personality)
        
        # Save changes
        self._save_sessions()
        
        logger.info(f"Handed off session {session_id} from {old_agent} to {new_agent}")
        return session
    
    def link_sessions(self, voice_session_id: str, email_session_id: str):
        """Link voice and email sessions for the same user"""
        voice_session = self.get_session(voice_session_id)
        email_session = self.get_session(email_session_id)
        
        if voice_session and email_session:
            # Merge contexts
            combined_context = sorted(
                voice_session.context + email_session.context,
                key=lambda x: x.timestamp
            )
            
            # Update both sessions
            voice_session.context = combined_context
            voice_session.channel = "hybrid"
            voice_session.metadata["linked_email"] = email_session_id
            
            email_session.context = combined_context
            email_session.channel = "hybrid"
            email_session.metadata["linked_voice"] = voice_session_id
            
            self._save_sessions()
            logger.info(f"Linked sessions: voice={voice_session_id}, email={email_session_id}")
    
    def get_session_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get a summary of a session"""
        session = self.get_session(session_id)
        
        if not session:
            return None
        
        return {
            "session_id": session_id,
            "channel": session.channel,
            "current_agent": session.current_agent,
            "voice": session.voice_personality,
            "turn_count": len(session.context),
            "duration_minutes": (session.last_active - session.created_at).total_seconds() / 60,
            "last_active": session.last_active.isoformat(),
            "recent_context": session.get_context_string(5)
        }
    
    def get_active_sessions(self) -> List[Dict[str, Any]]:
        """Get summaries of all active sessions"""
        summaries = []
        
        for session_id in self.sessions:
            summary = self.get_session_summary(session_id)
            if summary:
                summaries.append(summary)
        
        return summaries

# Singleton instance
_session_manager: Optional[SessionManager] = None

def get_session_manager() -> SessionManager:
    """Get or create singleton session manager"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager

# Helper functions for bridge integration
async def process_with_session(session_id: str, 
                              prompt: str,
                              agent: str,
                              channel: str = "voice") -> Dict[str, Any]:
    """Process a prompt with session context"""
    manager = get_session_manager()
    session = manager.get_or_create_session(session_id, channel, agent)
    
    # Add user turn
    session.add_turn("user", prompt, agent)
    
    # Get context for MCP call
    context = session.get_context_string()
    
    # Return session info for MCP call
    return {
        "session": session,
        "context": context,
        "voice": session.voice_personality,
        "agent": session.current_agent
    }

async def record_response(session_id: str, response: str, agent: str):
    """Record assistant response in session"""
    manager = get_session_manager()
    session = manager.get_session(session_id)
    
    if session:
        session.add_turn("assistant", response, agent, session.voice_personality)
        manager._save_sessions()