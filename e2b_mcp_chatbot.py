import json
import asyncio
import gradio as gr
import boto3
import os
import sys
import subprocess
import time
import signal
import threading
import queue
import tempfile
from typing import List, Dict, Any, AsyncGenerator, Optional
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

class MCPChatbot:
    def __init__(self):
        """Initialize the E2B MCP chatbot"""
        # Check for E2B API key
        self.e2b_api_key = os.getenv('API_KEY')
        if not self.e2b_api_key:
            raise ValueError("API_KEY environment variable is required")
        
        # Initialize Bedrock client
        self.bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
        self.model_id = "us.anthropic.claude-3-7-sonnet-20250219-v1:0"
        self.conversation_history = []
        
        # Initialize MCP state
        self.mcp_process = None
        self.io_thread = None
        self.running = True
        self.request_queue = queue.Queue()
        self.response_queue = queue.Queue()
        self.next_request_id = 1
        self.mcp_tools = []
        
        if self.start_e2b_mcp_server():
            # Initialize MCP tools after server starts
            self.initialize_mcp_tools()
        else:
            print("❌ Failed to start MCP server properly")
            # Continue anyway to allow the interface to start
        
    def start_e2b_mcp_server(self):
        """Start the E2B MCP server as a subprocess"""
        try:
            # Check for required environment variables
            api_key = os.environ.get("API_KEY")
            if not api_key:
                print("⚠️ Missing API_KEY environment variable")
                return False
                
            # Get template ID with default
            template_id = os.environ.get("CODE_INTERPRETER_TEMPLATE_ID", "base-python")
            
            # Create a temporary Python script to run the MCP server
            # This ensures proper async execution
            script_content = """
            import asyncio
            import os
            import sys
            import logging
            import json
            
            # Configure logging
            logging.basicConfig(
                level=logging.DEBUG,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            
            # Set environment variables for MCP server
            os.environ["E2B_API_KEY"] = "{api_key}"
            os.environ["E2B_TEMPLATE_ID"] = "{template_id}"
            
            # Print debug info
            print("E2B MCP Server starting...")
            print(f"API_KEY set: {{bool(os.environ.get('E2B_API_KEY'))}}")
            print(f"TEMPLATE_ID: {{os.environ.get('E2B_TEMPLATE_ID')}}")
            print(f"Working directory: {{os.getcwd()}}")
            print(f"Python version: {{sys.version}}")
            
            # Define custom handler for STDIO
            class StdioHandler:
                def __init__(self):
                    self.buffer = ""
                    
                async def read_message(self):
                    while True:
                        line = sys.stdin.readline()
                        if not line:
                            return None
                        try:
                            # Try to parse as JSON
                            message = json.loads(line)
                            print(f"Received message: {{message}}")
                            return message
                        except json.JSONDecodeError:
                            print(f"Invalid JSON received: {{line}}")
                            continue
                
                async def write_message(self, message):
                    try:
                        json_str = json.dumps(message)
                        print(f"Sending response: {{json_str}}")
                        sys.stdout.write(json_str + '\n')
                        sys.stdout.flush()
                    except Exception as e:
                        print(f"Error writing message: {{e}}")
            
            try:
                # Import and run the MCP server
                from e2b_mcp_server.server import main
                print("Imported e2b_mcp_server.server.main successfully")
                
                # Monkey patch any problematic functions if needed
                # This is where we could add custom handlers if the default ones have issues
                
                # Run the server with detailed error handling
                print("Starting MCP server main function...")
                asyncio.run(main())
                print("MCP server main function completed successfully")
            except Exception as e:
                print(f"Error running MCP server: {{str(e)}}")
                import traceback
                traceback.print_exc()
                sys.exit(1)
            """.format(api_key=api_key, template_id=template_id)
            
            # Write the script to a temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(script_content)
                script_path = f.name
                
            print(f"Starting MCP server using Python script: {script_path}")
            
            # Set up environment variables for the subprocess
            env = os.environ.copy()
            env['E2B_API_KEY'] = api_key
            env['E2B_TEMPLATE_ID'] = template_id
            env['PYTHONUNBUFFERED'] = '1'  # Ensure Python output is unbuffered
            
            # Start the MCP server subprocess
            self.mcp_process = subprocess.Popen(
                [sys.executable, script_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
                env=env
            )
            
            # Start I/O thread
            self.io_thread = threading.Thread(target=self._io_loop)
            self.io_thread.daemon = True
            self.io_thread.start()
            
            # Give the server a moment to start
            time.sleep(2)
            
            # Check if process is still running
            if self.mcp_process.poll() is not None:
                print(f"⚠️ MCP process exited immediately with code {self.mcp_process.returncode}")
                if self.mcp_process.stderr:
                    stderr_content = self.mcp_process.stderr.read()
                    print(f"🔴 MCP process stderr: {stderr_content}")
                return False
                
            print("✅ E2B MCP server started successfully")
            return True
        except Exception as e:
            print(f"❌ Failed to start MCP server: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def __del__(self):
        # Clean up the E2B MCP server process when the chatbot is destroyed
        self.running = False
        if self.io_thread and self.io_thread.is_alive():
            self.io_thread.join(timeout=2)
            
        if self.mcp_process and self.mcp_process.poll() is None:
            try:
                self.mcp_process.send_signal(signal.SIGTERM)
                self.mcp_process.wait(timeout=5)
                print("✅ E2B MCP server stopped successfully")
            except Exception as e:
                print(f"❌ Error stopping E2B MCP server: {str(e)}")
                # Force kill if graceful shutdown fails
                try:
                    self.mcp_process.kill()
                except:
                    pass
    
    def _io_loop(self):
        """Handle I/O communication with the MCP server"""
        print("🔄 Starting I/O loop for MCP server communication")
        
        # Flag to track if we've seen initialization request from server
        initialization_seen = False
        initialization_completed = False
        
        # Explicitly send initialization request first
        init_request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {"clientName": "e2b-mcp-chatbot", "capabilities": {}}
        }
        init_request_json = json.dumps(init_request)
        print(f"🔑 Sending initial initialization request: {init_request_json}")
        self.mcp_process.stdin.write(init_request_json + '\n')
        self.mcp_process.stdin.flush()
        
        while self.running and self.mcp_process and self.mcp_process.poll() is None:
            try:
                # Check if there are requests to send (only if initialization is complete)
                if initialization_completed:
                    try:
                        request = self.request_queue.get_nowait()
                        request_json = json.dumps(request)
                        print(f"📤 Sending request to MCP: {request_json}")
                        self.mcp_process.stdin.write(request_json + '\n')
                        self.mcp_process.stdin.flush()
                    except queue.Empty:
                        pass
                
                # Check for output from the MCP server
                if self.mcp_process.stdout and self.mcp_process.stdout.readable():
                    line = self.mcp_process.stdout.readline().strip()
                    if line:
                        print(f"📥 Received from MCP: {line}")
                        try:
                            response = json.loads(line)
                            
                            # Check if this is an initialization request from the server
                            if not initialization_seen and isinstance(response, dict) and response.get("method") == "initialize":
                                print("🔓 Received initialization request from MCP server")
                                initialization_seen = True
                                
                                # Send initialization response
                                init_response = {
                                    "jsonrpc": "2.0",
                                    "id": response.get("id"),
                                    "result": {"capabilities": {}}
                                }
                                init_response_json = json.dumps(init_response)
                                print(f"🔑 Sending initialization response: {init_response_json}")
                                self.mcp_process.stdin.write(init_response_json + '\n')
                                self.mcp_process.stdin.flush()
                            # Check if this is a response to our initialization request
                            elif not initialization_completed and "id" in response and response.get("id") == 0:
                                print("🔓 Received response to our initialization request")
                                initialization_completed = True
                                # Now we can start sending other requests
                            elif "id" in response:
                                # Put response in queue for processing
                                self.response_queue.put(response)
                            else:
                                print(f"🔴 Unexpected MCP response: {response}")
                        except json.JSONDecodeError:
                            print(f"⚠️ Invalid JSON from MCP server: {line}")
                
                # Check stderr for any error messages
                if self.mcp_process.stderr.readable():
                    error_line = self.mcp_process.stderr.readline().strip()
                    if error_line:
                        print(f"🔴 MCP stderr: {error_line}")
                
                # Sleep a bit to avoid high CPU usage
                time.sleep(0.01)
            except Exception as e:
                print(f"❌ Error in MCP I/O loop: {str(e)}")
                import traceback
                traceback.print_exc()
                time.sleep(0.1)  # Slightly longer sleep on error
                # Don't break the loop on error, just continue
        
        print("🔴 MCP I/O loop exited")
    
    def _send_request(self, method: str, params: Optional[Dict] = None, request_id: Optional[int] = None):
        """Send a request to the MCP server and return the request ID"""
        if request_id is None:
            request_id = self.next_request_id
            self.next_request_id += 1
            
        # Format as proper JSON-RPC 2.0 request
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method
        }
        if params is not None:
            request["params"] = params
            
        # For direct sending (bypass queue for more reliable delivery)
        if self.mcp_process and self.mcp_process.stdin and self.mcp_process.poll() is None:
            request_json = json.dumps(request)
            print(f"📤 Directly sending request to MCP: {request_json}")
            try:
                self.mcp_process.stdin.write(request_json + '\n')
                self.mcp_process.stdin.flush()
            except Exception as e:
                print(f"❌ Error sending request: {str(e)}")
        else:
            # Put request in queue for I/O thread to send
            self.request_queue.put(request)
            
        return request_id
        
    def _get_response(self, request_id: int, timeout: float = 5.0):
        """Wait for a response to a specific request ID"""
        start_time = time.time()
        print(f"🕒 Waiting for response to request {request_id} (timeout: {timeout}s)")
        
        while time.time() - start_time < timeout:
            # Check if we have a response for this request ID
            try:
                response = self.response_queue.get(block=True, timeout=0.5)  # Block with timeout
                if "id" in response and response["id"] == request_id:
                    print(f"✅ Got response for request {request_id}")
                    return response
                else:
                    # Put it back in the queue for other handlers
                    print(f"🔄 Received response for different request ID: {response.get('id')}")
                    self.response_queue.put(response)
            except queue.Empty:
                # Check if MCP process is still running
                if self.mcp_process and self.mcp_process.poll() is not None:
                    print(f"⚠️ MCP process exited while waiting for response (code: {self.mcp_process.returncode})")
                    return None
                    
                elapsed = time.time() - start_time
                if elapsed > timeout / 2 and elapsed < (timeout / 2) + 0.6:
                    # Send the request again halfway through the timeout period
                    print(f"🔄 Re-sending request {request_id} after {elapsed:.1f}s")
                    self._send_request("tools/list", request_id=request_id)
            
        print(f"⚠️ Timeout waiting for response to request {request_id} after {timeout} seconds")
        return None
        
    def initialize_mcp_tools(self):
        """Initialize MCP tools by listing available tools"""
        try:
            print("🔍 Initializing MCP tools...")
            # Wait longer to ensure server is fully initialized and I/O loop has processed initialization
            time.sleep(5)
            
            # Send a request to list available tools
            # Note: Initialization is now handled in the I/O loop
            request_id = self._send_request("tools/list")
            print(f"Sent tools/list request with ID: {request_id}")
            
            # Wait for response with increased timeout
            response = self._get_response(request_id, timeout=15.0)
            print(f"Received tools response: {response}")
            
            if response and "result" in response and "tools" in response["result"]:
                self.mcp_tools = response["result"]["tools"]
                print(f"✅ MCP tools initialized: {len(self.mcp_tools)} tools available")
                for tool in self.mcp_tools:
                    print(f"  - {tool['name']}: {tool['description']}")
                return True
            else:
                print("❌ Failed to initialize MCP tools: Invalid response")
                if response:
                    print(f"Response: {response}")
                return False
        except Exception as e:
            print(f"❌ Failed to initialize MCP tools: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    async def call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        # Ensure E2B MCP server is running
        if self.mcp_process and self.mcp_process.poll() is not None:
            # Server died, restart it
            print("🔄 E2B MCP server died, restarting...")
            self.start_e2b_mcp_server()
            # Reinitialize tools
            await self.initialize_mcp_tools()
            
        try:
            # Send tool call request through STDIO
            request_id = self._send_request(
                "tools/call", 
                {
                    "name": tool_name,
                    "arguments": arguments
                }
            )
            
            # Wait for the response
            response = self._get_response(request_id)
            if response and "result" in response:
                return response["result"]
            else:
                return "Failed to call E2B MCP tool: No valid response received"
        except Exception as e:
            return f"Error calling MCP tool: {str(e)}"

    def format_tools_for_bedrock(self) -> List[Dict]:
        bedrock_tools = []
        for tool in self.mcp_tools:
            bedrock_tool = {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "input_schema": tool.get("inputSchema", {})
            }
            bedrock_tools.append(bedrock_tool)
        return bedrock_tools

    async def chat_with_tools(self, user_message: str) -> AsyncGenerator[str, None]:
        self.conversation_history.append({"role": "user", "content": user_message})
        
        yield f"🤖 Processing your message: {user_message}\n\n"
        
        if not self.mcp_tools:
            init_result = await self.initialize_mcp_tools()
            yield f"📋 {init_result}\n\n"
        
        # 构建包含工具使用指令的系统消息
        system_message = """You are an AI assistant with access to E2B sandbox tools. When users ask for calculations, data analysis, or code execution, you should USE THE AVAILABLE TOOLS to provide accurate results. 

For example:
- If asked to calculate something (like π, mathematical expressions, etc.), use the appropriate E2B sandbox tool
- If asked to generate and run code, use the E2B sandbox tools
- Always prefer using tools for computational tasks rather than providing theoretical explanations only

Available tools will be provided in the function calling interface."""
        
        # 使用完整的对话历史，不仅仅是当前消息
        messages = self.conversation_history.copy()
        
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": messages,
            "max_tokens": int(os.getenv('MAX_TOKENS', '65536')),
            "temperature": 0.7,
            "system": system_message
        }
        
        if self.mcp_tools:
            request_body["tools"] = self.format_tools_for_bedrock()
            yield f"🔧 Available E2B sandbox tools: {', '.join([tool['name'] for tool in self.mcp_tools])}\n\n"

        try:
            response = self.bedrock.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body),
                contentType="application/json"
            )
            
            response_body = json.loads(response['body'].read())
            
            if response_body.get("stop_reason") == "tool_use":
                yield "🔨 Claude wants to use tools...\n\n"
                
                for content_block in response_body.get("content", []):
                    if content_block.get("type") == "tool_use":
                        tool_name = content_block.get("name")
                        tool_input = content_block.get("input", {})
                        tool_use_id = content_block.get("id")
                        
                        yield f"🛠️ Calling tool: {tool_name}\n"
                        yield f"📋 Parameters: {json.dumps(tool_input, indent=2)}\n\n"
                        
                        tool_result = await self.call_mcp_tool(tool_name, tool_input)
                        yield f"✅ Tool result:\n```\n{tool_result}\n```\n\n"
                        
                        self.conversation_history.append({
                            "role": "assistant",
                            "content": response_body.get("content", [])
                        })
                        
                        self.conversation_history.append({
                            "role": "user",
                            "content": [{
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": tool_result
                            }]
                        })
                        
                        follow_up_messages = [{"role": msg["role"], "content": msg["content"]} for msg in self.conversation_history]
                        
                        follow_up_request = {
                            "anthropic_version": "bedrock-2023-05-31",
                            "messages": follow_up_messages,
                            "max_tokens": int(os.getenv('MAX_TOKENS', '65536')),
                            "temperature": 0.7,
                            "tools": self.format_tools_for_bedrock()
                        }
                        
                        follow_up_response = self.bedrock.invoke_model(
                            modelId=self.model_id,
                            body=json.dumps(follow_up_request),
                            contentType="application/json"
                        )
                        
                        follow_up_body = json.loads(follow_up_response['body'].read())
                        final_content = ""
                        
                        for content_block in follow_up_body.get("content", []):
                            if content_block.get("type") == "text":
                                final_content += content_block.get("text", "")
                        
                        yield f"💬 Claude's response:\n{final_content}\n"
                        
                        self.conversation_history.append({
                            "role": "assistant",
                            "content": final_content
                        })
            else:
                assistant_message = ""
                for content_block in response_body.get("content", []):
                    if content_block.get("type") == "text":
                        assistant_message += content_block.get("text", "")
                
                yield f"💬 Claude's response:\n{assistant_message}\n"
                self.conversation_history.append({
                    "role": "assistant",
                    "content": assistant_message
                })
                
        except Exception as e:
            yield f"❌ Error: {str(e)}\n"

