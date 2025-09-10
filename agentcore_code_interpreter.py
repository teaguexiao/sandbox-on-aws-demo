"""
AWS Bedrock AgentCore Code Interpreter integration for web interface
Provides code execution capabilities using AWS Bedrock AgentCore service
"""

import boto3
import logging
from typing import Dict, Optional, Any
from datetime import datetime

# Global variables for session management
agentcore_logger = None

# Global AgentCore session tracking
agentcore_sessions: Dict[str, Any] = {}

# Configuration constants
AGENTCORE_REGION = "us-west-2"
AGENTCORE_ENDPOINT = "https://bedrock-agentcore.us-west-2.amazonaws.com"
CODE_INTERPRETER_IDENTIFIER = "aws.codeinterpreter.v1"
SESSION_TIMEOUT_SECONDS = 900
SESSION_NAME = "my-code-session"


class AgentCoreCodeInterpreter:
    """AWS Bedrock AgentCore Code Interpreter client wrapper"""
    
    def __init__(self, region: str = AGENTCORE_REGION, endpoint_url: str = AGENTCORE_ENDPOINT):
        self.region = region
        self.endpoint_url = endpoint_url
        self.client = None
        
    def _get_client(self):
        """Get or create boto3 client for Bedrock AgentCore"""
        if self.client is None:
            self.client = boto3.client(
                "bedrock-agentcore", 
                region_name=self.region, 
                endpoint_url=self.endpoint_url
            )
        return self.client
    
    def start_session(self, session_name: str = SESSION_NAME) -> str:
        """Start a new code interpreter session"""
        client = self._get_client()
        
        session_response = client.start_code_interpreter_session(
            codeInterpreterIdentifier=CODE_INTERPRETER_IDENTIFIER,
            name=session_name,
            sessionTimeoutSeconds=SESSION_TIMEOUT_SECONDS
        )
        
        session_id = session_response["sessionId"]
        
        if agentcore_logger:
            agentcore_logger.info(f"Started AgentCore session: {session_id}")
        
        return session_id
    
    def execute_code(self, session_id: str, code: str) -> str:
        """Execute code in the specified session and return output"""
        client = self._get_client()
        
        execute_response = client.invoke_code_interpreter(
            codeInterpreterIdentifier=CODE_INTERPRETER_IDENTIFIER,
            sessionId=session_id,
            name="executeCode",
            arguments={
                "language": "python",
                "code": code
            }
        )
        
        # Extract text output from the stream
        output_text = ""
        for event in execute_response['stream']:
            if 'result' in event:
                result = event['result']
                if 'content' in result:
                    for content_item in result['content']:
                        if content_item['type'] == 'text':
                            output_text += content_item['text'] + "\n"
        
        return output_text.strip()
    
    def stop_session(self, session_id: str) -> bool:
        """Stop a code interpreter session"""
        try:
            client = self._get_client()
            client.stop_code_interpreter_session(
                codeInterpreterIdentifier=CODE_INTERPRETER_IDENTIFIER,
                sessionId=session_id
            )
            
            if agentcore_logger:
                agentcore_logger.info(f"Stopped AgentCore session: {session_id}")
            
            return True
        except Exception as e:
            if agentcore_logger:
                agentcore_logger.warning(f"Error stopping session {session_id}: {e}")
            return False


async def execute_agentcore_code(code: str) -> Dict[str, Any]:
    """
    Execute code using AWS Bedrock AgentCore and return the result
    
    Args:
        code: Python code to execute
        
    Returns:
        Dictionary with success status, output, session_id, and error (if any)
    """
    try:
        # Create AgentCore client
        interpreter = AgentCoreCodeInterpreter()
        
        # Start a new session
        session_id = interpreter.start_session()
        
        # Execute the code
        output_text = interpreter.execute_code(session_id, code)
        
        # Store session and client for later cleanup
        agentcore_sessions[session_id] = interpreter
        
        return {
            "success": True,
            "output": output_text,
            "session_id": session_id
        }
    except Exception as e:
        if agentcore_logger:
            agentcore_logger.error(f"Error executing code in AgentCore: {str(e)}")
        
        return {
            "success": False,
            "error": str(e)
        }


async def reset_agentcore_sessions() -> Dict[str, Any]:
    """
    Reset AgentCore sessions by stopping all active sessions
    
    Returns:
        Dictionary with success status, message, and error (if any)
    """
    try:
        # Stop all active sessions
        stopped_sessions = []
        
        for session_id, interpreter in agentcore_sessions.items():
            if interpreter.stop_session(session_id):
                stopped_sessions.append(session_id)
        
        # Clear the sessions dictionary
        agentcore_sessions.clear()
        
        return {
            "success": True,
            "message": f"Reset completed. Stopped {len(stopped_sessions)} sessions."
        }
    except Exception as e:
        if agentcore_logger:
            agentcore_logger.error(f"Error resetting AgentCore sessions: {str(e)}")
        
        return {
            "success": False,
            "error": str(e)
        }


def get_active_sessions() -> Dict[str, Any]:
    """
    Get information about active AgentCore sessions
    
    Returns:
        Dictionary with session information
    """
    session_info = {}
    for session_id, interpreter in agentcore_sessions.items():
        session_info[session_id] = {
            "session_id": session_id,
            "region": interpreter.region,
            "created_at": datetime.now().isoformat()  # This would be better tracked in a session object
        }
    
    return {
        "total_sessions": len(agentcore_sessions),
        "sessions": session_info
    }


def init_agentcore_code_interpreter_vars(app_logger):
    """Initialize shared variables from app.py"""
    global agentcore_logger
    agentcore_logger = app_logger
