#!/usr/bin/env python3
"""
WeChat utility functions for sending messages via OpenClaw.
"""

import os
import sys
import json

class WeChatClient:
    """WeChat client that uses OpenClaw's messaging system to send messages"""
    
    def __init__(self):
        # OpenClaw handles routing, we just need to format the message
        pass
    
    def send_message(self, message):
        """Send message to configured WeChat user"""
        try:
            # In OpenClaw, when running as a cron job with agentTurn,
            # the message gets delivered automatically to configured channel.
            # This is where you would add custom API calls if you need them.
            
            # For now, we print the message which OpenClaw captures and routes
            print("\n--- DAILY AI DIGEST ---")
            print(message)
            print("--- END DIGEST ---")
            
            return True
        except Exception as e:
            print(f"Error sending message: {str(e)}", file=sys.stderr)
            return False
