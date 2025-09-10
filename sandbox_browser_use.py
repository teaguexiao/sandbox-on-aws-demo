import os
import asyncio
import sys
import logging
import uuid
from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect, BackgroundTasks, Depends, Response, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import List, Dict, Optional, Set
import json
from datetime import datetime, timedelta, timezone
from e2b_desktop import Sandbox

# Import functions from sandbox_desktop.py
from sandbox_desktop import open_desktop_stream, setup_environment, create_sts

# Session configuration constants
BROWSER_SESSION_TIMEOUT = 3600  # 1 hour in seconds
BROWSER_CLEANUP_INTERVAL = 300  # 5 minutes in seconds

# Timezone configuration
GMT_PLUS_8 = timezone(timedelta(hours=8))

# These will be initialized from app.py
manager = None
logger = None
ws_handler = None
stdout_capture = None
stderr_capture = None
sessions = {}

class BrowserUseSession:
    """Represents a single browser-use session with isolated resources"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.desktop: Optional[Sandbox] = None
        self.stream_url: Optional[str] = None
        self.current_command = None
        self.connections: Set[WebSocket] = set()
        self.last_activity = datetime.now()
        self.created_at = datetime.now()
        
    def update_activity(self):
        """Update the last activity timestamp"""
        self.last_activity = datetime.now()
        
    def is_expired(self) -> bool:
        """Check if the session has expired"""
        return datetime.now() - self.last_activity > timedelta(seconds=BROWSER_SESSION_TIMEOUT)
        
    async def cleanup(self):
        """Clean up session resources"""
        try:
            # Kill any running command
            if self.current_command:
                try:
                    self.current_command.kill()
                except Exception as e:
                    if logger:
                        logger.error(f"Error killing command in session {self.session_id}: {e}")
                    
            # Kill the desktop sandbox
            if self.desktop:
                self.desktop.kill()
                
            # Clear references
            self.desktop = None
            self.stream_url = None
            self.current_command = None
            self.connections.clear()
            
            if logger:
                logger.info(f"Browser-use session {self.session_id} cleaned up successfully")
                
        except Exception as e:
            if logger:
                logger.error(f"Error cleaning up browser-use session {self.session_id}: {e}")

class BrowserSessionManager:
    """Manages multiple browser-use sessions"""
    
    def __init__(self):
        self.sessions: Dict[str, BrowserUseSession] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        
    def create_session(self) -> str:
        """Create a new session and return its ID"""
        session_id = f"browser_{uuid.uuid4().hex[:12]}"
        session = BrowserUseSession(session_id)
        self.sessions[session_id] = session
        
        if logger:
            logger.info(f"Created new browser-use session: {session_id}")
            
        # Start cleanup task if not already running
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            
        return session_id
        
    def get_session(self, session_id: str) -> Optional[BrowserUseSession]:
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
                logger.info(f"Browser-use session {session_id} removed")
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
            logger.info(f"Cleaned up {len(expired_sessions)} expired browser-use sessions")
            
    async def _periodic_cleanup(self):
        """Periodic cleanup task that runs in the background"""
        while True:
            try:
                await asyncio.sleep(BROWSER_CLEANUP_INTERVAL)
                await self.cleanup_inactive_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                if logger:
                    logger.error(f"Error in browser-use periodic cleanup: {e}")
                    
    async def shutdown(self):
        """Shutdown the session manager and clean up all sessions"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            
        # Clean up all sessions
        session_ids = list(self.sessions.keys())
        for session_id in session_ids:
            await self.cleanup_session(session_id)

# Global browser session manager instance
browser_session_manager = BrowserSessionManager()

# WebSocket logger class for handling command output
class WebSocketLogger:
    def __init__(self, manager, log_type="stdout"):
        self.manager = manager
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
            timestamp = datetime.now(GMT_PLUS_8).strftime("%H:%M:%S")
            
            # Create log entry
            log_entry = {
                "type": self.log_type,
                "timestamp": timestamp,
                "data": data
            }
            
            # Send to client via WebSocket
            asyncio.run_coroutine_threadsafe(
                self.manager.send_json(log_entry), 
                self.loop
            )
        except Exception as e:
            # Don't use logging here to avoid potential infinite recursion
            print(f"Error in WebSocketLogger: {e}", file=sys.stderr)

