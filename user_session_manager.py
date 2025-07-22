import uuid
import time
import threading
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from fastapi import Cookie

logger = logging.getLogger(__name__)

@dataclass
class UserSession:
    """Represents a user session with isolated resources"""
    session_id: str
    username: str
    aws_login: str
    customer_name: str
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    
    # User-specific resources
    sandbox_instance: Optional[Any] = None
    stream_url: Optional[str] = None
    current_command: Optional[Any] = None
    websocket_connections: list = field(default_factory=list)
    log_buffer: list = field(default_factory=list)
    
    def update_activity(self):
        """Update the last activity timestamp"""
        self.last_activity = datetime.now()
    
    def is_expired(self, timeout_minutes: int = 60) -> bool:
        """Check if the session has expired"""
        return datetime.now() - self.last_activity > timedelta(minutes=timeout_minutes)
    
    def cleanup_resources(self):
        """Clean up session resources"""
        try:
            # Kill sandbox instance if it exists
            if self.sandbox_instance:
                logger.info(f"Cleaning up sandbox for session {self.session_id}")
                try:
                    self.sandbox_instance.kill()
                except Exception as e:
                    logger.error(f"Error killing sandbox for session {self.session_id}: {e}")
                self.sandbox_instance = None
            
            # Clear other resources
            self.stream_url = None
            self.current_command = None
            self.websocket_connections.clear()
            self.log_buffer.clear()
            
            logger.info(f"Session {self.session_id} resources cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up session {self.session_id}: {e}")


class UserSessionManager:
    """Manages user sessions with isolation and cleanup"""
    
    def __init__(self):
        self.sessions: Dict[str, UserSession] = {}
        self.lock = threading.RLock()
        self.cleanup_interval = 300  # 5 minutes
        self.session_timeout = 60  # 60 minutes
        self._start_cleanup_thread()
    
    def create_session(self, username: str, aws_login: str = "", customer_name: str = "") -> UserSession:
        """Create a new user session with unique ID"""
        with self.lock:
            # Generate unique session ID
            session_id = f"{username}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
            
            # Create new session
            session = UserSession(
                session_id=session_id,
                username=username,
                aws_login=aws_login,
                customer_name=customer_name
            )
            
            self.sessions[session_id] = session
            logger.info(f"Created new session {session_id} for user {username}")
            return session
    
    def get_session(self, session_id: str) -> Optional[UserSession]:
        """Get a session by ID"""
        with self.lock:
            session = self.sessions.get(session_id)
            if session:
                session.update_activity()
            return session
    
    def get_session_by_token(self, session_token: str) -> Optional[UserSession]:
        """Get session by legacy session token (for backward compatibility)"""
        # For now, treat session_token as session_id
        # In a full implementation, you might have a mapping
        return self.get_session(session_token)
    
    def remove_session(self, session_id: str) -> bool:
        """Remove a session and clean up its resources"""
        with self.lock:
            session = self.sessions.get(session_id)
            if session:
                session.cleanup_resources()
                del self.sessions[session_id]
                logger.info(f"Removed session {session_id}")
                return True
            return False
    
    def cleanup_expired_sessions(self):
        """Clean up expired sessions"""
        with self.lock:
            expired_sessions = []
            for session_id, session in self.sessions.items():
                if session.is_expired(self.session_timeout):
                    expired_sessions.append(session_id)
            
            for session_id in expired_sessions:
                logger.info(f"Cleaning up expired session {session_id}")
                self.remove_session(session_id)
    
    def get_active_sessions(self) -> Dict[str, UserSession]:
        """Get all active sessions"""
        with self.lock:
            return self.sessions.copy()
    
    def _start_cleanup_thread(self):
        """Start background thread for session cleanup"""
        def cleanup_worker():
            while True:
                try:
                    time.sleep(self.cleanup_interval)
                    self.cleanup_expired_sessions()
                except Exception as e:
                    logger.error(f"Error in session cleanup thread: {e}")
        
        cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        cleanup_thread.start()
        logger.info("Session cleanup thread started")


# Global session manager instance
session_manager = UserSessionManager()


def get_current_user_session(session_token: str = Cookie(None)) -> Optional[UserSession]:
    """Get the current user session from session token"""
    if not session_token:
        return None
    
    return session_manager.get_session_by_token(session_token)


def create_user_session(username: str, aws_login: str = "", customer_name: str = "") -> UserSession:
    """Create a new user session"""
    return session_manager.create_session(username, aws_login, customer_name)


def get_user_session(session_id: str) -> Optional[UserSession]:
    """Get a user session by ID"""
    return session_manager.get_session(session_id)


def remove_user_session(session_id: str) -> bool:
    """Remove a user session"""
    return session_manager.remove_session(session_id)
