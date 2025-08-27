#!/usr/bin/env python3
"""
Test Voice Flow - Simulates the complete voice command cycle
Tests bridge response and TTS playback on Windows
"""

import requests
import json
import time
import sys

# Configuration - UPDATE WITH YOUR IPS
WSL_BRIDGE = "http://localhost:7000"  # From WSL perspective
WINDOWS_TTS = "http://192.168.1.X:7002"  # Your Windows IP - update this!

def test_voice_command(text, wake_word, session_id=None):
    """Test a voice command through the bridge"""
    
    print(f"\n{'='*60}")
    print(f"Testing: {wake_word} → '{text}'")
    print('='*60)
    
    # Step 1: Send to bridge
    payload = {
        "text": text,
        "wake_word": wake_word,
        "session_id": session_id or f"test_{int(time.time())}",
        "two_stage_mode": False
    }
    
    print(f"1. Sending to bridge...")
    try:
        response = requests.post(
            f"{WSL_BRIDGE}/voice/command",
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"2. Got response from {result['server']}:")
            print(f"   Text: {result['response'][:100]}...")
            print(f"   Voice: {result['voice']}")
            print(f"   Speed: {result['voice_config']['speed']}")
            print(f"   Pitch: {result['voice_config']['pitch']}")
            
            return result
        else:
            print(f"   ERROR: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        print(f"   ERROR: {str(e)}")
        return None

def test_tts_playback(text, voice, speed=1.0, pitch=1.0):
    """Test TTS playback on Windows"""
    
    print(f"\n3. Testing TTS playback...")
    print(f"   Voice: {voice}")
    print(f"   Text: {text[:50]}...")
    
    # This would call Windows TTS - you'll test this from Windows
    payload = {
        "text": text,
        "voice": voice,
        "play_local": True  # Play on Windows speakers
    }
    
    print(f"   To test on Windows, run:")
    print(f"   curl -X POST {WINDOWS_TTS}/speak -H \"Content-Type: application/json\" -d '{json.dumps(payload)}'")

def run_test_suite():
    """Run complete test suite"""
    
    print("\n" + "="*60)
    print("VOICE COMMAND TEST SUITE")
    print("="*60)
    
    # Test 1: Router (Deep Thought) - British male
    result = test_voice_command(
        "What is the meaning of life?",
        "router",
        "test_session_001"
    )
    if result:
        test_tts_playback(result['response'], result['voice'])
    
    time.sleep(2)
    
    # Test 2: Office Assistant - American female
    result = test_voice_command(
        "Schedule a meeting for tomorrow at 2 PM",
        "office",
        "test_session_002"
    )
    if result:
        test_tts_playback(result['response'], result['voice'])
    
    time.sleep(2)
    
    # Test 3: Financial Analyst - American male
    result = test_voice_command(
        "What's the current price of Apple stock?",
        "analyst",
        "test_session_003"
    )
    if result:
        test_tts_playback(result['response'], result['voice'])
    
    # Test 4: Multi-turn conversation
    print("\n" + "="*60)
    print("TESTING MULTI-TURN CONVERSATION")
    print("="*60)
    
    session = "multi_turn_test"
    
    # Turn 1
    result = test_voice_command(
        "My name is John",
        "router",
        session
    )
    
    time.sleep(2)
    
    # Turn 2 - should remember name
    result = test_voice_command(
        "What's my name?",
        "router",
        session
    )
    
    # Test 5: Two-stage mode
    print("\n" + "="*60)
    print("TESTING TWO-STAGE DETECTION")
    print("="*60)
    
    payload = {
        "text": "Office, schedule a meeting with procurement about the new vendor",
        "wake_word": "generic",  # Ignored in two-stage
        "two_stage_mode": True,
        "session_id": "two_stage_test"
    }
    
    print("Sending with two-stage detection...")
    response = requests.post(f"{WSL_BRIDGE}/voice/command", json=payload)
    if response.status_code == 200:
        result = response.json()
        print(f"Detected agent: {result['server']}")
        print(f"Response: {result['response'][:100]}...")

if __name__ == "__main__":
    # First check bridge is running
    try:
        health = requests.get(f"{WSL_BRIDGE}/health").json()
        print(f"Bridge health: {health['status']}")
        print(f"MCP Servers: {health['servers']}")
    except:
        print("ERROR: Bridge service not running!")
        print("Start it with: ./start-all.sh")
        sys.exit(1)
    
    # Run tests
    run_test_suite()
    
    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("Now test from Windows with voice_capture.py")
    print("="*60)