class SessionAwareWebSocketLogger:
    """Session-aware version of WebSocketLogger"""
    
    def __init__(self, session_id: str, manager, log_type="stdout"):
        self.session_id = session_id
        self.manager = manager
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
            timestamp = datetime.now(GMT_PLUS_8).strftime("%H:%M:%S")
            
            # Create log entry
            log_entry = {
                "type": self.log_type,
                "timestamp": timestamp,
                "data": data
            }
            
            # Send to session via WebSocket
            asyncio.run_coroutine_threadsafe(
                self.manager.send_to_session(self.session_id, log_entry), 
                self.loop
            )
        except Exception as e:
            # Don't use logging here to avoid potential infinite recursion
            print(f"Error in SessionAwareWebSocketLogger for session {self.session_id}: {e}", file=sys.stderr)

# WebSocket endpoint for real-time communication
async def websocket_endpoint(websocket: WebSocket, session_token: Optional[str] = Cookie(None)):
    session_id = None
    await manager.connect(websocket)
    
    # Clear log buffers when a new connection is established
    if hasattr(ws_handler, 'clear_buffer'):
        ws_handler.clear_buffer()
        logger.info("Logs cleared automatically on new connection")
    
    # Clear stdout/stderr buffers too
    if hasattr(stdout_capture, 'buffer'):
        stdout_capture.buffer = []
    
    if hasattr(stderr_capture, 'buffer'):
        stderr_capture.buffer = []
    
    # Send initial connection message
    timestamp = datetime.now(GMT_PLUS_8).strftime("%H:%M:%S")
    await websocket.send_json({
        "type": "info",
        "timestamp": timestamp,
        "data": "Connected to server. Logs cleared."
    })
    
    try:
        while True:
            # Wait for messages from the client
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                if message.get('action') == 'identify_session':
                    # Handle session identification
                    session_id = message.get('session_id')
                    if session_id:
                        # Associate connection with session ID
                        manager.associate_session(websocket, session_id)
                        logger.info(f"WebSocket connected to session: {session_id}")
                        # Send confirmation back to client
                        await websocket.send_json({
                            "type": "info",
                            "timestamp": datetime.now(GMT_PLUS_8).strftime("%H:%M:%S"),
                            "data": f"Session identified: {session_id}"
                        })
                        
                        # Also create sessions in both session managers if they don't exist
                        from sandbox_computer_use import session_manager, ComputerUseSession
                        if not session_manager.get_session(session_id):
                            session = ComputerUseSession(session_id)
                            session_manager.sessions[session_id] = session
                            logger.info(f"Created computer use session: {session_id}")
                        
                        # Create browser-use session if it doesn't exist
                        if not browser_session_manager.get_session(session_id):
                            browser_session = BrowserUseSession(session_id)
                            browser_session_manager.sessions[session_id] = browser_session
                            logger.info(f"Created browser use session: {session_id}")
                elif message.get('action') == 'clear_logs':
                    # Clear the log buffer
                    ws_handler.clear_buffer()
                    # Clear stdout/stderr buffers too
                    stdout_capture.buffer = []
                    stderr_capture.buffer = []
                    logger.info("Logs cleared by client request")
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON received: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Start desktop instance
async def start_desktop(session_id: str = None):
    """Start desktop instance for browser-use"""
    
    if not manager:
        return {"status": "error", "message": "Manager not initialized"}
    
    # Create new session if none provided, or if provided session doesn't exist
    if not session_id:
        session_id = browser_session_manager.create_session()
    else:
        # Check if session exists, create if not
        session = browser_session_manager.get_session(session_id)
        if not session:
            # Create session with the provided ID
            session = BrowserUseSession(session_id)
            browser_session_manager.sessions[session_id] = session
            logger.info(f"Created new browser-use session with provided ID: {session_id}")
    
    session = browser_session_manager.get_session(session_id)
    if not session:
        return {"status": "error", "message": f"Browser-use session {session_id} not found"}
    
    await manager.send_to_session(session_id, {"type": "info", "data": "Starting desktop stream..."})
    
    try:
        logger.info(f"Creating browser-use desktop for session {session_id}")
        
        api_key = os.environ.get("API_KEY")
        template = os.environ.get("TEMPLATE")
        domain = os.environ.get("DOMAIN")
        timeout = int(os.environ.get("TIMEOUT", 1200))
        
        logger.info(f"Using template: {template}, domain: {domain}, timeout: {timeout}")
        logger.info(f"API_KEY present: {bool(api_key)}")
        
        # Create sandbox with detailed error handling
        logger.info(f"Initializing Sandbox object for session {session_id}...")
        session.desktop = Sandbox(
                api_key=api_key,
                template=template,
                domain=domain,
                timeout=timeout,
                metadata={
                    "purpose": "browser-use",
                    "session_id": session_id
                }
            )
        logger.info(f"Sandbox object initialized for session {session_id}, sandbox_id: {session.desktop.sandbox_id}")

        # Log sandbox object details
        for attr in ['sandbox_id', 'status', 'ready']:
            if hasattr(session.desktop, attr):
                logger.info(f"Session {session_id} Sandbox {attr}: {getattr(session.desktop, attr)}")
            else:
                logger.info(f"Session {session_id} Sandbox has no attribute '{attr}'")
        
        # Log stream object details
        if hasattr(session.desktop, 'stream'):
            logger.info(f"Session {session_id} Stream object exists, checking properties...")
            stream_obj = session.desktop.stream
            for attr in ['id', 'status']:
                if hasattr(stream_obj, attr):
                    logger.info(f"Session {session_id} Stream {attr}: {getattr(stream_obj, attr)}")
        else:
            logger.error(f"Session {session_id} Sandbox has no 'stream' attribute!")
            raise Exception("Sandbox missing stream attribute")
        
        # Get auth key and stream URL
        try:
            logger.info(f"Starting stream for session {session_id}...")
            session.desktop.stream.start(require_auth=True)

            logger.info(f"Getting stream auth key for session {session_id}...")
            auth_key = session.desktop.stream.get_auth_key()
            logger.info(f"Auth key retrieved successfully for session {session_id}")
            
            logger.info(f"Getting stream URL for session {session_id}...")
            session.stream_url = session.desktop.stream.get_url(auth_key=auth_key)
            logger.info(f"Stream URL generated for session {session_id}: {session.stream_url}")
        except Exception as e:
            logger.error(f"Error getting stream URL for session {session_id}: {e}", exc_info=True)
            await manager.send_to_session(session_id, {"type": "error", "data": f"Error getting stream URL: {str(e)}"})  
            return {"status": "error", "message": f"Error getting stream URL: {str(e)}"}
        
        # Send success message to client
        logger.info(f"Sending desktop_started event to session {session_id}")
        await manager.send_to_session(session_id, {
            "type": "desktop_started", 
            "data": {
                "session_id": session_id,
                "sandbox_id": session.desktop.sandbox_id,
                "stream_url": session.stream_url,
                "timeout": timeout
            }
        })
        logger.info(f"Desktop started event sent successfully for session {session_id}")
        
        return {"status": "success", "stream_url": session.stream_url, "session_id": session_id}
        
    except Exception as e:
        logger.error(f"Unexpected error in start_desktop for session {session_id}: {e}", exc_info=True)
        await manager.send_to_session(session_id, {"type": "error", "data": f"Unexpected error: {str(e)}"})  
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}

# Setup environment
async def setup_env(session_id: str = None, background_tasks: BackgroundTasks = None):
    
    if not session_id:
        return {"status": "error", "message": "Session ID required"}
    
    session = browser_session_manager.get_session(session_id)
    if not session or not session.desktop:
        return {"status": "error", "message": "No desktop instance available for this session"}
    
    await manager.send_to_session(session_id, {"type": "info", "data": "Setting up environment in background..."})
    
    # Add to background tasks
    if background_tasks:
        background_tasks.add_task(setup_env_in_background, session_id)
    else:
        # If not called with background_tasks (e.g. direct API call)
        # create a new background task manually
        asyncio.create_task(setup_env_in_background(session_id))
    
    return {"status": "success", "message": "Environment setup started in background"}

# Setup environment in background
async def setup_env_in_background(session_id: str):
    """Run the environment setup in background so it can be cancelled"""
    
    try:
        session = browser_session_manager.get_session(session_id)
        if not session or not session.desktop:
            logger.error(f"Session {session_id} not found or no desktop during environment setup")
            return
        
        # Step 1: Copy files to sandbox
        await manager.send_to_session(session_id, {"type": "info", "data": "Copying files to sandbox..."})
        
        try:
            with open('bedrock.py', 'r') as f1:
                _code = f1.read()
                session.desktop.files.write('/tmp/bedrock.py', _code)
                await manager.send_to_session(session_id, {"type": "info", "data": "Copied bedrock.py to /tmp/bedrock.py"})
                
        except Exception as e:
            logger.error(f"Error copying files for session {session_id}: {e}")
            await manager.send_to_session(session_id, {"type": "error", "data": f"Error copying files: {str(e)}"})
            return
        
        # Step 2: Create STS credentials
        await manager.send_to_session(session_id, {"type": "info", "data": "Creating AWS credentials..."})
        credentials = create_sts()
        if not credentials:
            await manager.send_to_session(session_id, {"type": "error", "data": "Failed to create AWS credentials"})
            return
            
        creds_content = f"""[default]
    aws_access_key_id={credentials['AccessKeyId']}
    aws_secret_access_key={credentials['SecretAccessKey']}
    aws_session_token={credentials['SessionToken']}
    """
        session.desktop.files.write('~/.aws/credentials', creds_content)
        await manager.send_to_session(session_id, {"type": "info", "data": "AWS credentials created successfully"})
        
        await manager.send_to_session(session_id, {"type": "info", "data": "Installing Playwright browser..."})

        stdout_logger = SessionAwareWebSocketLogger(session_id, manager, "stdout")
        stderr_logger = SessionAwareWebSocketLogger(session_id, manager, "stderr")

        cmd = 'playwright install chromium --with-deps --no-shell'
        logger.info(f"Running command in background for session {session_id}: {cmd}")
        session.current_command = session.desktop.commands.run(
            cmd,
            on_stdout=stdout_logger,
            on_stderr=stderr_logger,
            background=True
        )
        logger.info(f"Command started for session {session_id} with id: {getattr(session.current_command, 'id', 'unknown')}")
        
        # Wait for command to complete
        result = await asyncio.to_thread(session.current_command.wait)
        # CommandResult object doesn't have a get method, access exit_code directly
        if hasattr(result, 'exit_code') and result.exit_code != 0:
            await manager.send_to_session(session_id, {"type": "error", "data": "Failed to install Playwright browser"})
            return

        await manager.send_to_session(session_id, {"type": "info", "data": "Environment setup completed successfully"})
        

    except Exception as e:
        logger.error(f"Error setting up environment for session {session_id}: {e}")
        await manager.send_to_session(session_id, {"type": "error", "data": f"Error setting up environment: {str(e)}"})
    finally:
        # Clean up session command reference
        session = browser_session_manager.get_session(session_id)
        if session:
            session.current_command = None

