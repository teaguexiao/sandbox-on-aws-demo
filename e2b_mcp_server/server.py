import os
import json
import logging
from collections.abc import Sequence
from typing import Any

from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
)

from pydantic import BaseModel, ValidationError
from e2b_code_interpreter import Sandbox


# Load environment variables
load_dotenv()
template_id=os.getenv("CODE_INTERPRETER_TEMPLATE_ID")

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("e2b-mcp-server")
logger.info("E2B MCP server logging initialized")

# Tool schema
class ToolSchema(BaseModel):
    code: str

app = Server("e2b-code-mcp-server")

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    logger.debug("list_tools called")
    tools = [
        Tool(
            name="run_code",
            description="Run python code in a secure sandbox by E2B. Using the Jupyter Notebook syntax.",
            inputSchema=ToolSchema.model_json_schema()
        )
    ]
    logger.info(f"Returning {len(tools)} available tools")
    return tools

@app.call_tool()
async def call_tool(name: str, arguments: Any) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
    """Handle tool calls."""
    logger.info(f"Tool call received: {name}")
    logger.debug(f"Tool arguments: {arguments}")
    
    if name != "run_code":
        logger.error(f"Unknown tool called: {name}")
        raise ValueError(f"Unknown tool: {name}")

    try:
        logger.debug("Validating tool arguments")
        arguments = ToolSchema.model_validate(arguments)
        logger.debug("Tool arguments validated successfully")
    except ValidationError as e:
        logger.error(f"Invalid code arguments: {e}")
        raise ValueError(f"Invalid code arguments: {e}") from e

    logger.info(f"Creating sandbox with template: {template_id}")
    sbx = Sandbox(template=template_id, timeout=3600)
    
    logger.info("Running code in sandbox")
    logger.debug(f"Code to execute:\n{arguments.code}")
    
    try:
        execution = sbx.run_code(arguments.code)
        logger.info(f"Code execution completed")
        logger.debug(f"Execution details: {execution}")
    except Exception as e:
        logger.error(f"Error executing code: {str(e)}")
        raise

    result = {
        "stdout": execution.logs.stdout,
        "stderr": execution.logs.stderr,
    }
    
    logger.debug(f"Execution stdout: {execution.logs.stdout}")
    if execution.logs.stderr:
        logger.warning(f"Execution stderr: {execution.logs.stderr}")

    return [
        TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )
    ]

async def main():
    # Import here to avoid issues with event loops
    import sys
    from mcp.server.stdio import stdio_server
    
    logger.info("Starting E2B MCP server with STDIO communication")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Using MCP package: {__import__('mcp')}")
    logger.info(f"E2B API Key present: {bool(os.getenv('API_KEY'))}")
    logger.info(f"CODE_INTERPRETER_TEMPLATE_ID: {template_id if template_id else 'Not set'}")
    logger.info(f"Current directory: {os.getcwd()}")
    logger.info(f"Environment variables: {sorted([k for k in os.environ.keys()])}")
    
    
    # Debug stdin/stdout
    logger.info(f"stdin isatty: {sys.stdin.isatty()}, encoding: {sys.stdin.encoding}")
    logger.info(f"stdout isatty: {sys.stdout.isatty()}, encoding: {sys.stdout.encoding}")
    
    # Print directly to stderr for debugging
    print("E2B MCP Server starting with STDIO...", file=sys.stderr)
    
    try:
        # Test direct STDIO communication
        print("DIRECT-STDIO-TEST", flush=True)
        
        async with stdio_server() as (read_stream, write_stream):
            logger.info("STDIO streams established")
            logger.debug("Initializing server with read/write streams")
            
            # Debug the streams
            logger.info(f"Read stream type: {type(read_stream)}")
            logger.info(f"Write stream type: {type(write_stream)}")
            
            # Debug the stream types
            logger.info(f"Read stream type: {type(read_stream)}")
            logger.info(f"Write stream type: {type(write_stream)}")
            logger.info(f"Write stream methods: {dir(write_stream)}")
            
            # Don't try to write test messages directly, let the app.run handle it
            
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options()
            )
    except Exception as e:
        import traceback
        logger.critical(f"Critical error in MCP server: {str(e)}")
        logger.critical(traceback.format_exc())
        print(f"CRITICAL ERROR: {str(e)}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise
