import os
import asyncio
import sys
import logging
import uuid
from fastapi import BackgroundTasks, WebSocket
from typing import Optional, Dict, Set
import json
from datetime import datetime, timedelta
from e2b_desktop import Sandbox

# Import the ComputerUseAgent
from computer_use import ComputerUseAgent

# Session configuration constants
SESSION_TIMEOUT = 3600  # 1 hour in seconds
CLEANUP_INTERVAL = 300  # 5 minutes in seconds

# These will be initialized from app.py
manager = None
logger = None
ws_handler = None
stdout_capture = None
stderr_capture = None
sessions = {}

class ComputerUseSession:
    """Represents a single computer-use session with isolated resources"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.desktop: Optional[Sandbox] = None
        self.agent: Optional[ComputerUseAgent] = None
        self.current_task: Optional[asyncio.Task] = None
        self.manager: Optional['ComputerUseManager'] = None
        self.connections: Set[WebSocket] = set()
        self.last_activity = datetime.now()
        self.stop_requested = False
        self.created_at = datetime.now()
        
    def update_activity(self):
        """Update the last activity timestamp"""
        self.last_activity = datetime.now()
        
    def is_expired(self) -> bool:
        """Check if the session has expired"""
        return datetime.now() - self.last_activity > timedelta(seconds=SESSION_TIMEOUT)
        
    async def cleanup(self):
        """Clean up session resources"""
        try:
            # Stop any running task
            if self.current_task and not self.current_task.done():
                self.current_task.cancel()
                try:
                    await asyncio.wait_for(self.current_task, timeout=3.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                    
            # Kill the desktop sandbox
            if self.desktop:
                self.desktop.kill()
                
            # Clear references
            self.desktop = None
            self.agent = None
            self.current_task = None
            self.manager = None
            self.connections.clear()
            
            if logger:
                logger.info(f"Session {self.session_id} cleaned up successfully")
                
        except Exception as e:
            if logger:
                logger.error(f"Error cleaning up session {self.session_id}: {e}")

class SessionManager:
    """Manages multiple computer-use sessions"""
    
    def __init__(self):
        self.sessions: Dict[str, ComputerUseSession] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        
    def create_session(self) -> str:
        """Create a new session and return its ID"""
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        session = ComputerUseSession(session_id)
        self.sessions[session_id] = session
        
        if logger:
            logger.info(f"Created new session: {session_id}")
            
        # Start cleanup task if not already running
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            
        return session_id
        
    def get_session(self, session_id: str) -> Optional[ComputerUseSession]:
        """Get a session by ID, updating its activity timestamp"""
        session = self.sessions.get(session_id)
        if session:
            session.update_activity()
        return session
        
    async def cleanup_session(self, session_id: str) -> bool:
        """Clean up a specific session"""
        session = self.sessions.get(session_id)
        if session:
            await session.cleanup()
            del self.sessions[session_id]
            if logger:
                logger.info(f"Session {session_id} removed")
            return True
        return False
        
    async def cleanup_inactive_sessions(self):
        """Clean up expired sessions"""
        expired_sessions = [
            session_id for session_id, session in self.sessions.items()
            if session.is_expired()
        ]
        
        for session_id in expired_sessions:
            await self.cleanup_session(session_id)
            
        if expired_sessions and logger:
            logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")
            
    async def _periodic_cleanup(self):
        """Periodic cleanup task that runs in the background"""
        while True:
            try:
                await asyncio.sleep(CLEANUP_INTERVAL)
                await self.cleanup_inactive_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                if logger:
                    logger.error(f"Error in periodic cleanup: {e}")
                    
    async def shutdown(self):
        """Shutdown the session manager and clean up all sessions"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            
        # Clean up all sessions
        session_ids = list(self.sessions.keys())
        for session_id in session_ids:
            await self.cleanup_session(session_id)

# Global session manager instance
session_manager = SessionManager()

class ComputerUseManager:
    def __init__(self, connection_manager, app_logger):
        self.manager = connection_manager
        self.logger = app_logger
        self.desktop = None
        self.agent = None
        self.current_task = None
        
    async def callback(self, data):
        """Callback function to handle agent updates"""
        global stop_requested
        try:
            # Check if stop was requested
            if stop_requested:
                self.logger.info("Stop requested, interrupting callback")
                raise asyncio.CancelledError("Task stopped by user")
                
            await self.manager.send_json({
                "type": data.get("type", "info"),
                "data": data.get("data", ""),
                "timestamp": data.get("timestamp", datetime.now().strftime("%H:%M:%S"))
            })
        except Exception as e:
            self.logger.error(f"Error in callback: {e}")

