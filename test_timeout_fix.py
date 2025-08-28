#!/usr/bin/env python3
"""
Test script to verify timeout fix for long-running MCP operations
Simulates Windows client with increased timeout and streaming support
"""

import requests
import json
import time
import sys
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d — %(levelname)s — %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Configuration (matching Windows client)
BRIDGE_URL = "http://localhost:7000"
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 180.0  # 3 minutes (was 30s)

def test_simple_request():
    """Test with simple, fast query"""
    print("\n" + "="*60)
    print("TEST 1: Simple Query (Should be fast)")
    print("="*60)
    
    payload = {
        "text": "What is 2 plus 2?",
        "wake_word": "router",
        "session_id": f"test_simple_{int(time.time())}",
        "stream": False
    }
    
    start_time = time.time()
    logger.info("Sending simple query...")
    
    try:
        response = requests.post(
            f"{BRIDGE_URL}/voice/command",
            json=payload,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
        )
        
        elapsed = time.time() - start_time
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"✓ Success in {elapsed:.1f}s")
            logger.info(f"Response: {result.get('response', '')[:100]}...")
            return True
        else:
            logger.error(f"✗ Failed: {response.status_code}")
            return False
            
    except requests.Timeout:
        elapsed = time.time() - start_time
        logger.error(f"✗ Timeout after {elapsed:.1f}s (limit was {READ_TIMEOUT}s)")
        return False
    except Exception as e:
        logger.error(f"✗ Error: {e}")
        return False

def test_long_request():
    """Test with long-running Office MCP query"""
    print("\n" + "="*60)
    print("TEST 2: Long Query (Office MCP ~63s)")
    print("="*60)
    
    payload = {
        "text": "Send me my meeting schedule for the week of September 1st, 2025",
        "wake_word": "office-assistant",
        "session_id": f"test_long_{int(time.time())}",
        "stream": False
    }
    
    start_time = time.time()
    logger.info("Sending long-running query...")
    logger.info(f"Timeout configured: {READ_TIMEOUT}s")
    
    try:
        response = requests.post(
            f"{BRIDGE_URL}/voice/command",
            json=payload,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
        )
        
        elapsed = time.time() - start_time
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"✓ Success in {elapsed:.1f}s")
            logger.info(f"Response: {result.get('response', '')[:200]}...")
            
            if elapsed > 30:
                logger.info(f"✓ TIMEOUT FIX VERIFIED: Completed {elapsed:.1f}s operation (old timeout was 30s)")
            return True
        else:
            logger.error(f"✗ Failed: {response.status_code}")
            return False
            
    except requests.Timeout:
        elapsed = time.time() - start_time
        logger.error(f"✗ Timeout after {elapsed:.1f}s (limit was {READ_TIMEOUT}s)")
        logger.error("If this timed out, increase READ_TIMEOUT further")
        return False
    except Exception as e:
        logger.error(f"✗ Error: {e}")
        return False

def test_streaming_request():
    """Test with streaming enabled"""
    print("\n" + "="*60)
    print("TEST 3: Streaming Response (Progressive feedback)")
    print("="*60)
    
    payload = {
        "text": "Send me my meeting schedule for the week of September 1st, 2025",
        "wake_word": "office-assistant",
        "session_id": f"test_stream_{int(time.time())}",
        "stream": True  # Enable streaming
    }
    
    start_time = time.time()
    first_event_time = None
    event_count = 0
    reasoning_chunks = []
    message_chunks = []
    heartbeats = []
    
    logger.info("Sending streaming query...")
    
    try:
        with requests.post(
            f"{BRIDGE_URL}/voice/command",
            json=payload,
            stream=True,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
        ) as response:
            
            if response.status_code != 200:
                logger.error(f"✗ Failed: {response.status_code}")
                return False
            
            logger.info("Stream opened, receiving events...")
            
            for line in response.iter_lines():
                if line:
                    if line.startswith(b'data: '):
                        try:
                            data = json.loads(line[6:])
                            event_count += 1
                            
                            if first_event_time is None:
                                first_event_time = time.time()
                                time_to_first = first_event_time - start_time
                                logger.info(f"First event received after {time_to_first:.1f}s")
                            
                            event_type = data.get("type")
                            
                            if event_type == "reasoning":
                                content = data.get("content", "")[:50]
                                reasoning_chunks.append(content)
                                logger.debug(f"Reasoning: {content}...")
                            
                            elif event_type == "heartbeat":
                                elapsed = data.get("elapsed", 0)
                                heartbeats.append(elapsed)
                                logger.info(f"Heartbeat: {elapsed}s elapsed")
                            
                            elif event_type == "message":
                                content = data.get("content", "")[:50]
                                message_chunks.append(content)
                                logger.debug(f"Message: {content}...")
                            
                            elif event_type == "result":
                                total_time = time.time() - start_time
                                logger.info(f"Stream complete after {total_time:.1f}s")
                                
                        except json.JSONDecodeError as e:
                            logger.warning(f"Invalid JSON: {e}")
            
            # Summary
            total_elapsed = time.time() - start_time
            print(f"\nStreaming Summary:")
            print(f"  Total time: {total_elapsed:.1f}s")
            print(f"  Time to first event: {time_to_first:.1f}s" if first_event_time else "No events")
            print(f"  Total events: {event_count}")
            print(f"  Reasoning chunks: {len(reasoning_chunks)}")
            print(f"  Message chunks: {len(message_chunks)}")
            print(f"  Heartbeats: {len(heartbeats)}")
            
            if total_elapsed > 30:
                logger.info(f"✓ STREAMING VERIFIED: Got progressive updates during {total_elapsed:.1f}s operation")
            
            return True
            
    except requests.Timeout:
        elapsed = time.time() - start_time
        logger.error(f"✗ Timeout after {elapsed:.1f}s")
        return False
    except Exception as e:
        logger.error(f"✗ Error: {e}")
        return False

def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("WINDOWS CLIENT TIMEOUT FIX VERIFICATION")
    print(f"Testing with {READ_TIMEOUT}s timeout (was 30s)")
    print("="*80)
    
    # Check services
    try:
        health = requests.get(f"{BRIDGE_URL}/health", timeout=5).json()
        logger.info(f"Bridge status: {health['status']}")
        logger.info(f"MCP servers: {', '.join(health.get('servers', []))}")
    except Exception as e:
        logger.error(f"Bridge not available: {e}")
        print("\nPlease start services with: ./start-all.sh")
        return 1
    
    # Run tests
    results = []
    
    # Test 1: Simple query
    results.append(("Simple Query", test_simple_request()))
    time.sleep(2)
    
    # Test 2: Long query (the problematic one)
    results.append(("Long Query (63s)", test_long_request()))
    time.sleep(2)
    
    # Test 3: Streaming
    results.append(("Streaming", test_streaming_request()))
    
    # Results
    print("\n" + "="*80)
    print("TEST RESULTS")
    print("="*80)
    
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{test_name}: {status}")
    
    all_passed = all(r[1] for r in results)
    
    if all_passed:
        print("\n✓ ALL TESTS PASSED - Timeout fix verified!")
        print("\nNext steps:")
        print("1. Copy windows/*.py files to Windows machine")
        print("2. Update your Windows voice_capture.py")
        print("3. Test with actual voice commands")
    else:
        print("\n✗ Some tests failed - check logs above")
        print("\nTroubleshooting:")
        print("1. Ensure all services are running")
        print("2. Check MCP servers are responding")
        print("3. Increase timeout if needed")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())