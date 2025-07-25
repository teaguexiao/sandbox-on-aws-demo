import os
import asyncio
import sys
import base64
import json
import argparse
from typing import List, Dict, Any, Optional, Union, Tuple
from datetime import datetime
import logging

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import boto3
from botocore.config import Config
from e2b_desktop import Sandbox

# Configure logging
logger = logging.getLogger(__name__)

class ComputerUseAgent:
    def __init__(self, desktop_sandbox: Sandbox):
        """Initialize the Computer Use Agent with a desktop sandbox"""
        self.desktop = desktop_sandbox
        self.config = Config(retries={'max_attempts': 10, 'mode': 'adaptive'})
        # Use us-east-1 since that's where your Bedrock role is configured
        self.bedrock_client = boto3.client('bedrock-runtime', region_name='us-east-1', config=self.config)
        self.conversation_history = []
        
        # System message for computer use - based on surf project patterns
        self.system_message = """You are Claude, a helpful AI assistant with computer use capabilities. You can see the screen and interact with it by taking screenshots, clicking, typing, scrolling, and performing various computer actions.

IMPORTANT NOTES:
1. You automatically receive a screenshot after each action you take. You DO NOT need to request screenshots separately.
2. When a user asks you to run a command in the terminal, ALWAYS press Enter immediately after typing the command.
3. When the user explicitly asks you to press any key (Enter, Tab, Ctrl+C, etc.) in any application or interface, you MUST do so immediately.
4. Remember: In terminal environments, commands DO NOT execute until Enter is pressed.
5. When working on complex tasks, continue to completion without stopping to ask for confirmation. Break down complex tasks into steps and execute them fully.
6. Be precise with click coordinates based on what you can see in the screenshots.
7. Wait for applications to load before interacting with them.

You are operating in a secure Ubuntu 22.04 desktop environment with pre-installed applications including:
- Firefox browser
- Visual Studio Code (can be launched with 'code' command)
- LibreOffice suite
- Python 3 with common libraries
- Terminal (Ctrl+Alt+T)
- File manager
- Text editor and other basic utilities

Please help the user effectively by observing the current state of the computer and taking appropriate actions."""

    def encode_image(self, image_data: bytes) -> str:
        """Encode image data to base64"""
        return base64.b64encode(image_data).decode('utf-8')

    async def take_screenshot(self) -> str:
        """Take a screenshot and return it as base64"""
        try:
            screenshot_data = self.desktop.screenshot()
            return self.encode_image(screenshot_data)
        except Exception as e:
            logger.error(f"Error taking screenshot: {e}")
            raise

    async def wait_for_desktop_ready(self, max_wait_time: int = 30) -> bool:
        """Wait for the desktop environment to be ready and stream loaded"""
        import asyncio
        logger.info("Waiting for desktop environment to be ready...")
        
        # Reasonable initial wait - desktop needs time to load
        initial_wait = 4
        logger.info(f"Initial wait of {initial_wait} seconds for desktop startup...")
        await asyncio.sleep(initial_wait)
        
        desktop_ready = False
        for i in range(max_wait_time - initial_wait):
            try:
                # Simplified desktop readiness check - just take one screenshot
                screenshot_base64 = await self.take_screenshot()
                
                if not screenshot_base64:
                    logger.debug(f"No screenshot data (attempt {i+1})")
                    await asyncio.sleep(1)
                    continue
                
                # Simple check - if we can take a screenshot and it's not empty, we're ready
                screenshot_data = base64.b64decode(screenshot_base64)
                if len(screenshot_data) > 5000:  # Reasonable size
                    logger.info(f"Desktop appears ready after {initial_wait + i + 1} seconds")
                    desktop_ready = True
                    break
                else:
                    logger.debug(f"Screenshot too small: {len(screenshot_data)} bytes (attempt {i+1})")
                    
            except Exception as e:
                logger.debug(f"Desktop not ready yet (attempt {i+1}): {e}")
            
            await asyncio.sleep(1)
        
        if desktop_ready:
            # Wait for stream loading
            stream_wait = 3
            logger.info(f"Desktop ready. Waiting additional {stream_wait} seconds for stream to load...")
            await asyncio.sleep(stream_wait)
            
            # Add stabilization period to ensure desktop view is settled
            # This helps prevent coordinate misalignment between screenshots and clicks
            stabilization_wait = 2
            logger.info(f"Adding {stabilization_wait} seconds stabilization period to ensure desktop view is settled...")
            await asyncio.sleep(stabilization_wait)
            
            # Take a few screenshots to stabilize the view
            logger.info("Taking stabilization screenshots...")
            for _ in range(3):
                await self.take_screenshot()
                await asyncio.sleep(0.5)
                
            logger.info("Desktop and stream should now be ready and stabilized for interaction")
            return True
        else:
            logger.warning(f"Desktop may not be fully ready after {max_wait_time} seconds")
            return False

    def _calibrate_coordinates(self, x: int, y: int) -> tuple:
        """
        Calibrate coordinates to account for potential view shifts.
        This function can be adjusted based on observed offset patterns.
        
        Based on the observed issue where the desktop shifts to the left after
        the first screenshot, we apply a small adjustment to compensate.
        """
        # Apply a small adjustment to compensate for the observed shift
        # These values can be fine-tuned based on testing
        
        # Store calibration values as class attributes if not already set
        if not hasattr(self, '_calibration_offset_x'):
            self._calibration_offset_x = 0  # Horizontal offset (positive moves right)
            self._calibration_offset_y = 0  # Vertical offset (positive moves down)
            
            # Log that we're using calibration
            logger.info(f"Using coordinate calibration with offsets: x={self._calibration_offset_x}, y={self._calibration_offset_y}")
        
        # Apply the calibration
        calibrated_x = x + self._calibration_offset_x
        calibrated_y = y + self._calibration_offset_y
        
        # Log calibration if values changed significantly
        if abs(calibrated_x - x) > 5 or abs(calibrated_y - y) > 5:
            logger.debug(f"Calibrated coordinates: ({x}, {y}) -> ({calibrated_x}, {calibrated_y})")
            
        return calibrated_x, calibrated_y

    async def execute_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a computer action"""
        try:
            action_type = action.get("action")
            
            if action_type == "screenshot":
                screenshot_base64 = await self.take_screenshot()
                return {
                    "type": "screenshot",
                    "screenshot": screenshot_base64,
                    "success": True
                }
                
            elif action_type == "left_click":
                coordinate = action.get("coordinate", [0, 0])
                x, y = coordinate[0], coordinate[1]
                
                # Calibrate coordinates to account for potential view shifts
                x, y = self._calibrate_coordinates(x, y)
                
                # Handle optional key press before click (surf pattern)
                if action.get("text"):
                    await self.desktop.move_mouse(x, y)
                    self.desktop.press(action.get("text"))
                
                # E2B Desktop API uses left_click(x, y)
                self.desktop.left_click(x, y)
                return {"type": "left_click", "coordinate": [x, y], "success": True}
                
            elif action_type == "right_click":
                coordinate = action.get("coordinate", [0, 0])
                x, y = coordinate[0], coordinate[1]
                
                # Calibrate coordinates to account for potential view shifts
                x, y = self._calibrate_coordinates(x, y)
                
                # Handle optional key press before click (surf pattern)
                if action.get("text"):
                    self.desktop.move_mouse(x, y)
                    self.desktop.press(action.get("text"))
                
                self.desktop.right_click(x, y)
                return {"type": "right_click", "coordinate": [x, y], "success": True}
                
            elif action_type == "double_click":
                coordinate = action.get("coordinate", [0, 0])
                x, y = coordinate[0], coordinate[1]
                
                # Calibrate coordinates to account for potential view shifts
                x, y = self._calibrate_coordinates(x, y)
                
                # Handle optional key press before click (surf pattern)
                if action.get("text"):
                    self.desktop.move_mouse(x, y)
                    self.desktop.press(action.get("text"))
                
                self.desktop.double_click(x, y)
                return {"type": "double_click", "coordinate": [x, y], "success": True}
                
            elif action_type == "middle_click":
                coordinate = action.get("coordinate", [0, 0])
                x, y = coordinate[0], coordinate[1]
                
                # Calibrate coordinates to account for potential view shifts
                x, y = self._calibrate_coordinates(x, y)
                
                # Handle optional key press before click (surf pattern)
                if action.get("text"):
                    self.desktop.move_mouse(x, y)
                    self.desktop.press(action.get("text"))
                
                self.desktop.middle_click(x, y)
                return {"type": "middle_click", "coordinate": [x, y], "success": True}
                
            elif action_type == "type":
                text = action.get("text", "")
                # E2B Desktop API uses write(text)
                self.desktop.write(text)
                return {"type": "type", "text": text, "success": True}
                
            elif action_type == "key":
                text = action.get("text", "")
                # E2B Desktop API uses press(key) - can be a string or list of strings
                self.desktop.press(text)
                return {"type": "key", "text": text, "success": True}
                
            elif action_type == "scroll":
                coordinate = action.get("coordinate", [640, 360])
                scroll_direction = action.get("scroll_direction", "down")
                scroll_amount = action.get("scroll_amount", 3)
                x, y = coordinate[0], coordinate[1]
                
                # Calibrate coordinates to account for potential view shifts
                x, y = self._calibrate_coordinates(x, y)
                
                # Move mouse to position first
                self.desktop.move_mouse(x, y)
                
                # Handle optional key press before scroll (surf pattern)
                if action.get("text"):
                    self.desktop.press(action.get("text"))
                
                # E2B Desktop API: scroll(direction='down', amount=1)
                direction = "up" if scroll_direction == "up" else "down"
                self.desktop.scroll(direction, scroll_amount)
                    
                return {
                    "type": "scroll", 
                    "coordinate": [x, y],
                    "direction": scroll_direction,
                    "amount": scroll_amount,
                    "success": True
                }
                
            elif action_type == "left_click_drag":
                start_coordinate = action.get("start_coordinate", [0, 0])
                end_coordinate = action.get("coordinate", [0, 0])
                
                # Calibrate coordinates to account for potential view shifts
                start_x, start_y = self._calibrate_coordinates(start_coordinate[0], start_coordinate[1])
                end_x, end_y = self._calibrate_coordinates(end_coordinate[0], end_coordinate[1])
                
                # E2B Desktop API: drag(fr: tuple[int, int], to: tuple[int, int])
                start = (start_x, start_y)
                end = (end_x, end_y)
                self.desktop.drag(start, end)
                return {
                    "type": "left_click_drag",
                    "start_coordinate": [start_x, start_y],
                    "coordinate": [end_x, end_y],
                    "success": True
                }
                
            elif action_type == "mouse_move":
                coordinate = action.get("coordinate", [0, 0])
                x, y = coordinate[0], coordinate[1]
                
                # Calibrate coordinates to account for potential view shifts
                x, y = self._calibrate_coordinates(x, y)
                
                # E2B Desktop API uses move_mouse(x, y)
                self.desktop.move_mouse(x, y)
                return {"type": "mouse_move", "coordinate": [x, y], "success": True}
                
            elif action_type == "triple_click":
                coordinate = action.get("coordinate", [0, 0])
                x, y = coordinate[0], coordinate[1]
                
                # Calibrate coordinates to account for potential view shifts
                x, y = self._calibrate_coordinates(x, y)
                
                self.desktop.move_mouse(x, y)
                if action.get("text"):
                    self.desktop.press(action.get("text"))
                # Triple click implementation
                self.desktop.left_click()
                self.desktop.left_click()
                self.desktop.left_click()
                return {"type": "triple_click", "coordinate": [x, y], "success": True}
                
            elif action_type in ["cursor_position", "left_mouse_down", "left_mouse_up"]:
                # These actions are handled by E2B internally or not needed
                return {"type": action_type, "success": True}
                
            elif action_type == "wait":
                duration = action.get("duration", 1)
                await asyncio.sleep(duration)
                return {"type": "wait", "duration": duration, "success": True}
                
            else:
                return {"type": "error", "message": f"Unknown action type: {action_type}", "success": False}
                
        except Exception as e:
            logger.error(f"Error executing action {action}: {e}")
            return {"type": "error", "message": str(e), "success": False}

    def create_bedrock_messages(self, user_message: str, screenshot_base64: str = None) -> List[Dict]:
        """Create messages for Bedrock API"""
        messages = []
        
        # Add conversation history
        for msg in self.conversation_history:
            messages.append(msg)
        
        # Create user message with screenshot if provided
        content = []
        
        if screenshot_base64:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": screenshot_base64
                }
            })
        
        content.append({
            "type": "text",
            "text": user_message
        })
        
        messages.append({
            "role": "user",
            "content": content
        })
        
        return messages

    async def call_bedrock(self, messages: List[Dict]) -> Dict[str, Any]:
        """Call AWS Bedrock Claude model"""
        try:
            # Check for cancellation before making the API call
            await asyncio.sleep(0)  # Yield control to check for cancellation
            
            # Prepare the request
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4096,
                "system": self.system_message,
                "messages": messages,
                "tools": [
                    {
                        "name": "computer",
                        "description": "Use a computer to take screenshots and perform actions like clicking, typing, scrolling, etc.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "enum": [
                                        "screenshot", 
                                        "left_click", "right_click", "double_click", "middle_click", "triple_click",
                                        "type", "key", 
                                        "scroll", "left_click_drag", "mouse_move", "wait"
                                    ],
                                    "description": "The action to perform"
                                },
                                "coordinate": {
                                    "type": "array",
                                    "items": {"type": "integer"},
                                    "description": "The [x, y] coordinate for actions that require a position"
                                },
                                "start_coordinate": {
                                    "type": "array", 
                                    "items": {"type": "integer"},
                                    "description": "Starting coordinate for drag actions"
                                },
                                "text": {
                                    "type": "string",
                                    "description": "Text to type or keys to press"
                                },
                                "scroll_direction": {
                                    "type": "string",
                                    "enum": ["up", "down"],
                                    "description": "Direction to scroll"
                                },
                                "scroll_amount": {
                                    "type": "integer",
                                    "description": "Amount to scroll (default: 3)"
                                },
                                "duration": {
                                    "type": "number",
                                    "description": "Duration to wait in seconds"
                                }
                            },
                            "required": ["action"]
                        }
                    }
                ]
            }
            
            # Call Bedrock
            try:
                request_json = json.dumps(request_body)
            except TypeError as e:
                logger.error(f"JSON serialization error: {e}")
                logger.error(f"Request body type issues: {self._debug_json_serialization(request_body)}")
                raise
            
            # Try different model IDs in order of preference
            model_ids = [
                "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
                "anthropic.claude-3-5-sonnet-20240620-v1:0",  # Claude 3.5 Sonnet (newer)
                "anthropic.claude-3-sonnet-20240229-v1:0",    # Claude 3 Sonnet (fallback)
                "anthropic.claude-3-haiku-20240307-v1:0"      # Claude 3 Haiku (backup)
            ]
            
            last_error = None
            for model_id in model_ids:
                try:
                    # Run the Bedrock API call in a way that can be cancelled
                    response = await asyncio.to_thread(
                        self.bedrock_client.invoke_model,
                        modelId=model_id,
                        body=request_json,
                        contentType="application/json",
                        accept="application/json"
                    )
                    logger.info(f"Successfully using model: {model_id}")
                    break
                except Exception as e:
                    logger.warning(f"Model {model_id} failed: {e}")
                    last_error = e
                    continue
            else:
                # If all models failed, raise the last error
                raise last_error
            
            # Parse response
            response_body = json.loads(response['body'].read())
            return response_body
            
        except Exception as e:
            logger.error(f"Error calling Bedrock: {e}")
            raise
    
    def _debug_json_serialization(self, obj, path=""):
        """Debug helper to find non-serializable objects"""
        if isinstance(obj, bytes):
            return f"{path}: bytes object found"
        elif isinstance(obj, dict):
            for k, v in obj.items():
                result = self._debug_json_serialization(v, f"{path}.{k}")
                if result:
                    return result
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                result = self._debug_json_serialization(v, f"{path}[{i}]")
                if result:
                    return result
        return None
        
    def adjust_calibration(self, offset_x: int = 0, offset_y: int = 0):
        """
        Adjust the coordinate calibration offsets.
        This can be called to fine-tune the calibration based on observed behavior.
        
        Args:
            offset_x: Horizontal offset adjustment (positive moves right)
            offset_y: Vertical offset adjustment (positive moves down)
        """
        # Initialize calibration values if not already set
        if not hasattr(self, '_calibration_offset_x'):
            self._calibration_offset_x = 0
            self._calibration_offset_y = 0
            
        # Apply the adjustments
        self._calibration_offset_x += offset_x
        self._calibration_offset_y += offset_y
        
        logger.info(f"Adjusted coordinate calibration. New offsets: x={self._calibration_offset_x}, y={self._calibration_offset_y}")

    async def process_user_message(self, user_message: str, callback=None) -> str:
        """Process a user message and execute computer actions"""
        try:
            # Check for cancellation periodically
            await asyncio.sleep(0)  # Yield control to check for cancellation
            
            # Wait for desktop to be ready
            if callback:
                await callback({"type": "info", "data": "Waiting for desktop environment to load..."})
            
            await self.wait_for_desktop_ready(max_wait_time=30)
            
            # Take initial screenshot
            if callback:
                await callback({"type": "info", "data": "Taking initial screenshot of the desktop..."})
            
            # Take multiple screenshots to ensure the view is stable
            # This helps prevent coordinate misalignment between screenshots and clicks
            for i in range(2):
                await self.take_screenshot()
                await asyncio.sleep(0.5)
            
            # Now take the actual screenshot for analysis
            screenshot_base64 = await self.take_screenshot()
            
            if callback:
                await callback({
                    "type": "screenshot", 
                    "data": screenshot_base64,
                    "timestamp": datetime.now().strftime("%H:%M:%S")
                })
                await callback({
                    "type": "info", 
                    "data": "Screenshot captured. Analyzing the desktop to understand what's visible before taking any actions..."
                })
            
            # Create messages for Bedrock
            messages = self.create_bedrock_messages(user_message, screenshot_base64)
            
            if callback:
                await callback({"type": "info", "data": "Analyzing screenshot and planning actions..."})
            
            max_iterations = 50  # Restored proper limit for computer use tasks
            iteration = 0
            
            while iteration < max_iterations:
                # Check for cancellation
                await asyncio.sleep(0)  # Yield control to check for cancellation
                
                if callback and iteration == 0:  # Only show thinking message on first iteration
                    await callback({"type": "info", "data": "Analyzing and planning actions..."})
                
                # Call Bedrock
                response = await self.call_bedrock(messages)
                
                # Parse response
                assistant_message = response.get("content", [])
                stop_reason = response.get("stop_reason")
                
                # Extract text and tool use
                response_text = ""
                tool_calls = []
                
                for content in assistant_message:
                    if content.get("type") == "text":
                        response_text += content.get("text", "")
                    elif content.get("type") == "tool_use":
                        tool_calls.append(content)
                
                if callback and response_text:
                    await callback({
                        "type": "reasoning",
                        "data": response_text,
                        "timestamp": datetime.now().strftime("%H:%M:%S")
                    })
                
                # Add assistant message to conversation
                self.conversation_history.append({
                    "role": "assistant",
                    "content": assistant_message
                })
                
                # Process tool calls
                if tool_calls:
                    tool_results = []
                    
                    for tool_call in tool_calls:
                        tool_name = tool_call.get("name")
                        tool_input = tool_call.get("input", {})
                        tool_id = tool_call.get("id")
                        
                        if tool_name == "computer":
                            if callback:
                                await callback({
                                    "type": "action",
                                    "data": {
                                        "action": tool_input.get("action"),
                                        **tool_input
                                    },
                                    "timestamp": datetime.now().strftime("%H:%M:%S")
                                })
                            
                            # Check for cancellation before executing action
                            await asyncio.sleep(0)  # Yield control to check for cancellation
                            
                            # Execute the action
                            result = await self.execute_action(tool_input)
                            
                            if callback:
                                await callback({
                                    "type": "action_completed",
                                    "data": result,
                                    "timestamp": datetime.now().strftime("%H:%M:%S")
                                })
                            
                            # CRITICAL: Always take screenshot after EVERY action (following surf pattern)
                            # This is essential for the computer use feedback loop
                            await asyncio.sleep(0.2)  # Brief pause to let UI update
                            new_screenshot_base64 = await self.take_screenshot()
                            
                            if callback:
                                await callback({
                                    "type": "screenshot",
                                    "data": new_screenshot_base64,
                                    "timestamp": datetime.now().strftime("%H:%M:%S")
                                })
                            
                            # Always return screenshot as tool result (surf pattern)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": [
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": "image/png",
                                            "data": new_screenshot_base64
                                        }
                                    }
                                ],
                                "is_error": False
                            })
                    
                    # Add tool results to conversation
                    if tool_results:
                        self.conversation_history.append({
                            "role": "user",
                            "content": tool_results
                        })
                        
                        # Continue the conversation
                        messages = self.conversation_history.copy()
                        iteration += 1
                        continue
                
                # If no tool calls or max iterations reached, break
                if stop_reason == "end_turn" or not tool_calls:
                    break
                    
                iteration += 1
            
            if callback:
                await callback({"type": "task_completed", "data": "Task completed successfully"})
                
            return response_text or "Task completed"
            
        except asyncio.CancelledError:
            logger.info("Task was cancelled")
            if callback:
                await callback({"type": "info", "data": "Task cancelled by user"})
            raise
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            if callback:
                await callback({"type": "error", "data": f"Error: {str(e)}"})
            raise

async def main():
    """Main function for command line usage"""
    parser = argparse.ArgumentParser(description="Computer Use Agent")
    parser.add_argument('--query', type=str, required=True, help='Task for the agent to execute')
    parser.add_argument('--sandbox-id', type=str, help='Existing sandbox ID to connect to')
    args = parser.parse_args()
    
    # Initialize desktop sandbox
    api_key = os.environ.get("API_KEY")
    template = os.environ.get("TEMPLATE")
    domain = os.environ.get("DOMAIN")
    timeout = int(os.environ.get("TIMEOUT", 1200))
    
    if args.sandbox_id:
        # Connect to existing sandbox
        desktop = Sandbox(sandbox_id=args.sandbox_id)
    else:
        # Create new sandbox
        desktop = Sandbox(
            api_key=api_key,
            template=template,
            domain=domain,
            timeout=timeout
        )
    
    # Initialize agent
    agent = ComputerUseAgent(desktop)
    
    # Simple callback for command line usage
    async def print_callback(data):
        print(f"[{data.get('timestamp', '')}] {data.get('type', '')}: {data.get('data', '')}")
    
    # Process the query
    try:
        result = await agent.process_user_message(args.query, callback=print_callback)
        print(f"\nFinal result: {result}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Clean up
        if not args.sandbox_id:
            try:
                desktop.kill()
            except:
                pass

if __name__ == "__main__":
    asyncio.run(main())
