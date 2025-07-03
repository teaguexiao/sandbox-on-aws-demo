import os
import asyncio
import sys
import threading
from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
from typing import List, Dict, Optional
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
import io

# Import functions from test-e2b-desktop.py
from test_e2b_desktop import open_desktop_stream, setup_environment, create_sts

# Load environment variables
load_dotenv()

# Configure logging
class WebSocketLogHandler(logging.Handler):
    def __init__(self, connection_manager):
        super().__init__()
        self.connection_manager = connection_manager
        self.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        self.buffer = []

    def emit(self, record):
        try:
            log_entry = self.format(record)
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_type = record.levelname.lower()
            
            # Map log levels to UI log types
            if log_type == 'warning':
                log_type = 'stderr'
            elif log_type == 'error' or log_type == 'critical':
                log_type = 'error'
            elif log_type == 'info':
                log_type = 'info'
            elif log_type == 'debug':
                log_type = 'stdout'
            
            # Store in buffer instead of trying to send immediately
            # Will be sent when a client connects
            self.buffer.append({
                "type": log_type,
                "timestamp": timestamp,
                "data": log_entry
            })
            
            # Only keep the last 1000 log entries to avoid memory issues
            if len(self.buffer) > 1000:
                self.buffer = self.buffer[-1000:]
                
        except Exception as e:
            # Don't use self.handleError to avoid potential infinite recursion
            print(f"Error in WebSocketLogHandler: {e}", file=sys.stderr)

# Set up connection manager first (will be initialized later)
connection_manager = None

# Configure root logger
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                   handlers=[logging.StreamHandler()])

logger = logging.getLogger(__name__)

app = FastAPI(title="Sandbox Desktop WebUI")

# Mount static files directory
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Set up Jinja2 templates
templates = Jinja2Templates(directory="templates")