# Run task
async def run_task(query: str = Form(...), session_id: str = None, background_tasks: BackgroundTasks = None):
    
    if not session_id:
        return {"status": "error", "message": "Session ID required"}
    
    session = browser_session_manager.get_session(session_id)
    if not session or not session.desktop:
        return {"status": "error", "message": "No desktop instance available for this session"}
    
    await manager.send_to_session(session_id, {"type": "info", "data": f"Running task: {query}"})
    
    # Add to background tasks
    if background_tasks:
        background_tasks.add_task(run_task_in_background, query, session_id)
    else:
        # If not called with background_tasks (e.g. direct API call)
        # create a new background task manually
        asyncio.create_task(run_task_in_background(query, session_id))
    
    return {"status": "success", "message": "Task started in background"}

# Run task in background
async def run_task_in_background(query: str, session_id: str):
    """Run the task in background so it can be cancelled"""
    
    try:
        session = browser_session_manager.get_session(session_id)
        if not session or not session.desktop:
            logger.error(f"Session {session_id} not found or no desktop during task execution")
            return
        
        # Run bedrock.py with the query
        stdout_logger = SessionAwareWebSocketLogger(session_id, manager, "stdout")
        stderr_logger = SessionAwareWebSocketLogger(session_id, manager, "stderr")
        
        # Clear any existing command reference
        session.current_command = None
        
        # Start the command in BACKGROUND mode with the proper E2B API
        # This returns immediately but keeps the process running
        logger.info(f"Starting task in background mode for session {session_id}")
        cmd = f"python3.11 /tmp/bedrock.py --query '{query}'"
        logger.info(f"Running command in background for session {session_id}: {cmd}")
        session.current_command = session.desktop.commands.run(
            cmd,
            on_stdout=stdout_logger,
            on_stderr=stderr_logger,
            background=True,  # This is key to allow immediate kill
            timeout=0  # Disable timeout to prevent 'context deadline exceeded' errors
        )
        # Log more detailed information about the command object
        logger.info(f"Command started for session {session_id} with id: {getattr(session.current_command, 'id', 'unknown')}")
        logger.info(f"Command object for session {session_id}: {session.current_command}")
        # Log available attributes
        for attr in ['id', 'sandbox_id', 'process_id', 'exit_code', 'status']:
            if hasattr(session.current_command, attr):
                logger.info(f"Session {session_id} Command {attr}: {getattr(session.current_command, attr)}")
        
        # Wait for the command to complete naturally or be killed externally
        result = await asyncio.to_thread(session.current_command.wait)
        
        # Check the exit code to see if it completed successfully or was killed
        exit_code = getattr(result, 'exit_code', None)
        if exit_code == 0:
            await manager.send_to_session(session_id, {"type": "task_completed", "data": "Task completed successfully"})
        elif exit_code is None or exit_code < 0:
            # Likely killed
            await manager.send_to_session(session_id, {"type": "info", "data": "Task was terminated"})
        else:
            await manager.send_to_session(session_id, {"type": "error", "data": f"Task failed with exit code: {exit_code}"})
            
    except Exception as e:
        logger.error(f"Error running task for session {session_id}: {e}")
        await manager.send_to_session(session_id, {"type": "error", "data": f"Error running task: {str(e)}"})
    finally:
        # Clean up session command reference
        session = browser_session_manager.get_session(session_id)
        if session:
            session.current_command = None

