import os
import asyncio
import sys
import logging
from fastapi import BackgroundTasks
from typing import Optional
import json
from datetime import datetime
from e2b_desktop import Sandbox

# Import the ComputerUseAgent
from computer_use import ComputerUseAgent

# Global variables that will be shared with app.py
computer_desktop = None
computer_agent = None
current_computer_task = None
stop_requested = False  # Flag to handle stop requests

# These will be initialized from app.py
manager = None
logger = None
ws_handler = None
stdout_capture = None
stderr_capture = None
sessions = {}

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

# Global computer use manager
computer_manager = None

# Start desktop stream for computer use
async def start_computer_desktop():
    """Start desktop instance for computer use"""
    global computer_desktop, computer_agent, computer_manager
    
    if not manager:
        return {"status": "error", "message": "Manager not initialized"}
    
    await manager.send_json({"type": "info", "data": "Starting computer use desktop..."})
    
    try:
        # Initialize computer manager if needed
        if not computer_manager:
            computer_manager = ComputerUseManager(manager, logger)
        
        api_key = os.environ.get("API_KEY")
        template = os.environ.get("TEMPLATE")
        domain = os.environ.get("DOMAIN")
        timeout = int(os.environ.get("TIMEOUT", 1200))
        
        logger.info(f"Creating computer use desktop with template: {template}")
        
        # Create sandbox
        computer_desktop = Sandbox(
            api_key=api_key,
            template=template,
            domain=domain,
            timeout=timeout,
            metadata={
                "purpose": "computer-use"
            }
        )
        
        logger.info(f"Computer desktop created: {computer_desktop.sandbox_id}")
        
        # Start stream
        computer_desktop.stream.start(require_auth=True)
        auth_key = computer_desktop.stream.get_auth_key()
        stream_url = computer_desktop.stream.get_url(auth_key=auth_key)
        
        # Initialize computer use agent
        computer_agent = ComputerUseAgent(computer_desktop)
        computer_manager.desktop = computer_desktop
        computer_manager.agent = computer_agent
        
        # Send success message to client
        await manager.send_json({
            "type": "desktop_started",
            "data": {
                "sandbox_id": computer_desktop.sandbox_id,
                "stream_url": stream_url,
                "timeout": timeout
            }
        })
        
        # Inform user that desktop is loading
        await manager.send_json({
            "type": "info",
            "data": "Desktop stream is loading. Please wait for the display to appear before starting tasks..."
        })
        
        # Wait for browser iframe to load the stream
        await asyncio.sleep(2)
        logger.info("Computer use desktop started successfully and stream should be loading")
        return {"status": "success", "stream_url": stream_url}
        
    except Exception as e:
        logger.error(f"Error starting computer desktop: {e}", exc_info=True)
        await manager.send_json({"type": "error", "data": f"Error starting desktop: {str(e)}"})
        return {"status": "error", "message": str(e)}

# Run computer use task
async def run_computer_use_task(query: str, sandbox_id: str = None, background_tasks: BackgroundTasks = None):
    """Run a computer use task"""
    global computer_desktop, computer_agent, current_computer_task, computer_manager
    
    if not manager:
        return {"status": "error", "message": "Manager not initialized"}
    
    # If no sandbox_id provided, start a new desktop
    if not sandbox_id and not computer_desktop:
        logger.info("No existing desktop, starting new one")
        desktop_result = await start_computer_desktop()
        if desktop_result["status"] == "error":
            return desktop_result
    elif sandbox_id and sandbox_id != getattr(computer_desktop, 'sandbox_id', None):
        # Connect to existing sandbox
        try:
            # Initialize computer manager if needed
            if not computer_manager:
                computer_manager = ComputerUseManager(manager, logger)
                
            computer_desktop = Sandbox(sandbox_id=sandbox_id)
            computer_agent = ComputerUseAgent(computer_desktop)
            computer_manager.desktop = computer_desktop
            computer_manager.agent = computer_agent
        except Exception as e:
            logger.error(f"Error connecting to sandbox {sandbox_id}: {e}")
            return {"status": "error", "message": f"Failed to connect to sandbox: {str(e)}"}
    
    if not computer_agent:
        return {"status": "error", "message": "No computer use agent available"}
    
    # Check if task is already running
    if current_computer_task and not current_computer_task.done():
        return {"status": "error", "message": "A computer use task is already running"}
    
    await manager.send_json({"type": "info", "data": f"Running computer use task: {query}"})
    
    # Add to background tasks with proper task tracking
    if background_tasks:
        background_tasks.add_task(run_computer_task_in_background, query)
    else:
        # Store task reference for cancellation
        current_computer_task = asyncio.create_task(run_computer_task_in_background(query))
    
    return {"status": "success", "message": "Computer use task started"}

