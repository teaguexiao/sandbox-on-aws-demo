#!/usr/bin/env python3
"""
Debug script to test the health check issue with Agentcore Browser Tool
"""

import asyncio
import requests
import time
import sys
import json
from agentcore_browser_tool import start_agentcore_browser, agentcore_session_manager

async def test_health_check_issue():
    """Test the health check issue step by step"""
    
    print("=== AGENTCORE BROWSER HEALTH CHECK DEBUG ===\n")
    
    # Test 1: Start a browser session
    print("1. Starting Agentcore browser session...")
    session_id = "test_health_debug_session"
    
    try:
        result = await start_agentcore_browser(session_id=session_id, region='us-west-2')
        print(f"   Result: {result}")
        
        if result['status'] != 'success':
            print(f"   ERROR: Failed to start browser session: {result['message']}")
            return
            
        viewer_url = result['viewer_url']
        print(f"   Viewer URL: {viewer_url}")
        
    except Exception as e:
        print(f"   ERROR: Exception during startup: {e}")
        return
    
    # Test 2: Wait and verify server is running
    print("\n2. Waiting for server to be ready...")
    time.sleep(3)
    
    # Test 3: Check if session exists in manager
    print("\n3. Checking session in manager...")
    session = agentcore_session_manager.get_session(session_id)
    if session:
        print(f"   Session found: {session_id}")
        print(f"   Viewer server exists: {session.viewer_server is not None}")
        print(f"   Viewer server running: {session.viewer_server.is_running if session.viewer_server else 'N/A'}")
        print(f"   Viewer URL: {session.viewer_url}")
    else:
        print(f"   ERROR: Session not found in manager!")
        return
    
    # Test 4: Test health check endpoint directly
    print("\n4. Testing health check endpoint...")
    health_url = viewer_url + '/api/health'
    print(f"   Health URL: {health_url}")
    
    try:
        response = requests.get(health_url, timeout=10)
        print(f"   Status Code: {response.status_code}")
        if response.status_code == 200:
            health_data = response.json()
            print(f"   Health Data: {json.dumps(health_data, indent=2)}")
        else:
            print(f"   Error Response: {response.text}")
    except Exception as e:
        print(f"   ERROR: {e}")
    
    # Test 5: Test other endpoints
    print("\n5. Testing other endpoints...")
    endpoints = ['/api/session-info', '/api/debug-info', '/']
    
    for endpoint in endpoints:
        url = viewer_url + endpoint
        print(f"   Testing: {endpoint}")
        try:
            response = requests.get(url, timeout=5)
            print(f"     Status: {response.status_code}")
            if response.status_code != 200:
                print(f"     Error: {response.text[:100]}...")
        except Exception as e:
            print(f"     ERROR: {e}")
    
    # Test 6: Simulate JavaScript fetch (with same headers/options)
    print("\n6. Simulating JavaScript fetch...")
    try:
        # This simulates what the JavaScript fetch() would do
        import urllib.request
        import urllib.error
        
        req = urllib.request.Request(health_url)
        req.add_header('User-Agent', 'Mozilla/5.0 (compatible; test)')
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = response.read().decode('utf-8')
            print(f"   Success: {response.status}")
            print(f"   Data: {data}")
            
    except urllib.error.URLError as e:
        print(f"   URLError: {e}")
    except Exception as e:
        print(f"   ERROR: {e}")
    
    # Test 7: Check for port conflicts
    print("\n7. Checking for port conflicts...")
    import socket
    from urllib.parse import urlparse
    
    parsed = urlparse(viewer_url)
    port = parsed.port
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(('localhost', port))
        sock.close()
        
        if result == 0:
            print(f"   Port {port}: OPEN and accessible")
        else:
            print(f"   Port {port}: CLOSED or not accessible (error code: {result})")
    except Exception as e:
        print(f"   Port check error: {e}")
    
    print("\n=== DEBUG COMPLETE ===")

if __name__ == "__main__":
    try:
        asyncio.run(test_health_check_issue())
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
