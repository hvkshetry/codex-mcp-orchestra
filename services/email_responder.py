#!/usr/bin/env python3
"""
Email Responder Service
Sends email responses using Graph API reply endpoints
"""

import os
import logging
import asyncio
from typing import Dict, Any, Optional, List
from pathlib import Path
import aiohttp
import tomli

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class EmailResponder:
    def __init__(self, access_token: str):
        """
        Initialize responder with Graph API access token
        
        Args:
            access_token: Valid Graph API access token with Mail.Send permission
        """
        self.access_token = access_token
        self.graph_base = "https://graph.microsoft.com/v1.0"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
    
    async def reply_to_message(
        self,
        message_id: str,
        reply_content: str,
        user_id: str = "me",
        reply_all: bool = False,
        agent_name: Optional[str] = None,
        set_category: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Reply to a message using Graph API reply endpoints
        
        Args:
            message_id: ID of the message to reply to
            reply_content: The reply text content
            user_id: User ID or 'me' for current user
            reply_all: Whether to reply to all recipients
            agent_name: Name of the agent responding (for signature)
            set_category: Optional category to set on the original message
        
        Returns:
            Response from Graph API
        """
        try:
            # Format the reply content with agent signature
            if agent_name:
                formatted_content = f"{reply_content}\n\n— Response from AI {agent_name}"
            else:
                formatted_content = f"{reply_content}\n\n— AI Assistant Response"
            
            # Method 1: Direct reply (simpler)
            endpoint = "replyAll" if reply_all else "reply"
            url = f"{self.graph_base}/users/{user_id}/messages/{message_id}/{endpoint}"
            
            payload = {
                "comment": formatted_content
            }
            
            async with aiohttp.ClientSession() as session:
                # Send the reply
                async with session.post(url, headers=self.headers, json=payload) as response:
                    if response.status == 202:  # Accepted
                        logger.info(f"Reply sent successfully to message {message_id}")
                        result = {"status": "sent", "messageId": message_id}
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to send reply: {response.status} - {error_text}")
                        result = {"status": "error", "error": error_text}
                
                # Set category if requested
                if set_category and response.status == 202:
                    await self.set_message_category(message_id, set_category, user_id)
                
                return result
        
        except Exception as e:
            logger.error(f"Error replying to message: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    async def reply_with_draft(
        self,
        message_id: str,
        reply_content: str,
        user_id: str = "me",
        reply_all: bool = False,
        agent_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a draft reply, modify it, then send
        More control but requires multiple API calls
        
        Args:
            message_id: ID of the message to reply to
            reply_content: The reply text content
            user_id: User ID or 'me' for current user
            reply_all: Whether to reply to all recipients
            agent_name: Name of the agent responding
        
        Returns:
            Response from Graph API
        """
        try:
            # Step 1: Create draft reply
            endpoint = "createReplyAll" if reply_all else "createReply"
            url = f"{self.graph_base}/users/{user_id}/messages/{message_id}/{endpoint}"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=self.headers) as response:
                    if response.status != 201:
                        error_text = await response.text()
                        logger.error(f"Failed to create draft: {error_text}")
                        return {"status": "error", "error": error_text}
                    
                    draft = await response.json()
                    draft_id = draft["id"]
                
                # Step 2: Update draft with content
                update_url = f"{self.graph_base}/users/{user_id}/messages/{draft_id}"
                
                # Format content
                if agent_name:
                    formatted_content = f"{reply_content}\n\n— Response from AI {agent_name}"
                else:
                    formatted_content = f"{reply_content}\n\n— AI Assistant Response"
                
                update_payload = {
                    "body": {
                        "contentType": "text",
                        "content": formatted_content
                    }
                }
                
                async with session.patch(update_url, headers=self.headers, json=update_payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Failed to update draft: {error_text}")
                        return {"status": "error", "error": error_text}
                
                # Step 3: Send the draft
                send_url = f"{self.graph_base}/users/{user_id}/messages/{draft_id}/send"
                
                async with session.post(send_url, headers=self.headers) as response:
                    if response.status == 202:
                        logger.info(f"Draft reply sent successfully for message {message_id}")
                        return {"status": "sent", "messageId": message_id, "draftId": draft_id}
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to send draft: {error_text}")
                        return {"status": "error", "error": error_text}
        
        except Exception as e:
            logger.error(f"Error creating draft reply: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    async def set_message_category(
        self,
        message_id: str,
        category: str,
        user_id: str = "me"
    ) -> bool:
        """
        Set a category on a message using PATCH
        
        Args:
            message_id: ID of the message
            category: Category name to apply
            user_id: User ID or 'me'
        
        Returns:
            True if successful
        """
        try:
            url = f"{self.graph_base}/users/{user_id}/messages/{message_id}"
            payload = {
                "categories": [category]
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, headers=self.headers, json=payload) as response:
                    if response.status == 200:
                        logger.info(f"Category '{category}' set on message {message_id}")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to set category: {error_text}")
                        return False
        
        except Exception as e:
            logger.error(f"Error setting category: {str(e)}")
            return False
    
    async def send_new_email(
        self,
        to_recipients: List[str],
        subject: str,
        content: str,
        user_id: str = "me",
        agent_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send a new email (not a reply)
        Sends from the configured sender email
        
        Args:
            to_recipients: List of recipient email addresses
            subject: Email subject
            content: Email body content
            user_id: User ID or 'me'
            agent_name: Name of the agent sending
        
        Returns:
            Response from Graph API
        """
        try:
            url = f"{self.graph_base}/users/{user_id}/sendMail"
            
            # Format content with agent signature
            if agent_name:
                formatted_content = f"{content}\n\n— {agent_name}\nAI Assistant"
            else:
                formatted_content = f"{content}\n\n— AI Assistant"
            
            # Build recipient list
            recipients = [
                {"emailAddress": {"address": addr}}
                for addr in to_recipients
            ]
            
            payload = {
                "message": {
                    "subject": subject,
                    "body": {
                        "contentType": "text",
                        "content": formatted_content
                    },
                    "toRecipients": recipients,
                    "from": {
                        "emailAddress": {
                            "address": os.environ.get("SENDER_EMAIL", "user@example.com")
                        }
                    }
                },
                "saveToSentItems": "true"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=self.headers, json=payload) as response:
                    if response.status == 202:
                        logger.info(f"Email sent successfully to {to_recipients}")
                        return {"status": "sent", "recipients": to_recipients}
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to send email: {error_text}")
                        return {"status": "error", "error": error_text}
        
        except Exception as e:
            logger.error(f"Error sending email: {str(e)}")
            return {"status": "error", "error": str(e)}

# Helper functions for integration
async def reply_to_email(
    access_token: str,
    message_id: str,
    reply_content: str,
    agent_suffix: Optional[str] = None,
    reply_all: bool = False
) -> Dict[str, Any]:
    """
    Convenience function to reply to an email
    
    Args:
        access_token: Graph API access token
        message_id: Message to reply to
        reply_content: Reply text
        agent_suffix: Plus addressing suffix (e.g., 'office', 'analyst')
        reply_all: Whether to reply to all
    
    Returns:
        Response from Graph API
    """
    responder = EmailResponder(access_token)
    
    # Map suffix to agent name
    agent_names = {
        "office": "Office Assistant",
        "analyst": "Financial Analyst",
        "engineering": "Engineering Assistant",
        "procurement": "Procurement Assistant",
        "accounting": "Accounting Assistant"
    }
    
    agent_name = agent_names.get(agent_suffix, "Assistant")
    
    # Optionally set category based on suffix
    category = f"AI-{agent_suffix.title()}" if agent_suffix else None
    
    return await responder.reply_to_message(
        message_id=message_id,
        reply_content=reply_content,
        agent_name=agent_name,
        set_category=category,
        reply_all=reply_all
    )

if __name__ == "__main__":
    # Test the responder
    print("Email responder module loaded")
    print("Requires valid Graph API access token to function")