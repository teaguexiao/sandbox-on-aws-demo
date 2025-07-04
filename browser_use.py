import os
import asyncio
import sys
import threading
from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.responses import HTMLResponse
from typing import List, Dict, Optional
import json
import logging
from datetime import datetime
import io

# Import functions from test-e2b-desktop.py
from test_e2b_desktop import open_desktop_stream, setup_environment, create_sts

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
            
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception as e:
                print(f"Error sending JSON: {e}", file=sys.stderr)

# WebSocket log handler
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

# Custom stdout/stderr handler for desktop commands
class StdoutCaptureHandler:
    def __init__(self, connection_manager, log_type="stdout"):
        super().__init__()
        self.connection_manager = connection_manager
        self.log_type = log_type
        self.original = None
        self.buffer = []
        
    def write(self, data):
        if self.original:
            self.original.write(data)
            self.original.flush()
        
        # Skip empty writes
        if not data or data.isspace():
            return
            
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Store in buffer
        self.buffer.append({
            "type": self.log_type,
            "timestamp": timestamp,
            "data": data
        })
        
        # Only keep the last 1000 log entries
        if len(self.buffer) > 1000:
            self.buffer = self.buffer[-1000:]
            
        # Try to send to WebSocket clients
        if self.connection_manager:
            asyncio.create_task(self.connection_manager.send_json({
                "type": self.log_type,
                "timestamp": timestamp,
                "data": data
            }))
            
    def flush(self):
        if self.original:
            self.original.flush()

# WebSocket logger for desktop commands
class WebSocketLogger:
    def __init__(self, manager, log_type="stdout"):
        self.manager = manager
        self.log_type = log_type
        self.loop = None
        
    def __call__(self, data):
        # Convert bytes to string if needed
        if isinstance(data, bytes):
            data = data.decode('utf-8', errors='replace')
            
        # Skip empty data
        if not data or data.isspace():
            return
            
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Get the current event loop or create a new one
        try:
            self.loop = asyncio.get_event_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
        # Create a task to send the data
        try:
            if self.loop.is_running():
                # If the loop is already running, create a future
                asyncio.run_coroutine_threadsafe(
                    self.manager.send_json({
                        "type": self.log_type,
                        "timestamp": timestamp,
                        "data": data
                    }), 
                    self.loop
                )
            else:
                # Otherwise create a task
                self.loop.create_task(
                    self.manager.send_json({
                        "type": self.log_type,
                        "timestamp": timestamp,
                        "data": data
                    })
                )
        except Exception as e:
            print(f"Error in WebSocketLogger: {e}", file=sys.stderr)

# Start desktop stream
async def start_desktop():
    global desktop_instance, stream_url, current_command
    
    if desktop_instance:
        return {"status": "success", "message": "Desktop already started", "stream_url": stream_url}
    
    try:
        await manager.send_json({"type": "info", "data": "Starting desktop instance..."})
        desktop_result = await open_desktop_stream()
        
        if desktop_result["status"] == "error":
            await manager.send_json({"type": "error", "data": desktop_result["message"]})
            return desktop_result
            
        desktop_instance = desktop_result["desktop"]
        stream_url = desktop_result["stream_url"]
        
        # Set up stdout/stderr handlers for desktop commands
        desktop_instance.commands.stdout = WebSocketLogger(manager, "stdout")
        desktop_instance.commands.stderr = WebSocketLogger(manager, "stderr")
        
        await manager.send_json({
            "type": "desktop_ready", 
            "data": "Desktop instance started", 
            "stream_url": stream_url
        })
        
        return {
            "status": "success", 
            "message": "Desktop instance started", 
            "stream_url": stream_url
        }
    except Exception as e:
        error_message = f"Error starting desktop: {str(e)}"
        await manager.send_json({"type": "error", "data": error_message})
        return {"status": "error", "message": error_message}

# Setup environment
async def setup_env(background_tasks: BackgroundTasks = None):
    if not desktop_instance:
        return {"status": "error", "message": "No desktop instance available"}
    
    await manager.send_json({"type": "info", "data": "Setting up environment..."})
    
    if background_tasks:
        background_tasks.add_task(setup_env_in_background)
        return {"status": "success", "message": "Environment setup started in background"}
    else:
        return await setup_env_in_background()