# Run computer task in background
async def run_computer_task_in_background(query: str):
    """Run the computer task in background"""
    global current_computer_task, computer_agent, computer_desktop, computer_manager, stop_requested
    
    try:
        if not computer_agent:
            await manager.send_json({"type": "error", "data": "No computer agent available"})
            return
        
        # Reset stop flag
        stop_requested = False
        
        # Set current task reference (for stopping) - get actual current task
        current_computer_task = asyncio.current_task()
        
        logger.info(f"Starting computer task: {query}")
        await manager.send_json({"type": "info", "data": "Starting computer use task..."})
        
        # Wait to ensure desktop is visible and ready
        await asyncio.sleep(1)
        
        # Initialize computer manager if needed
        if not computer_manager:
            computer_manager = ComputerUseManager(manager, logger)
            
        # Process the user message with the agent
        # This handles the full computer use loop: screenshot -> analyze -> execute actions -> repeat
        result = await computer_agent.process_user_message(query, callback=computer_manager.callback)
        
        await manager.send_json({
            "type": "task_completed",
            "data": f"Task completed: {result}"
        })
        
    except asyncio.CancelledError:
        logger.info("Computer task was cancelled")
        await manager.send_json({"type": "info", "data": "Computer task was stopped"})
        # Re-raise to properly handle cancellation
        raise
    except Exception as e:
        logger.error(f"Error in computer task: {e}", exc_info=True)
        await manager.send_json({"type": "error", "data": f"Error in computer task: {str(e)}"})
    finally:
        current_computer_task = None
        stop_requested = False

# Take screenshot
async def take_computer_screenshot(sandbox_id: str = None):
    """Take a screenshot of the computer desktop"""
    global computer_agent, computer_desktop
    
    if not computer_agent:
        return {"status": "error", "message": "No computer agent available"}
    
    try:
        # Take screenshot
        screenshot_base64 = await computer_agent.take_screenshot()
        
        # Send screenshot to clients
        await manager.send_json({
            "type": "screenshot",
            "data": screenshot_base64,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        })
        
        return {"status": "success", "message": "Screenshot taken"}
        
    except Exception as e:
        logger.error(f"Error taking computer screenshot: {e}")
        await manager.send_json({"type": "error", "data": f"Error taking screenshot: {str(e)}"})
        return {"status": "error", "message": str(e)}

# Stop computer task
async def stop_computer_task():
    """Stop the currently running computer task"""
    global current_computer_task, stop_requested
    
    if not current_computer_task or current_computer_task.done():
        return {"status": "error", "message": "No computer task is running"}
    
    try:
        logger.info(f"Stopping computer task: {current_computer_task}")
        await manager.send_json({"type": "info", "data": "Stopping computer task..."})
        
        # Set stop flag first to interrupt any ongoing operations
        stop_requested = True
        
        # Cancel the current task
        current_computer_task.cancel()
        
        # Wait for the task to be cancelled with timeout
        try:
            await asyncio.wait_for(current_computer_task, timeout=3.0)
        except asyncio.TimeoutError:
            logger.warning("Task cancellation timed out")
        except asyncio.CancelledError:
            logger.info("Task cancelled successfully")
        
        await manager.send_json({"type": "info", "data": "Computer task stopped"})
        
        return {"status": "success", "message": "Computer task stopped"}
        
    except Exception as e:
        logger.error(f"Error stopping computer task: {e}")
        await manager.send_json({"type": "error", "data": f"Error stopping task: {str(e)}"})
        return {"status": "error", "message": str(e)}
    finally:
        stop_requested = False

# Kill computer desktop
async def kill_computer_desktop():
    """Kill the computer desktop instance"""
    global computer_desktop, computer_agent, current_computer_task, computer_manager
    
    if not computer_desktop:
        return {"status": "error", "message": "No computer desktop instance available"}
    
    await manager.send_json({"type": "info", "data": "Stopping computer desktop..."})
    
    try:
        # First stop any running task
        if current_computer_task:
            current_computer_task.cancel()
            current_computer_task = None
        
        # Kill the desktop
        computer_desktop.kill()
        computer_desktop = None
        computer_agent = None
        
        if computer_manager:
            computer_manager.desktop = None
            computer_manager.agent = None
        
        await manager.send_json({"type": "desktop_killed", "data": "Computer desktop stopped"})
        
        logger.info("Computer desktop killed successfully")
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"Error killing computer desktop: {e}")
        await manager.send_json({"type": "error", "data": f"Error stopping desktop: {str(e)}"})
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
