import os
import asyncio
import sys
import logging
from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect, BackgroundTasks, Depends, Response, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import List, Dict, Optional
import json
from datetime import datetime
from e2b_desktop import Sandbox

# Import functions from sandbox_desktop.py
#from sandbox_desktop import open_desktop_stream, setup_environment, create_sts
from sandbox_desktop import open_desktop_stream, setup_environment, create_sts

# Global variables that will be shared with app.py
desktop = None
stream_url = None
current_command = None

# These will be initialized from app.py
manager = None
logger = None
ws_handler = None
stdout_capture = None
stderr_capture = None
sessions = {}

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
            timestamp = datetime.now().strftime("%H:%M:%S")
            
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

# WebSocket endpoint for real-time communication
async def websocket_endpoint(websocket: WebSocket, session_token: Optional[str] = Cookie(None)):
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
    timestamp = datetime.now().strftime("%H:%M:%S")
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
                if message.get('action') == 'clear_logs':
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
async def start_desktop():
    global desktop, stream_url
    await manager.send_json({"type": "info", "data": "Starting desktop stream..."})
    
    try:
        logger.info("Calling open_desktop_stream function...")
        # Run in a separate thread to avoid blocking
        desktop = None
        try:
            # Log sandbox creation attempt
            #logger.info("Creating sandbox via open_desktop_stream...")
            #desktop = open_desktop_stream(open_browser=False)
            api_key = os.environ.get("API_KEY")
            template = os.environ.get("TEMPLATE")
            domain = os.environ.get("DOMAIN")
            timeout = int(os.environ.get("TIMEOUT", 1200))
            
            logger.info(f"Using template: {template}, domain: {domain}, timeout: {timeout}")
            logger.info(f"API_KEY present: {bool(api_key)}")
            
            # Create sandbox with detailed error handling
            logger.info("Initializing Sandbox object...")
            desktop = Sandbox(
                    api_key=api_key,
                    template=template,
                    domain=domain,
                    timeout=timeout,
                    metadata={
                        "purpose": "sandbox-on-aws"
                    }
                )
            logger.info(f"Sandbox object initialized, sandbox_id: {desktop.sandbox_id}")

            # Log sandbox object details
            for attr in ['sandbox_id', 'status', 'ready']:
                if hasattr(desktop, attr):
                    logger.info(f"Sandbox {attr}: {getattr(desktop, attr)}")
                else:
                    logger.info(f"Sandbox has no attribute '{attr}'")
            
            # Log stream object details
            if hasattr(desktop, 'stream'):
                logger.info("Stream object exists, checking properties...")
                stream_obj = desktop.stream
                for attr in ['id', 'status']:
                    if hasattr(stream_obj, attr):
                        logger.info(f"Stream {attr}: {getattr(stream_obj, attr)}")
            else:
                logger.error("Sandbox has no 'stream' attribute!")
                raise Exception("Sandbox missing stream attribute")
        except Exception as e:
            logger.error(f"Error creating sandbox: {e}", exc_info=True)
            await manager.send_json({"type": "error", "data": f"Error creating sandbox: {str(e)}"})  
            return {"status": "error", "message": f"Error creating sandbox: {str(e)}"}
        
        # Get auth key and stream URL
        try:
            logger.info("Starting stream...")
            desktop.stream.start(require_auth=True)

            logger.info("Getting stream auth key...")
            auth_key = desktop.stream.get_auth_key()
            logger.info("Auth key retrieved successfully")
            
            logger.info("Getting stream URL...")
            stream_url = desktop.stream.get_url(auth_key=auth_key)
            logger.info(f"Stream URL generated: {stream_url}")
        except Exception as e:
            logger.error(f"Error getting stream URL: {e}", exc_info=True)
            await manager.send_json({"type": "error", "data": f"Error getting stream URL: {str(e)}"})  
            return {"status": "error", "message": f"Error getting stream URL: {str(e)}"}
        
        # Get timeout from environment variables or use default
        timeout = int(os.environ.get("TIMEOUT", 1200))
        logger.info(f"Using timeout value: {timeout}")
        
        # Send success message to client
        logger.info("Sending desktop_started event to client")
        await manager.send_json({
            "type": "desktop_started", 
            "data": {
                "sandbox_id": desktop.sandbox_id,
                "stream_url": stream_url,
                "timeout": timeout
            }
        })
        logger.info("Desktop started event sent successfully")
    except Exception as e:
        logger.error(f"Unexpected error in start_desktop: {e}", exc_info=True)
        await manager.send_json({"type": "error", "data": f"Unexpected error: {str(e)}"})  
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}
    
    return {"status": "success", "stream_url": stream_url}

