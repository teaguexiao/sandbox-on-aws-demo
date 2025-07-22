#!/usr/bin/env python3
"""
Multi-User Functionality Test Script

This script tests the user isolation functionality of the sandbox demo system.
It verifies that multiple users can use the system simultaneously without interference.
"""

import asyncio
import aiohttp
import json
import time
import logging
from typing import Dict, List
import websockets
import concurrent.futures
from dataclasses import dataclass

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class TestUser:
    """Represents a test user session"""
    username: str
    password: str
    session_token: str = None
    websocket: object = None
    messages: List[Dict] = None
    
    def __post_init__(self):
        if self.messages is None:
            self.messages = []

class MultiUserTester:
    """Test class for multi-user functionality"""
    
    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self.ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
        self.test_users = []
        
    async def create_test_user(self, username: str, password: str) -> TestUser:
        """Create a test user and login"""
        user = TestUser(username=username, password=password)
        
        async with aiohttp.ClientSession() as session:
            # Login
            login_data = {
                'username': username,
                'password': password,
                'aws_login': f'test-aws-{username}',
                'customer_name': f'Test Customer {username}'
            }
            
            async with session.post(f"{self.base_url}/login", data=login_data) as response:
                if response.status == 303:  # Redirect on success
                    # Extract session token from cookies
                    cookies = response.cookies
                    if 'session_token' in cookies:
                        user.session_token = cookies['session_token'].value
                        logger.info(f"User {username} logged in successfully with session {user.session_token}")
                        return user
                    else:
                        raise Exception(f"No session token found for user {username}")
                else:
                    raise Exception(f"Login failed for user {username}: {response.status}")
    
    async def connect_websocket(self, user: TestUser):
        """Connect WebSocket for a user"""
        try:
            # Create WebSocket connection with session cookie
            headers = {
                'Cookie': f'session_token={user.session_token}'
            }
            
            user.websocket = await websockets.connect(
                f"{self.ws_url}/ws",
                extra_headers=headers
            )
            
            logger.info(f"WebSocket connected for user {user.username}")
            
            # Start listening for messages
            asyncio.create_task(self._listen_websocket(user))
            
        except Exception as e:
            logger.error(f"Failed to connect WebSocket for user {user.username}: {e}")
            raise
    
    async def _listen_websocket(self, user: TestUser):
        """Listen for WebSocket messages"""
        try:
            async for message in user.websocket:
                data = json.loads(message)
                user.messages.append(data)
                logger.info(f"User {user.username} received: {data.get('type', 'unknown')} - {data.get('data', '')[:100]}")
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"WebSocket connection closed for user {user.username}")
        except Exception as e:
            logger.error(f"Error listening to WebSocket for user {user.username}: {e}")
    
    async def start_desktop_for_user(self, user: TestUser):
        """Start desktop for a specific user"""
        async with aiohttp.ClientSession() as session:
            headers = {'Cookie': f'session_token={user.session_token}'}
            
            async with session.post(f"{self.base_url}/start-desktop", headers=headers) as response:
                result = await response.json()
                logger.info(f"Start desktop for user {user.username}: {result}")
                return result
    
    async def setup_environment_for_user(self, user: TestUser):
        """Setup environment for a specific user"""
        async with aiohttp.ClientSession() as session:
            headers = {'Cookie': f'session_token={user.session_token}'}
            
            async with session.post(f"{self.base_url}/setup-environment", headers=headers) as response:
                result = await response.json()
                logger.info(f"Setup environment for user {user.username}: {result}")
                return result
    
    async def run_task_for_user(self, user: TestUser, query: str):
        """Run a task for a specific user"""
        async with aiohttp.ClientSession() as session:
            headers = {'Cookie': f'session_token={user.session_token}'}
            data = {'query': query}
            
            async with session.post(f"{self.base_url}/run-task", headers=headers, data=data) as response:
                result = await response.json()
                logger.info(f"Run task for user {user.username}: {result}")
                return result
    
    async def kill_desktop_for_user(self, user: TestUser):
        """Kill desktop for a specific user"""
        async with aiohttp.ClientSession() as session:
            headers = {'Cookie': f'session_token={user.session_token}'}
            
            async with session.post(f"{self.base_url}/kill-desktop", headers=headers) as response:
                result = await response.json()
                logger.info(f"Kill desktop for user {user.username}: {result}")
                return result
    
    async def test_concurrent_users(self, num_users: int = 2):
        """Test multiple users using the system concurrently"""
        logger.info(f"Starting concurrent user test with {num_users} users")
        
        # Create test users
        users = []
        for i in range(num_users):
            try:
                user = await self.create_test_user(f"testuser{i+1}", "testpass")
                users.append(user)
                await self.connect_websocket(user)
            except Exception as e:
                logger.error(f"Failed to create test user {i+1}: {e}")
                continue
        
        if not users:
            logger.error("No users created successfully")
            return False
        
        logger.info(f"Created {len(users)} test users")
        
        # Test concurrent operations
        try:
            # Start desktops concurrently
            logger.info("Starting desktops for all users concurrently...")
            start_tasks = [self.start_desktop_for_user(user) for user in users]
            start_results = await asyncio.gather(*start_tasks, return_exceptions=True)
            
            # Check results
            for i, result in enumerate(start_results):
                if isinstance(result, Exception):
                    logger.error(f"User {users[i].username} desktop start failed: {result}")
                else:
                    logger.info(f"User {users[i].username} desktop start: {result.get('status', 'unknown')}")
            
            # Wait a bit for desktops to initialize
            await asyncio.sleep(5)
            
            # Setup environments concurrently
            logger.info("Setting up environments for all users concurrently...")
            setup_tasks = [self.setup_environment_for_user(user) for user in users]
            setup_results = await asyncio.gather(*setup_tasks, return_exceptions=True)
            
            # Check results
            for i, result in enumerate(setup_results):
                if isinstance(result, Exception):
                    logger.error(f"User {users[i].username} environment setup failed: {result}")
                else:
                    logger.info(f"User {users[i].username} environment setup: {result.get('status', 'unknown')}")
            
            # Wait for environment setup to complete
            await asyncio.sleep(10)
            
            # Run different tasks for each user
            logger.info("Running different tasks for each user...")
            task_queries = [
                f"Test query for user {user.username} - current time and weather"
                for user in users
            ]
            
            run_tasks = [
                self.run_task_for_user(users[i], task_queries[i])
                for i in range(len(users))
            ]
            run_results = await asyncio.gather(*run_tasks, return_exceptions=True)
            
            # Check results
            for i, result in enumerate(run_results):
                if isinstance(result, Exception):
                    logger.error(f"User {users[i].username} task run failed: {result}")
                else:
                    logger.info(f"User {users[i].username} task run: {result.get('status', 'unknown')}")
            
            # Wait for tasks to complete
            await asyncio.sleep(30)
            
            # Analyze message isolation
            logger.info("Analyzing message isolation...")
            self.analyze_message_isolation(users)
            
            # Clean up - kill desktops
            logger.info("Cleaning up - killing desktops...")
            kill_tasks = [self.kill_desktop_for_user(user) for user in users]
            await asyncio.gather(*kill_tasks, return_exceptions=True)
            
            return True
            
        except Exception as e:
            logger.error(f"Error during concurrent user test: {e}")
            return False
        finally:
            # Close WebSocket connections
            for user in users:
                if user.websocket:
                    await user.websocket.close()
    
    def analyze_message_isolation(self, users: List[TestUser]):
        """Analyze if users received isolated messages"""
        logger.info("=== MESSAGE ISOLATION ANALYSIS ===")
        
        for user in users:
            logger.info(f"User {user.username} received {len(user.messages)} messages")
            
            # Check for session-specific messages
            session_messages = [msg for msg in user.messages if user.username in str(msg)]
            logger.info(f"User {user.username} received {len(session_messages)} session-specific messages")
            
            # Check for messages from other users (should be 0)
            other_user_messages = []
            for other_user in users:
                if other_user.username != user.username:
                    other_messages = [msg for msg in user.messages if other_user.username in str(msg)]
                    other_user_messages.extend(other_messages)
            
            if other_user_messages:
                logger.error(f"ISOLATION VIOLATION: User {user.username} received {len(other_user_messages)} messages from other users!")
                for msg in other_user_messages[:5]:  # Show first 5
                    logger.error(f"  Cross-user message: {msg}")
            else:
                logger.info(f"✓ User {user.username} properly isolated - no cross-user messages")


async def main():
    """Main test function"""
    logger.info("Starting Multi-User Functionality Test")
    
    tester = MultiUserTester()
    
    try:
        # Test with 2 concurrent users
        success = await tester.test_concurrent_users(num_users=2)
        
        if success:
            logger.info("✓ Multi-user test completed successfully")
        else:
            logger.error("✗ Multi-user test failed")
            
    except Exception as e:
        logger.error(f"Test failed with exception: {e}")


if __name__ == "__main__":
    asyncio.run(main())