class SessionAwareComputerUseManager:
    """Session-aware version of ComputerUseManager"""
    
    def __init__(self, session_id: str, connection_manager, app_logger):
        self.session_id = session_id
        self.manager = connection_manager
        self.logger = app_logger
        self.desktop = None
        self.agent = None
        self.current_task = None
        
    async def callback(self, data):
        """Callback function to handle agent updates for a specific session"""
        try:
            session = session_manager.get_session(self.session_id)
            if not session:
                self.logger.warning(f"Session {self.session_id} not found during callback")
                return
                
            # Check if stop was requested for this session
            if session.stop_requested:
                self.logger.info(f"Stop requested for session {self.session_id}, interrupting callback")
                raise asyncio.CancelledError("Task stopped by user")
                
            # Send message only to connections in this session
            await self.manager.send_to_session(self.session_id, {
                "type": data.get("type", "info"),
                "data": data.get("data", ""),
                "timestamp": data.get("timestamp", datetime.now().strftime("%H:%M:%S"))
            })
        except Exception as e:
            self.logger.error(f"Error in session {self.session_id} callback: {e}")

# Start desktop stream for computer use
async def start_computer_desktop(session_id: str = None):
    """Start desktop instance for computer use"""
    
    if not manager:
        return {"status": "error", "message": "Manager not initialized"}
    
    # Create new session if none provided, or if provided session doesn't exist
    if not session_id:
        session_id = session_manager.create_session()
    else:
        # Check if session exists, create if not
        session = session_manager.get_session(session_id)
        if not session:
            # Create session with the provided ID
            session = ComputerUseSession(session_id)
            session_manager.sessions[session_id] = session
            logger.info(f"Created new session with provided ID: {session_id}")
    
    session = session_manager.get_session(session_id)
    if not session:
        return {"status": "error", "message": f"Session {session_id} not found"}
    
    await manager.send_to_session(session_id, {"type": "info", "data": "Starting computer use desktop..."})
    
    try:
        # Initialize session manager if needed
        if not session.manager:
            session.manager = SessionAwareComputerUseManager(session_id, manager, logger)
        
        api_key = os.environ.get("API_KEY")
        template = os.environ.get("TEMPLATE")
        domain = os.environ.get("DOMAIN")
        timeout = int(os.environ.get("TIMEOUT", 1200))
        
        logger.info(f"Creating computer use desktop for session {session_id} with template: {template}")
        
        # Create sandbox
        session.desktop = Sandbox(
            api_key=api_key,
            template=template,
            domain=domain,
            timeout=timeout,
            metadata={
                "purpose": "computer-use",
                "session_id": session_id
            }
        )
        
        logger.info(f"Computer desktop created for session {session_id}: {session.desktop.sandbox_id}")
        
        # Start stream
        session.desktop.stream.start(require_auth=True)
        auth_key = session.desktop.stream.get_auth_key()
        stream_url = session.desktop.stream.get_url(auth_key=auth_key)
        
        # Initialize computer use agent
        session.agent = ComputerUseAgent(session.desktop)
        session.manager.desktop = session.desktop
        session.manager.agent = session.agent
        
        # Send success message to client
        await manager.send_to_session(session_id, {
            "type": "desktop_started",
            "data": {
                "session_id": session_id,
                "sandbox_id": session.desktop.sandbox_id,
                "stream_url": stream_url,
                "timeout": timeout
            }
        })
        
        # Inform user that desktop is loading
        await manager.send_to_session(session_id, {
            "type": "info",
            "data": "Desktop stream is loading. Please wait for the display to appear before starting tasks..."
        })
        
        # Wait for browser iframe to load the stream
        await asyncio.sleep(2)
        logger.info(f"Computer use desktop started successfully for session {session_id}")
        return {"status": "success", "stream_url": stream_url, "session_id": session_id}
        
    except Exception as e:
        logger.error(f"Error starting computer desktop for session {session_id}: {e}", exc_info=True)
        await manager.send_to_session(session_id, {"type": "error", "data": f"Error starting desktop: {str(e)}"})
        return {"status": "error", "message": str(e)}