# Setup environment
async def setup_env(background_tasks: BackgroundTasks = None):
    global desktop
    
    if not desktop:
        return {"status": "error", "message": "No desktop instance available"}
    
    await manager.send_json({"type": "info", "data": "Setting up environment in background..."})
    
    # Add to background tasks
    if background_tasks:
        background_tasks.add_task(setup_env_in_background)
    else:
        # If not called with background_tasks (e.g. direct API call)
        # create a new background task manually
        asyncio.create_task(setup_env_in_background())
    
    return {"status": "success", "message": "Environment setup started in background"}

# Setup environment in background
async def setup_env_in_background():
    """Run the environment setup in background so it can be cancelled"""
    global desktop, current_command
    
    try:
        # Step 1: Copy files to sandbox
        await manager.send_json({"type": "info", "data": "Copying files to sandbox..."})
        
        try:
            with open('bedrock.py', 'r') as f1:
                _code = f1.read()
                desktop.files.write('/tmp/bedrock.py', _code)
                await manager.send_json({"type": "info", "data": "Copied bedrock.py to /tmp/bedrock.py"})
                
        except Exception as e:
            logger.error(f"Error copying files: {e}")
            await manager.send_json({"type": "error", "data": f"Error copying files: {str(e)}"})
            return
        
        # Step 2: Create STS credentials
        await manager.send_json({"type": "info", "data": "Creating AWS credentials..."})
        credentials = create_sts()
        if not credentials:
            await manager.send_json({"type": "error", "data": "Failed to create AWS credentials"})
            return
            
        creds_content = f"""[default]
    aws_access_key_id={credentials['AccessKeyId']}
    aws_secret_access_key={credentials['SecretAccessKey']}
    aws_session_token={credentials['SessionToken']}
    """
        desktop.files.write('~/.aws/credentials', creds_content)
        await manager.send_json({"type": "info", "data": "AWS credentials created successfully"})
        
        await manager.send_json({"type": "info", "data": "Installing Playwright browser..."})

        stdout_logger = WebSocketLogger(manager, "stdout")
        stderr_logger = WebSocketLogger(manager, "stderr")

        cmd = 'playwright install chromium --with-deps --no-shell'
        logger.info(f"Running command in background: {cmd}")
        current_command = desktop.commands.run(
            cmd,
            on_stdout=stdout_logger,
            on_stderr=stderr_logger,
            background=True
        )
        logger.info(f"Command started with id: {getattr(current_command, 'id', 'unknown')}")
        
        # Wait for command to complete
        result = await asyncio.to_thread(current_command.wait)
        # CommandResult object doesn't have a get method, access exit_code directly
        if hasattr(result, 'exit_code') and result.exit_code != 0:
            await manager.send_json({"type": "error", "data": "Failed to install Playwright browser"})
            return

        await manager.send_json({"type": "info", "data": "Environment setup completed successfully"})
        

    except Exception as e:
        logger.error(f"Error setting up environment: {e}")
        await manager.send_json({"type": "error", "data": f"Error setting up environment: {str(e)}"})
    finally:
        current_command = None

# Run task
async def run_task(query: str = Form(...), background_tasks: BackgroundTasks = None):
    global desktop, current_command
    
    if not desktop:
        return {"status": "error", "message": "No desktop instance available"}
    
    await manager.send_json({"type": "info", "data": f"Running task: {query}"})
    
    # Add to background tasks
    if background_tasks:
        background_tasks.add_task(run_task_in_background, query)
    else:
        # If not called with background_tasks (e.g. direct API call)
        # create a new background task manually
        asyncio.create_task(run_task_in_background(query))
    
    return {"status": "success", "message": "Task started in background"}

