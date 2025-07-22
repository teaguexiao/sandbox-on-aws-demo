import asyncio
import logging
from typing import Dict, List, Optional, Any
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime
import json

logger = logging.getLogger(__name__)


class UserConnectionManager:
    """Manages WebSocket connections per user session"""
    
    def __init__(self):
        # Map session_id -> list of WebSocket connections
        self.user_connections: Dict[str, List[WebSocket]] = {}
        # Map WebSocket -> session_id for reverse lookup
        self.connection_sessions: Dict[WebSocket, str] = {}
        # Message queues per user session
        self.user_message_queues: Dict[str, List[Dict]] = {}
    
    async def connect(self, websocket: WebSocket, session_id: str):
        """Connect a WebSocket for a specific user session"""
        await websocket.accept()
        
        # Add to user connections
        if session_id not in self.user_connections:
            self.user_connections[session_id] = []
            self.user_message_queues[session_id] = []
        
        self.user_connections[session_id].append(websocket)
        self.connection_sessions[websocket] = session_id
        
        logger.info(f"WebSocket connected for session {session_id}")
        
        # Send any queued messages to this connection
        await self._send_queued_messages(websocket, session_id)
    
    def disconnect(self, websocket: WebSocket):
        """Disconnect a WebSocket"""
        session_id = self.connection_sessions.get(websocket)
        if session_id:
            # Remove from user connections
            if session_id in self.user_connections:
                try:
                    self.user_connections[session_id].remove(websocket)
                    # Clean up empty connection lists
                    if not self.user_connections[session_id]:
                        del self.user_connections[session_id]
                        # Keep message queue for potential reconnection
                except ValueError:
                    pass  # Connection already removed
            
            # Remove from reverse lookup
            del self.connection_sessions[websocket]
            
            logger.info(f"WebSocket disconnected for session {session_id}")
    
    async def send_to_user(self, session_id: str, message: str):
        """Send a text message to all connections for a specific user"""
        connections = self.user_connections.get(session_id, [])
        
        if not connections:
            # Queue the message if no active connections
            self._queue_message(session_id, {"type": "text", "data": message})
            return
        
        # Send to all user connections
        disconnected = []
        for connection in connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Error sending text to session {session_id}: {e}")
                disconnected.append(connection)
        
        # Clean up disconnected connections
        for conn in disconnected:
            self.disconnect(conn)
    
    async def send_json_to_user(self, session_id: str, data: Dict):
        """Send JSON data to all connections for a specific user"""
        connections = self.user_connections.get(session_id, [])
        
        if not connections:
            # Queue the message if no active connections
            self._queue_message(session_id, data)
            return
        
        # Send to all user connections
        disconnected = []
        for connection in connections:
            try:
                await connection.send_json(data)
            except Exception as e:
                logger.error(f"Error sending JSON to session {session_id}: {e}")
                disconnected.append(connection)
        
        # Clean up disconnected connections
        for conn in disconnected:
            self.disconnect(conn)
    
    async def broadcast_to_all(self, data: Dict):
        """Broadcast a message to all connected users (use sparingly)"""
        for session_id in self.user_connections.keys():
            await self.send_json_to_user(session_id, data)
    
    def _queue_message(self, session_id: str, data: Dict):
        """Queue a message for a user session"""
        if session_id not in self.user_message_queues:
            self.user_message_queues[session_id] = []
        
        # Add timestamp to queued messages
        data_with_timestamp = data.copy()
        if "timestamp" not in data_with_timestamp:
            data_with_timestamp["timestamp"] = datetime.now().strftime("%H:%M:%S")
        
        self.user_message_queues[session_id].append(data_with_timestamp)
        
        # Keep queue size reasonable
        if len(self.user_message_queues[session_id]) > 1000:
            self.user_message_queues[session_id] = self.user_message_queues[session_id][-1000:]
    
    async def _send_queued_messages(self, websocket: WebSocket, session_id: str):
        """Send all queued messages to a newly connected WebSocket"""
        queued_messages = self.user_message_queues.get(session_id, [])

        logger.info(f"Sending {len(queued_messages)} queued messages to session {session_id}")

        for message in queued_messages:
            try:
                await websocket.send_json(message)
                logger.info(f"Sent queued message to session {session_id}: {message}")
            except Exception as e:
                logger.error(f"Error sending queued message to session {session_id}: {e}")
                break

        # Clear the queue after sending
        if session_id in self.user_message_queues:
            self.user_message_queues[session_id] = []
    
    def get_user_connections(self, session_id: str) -> List[WebSocket]:
        """Get all connections for a user session"""
        return self.user_connections.get(session_id, [])
    
    def get_session_for_connection(self, websocket: WebSocket) -> Optional[str]:
        """Get the session ID for a WebSocket connection"""
        return self.connection_sessions.get(websocket)
    
    def get_active_sessions(self) -> List[str]:
        """Get list of session IDs with active connections"""
        return list(self.user_connections.keys())
    
    def cleanup_session(self, session_id: str):
        """Clean up all connections and data for a session"""
        # Disconnect all connections for this session
        connections = self.user_connections.get(session_id, [])
        for connection in connections.copy():  # Copy to avoid modification during iteration
            self.disconnect(connection)

        # Clear message queue only when explicitly cleaning up the session
        if session_id in self.user_message_queues:
            del self.user_message_queues[session_id]

        logger.info(f"Cleaned up all connections for session {session_id}")

    def clear_message_queue(self, session_id: str):
        """Clear message queue for a specific session"""
        if session_id in self.user_message_queues:
            self.user_message_queues[session_id] = []
            logger.info(f"Cleared message queue for session {session_id}")


class UserWebSocketLogger:
    """WebSocket logger that sends logs to specific user sessions"""
    
    def __init__(self, connection_manager: UserConnectionManager, session_id: str, log_type: str = "stdout"):
        self.connection_manager = connection_manager
        self.session_id = session_id
        self.log_type = log_type
        self.loop = None
    
    def __call__(self, data):
        try:
            # Get or create event loop
            try:
                self.loop = asyncio.get_event_loop()
            except RuntimeError:
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)
            
            # Convert bytes to string if needed
            if isinstance(data, bytes):
                data = data.decode('utf-8', errors='replace')
            
            # Clean up the data
            data = data.rstrip()
            if not data:  # Skip empty lines
                return
                
            # Get timestamp
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            # Create log entry
            log_entry = {
                "type": self.log_type,
                "timestamp": timestamp,
                "data": data
            }
            
            # Send to specific user session
            asyncio.run_coroutine_threadsafe(
                self.connection_manager.send_json_to_user(self.session_id, log_entry), 
                self.loop
            )
            
        except Exception as e:
            logger.error(f"Error in UserWebSocketLogger for session {self.session_id}: {e}")


# Global user connection manager instance
user_connection_manager = UserConnectionManager()
