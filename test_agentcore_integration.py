#!/usr/bin/env python3
"""
Test script for Agentcore BrowserTool integration
"""

import asyncio
import sys
import os

# Add current directory to path
sys.path.append('.')

async def test_agentcore_imports():
    """Test that all Agentcore modules can be imported"""
    print("Testing Agentcore imports...")
    
    try:
        from agentcore_browser_tool import (
            start_agentcore_browser, 
            run_agentcore_browser_task, 
            stop_agentcore_browser,
            init_agentcore_vars, 
            agentcore_session_manager,
            AgentcoreBrowserSession,
            AgentcoreSessionManager
        )
        print("✅ All Agentcore imports successful")
        return True
    except Exception as e:
        print(f"❌ Agentcore import failed: {e}")
        return False

async def test_session_manager():
    """Test the session manager functionality"""
    print("\nTesting session manager...")
    
    try:
        from agentcore_browser_tool import agentcore_session_manager
        
        # Create a test session
        session_id = agentcore_session_manager.create_session()
        print(f"✅ Created session: {session_id}")
        
        # Get the session
        session = agentcore_session_manager.get_session(session_id)
        if session:
            print(f"✅ Retrieved session: {session.session_id}")
        else:
            print("❌ Failed to retrieve session")
            return False
        
        # Test session expiry check
        is_expired = session.is_expired()
        print(f"✅ Session expiry check: {is_expired}")
        
        # Clean up session
        await agentcore_session_manager.cleanup_session(session_id)
        print("✅ Session cleanup successful")
        
        return True
    except Exception as e:
        print(f"❌ Session manager test failed: {e}")
        return False

async def test_app_integration():
    """Test that app.py can import Agentcore functions"""
    print("\nTesting app.py integration...")
    
    try:
        # Test the imports that app.py uses
        from agentcore_browser_tool import (
            start_agentcore_browser, run_agentcore_browser_task, stop_agentcore_browser,
            init_agentcore_vars, agentcore_session_manager
        )
        print("✅ App.py imports successful")
        
        # Test initialization function
        class MockManager:
            pass
        
        class MockLogger:
            def info(self, msg):
                pass
            def error(self, msg):
                pass
        
        init_agentcore_vars(MockManager(), MockLogger())
        print("✅ Initialization function works")
        
        return True
    except Exception as e:
        print(f"❌ App integration test failed: {e}")
        return False

def test_static_files():
    """Test that static files exist"""
    print("\nTesting static files...")
    
    files_to_check = [
        "static/js/agentcore-browser.js",
        "templates/browser-use.html",
        "interactive_tools/browser_viewer.py"
    ]
    
    all_exist = True
    for file_path in files_to_check:
        if os.path.exists(file_path):
            print(f"✅ {file_path} exists")
        else:
            print(f"❌ {file_path} missing")
            all_exist = False
    
    return all_exist

async def main():
    """Run all tests"""
    print("🧪 Testing Agentcore BrowserTool Integration\n")
    
    tests = [
        ("Import Test", test_agentcore_imports()),
        ("Session Manager Test", test_session_manager()),
        ("App Integration Test", test_app_integration()),
        ("Static Files Test", test_static_files())
    ]
    
    results = []
    for test_name, test_coro in tests:
        if asyncio.iscoroutine(test_coro):
            result = await test_coro
        else:
            result = test_coro
        results.append((test_name, result))
    
    print("\n" + "="*50)
    print("TEST RESULTS:")
    print("="*50)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name}: {status}")
        if result:
            passed += 1
    
    print(f"\nSummary: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Agentcore BrowserTool integration is ready.")
        return True
    else:
        print("⚠️  Some tests failed. Please check the implementation.")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