chatbot = MCPChatbot()

def create_gradio_interface():
    def chat_fn(message, history):
        """实时流式聊天函数 - 支持多轮对话"""
        if not message.strip():
            yield history, ""
            return
        
        # 同步UI历史到chatbot内部历史
        # 只有在UI历史与内部历史不同步时才更新
        if history:
            # 重建内部对话历史
            chatbot.conversation_history = []
            for msg in history:
                if isinstance(msg, dict) and "role" in msg and "content" in msg:
                    chatbot.conversation_history.append({
                        "role": msg["role"], 
                        "content": msg["content"]
                    })
        
        # 添加用户消息到历史（使用messages格式）
        history = history or []
        history.append({"role": "user", "content": message})
        
        # 立即显示用户消息
        yield history, ""
        
        # 添加助手消息占位符
        history.append({"role": "assistant", "content": ""})
        ai_response = ""
        
        # 创建新的事件循环处理异步调用
        import threading
        import queue
        import asyncio
        import time
        
        result_queue = queue.Queue()
        
        def run_async_chat():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def collect_chunks():
                async for chunk in chatbot.chat_with_tools(message):
                    result_queue.put(chunk)
                result_queue.put(None)  # 结束标记
            
            loop.run_until_complete(collect_chunks())
            loop.close()
        
        # 在新线程中运行异步函数
        thread = threading.Thread(target=run_async_chat)
        thread.start()
        
        # 实时流式收集和显示结果
        while True:
            try:
                chunk = result_queue.get(timeout=0.1)  # 减小超时时间以提高响应性
                if chunk is None:  # 结束标记
                    break
                ai_response += chunk
                # 更新最后一条回复并立即yield
                history[-1]["content"] = ai_response
                yield history, ""
                time.sleep(0.05)  # 小延迟让用户看到流式效果
            except queue.Empty:
                # 即使没有新内容也要yield保持连接
                yield history, ""
                continue
        
        thread.join()
        # 最终确认
        yield history, ""
    
    def clear_fn():
        chatbot.conversation_history = []
        return [], ""
    
    with gr.Blocks(title="E2B Sandbox Chatbot Demo", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🤖 E2B Sandbox Chatbot Demo")
        gr.Markdown("This chatbot uses AWS Bedrock Claude 3.7 Sonnet with E2B sandbox via STDIO MCP tools")
        
        chatbot_ui = gr.Chatbot(
            label="Chat with E2B Sandbox Bot",
            height=600,
            show_copy_button=True,
            placeholder="Welcome! Ask me to calculate something or run Python code...",
            type="messages",
            scale=1,
            min_height=300,
            max_height=800,
            autoscroll=True
        )
        
        with gr.Row():
            msg = gr.Textbox(
                label="Your message",
                placeholder="Type your message here... (e.g., 'Calculate π to 10 decimal places')",
                scale=4,
                lines=2
            )
            send_btn = gr.Button("Send", variant="primary", scale=1)
            clear_btn = gr.Button("Clear Chat", variant="secondary", scale=1)
        
        # 事件绑定 - 简化版本
        msg.submit(
            chat_fn,
            inputs=[msg, chatbot_ui],
            outputs=[chatbot_ui, msg]
        )
        
        send_btn.click(
            chat_fn,
            inputs=[msg, chatbot_ui],
            outputs=[chatbot_ui, msg]
        )
        
        clear_btn.click(
            clear_fn,
            outputs=[chatbot_ui, msg]
        )
        
        gr.Markdown("""
        ### 使用说明:
        1. 输入消息并点击发送或按Enter
        2. 如果Claude需要使用工具，会显示工具调用过程
        3. 支持Python代码执行
        4. 点击"Clear Chat"清空对话历史
        """)
    
    return demo

if __name__ == "__main__":
    # 从环境变量获取配置
    server_host = os.getenv('GRADIO_SERVER_HOST', '0.0.0.0')
    server_port = int(os.getenv('GRADIO_SERVER_PORT', os.getenv('E2B_GRADIO_SERVER_PORT', '7861')))
    debug_mode = os.getenv('DEBUG', 'true').lower() == 'true'
    
    print(f"🚀 Starting E2B Sandbox Chatbot (STDIO mode)...")
    print(f"🔑 E2B API Key: {'***' + os.getenv('API_KEY', '')[-4:] if os.getenv('API_KEY') else 'Not set'}")
    print(f"🌐 MCP Server: E2B MCP Server (STDIO)")
    print(f"📱 Interface: http://{server_host}:{server_port}")
    print(f"🔧 Debug mode: {'enabled' if debug_mode else 'disabled'}")
    
    # Force a specific port to avoid conflicts
    server_port = 7863
    
    demo = create_gradio_interface()
    demo.launch(
        server_name=server_host,
        server_port=server_port,
        share=False,
        debug=debug_mode
    )