# Run task in background
async def run_task_in_background(query: str):
    """Run the task in background so it can be cancelled"""
    global desktop, current_command
    
    try:
        # Run bedrock.py with the query
        stdout_logger = WebSocketLogger(manager, "stdout")
        stderr_logger = WebSocketLogger(manager, "stderr")
        
        # Clear any existing command reference
        current_command = None
        
        # Start the command in BACKGROUND mode with the proper E2B API
        # This returns immediately but keeps the process running
        logger.info("Starting task in background mode")
        #cmd = f"env"
        cmd = f"python3.11 /tmp/bedrock.py --query '{query}'"
        #cmd = f"uv run python3 /tmp/bedrock.py --query '{query}'"
        logger.info(f"Running command in background: {cmd}")
        current_command = desktop.commands.run(
            cmd,
            on_stdout=stdout_logger,
            on_stderr=stderr_logger,
            background=True,  # This is key to allow immediate kill
            timeout=0  # Disable timeout to prevent 'context deadline exceeded' errors
        )
        # Log more detailed information about the command object
        logger.info(f"Command started with id: {getattr(current_command, 'id', 'unknown')}")
        logger.info(f"Command object: {current_command}")
        # Log available attributes
        for attr in ['id', 'sandbox_id', 'process_id', 'exit_code', 'status']:
            if hasattr(current_command, attr):
                logger.info(f"Command {attr}: {getattr(current_command, attr)}")
        
        # Wait for the command to complete naturally or be killed externally
        result = await asyncio.to_thread(current_command.wait)
        
        # Check the exit code to see if it completed successfully or was killed
        exit_code = getattr(result, 'exit_code', None)
        if exit_code == 0:
            await manager.send_json({"type": "task_completed", "data": "Task completed successfully"})
        elif exit_code is None or exit_code < 0:
            # Likely killed
            await manager.send_json({"type": "info", "data": "Task was terminated"})
        else:
            await manager.send_json({"type": "error", "data": f"Task failed with exit code: {exit_code}"})
            
    except Exception as e:
        logger.error(f"Error running task: {e}")
        await manager.send_json({"type": "error", "data": f"Error running task: {str(e)}"})
    finally:
        current_command = None

# Kill desktop
async def kill_desktop():
    global desktop, stream_url, current_command
    
    if not desktop:
        return {"status": "error", "message": "No desktop instance available"}
    
    await manager.send_json({"type": "info", "data": "Killing desktop instance and workflow processes..."})
    
    try:
        # First, kill any running command with the proper API
        if current_command:
            logger.info(f"Killing current command: {current_command}")
            for attr in ['id', 'sandbox_id', 'process_id', 'exit_code', 'status']:
                if hasattr(current_command, attr):
                    logger.info(f"Command {attr} before kill: {getattr(current_command, attr)}")
            
            try:
                # Use the E2B command kill method
                current_command.kill()
                logger.info("Command kill() method called successfully")
                
                # Log command attributes after killing
                for attr in ['id', 'sandbox_id', 'process_id', 'exit_code', 'status']:
                    if hasattr(current_command, attr):
                        logger.info(f"Command {attr} after kill: {getattr(current_command, attr)}")
            except Exception as e:
                logger.error(f"Error killing command: {e}")
        
        # Force kill any Python processes for good measure
        try:
            await manager.send_json({"type": "info", "data": "Killing all Python processes"})
            cmd = "pkill -9 python"
            logger.info(f"Running command in background: {cmd}")
            result = desktop.commands.run(cmd, timeout=2)
            logger.info(f"Command started with id: {getattr(result, 'id', 'unknown')}")
            for attr in ['id', 'sandbox_id', 'process_id', 'exit_code', 'status']:
                if hasattr(result, attr):
                    logger.info(f"Command {attr}: {getattr(result, attr)}")
            await manager.send_json({"type": "info", "data": "Killed all Python processes"})
        except Exception as process_error:
            # Log but continue with sandbox kill
            logger.warning(f"Error killing processes: {process_error}")
        
        # Now kill the desktop sandbox
        desktop.kill()
        desktop = None
        stream_url = None
        current_command = None
        await manager.send_json({"type": "desktop_killed", "data": "Desktop instance killed"})
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error killing desktop: {e}")
        await manager.send_json({"type": "error", "data": f"Error killing desktop: {str(e)}"})
        return {"status": "error", "message": str(e)}

# Run the entire workflow
async def run_workflow(query: str = Form(...), background_tasks: BackgroundTasks = BackgroundTasks()):
    # Start desktop
    start_result = await start_desktop()
    if start_result["status"] == "error":
        return start_result
    
    # Setup environment in background
    setup_result = await setup_env(background_tasks=background_tasks)
    if setup_result["status"] == "error":
        return setup_result
    
    # Run task in background
    await run_task(query, background_tasks=background_tasks)
    
    return {"status": "success", "message": "Workflow started"}

# Function to initialize shared variables from app.py
def init_shared_vars(app_manager, app_logger, app_ws_handler, app_stdout_capture, app_stderr_capture, app_sessions):
    global manager, logger, ws_handler, stdout_capture, stderr_capture, sessions
    manager = app_manager
    logger = app_logger
    ws_handler = app_ws_handler
    stdout_capture = app_stdout_capture
    stderr_capture = app_stderr_capture
    sessions = app_sessions