# Run computer use task
async def run_computer_use_task(query: str, session_id: str = None, sandbox_id: str = None, background_tasks: BackgroundTasks = None):
    """Run a computer use task"""
    
    if not manager:
        return {"status": "error", "message": "Manager not initialized"}
    
    # Create new session if none provided, or if provided session doesn't exist
    if not session_id:
        session_id = session_manager.create_session()
    else:
        # Check if session exists, create if not
        session = session_manager.get_session(session_id)
        if not session:
            # Create session with the provided ID
            session = ComputerUseSession(session_id)
            session_manager.sessions[session_id] = session
            logger.info(f"Created new session with provided ID: {session_id}")
    
    session = session_manager.get_session(session_id)
    if not session:
        return {"status": "error", "message": f"Session {session_id} not found"}
    
    # If no sandbox exists for this session, start a new desktop
    if not session.desktop:
        logger.info(f"No existing desktop for session {session_id}, starting new one")
        desktop_result = await start_computer_desktop(session_id)
        if desktop_result["status"] == "error":
            return desktop_result
    elif sandbox_id and sandbox_id != getattr(session.desktop, 'sandbox_id', None):
        # Connect to existing sandbox
        try:
            # Initialize session manager if needed
            if not session.manager:
                session.manager = SessionAwareComputerUseManager(session_id, manager, logger)
                
            session.desktop = Sandbox(sandbox_id=sandbox_id)
            session.agent = ComputerUseAgent(session.desktop)
            session.manager.desktop = session.desktop
            session.manager.agent = session.agent
        except Exception as e:
            logger.error(f"Error connecting to sandbox {sandbox_id} for session {session_id}: {e}")
            return {"status": "error", "message": f"Failed to connect to sandbox: {str(e)}"}
    
    if not session.agent:
        return {"status": "error", "message": "No computer use agent available"}
    
    # Check if task is already running for this session
    if session.current_task and not session.current_task.done():
        return {"status": "error", "message": "A computer use task is already running in this session"}
    
    await manager.send_to_session(session_id, {"type": "info", "data": f"Running computer use task: {query}"})
    
    # Add to background tasks with proper task tracking
    if background_tasks:
        background_tasks.add_task(run_computer_task_in_background, query, session_id)
    else:
        # Store task reference for cancellation
        session.current_task = asyncio.create_task(run_computer_task_in_background(query, session_id))
    
    return {"status": "success", "message": "Computer use task started", "session_id": session_id}

# Run computer task in background
async def run_computer_task_in_background(query: str, session_id: str):
    """Run the computer task in background for a specific session"""
    
    try:
        session = session_manager.get_session(session_id)
        if not session:
            logger.error(f"Session {session_id} not found during task execution")
            return
            
        if not session.agent:
            await manager.send_to_session(session_id, {"type": "error", "data": "No computer agent available"})
            return
        
        # Reset stop flag for this session
        session.stop_requested = False
        
        # Set current task reference (for stopping) - get actual current task
        session.current_task = asyncio.current_task()
        
        logger.info(f"Starting computer task for session {session_id}: {query}")
        await manager.send_to_session(session_id, {"type": "info", "data": "Starting computer use task..."})
        
        # Wait to ensure desktop is visible and ready
        await asyncio.sleep(1)
        
        # Initialize session manager if needed
        if not session.manager:
            session.manager = SessionAwareComputerUseManager(session_id, manager, logger)
            
        # Process the user message with the agent
        # This handles the full computer use loop: screenshot -> analyze -> execute actions -> repeat
        result = await session.agent.process_user_message(query, callback=session.manager.callback)
        
        await manager.send_to_session(session_id, {
            "type": "task_completed",
            "data": f"Task completed: {result}"
        })
        
    except asyncio.CancelledError:
        logger.info(f"Computer task was cancelled for session {session_id}")
        await manager.send_to_session(session_id, {"type": "info", "data": "Computer task was stopped"})
        # Re-raise to properly handle cancellation
        raise
    except Exception as e:
        logger.error(f"Error in computer task for session {session_id}: {e}", exc_info=True)
        await manager.send_to_session(session_id, {"type": "error", "data": f"Error in computer task: {str(e)}"})
    finally:
        # Clean up session task reference
        session = session_manager.get_session(session_id)
        if session:
            session.current_task = None
            session.stop_requested = False