# Run the environment setup in background so it can be cancelled
async def setup_env_in_background():
    global current_command
    
    if not desktop_instance:
        await manager.send_json({"type": "error", "data": "No desktop instance available"})
        return {"status": "error", "message": "No desktop instance available"}
    
    try:
        await manager.send_json({"type": "info", "data": "Setting up environment..."})
        
        # Create STS credentials
        sts_result = await create_sts()
        if sts_result["status"] == "error":
            await manager.send_json({"type": "error", "data": sts_result["message"]})
            return sts_result
            
        # Set up environment variables
        env_vars = {
            "AWS_ACCESS_KEY_ID": sts_result["access_key"],
            "AWS_SECRET_ACCESS_KEY": sts_result["secret_key"],
            "AWS_SESSION_TOKEN": sts_result["session_token"],
            "AWS_DEFAULT_REGION": "us-west-2"
        }
        
        # Run the setup environment command
        await manager.send_json({"type": "info", "data": "Running setup environment command..."})
        
        # Run the setup environment command with the environment variables
        cmd = "cd /home && python -c \"import os; print('Environment setup complete'); print('AWS credentials:', os.environ.get('AWS_ACCESS_KEY_ID', 'Not set')[:4] + '...')\""
        
        logger.info(f"Running command in background: {cmd}")
        current_command = desktop_instance.commands.start(cmd, env=env_vars)
        logger.info(f"Command started with id: {getattr(current_command, 'id', 'unknown')}")
        
        # Wait for the command to complete
        exit_code = current_command.wait()
        logger.info(f"Command completed with exit code: {exit_code}")
        
        if exit_code == 0:
            await manager.send_json({"type": "success", "data": "Environment setup complete"})
            return {"status": "success", "message": "Environment setup complete"}
        else:
            await manager.send_json({"type": "error", "data": f"Environment setup failed with exit code: {exit_code}"})
            return {"status": "error", "message": f"Environment setup failed with exit code: {exit_code}"}
            
    except Exception as e:
        logger.error(f"Error setting up environment: {e}")
        await manager.send_json({"type": "error", "data": f"Error setting up environment: {str(e)}"})
        return {"status": "error", "message": str(e)}
    finally:
        current_command = None

# Run task
async def run_task(query: str = Form(...), background_tasks: BackgroundTasks = None):
    if not desktop_instance:
        return {"status": "error", "message": "No desktop instance available"}
    
    await manager.send_json({"type": "info", "data": f"Running task: {query}"})
    
    if background_tasks:
        background_tasks.add_task(run_task_in_background, query)
        return {"status": "success", "message": "Task started in background"}
    else:
        return await run_task_in_background(query)

# Run the task in background so it can be cancelled
async def run_task_in_background(query: str):
    global current_command
    
    if not desktop_instance:
        await manager.send_json({"type": "error", "data": "No desktop instance available"})
        return {"status": "error", "message": "No desktop instance available"}
    
    try:
        await manager.send_json({"type": "info", "data": f"Running task: {query}"})
        
        # Escape the query for shell
        escaped_query = query.replace('"', '\\"')
        
        # Run the Python script with the query
        cmd = f'cd /home && python -c "print(\'Running task: {escaped_query}\'); import time; print(\'Task complete\')"'
        
        logger.info(f"Running command in background: {cmd}")
        current_command = desktop_instance.commands.start(cmd)
        logger.info(f"Command started with id: {getattr(current_command, 'id', 'unknown')}")
        
        # Wait for the command to complete
        exit_code = current_command.wait()
        logger.info(f"Command completed with exit code: {exit_code}")
        
        if exit_code == 0:
            await manager.send_json({"type": "success", "data": "Task complete"})
            return {"status": "success", "message": "Task complete"}
        else:
            await manager.send_json({"type": "error", "data": f"Task failed with exit code: {exit_code}"})
            return {"status": "error", "message": f"Task failed with exit code: {exit_code}"}
            
    except Exception as e:
        logger.error(f"Error running task: {e}")
        await manager.send_json({"type": "error", "data": f"Error running task: {str(e)}"})
        return {"status": "error", "message": str(e)}
    finally:
        current_command = None

# Kill desktop
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

# Initialize global variables
desktop_instance = None
stream_url = None
current_command = None

# Create connection manager
manager = ConnectionManager()

# Create logger
logger = logging.getLogger(__name__)
