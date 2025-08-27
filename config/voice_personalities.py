#!/usr/bin/env python3
"""
Voice Personality Configuration for Multi-Agent System
Each agent has a distinct voice, speaking style, and personality
"""

from typing import Dict, Any

# Agent voice personalities - customize after testing voices
AGENT_VOICES: Dict[str, Dict[str, Any]] = {
    "router": {
        "voice": "en_GB-alan-medium",  # British male - contemplative, thoughtful (AVAILABLE)
        "speed": 0.9,  # Slightly slower for thoughtfulness
        "pitch": 1.0,
        "intro_chime": "thinking.wav",
        "personality": "contemplative",
        "response_style": {
            "prefix_phrases": ["Hmm, let me think about that", "That's interesting", "I see"],
            "thinking_pause": 0.5,
            "use_fillers": True,  # "Well", "You see", etc.
        }
    },
    "office": {
        "voice": "en_GB-jenny_dioco-medium",  # British female - professional assistant (AVAILABLE)
        "speed": 1.0,
        "pitch": 1.1,  # Slightly higher for friendliness
        "intro_chime": "office.wav",
        "personality": "assistant",
        "response_style": {
            "prefix_phrases": ["I'll handle that", "Right away", "Let me check"],
            "thinking_pause": 0.2,
            "use_fillers": False,  # More direct
        }
    },
    "analyst": {
        "voice": "en_US-joe-medium",  # American male - analytical, data-focused (AVAILABLE)
        "speed": 1.1,  # Faster for data delivery
        "pitch": 0.95,
        "intro_chime": "data.wav",
        "personality": "analytical",
        "response_style": {
            "prefix_phrases": ["Based on the data", "Analysis shows", "The numbers indicate"],
            "thinking_pause": 0.1,
            "use_fillers": False,
        }
    },
    "procurement": {
        "voice": "en_GB-northern_english_male-medium",  # Placeholder - business-focused
        "speed": 1.0,
        "pitch": 1.0,
        "intro_chime": "business.wav",
        "personality": "business",
        "response_style": {
            "prefix_phrases": ["From a procurement perspective", "Vendor analysis shows", "Cost-wise"],
            "thinking_pause": 0.3,
            "use_fillers": False,
        }
    },
    "engineering": {
        "voice": "en_US-danny-low",  # Placeholder - technical, precise
        "speed": 1.05,
        "pitch": 0.9,
        "intro_chime": "tech.wav",
        "personality": "technical",
        "response_style": {
            "prefix_phrases": ["Technically speaking", "The implementation", "System status"],
            "thinking_pause": 0.2,
            "use_fillers": False,
        }
    },
    "accounting": {
        "voice": "en_GB-jenny_dioco-medium",  # Placeholder - precise, clear
        "speed": 0.95,
        "pitch": 1.0,
        "intro_chime": "finance.wav",
        "personality": "financial",
        "response_style": {
            "prefix_phrases": ["Financially", "The books show", "From an accounting standpoint"],
            "thinking_pause": 0.3,
            "use_fillers": False,
        }
    }
}

# Voice fallback configuration
FALLBACK_VOICE = {
    "voice": "en_US-amy-medium",
    "speed": 1.0,
    "pitch": 1.0,
    "personality": "default"
}

# Performance optimization settings
VOICE_CACHE_CONFIG = {
    "preload_voices": ["en_GB-alan-medium", "en_US-amy-medium", "en_US-ryan-medium"],
    "max_cached_voices": 5,
    "cache_ttl_seconds": 3600,  # 1 hour
    "enable_lazy_loading": True
}

# Agent handoff transitions
HANDOFF_TRANSITIONS = {
    "office_to_analyst": "Let me connect you with our financial analyst for that information",
    "office_to_procurement": "I'll transfer you to procurement for vendor matters",
    "office_to_engineering": "Our engineering team can better assist with technical questions",
    "analyst_to_office": "I'll hand you back to the office assistant for scheduling",
    "default": "Let me connect you with the {target} specialist"
}

# Email announcement voices
EMAIL_ANNOUNCEMENTS = {
    "office": {
        "text": "New office request received",
        "voice": "en_US-amy-medium",
        "urgent_prefix": "Urgent: "
    },
    "analyst": {
        "text": "Market analysis request arrived",
        "voice": "en_US-ryan-medium",
        "urgent_prefix": "Priority: "
    },
    "procurement": {
        "text": "New procurement inquiry",
        "voice": "en_GB-northern_english_male-medium",
        "urgent_prefix": "Immediate: "
    },
    "default": {
        "text": "New message requires attention",
        "voice": "en_GB-alan-medium",
        "urgent_prefix": "Important: "
    }
}

# Two-stage wake word configuration
WAKE_WORD_CONFIG = {
    "two_stage_mode": True,
    "primary_wake_models": ["alexa", "hey_jarvis"],  # Until custom models
    "confirmation_sounds": {
        "router": "chime_thinking.wav",
        "office": "chime_ready.wav",
        "analyst": "chime_data.wav",
        "default": "chime_default.wav"
    },
    "timeout_seconds": 5
}

# Keyword detection for two-stage mode
AGENT_KEYWORDS = {
    "office": [
        "office", "assistant", "calendar", "schedule", "meeting",
        "email", "teams", "appointment", "reminder", "task"
    ],
    "analyst": [
        "analyst", "market", "stock", "trading", "finance",
        "price", "portfolio", "investment", "earnings", "analysis"
    ],
    "procurement": [
        "procurement", "purchase", "vendor", "supplier", "order",
        "quote", "contract", "sourcing", "negotiate", "cost"
    ],
    "engineering": [
        "engineering", "code", "technical", "build", "deploy",
        "debug", "system", "server", "database", "architecture"
    ],
    "accounting": [
        "accounting", "invoice", "payment", "expense", "budget",
        "financial", "books", "ledger", "reconcile", "audit"
    ],
    "router": [
        "router", "general", "help", "deep thought", "think",
        "question", "wondering", "curious", "explain", "understand"
    ]
}

def get_agent_voice(agent: str) -> Dict[str, Any]:
    """Get voice configuration for an agent"""
    return AGENT_VOICES.get(agent, FALLBACK_VOICE)

def get_agent_from_keywords(text: str) -> str:
    """Detect agent from keywords in text"""
    text_lower = text.lower()
    
    # Check each agent's keywords
    best_match = None
    best_score = 0
    
    for agent, keywords in AGENT_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in text_lower)
        if score > best_score:
            best_score = score
            best_match = agent
    
    return best_match or "router"

def get_handoff_message(from_agent: str, to_agent: str) -> str:
    """Get appropriate handoff message between agents"""
    key = f"{from_agent}_to_{to_agent}"
    if key in HANDOFF_TRANSITIONS:
        return HANDOFF_TRANSITIONS[key]
    else:
        return HANDOFF_TRANSITIONS["default"].format(target=to_agent)

def get_email_announcement(agent: str, urgent: bool = False) -> Dict[str, str]:
    """Get email announcement configuration for an agent"""
    config = EMAIL_ANNOUNCEMENTS.get(agent, EMAIL_ANNOUNCEMENTS["default"])
    
    if urgent:
        config = config.copy()
        config["text"] = config["urgent_prefix"] + config["text"]
    
    return config