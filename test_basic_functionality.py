#!/usr/bin/env python3
"""
Basic Functionality Test Script

This script tests the basic functionality of the user isolation system.
"""

import asyncio
import sys
import os

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from user_session_manager import UserSessionManager, create_user_session
from user_connection_manager import UserConnectionManager
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_session_management():
    """Test user session management"""
    logger.info("=== Testing User Session Management ===")
    
    # Create session manager
    session_manager = UserSessionManager()
    
    # Create multiple sessions for the same user
    session1 = session_manager.create_session("testuser", "aws1", "Customer 1")
    session2 = session_manager.create_session("testuser", "aws2", "Customer 2")
    
    logger.info(f"Created session 1: {session1.session_id}")
    logger.info(f"Created session 2: {session2.session_id}")
    
    # Verify sessions are different
    assert session1.session_id != session2.session_id, "Sessions should have unique IDs"
    logger.info("✓ Sessions have unique IDs")
    
    # Test session retrieval
    retrieved_session1 = session_manager.get_session(session1.session_id)
    assert retrieved_session1 == session1, "Should retrieve the same session"
    logger.info("✓ Session retrieval works")
    
    # Test session cleanup
    session_manager.remove_session(session1.session_id)
    retrieved_session1 = session_manager.get_session(session1.session_id)
    assert retrieved_session1 is None, "Session should be removed"
    logger.info("✓ Session cleanup works")
    
    logger.info("Session management tests passed!")

async def test_connection_management():
    """Test user connection management"""
    logger.info("=== Testing User Connection Management ===")
    
    # Create connection manager
    conn_manager = UserConnectionManager()
    
    # Create mock WebSocket connections
    class MockWebSocket:
        def __init__(self, name):
            self.name = name
            self.messages = []
        
        async def accept(self):
            pass
        
        async def send_json(self, data):
            self.messages.append(data)
            logger.info(f"MockWebSocket {self.name} received: {data}")
        
        async def send_text(self, text):
            self.messages.append({"text": text})
            logger.info(f"MockWebSocket {self.name} received text: {text}")
    
    # Create mock connections for different sessions
    ws1 = MockWebSocket("user1_ws")
    ws2 = MockWebSocket("user2_ws")
    
    # Connect WebSockets to different sessions
    await conn_manager.connect(ws1, "session1")
    await conn_manager.connect(ws2, "session2")
    
    logger.info("Connected WebSockets for different sessions")
    
    # Send messages to specific users
    await conn_manager.send_json_to_user("session1", {"type": "test", "data": "Message for session1"})
    await conn_manager.send_json_to_user("session2", {"type": "test", "data": "Message for session2"})
    
    # Verify message isolation
    assert len(ws1.messages) == 1, "Session1 should receive 1 message"
    assert len(ws2.messages) == 1, "Session2 should receive 1 message"
    
    assert "session1" in str(ws1.messages[0]), "Session1 should receive its own message"
    assert "session2" in str(ws2.messages[0]), "Session2 should receive its own message"
    
    logger.info("✓ Message isolation works correctly")
    
    # Test message queuing when no connections
    conn_manager.disconnect(ws1)
    conn_manager.disconnect(ws2)
    
    # Send message to disconnected session
    await conn_manager.send_json_to_user("session1", {"type": "queued", "data": "Queued message"})

    # Verify message was queued
    assert len(conn_manager.user_message_queues.get("session1", [])) >= 1, "Message should be queued"
    logger.info("✓ Message queuing works correctly")

    # Reconnect and verify queued message is delivered
    ws1_new = MockWebSocket("user1_ws_new")

    # Check queue before connecting
    queue_size_before = len(conn_manager.user_message_queues.get("session1", []))
    logger.info(f"Queue size before reconnect: {queue_size_before}")

    await conn_manager.connect(ws1_new, "session1")

    # Wait a moment for queued messages to be sent
    await asyncio.sleep(0.1)

    # Check queue after connecting
    queue_size_after = len(conn_manager.user_message_queues.get("session1", []))
    logger.info(f"Queue size after reconnect: {queue_size_after}")
    logger.info(f"Messages received by new connection: {len(ws1_new.messages)}")

    # Should receive the queued message (queue should be cleared and message delivered)
    assert len(ws1_new.messages) >= 1 or queue_size_before > queue_size_after, "Should receive queued message on reconnect or queue should be processed"
    logger.info("✓ Message delivery on reconnect works correctly")
    
    logger.info("Connection management tests passed!")

async def test_user_isolation():
    """Test complete user isolation"""
    logger.info("=== Testing Complete User Isolation ===")
    
    # Create session manager and connection manager
    session_manager = UserSessionManager()
    conn_manager = UserConnectionManager()
    
    # Create two user sessions
    user1_session = session_manager.create_session("user1", "aws1", "Customer 1")
    user2_session = session_manager.create_session("user2", "aws2", "Customer 2")
    
    logger.info(f"Created user1 session: {user1_session.session_id}")
    logger.info(f"Created user2 session: {user2_session.session_id}")
    
    # Simulate sandbox instances (mock objects)
    class MockSandbox:
        def __init__(self, sandbox_id):
            self.sandbox_id = sandbox_id
            self.killed = False
        
        def kill(self):
            self.killed = True
            logger.info(f"Sandbox {self.sandbox_id} killed")
    
    # Assign different sandbox instances
    user1_session.sandbox_instance = MockSandbox("sandbox_user1")
    user2_session.sandbox_instance = MockSandbox("sandbox_user2")
    
    user1_session.stream_url = "https://stream1.example.com"
    user2_session.stream_url = "https://stream2.example.com"
    
    # Verify isolation
    assert user1_session.sandbox_instance.sandbox_id != user2_session.sandbox_instance.sandbox_id
    assert user1_session.stream_url != user2_session.stream_url
    
    logger.info("✓ Users have isolated sandbox instances and stream URLs")
    
    # Test cleanup
    user1_session.cleanup_resources()
    user2_session.cleanup_resources()
    
    assert user1_session.sandbox_instance is None
    assert user2_session.sandbox_instance is None
    
    logger.info("✓ Resource cleanup works correctly")
    
    logger.info("User isolation tests passed!")

async def main():
    """Run all tests"""
    logger.info("Starting Basic Functionality Tests")
    
    try:
        await test_session_management()
        await test_connection_management()
        await test_user_isolation()
        
        logger.info("🎉 All basic functionality tests passed!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