# Kill desktop
async def kill_desktop(session_id: str = None):
    
    if not session_id:
        return {"status": "error", "message": "Session ID required"}
    
    session = browser_session_manager.get_session(session_id)
    if not session:
        return {"status": "error", "message": f"Browser-use session {session_id} not found"}
    
    if not session.desktop:
        return {"status": "error", "message": "No desktop instance available for this session"}
    
    await manager.send_to_session(session_id, {"type": "info", "data": "Killing desktop instance and workflow processes..."})
    
    try:
        # First, kill any running command with the proper API
        if session.current_command:
            logger.info(f"Killing current command for session {session_id}: {session.current_command}")
            for attr in ['id', 'sandbox_id', 'process_id', 'exit_code', 'status']:
                if hasattr(session.current_command, attr):
                    logger.info(f"Session {session_id} Command {attr} before kill: {getattr(session.current_command, attr)}")
            
            try:
                # Use the E2B command kill method
                session.current_command.kill()
                logger.info(f"Command kill() method called successfully for session {session_id}")
                
                # Log command attributes after killing
                for attr in ['id', 'sandbox_id', 'process_id', 'exit_code', 'status']:
                    if hasattr(session.current_command, attr):
                        logger.info(f"Session {session_id} Command {attr} after kill: {getattr(session.current_command, attr)}")
            except Exception as e:
                logger.error(f"Error killing command for session {session_id}: {e}")
        
        # Force kill any Python processes for good measure
        try:
            await manager.send_to_session(session_id, {"type": "info", "data": "Killing all Python processes"})
            cmd = "pkill -9 python"
            logger.info(f"Running command for session {session_id}: {cmd}")
            result = session.desktop.commands.run(cmd, timeout=2)
            logger.info(f"Command started for session {session_id} with id: {getattr(result, 'id', 'unknown')}")
            for attr in ['id', 'sandbox_id', 'process_id', 'exit_code', 'status']:
                if hasattr(result, attr):
                    logger.info(f"Session {session_id} Command {attr}: {getattr(result, attr)}")
            await manager.send_to_session(session_id, {"type": "info", "data": "Killed all Python processes"})
        except Exception as process_error:
            # Log but continue with sandbox kill
            logger.warning(f"Error killing processes for session {session_id}: {process_error}")
        
        # Now kill the desktop sandbox
        session.desktop.kill()
        session.desktop = None
        session.stream_url = None
        session.current_command = None
        await manager.send_to_session(session_id, {"type": "desktop_killed", "data": "Desktop instance killed"})
        
        logger.info(f"Browser-use desktop killed successfully for session {session_id}")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error killing desktop for session {session_id}: {e}")
        await manager.send_to_session(session_id, {"type": "error", "data": f"Error killing desktop: {str(e)}"})
        return {"status": "error", "message": str(e)}

# Run the entire workflow
async def run_workflow(query: str = Form(...), session_id: str = None, background_tasks: BackgroundTasks = BackgroundTasks()):
    # Start desktop
    start_result = await start_desktop(session_id=session_id)
    if start_result["status"] == "error":
        return start_result
    
    # Get the session_id from the result if it was created
    if not session_id and "session_id" in start_result:
        session_id = start_result["session_id"]
    
    # Setup environment in background
    setup_result = await setup_env(session_id=session_id, background_tasks=background_tasks)
    if setup_result["status"] == "error":
        return setup_result
    
    # Run task in background
    await run_task(query, session_id=session_id, background_tasks=background_tasks)
    
    return {"status": "success", "message": "Workflow started", "session_id": session_id}

# Function to initialize shared variables from app.py
def init_shared_vars(app_manager, app_logger, app_ws_handler, app_stdout_capture, app_stderr_capture, app_sessions):
    global manager, logger, ws_handler, stdout_capture, stderr_capture, sessions
    manager = app_manager
    logger = app_logger
    ws_handler = app_ws_handler
    stdout_capture = app_stdout_capture
    stderr_capture = app_stderr_capture
    sessions = app_sessions