# Store active connections and desktop instance
connections: List[WebSocket] = []
desktop_instance = None
stream_url = None
# Current running background command reference
current_command = None

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.message_queue: List[Dict] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    
    async def send_message(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                print(f"Error sending message: {e}", file=sys.stderr)
    
    async def send_json(self, data: Dict):
        # If no active connections, queue the message
        if not self.active_connections:
            self.message_queue.append(data)
            # Keep queue size reasonable
            if len(self.message_queue) > 1000:
                self.message_queue = self.message_queue[-1000:]
            return
            
        # Otherwise send to all connections
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception as e:
                print(f"Error sending JSON: {e}", file=sys.stderr)

manager = ConnectionManager()

# Now initialize the WebSocketLogHandler
ws_handler = WebSocketLogHandler(manager)

# Add the WebSocket handler to the root logger to capture all logs
root_logger = logging.getLogger()
root_logger.addHandler(ws_handler)

# Capture stdout and stderr
class StdoutCaptureHandler(io.StringIO):
    def __init__(self, connection_manager, log_type="stdout"):
        super().__init__()
        self.connection_manager = connection_manager
        self.log_type = log_type
        self.original = None
        self.buffer = []
    
    def write(self, data):
        if data and data.strip():
            timestamp = datetime.now().strftime("%H:%M:%S")
            # Store in buffer instead of trying to send immediately
            self.buffer.append({
                "type": self.log_type,
                "timestamp": timestamp,
                "data": data
            })
            
            # Only keep the last 1000 log entries
            if len(self.buffer) > 1000:
                self.buffer = self.buffer[-1000:]
                
        # Write to the original stdout/stderr as well
        if self.original:
            self.original.write(data)
    
    def flush(self):
        if self.original:
            self.original.flush()

# Capture stdout and stderr
stdout_capture = StdoutCaptureHandler(manager, "stdout")
stdout_capture.original = sys.stdout
sys.stdout = stdout_capture

stderr_capture = StdoutCaptureHandler(manager, "stderr")
stderr_capture.original = sys.stderr
sys.stderr = stderr_capture

# Custom stdout/stderr handler for desktop commands
class WebSocketLogger:
    def __init__(self, manager, log_type="stdout"):
        self.manager = manager
        self.log_type = log_type
        self.loop = None
    
    def __call__(self, data):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_data = {
            "type": self.log_type,
            "timestamp": timestamp,
            "data": data
        }
        
        # Store in manager's message queue for later delivery
        self.manager.message_queue.append(log_data)
        
        # Try to get event loop if we don't have one yet
        if not self.loop:
            try:
                self.loop = asyncio.get_event_loop()
            except RuntimeError:
                # No event loop, just use the queue
                pass
        
        # If we have an event loop and it's running, try to send immediately
        if self.loop and self.loop.is_running() and self.manager.active_connections:
            asyncio.run_coroutine_threadsafe(self.manager.send_json(log_data), self.loop)
            
        # Use print instead of logger to avoid duplicate logs
        print(f"[{self.log_type}] {data}")

# Main route
@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/browser-use", response_class=HTMLResponse)
async def get_browser_use(request: Request):
    return templates.TemplateResponse("browser-use.html", {"request": request, "stream_url": stream_url})

@app.get("/computer-use", response_class=HTMLResponse)
async def get_computer_use(request: Request):
    return templates.TemplateResponse("computer-use.html", {"request": request})

@app.get("/ai-coding", response_class=HTMLResponse)
async def get_ai_coding(request: Request):
    return templates.TemplateResponse("ai-coding.html", {"request": request})

@app.get("/ai-search", response_class=HTMLResponse)
async def get_ai_search(request: Request):
    return templates.TemplateResponse("ai-search.html", {"request": request})

@app.get("/ai-ppt", response_class=HTMLResponse)
async def get_ai_ppt(request: Request):
    return templates.TemplateResponse("ai-ppt.html", {"request": request})

# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    
    # Send any buffered logs when a client connects
    if hasattr(ws_handler, 'buffer'):
        for log_entry in ws_handler.buffer:
            await websocket.send_json(log_entry)
    
    # Send any buffered stdout/stderr logs
    if hasattr(stdout_capture, 'buffer'):
        for log_entry in stdout_capture.buffer:
            await websocket.send_json(log_entry)
    
    if hasattr(stderr_capture, 'buffer'):
        for log_entry in stderr_capture.buffer:
            await websocket.send_json(log_entry)
    
    # Send any messages in the manager's queue
    if manager.message_queue:
        for message in manager.message_queue:
            await websocket.send_json(message)
        # Clear the queue after sending
        manager.message_queue = []
    
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Start desktop stream
@app.post("/start-desktop")
async def start_desktop():
    global desktop_instance, stream_url
    '''
    if desktop_instance:
        await manager.send_json({"type": "info", "data": "Killing existing desktop instance..."})
        try:
            desktop_instance.kill()
        except Exception as e:
            logger.error(f"Error killing desktop: {e}")
    '''
    await manager.send_json({"type": "info", "data": "Starting desktop stream..."})
    
    try:
        logger.info("Calling open_desktop_stream function...")
        # Run in a separate thread to avoid blocking
        desktop_instance = None
        try:
            # Log sandbox creation attempt
            logger.info("Creating sandbox via open_desktop_stream...")
            desktop_instance = open_desktop_stream(open_browser=False)
            logger.info(f"Sandbox created successfully with ID: {desktop_instance.sandbox_id if desktop_instance else 'unknown'}")
            
            # Log sandbox object details
            for attr in ['sandbox_id', 'status', 'ready']:
                if hasattr(desktop_instance, attr):
                    logger.info(f"Sandbox {attr}: {getattr(desktop_instance, attr)}")
                else:
                    logger.info(f"Sandbox has no attribute '{attr}'")
            
            # Log stream object details
            if hasattr(desktop_instance, 'stream'):
                logger.info("Stream object exists, checking properties...")
                stream_obj = desktop_instance.stream
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
            logger.info("Getting stream auth key...")
            auth_key = desktop_instance.stream.get_auth_key()
            logger.info("Auth key retrieved successfully")
            
            logger.info("Getting stream URL...")
            stream_url = desktop_instance.stream.get_url(auth_key=auth_key)
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
                "sandbox_id": desktop_instance.sandbox_id,
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
@app.post("/setup-environment")
async def setup_env(background_tasks: BackgroundTasks = None):
    global desktop_instance
    
    if not desktop_instance:
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

async def setup_env_in_background():
    """Run the environment setup in background so it can be cancelled"""
    global desktop_instance, current_command
    
    try:
        # Step 1: Copy files to sandbox
        await manager.send_json({"type": "info", "data": "Copying files to sandbox..."})
        
        try:
            with open('bedrock.py', 'r') as f1, open('.env', 'r') as f2:
                _code = f1.read()
                desktop_instance.files.write('/tmp/bedrock.py', _code)
                await manager.send_json({"type": "info", "data": "Copied bedrock.py to /tmp/bedrock.py"})
                
                _env = f2.read()
                desktop_instance.files.write('~/.env', _env)
                await manager.send_json({"type": "info", "data": "Copied .env to ~/.env"})
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
        desktop_instance.files.write('~/.aws/credentials', creds_content)
        await manager.send_json({"type": "info", "data": "AWS credentials created successfully"})
        
        
        # Step 3: Install uv package manager (in background mode)
        await manager.send_json({"type": "info", "data": "Installing uv package manager..."})
        stdout_logger = WebSocketLogger(manager, "stdout")
        stderr_logger = WebSocketLogger(manager, "stderr")
        
        cmd = 'curl -LsSf https://astral.sh/uv/install.sh | sh; source $HOME/.local/bin/env; uv venv --python 3.11;'
        logger.info(f"Running command in background: {cmd}")
        current_command = desktop_instance.commands.run(
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
            await manager.send_json({"type": "error", "data": "Failed to install uv package manager"})
            return
        
        # Step 4: Install required packages (in background mode)
        await manager.send_json({"type": "info", "data": "Installing required Python packages..."})
        cmd = 'uv pip install boto3 langchain-aws pydantic browser_use==0.3.2 browser-use[memory] playwright'
        logger.info(f"Running command in background: {cmd}")
        current_command = desktop_instance.commands.run(
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
            await manager.send_json({"type": "error", "data": "Failed to install required packages"})
            return
        
        # Step 5: Install Playwright browser (in background mode)
        await manager.send_json({"type": "info", "data": "Installing Playwright browser..."})
        cmd = 'uv run playwright install chromium --with-deps --no-shell'
        logger.info(f"Running command in background: {cmd}")
        current_command = desktop_instance.commands.run(
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
@app.post("/run-task")
async def run_task(query: str = Form(...), background_tasks: BackgroundTasks = None):
    global desktop_instance, current_command
    
    if not desktop_instance:
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

async def run_task_in_background(query: str):
    """Run the task in background so it can be cancelled"""
    global desktop_instance, current_command
    
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
        #cmd = f"python3.11 /tmp/bedrock.py --query '{query}'"
        cmd = f"uv run python3 /tmp/bedrock.py --query '{query}'"
        logger.info(f"Running command in background: {cmd}")
        current_command = desktop_instance.commands.run(
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
@app.post("/kill-desktop")
async def kill_desktop():
    global desktop_instance, stream_url, current_command
    
    if not desktop_instance:
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
            result = desktop_instance.commands.run(cmd, timeout=2)
            logger.info(f"Command started with id: {getattr(result, 'id', 'unknown')}")
            for attr in ['id', 'sandbox_id', 'process_id', 'exit_code', 'status']:
                if hasattr(result, attr):
                    logger.info(f"Command {attr}: {getattr(result, attr)}")
            await manager.send_json({"type": "info", "data": "Killed all Python processes"})
        except Exception as process_error:
            # Log but continue with sandbox kill
            logger.warning(f"Error killing processes: {process_error}")
        
        # Now kill the desktop sandbox
        desktop_instance.kill()
        desktop_instance = None
        stream_url = None
        current_command = None
        await manager.send_json({"type": "desktop_killed", "data": "Desktop instance killed"})
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error killing desktop: {e}")
        await manager.send_json({"type": "error", "data": f"Error killing desktop: {str(e)}"})
        return {"status": "error", "message": str(e)}

# Run the entire workflow
@app.post("/run-workflow")
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

if __name__ == "__main__":
    # Log startup message
    logger.info("Starting Sandbox Desktop WebUI")
    logger.info("All logs will be streamed to the WebUI")
    
    # Start the FastAPI application
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
