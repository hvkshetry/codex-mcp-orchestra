#!/usr/bin/env python3
"""
Email Router Service
Routes emails based on headers and plus addressing suffixes
"""

import re
import os
import logging
import tomli
from pathlib import Path
from typing import Dict, Any, Optional, List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load routing configuration
config_path = Path(__file__).parent.parent / "config" / "routing.toml"

class EmailRouter:
    def __init__(self, config_path: Path = config_path):
        """Initialize router with configuration"""
        self.config = self._load_config(config_path)
        # Get email domain from config or environment
        domain = self.config.get('domain', {}).get('email_domain', 'example.com')
        domain = os.environ.get('EMAIL_DOMAIN', domain).replace('.', '\\.')
        self.suffix_pattern = re.compile(rf'^[^+@]+\+(?P<suffix>[^@]+)@{domain}$', re.IGNORECASE)
        logger.info(f"Email router initialized with {len(self.config['suffixes'])} suffix mappings")
    
    def _load_config(self, path: Path) -> Dict[str, Any]:
        """Load routing configuration from TOML"""
        if not path.exists():
            logger.warning(f"Config not found at {path}, using defaults")
            return {
                "suffixes": {},
                "defaults": {"fallback": "http://127.0.0.1:8080"}
            }
        
        with open(path, "rb") as f:
            return tomli.load(f)
    
    def extract_suffix(self, recipients: List[Dict[str, Any]]) -> Optional[str]:
        """
        Extract plus suffix from recipient addresses
        
        Args:
            recipients: List of recipient objects from Graph API
        
        Returns:
            The suffix if found, None otherwise
        """
        for recipient in recipients:
            email_address = recipient.get("emailAddress", {})
            address = email_address.get("address", "")
            
            match = self.suffix_pattern.match(address)
            if match:
                suffix = match.group("suffix")
                logger.info(f"Extracted suffix '{suffix}' from {address}")
                return suffix
        
        return None
    
    def route_email(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Determine routing for an email message
        
        Args:
            message: Email message from Graph API
        
        Returns:
            Dict with routing information:
            - endpoint: MCP server endpoint URL
            - suffix: Detected suffix (if any)
            - reason: Why this routing was chosen
        """
        # Step 1: Check for X-AI-Agent header (future enhancement)
        headers = message.get("internetMessageHeaders", [])
        for header in headers:
            if header.get("name") == "X-AI-Agent":
                agent = header.get("value")
                if agent in self.config["suffixes"]:
                    return {
                        "endpoint": self.config["suffixes"][agent],
                        "suffix": agent,
                        "reason": f"X-AI-Agent header: {agent}"
                    }
        
        # Step 2: Check plus addressing in recipients
        all_recipients = []
        
        # Add toRecipients
        to_recipients = message.get("toRecipients", [])
        all_recipients.extend(to_recipients)
        
        # Add ccRecipients
        cc_recipients = message.get("ccRecipients", [])
        all_recipients.extend(cc_recipients)
        
        # Extract suffix
        suffix = self.extract_suffix(all_recipients)
        
        if suffix:
            # Look up suffix in routing table
            if suffix in self.config["suffixes"]:
                return {
                    "endpoint": self.config["suffixes"][suffix],
                    "suffix": suffix,
                    "reason": f"Plus suffix matched: +{suffix}"
                }
            else:
                logger.warning(f"Unknown suffix '{suffix}', using fallback")
                return {
                    "endpoint": self.config["defaults"]["fallback"],
                    "suffix": suffix,
                    "reason": f"Unknown suffix +{suffix}, using fallback"
                }
        
        # Step 3: No suffix found, use fallback
        return {
            "endpoint": self.config["defaults"]["fallback"],
            "suffix": None,
            "reason": "No suffix detected, using fallback router"
        }
    
    def get_agent_name(self, suffix: Optional[str]) -> str:
        """
        Get friendly agent name from suffix
        
        Args:
            suffix: The plus addressing suffix
        
        Returns:
            Friendly agent name
        """
        agent_names = {
            "office": "Office Assistant",
            "analyst": "Financial Analyst",
            "engineering": "Engineering Assistant",
            "procurement": "Procurement Assistant",
            "accounting": "Accounting Assistant",
            "test": "Test Agent"
        }
        
        if suffix and suffix in agent_names:
            return agent_names[suffix]
        elif suffix:
            return f"{suffix.title()} Assistant"
        else:
            return "General Assistant"
    
    def reload_config(self):
        """Reload routing configuration from file"""
        self.config = self._load_config(config_path)
        logger.info("Routing configuration reloaded")

# Singleton instance
_router = None

def get_router() -> EmailRouter:
    """Get singleton router instance"""
    global _router
    if _router is None:
        _router = EmailRouter()
    return _router

def route_email(message: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience function for routing emails"""
    router = get_router()
    return router.route_email(message)

if __name__ == "__main__":
    # Test the router
    test_message = {
        "toRecipients": [
            {"emailAddress": {"address": "hersh+office@circleh2o.com"}}
        ],
        "subject": "Test email"
    }
    
    router = EmailRouter()
    result = router.route_email(test_message)
    print(f"Routing result: {result}")