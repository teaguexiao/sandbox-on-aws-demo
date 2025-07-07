import os
import asyncio
import sys
import threading
from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect, BackgroundTasks, Depends, Response, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
from typing import List, Dict, Optional
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
import io
import secrets
from fastapi.middleware.wsgi import WSGIMiddleware

# Import functions from e2b-desktop.py
from sandbox_desktop import open_desktop_stream, setup_environment, create_sts

# Import functions from browser_use.py
from sandbox_browser_use import (
    websocket_endpoint, start_desktop, setup_env, setup_env_in_background,
    run_task, run_task_in_background, kill_desktop, run_workflow,
    init_shared_vars
)

# Load environment variables
load_dotenv()

# Configure logging
class WebSocketLogHandler(logging.Handler):
    def __init__(self, connection_manager):
        super().__init__()
        self.connection_manager = connection_manager
        self.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        self.buffer = []
        
    def clear_buffer(self):
        """Clear the log buffer"""
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

# Session management
sessions = {}

def get_current_user(session_token: str = Cookie(None)):
    # Check if login is enabled
    login_enabled = os.getenv("LOGIN_ENABLE", "true").lower() == "true"
    
    # If login is disabled, return a default user
    if not login_enabled:
        return {"username": "default_user", "aws_login": "", "customer_name": ""}
    
    # Otherwise, check for valid session
    if session_token and session_token in sessions:
        return sessions[session_token]
    return None

# Login route
@app.get("/login", response_class=HTMLResponse)
async def get_login(request: Request):
    # Check if login is enabled
    login_enabled = os.getenv("LOGIN_ENABLE", "true").lower() == "true"
    
    # If login is disabled, redirect to home page
    if not login_enabled:
        return RedirectResponse(url="/", status_code=303)
        
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login", response_class=HTMLResponse)
async def post_login(request: Request, response: Response, username: str = Form(...), password: str = Form(...), aws_login: str = Form(""), customer_name: str = Form("")):
    # Check if login is enabled
    login_enabled = os.getenv("LOGIN_ENABLE", "true").lower() == "true"
    
    # If login is disabled, redirect to home page
    if not login_enabled:
        return RedirectResponse(url="/", status_code=303)
    
    # Get credentials from .env
    expected_username = os.getenv("LOGIN_USERNAME")
    expected_password = os.getenv("LOGIN_PASSWORD")
    
    # Log the login attempt
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"{timestamp} | Username: {username} | Password: {'*' * len(password)} | AWS Login: {aws_login} | Customer Name: {customer_name}\n"
    
    try:
        with open("login_history.txt", "a") as log_file:
            log_file.write(log_entry)
    except Exception as e:
        logger.error(f"Failed to write to login history: {e}")
    
    # Validate credentials
    if username == expected_username and password == expected_password:
        # Create session
        session_token = secrets.token_hex(16)
        sessions[session_token] = {"username": username, "aws_login": aws_login, "customer_name": customer_name}
        
        # Set cookie and redirect
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(key="session_token", value=session_token, httponly=True)
        return response
    else:
        return templates.TemplateResponse(
            "login.html", 
            {"request": request, "error": "Invalid username or password"}
        )

# Logout route
@app.get("/logout")
async def logout(response: Response):
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="session_token")
    return response

# Main route
@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

@app.get("/browser-use", response_class=HTMLResponse)
async def get_browser_use(request: Request, user: dict = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("browser-use.html", {"request": request, "user": user, "stream_url": stream_url})

@app.get("/computer-use", response_class=HTMLResponse)
async def get_computer_use(request: Request, user: dict = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("computer-use.html", {"request": request, "user": user})

@app.get("/ai-coding", response_class=HTMLResponse)
async def get_ai_coding(request: Request, user: dict = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("ai-coding.html", {"request": request, "user": user})

@app.get("/ai-coding-e2b", response_class=HTMLResponse)
async def get_ai_coding_e2b(request: Request, user: dict = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("ai-coding-e2b.html", {"request": request, "user": user})

@app.get("/ai-search", response_class=HTMLResponse)
async def get_ai_search(request: Request, user: dict = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("ai-search.html", {"request": request, "user": user})

@app.get("/ai-ppt", response_class=HTMLResponse)
async def get_ai_ppt(request: Request, user: dict = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("ai-ppt.html", {"request": request, "user": user})

# WebSocket endpoint
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, session_token: Optional[str] = Cookie(None)):
    # Use the imported websocket_endpoint function
    await websocket_endpoint(websocket, session_token)

# Start desktop stream
@app.post("/start-desktop")
async def start_desktop_endpoint():
    # Use the imported start_desktop function
    return await start_desktop()

# Setup environment
@app.post("/setup-environment")
async def setup_env_endpoint(background_tasks: BackgroundTasks = None):
    # Use the imported setup_env function
    return await setup_env(background_tasks)

# Run task
@app.post("/run-task")
async def run_task_endpoint(query: str = Form(...), background_tasks: BackgroundTasks = None):
    # Use the imported run_task function
    return await run_task(query, background_tasks)

# Kill desktop
@app.post("/kill-desktop")
async def kill_desktop_endpoint():
    # Use the imported kill_desktop function
    return await kill_desktop()

# Run the entire workflow
@app.post("/run-workflow")
async def run_workflow_endpoint(query: str = Form(...), background_tasks: BackgroundTasks = BackgroundTasks()):
    # Use the imported run_workflow function
    return await run_workflow(query, background_tasks)

# Initialize shared variables in browser_use.py
if __name__ == "__main__":
    # Initialize shared variables in browser_use.py
    init_shared_vars(manager, logger, ws_handler, stdout_capture, stderr_capture, sessions)
    
    # Log startup message
    logger.info("Starting Sandbox Desktop WebUI")
    logger.info("All logs will be streamed to the WebUI")
    
    # Start the FastAPI application
    uvicorn.run("app:app", host="0.0.0.0", port=8080, log_level="info")