# Take screenshot
async def take_computer_screenshot(session_id: str = None, sandbox_id: str = None):
    """Take a screenshot of the computer desktop"""
    
    if not session_id:
        return {"status": "error", "message": "Session ID required"}
    
    session = session_manager.get_session(session_id)
    if not session or not session.agent:
        return {"status": "error", "message": "No computer agent available for this session"}
    
    try:
        # Take screenshot
        screenshot_base64 = await session.agent.take_screenshot()
        
        # Send screenshot to clients in this session
        await manager.send_to_session(session_id, {
            "type": "screenshot",
            "data": screenshot_base64,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        })
        
        return {"status": "success", "message": "Screenshot taken"}
        
    except Exception as e:
        logger.error(f"Error taking computer screenshot for session {session_id}: {e}")
        await manager.send_to_session(session_id, {"type": "error", "data": f"Error taking screenshot: {str(e)}"})
        return {"status": "error", "message": str(e)}

# Stop computer task
async def stop_computer_task(session_id: str = None):
    """Stop the currently running computer task"""
    
    if not session_id:
        return {"status": "error", "message": "Session ID required"}
    
    session = session_manager.get_session(session_id)
    if not session:
        return {"status": "error", "message": f"Session {session_id} not found"}
    
    if not session.current_task or session.current_task.done():
        return {"status": "error", "message": "No computer task is running in this session"}
    
    try:
        logger.info(f"Stopping computer task for session {session_id}: {session.current_task}")
        await manager.send_to_session(session_id, {"type": "info", "data": "Stopping computer task..."})
        
        # Set stop flag first to interrupt any ongoing operations
        session.stop_requested = True
        
        # Cancel the current task
        session.current_task.cancel()
        
        # Wait for the task to be cancelled with timeout
        try:
            await asyncio.wait_for(session.current_task, timeout=3.0)
        except asyncio.TimeoutError:
            logger.warning(f"Task cancellation timed out for session {session_id}")
        except asyncio.CancelledError:
            logger.info(f"Task cancelled successfully for session {session_id}")
        
        await manager.send_to_session(session_id, {"type": "info", "data": "Computer task stopped"})
        
        return {"status": "success", "message": "Computer task stopped"}
        
    except Exception as e:
        logger.error(f"Error stopping computer task for session {session_id}: {e}")
        await manager.send_to_session(session_id, {"type": "error", "data": f"Error stopping task: {str(e)}"})
        return {"status": "error", "message": str(e)}
    finally:
        session.stop_requested = False

# Kill computer desktop
async def kill_computer_desktop(session_id: str = None):
    """Kill the computer desktop instance"""
    
    if not session_id:
        return {"status": "error", "message": "Session ID required"}
    
    session = session_manager.get_session(session_id)
    if not session:
        return {"status": "error", "message": f"Session {session_id} not found"}
    
    if not session.desktop:
        return {"status": "error", "message": "No computer desktop instance available for this session"}
    
    await manager.send_to_session(session_id, {"type": "info", "data": "Stopping computer desktop..."})
    
    try:
        # First stop any running task
        if session.current_task:
            session.current_task.cancel()
            session.current_task = None
        
        # Kill the desktop
        session.desktop.kill()
        session.desktop = None
        session.agent = None
        
        if session.manager:
            session.manager.desktop = None
            session.manager.agent = None
        
        await manager.send_to_session(session_id, {"type": "desktop_killed", "data": "Computer desktop stopped"})
        
        logger.info(f"Computer desktop killed successfully for session {session_id}")
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"Error killing computer desktop for session {session_id}: {e}")
        await manager.send_to_session(session_id, {"type": "error", "data": f"Error stopping desktop: {str(e)}"})
        return {"status": "error", "message": str(e)}

# Initialize shared variables
def init_computer_use_vars(app_manager, app_logger, app_ws_handler, app_stdout_capture, app_stderr_capture, app_sessions):
    """Initialize shared variables from app.py"""
    global manager, logger, ws_handler, stdout_capture, stderr_capture, sessions
    manager = app_manager
    logger = app_logger
    ws_handler = app_ws_handler
    stdout_capture = app_stdout_capture
    stderr_capture = app_stderr_capture
    sessions = app_sessions
