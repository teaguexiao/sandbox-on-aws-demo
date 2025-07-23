from dotenv import load_dotenv
load_dotenv()
import os
import time

api_key = os.environ.get("API_KEY")
template = os.environ.get("TEMPLATE")
domain = os.environ.get("DOMAIN")

class Logs:
    """
    Represents logs from code execution.
    """
    def __init__(self, stdout=None, stderr=None):
        self.stdout = stdout or []
        self.stderr = stderr or []
        
    def __str__(self) -> str:
        stdout_str = "\n".join(self.stdout) if self.stdout else ""
        stderr_str = "\n".join(self.stderr) if self.stderr else ""
        return f"stdout: {stdout_str}, stderr: {stderr_str}"

class ExecutionResult:
    """
    Represents the result of code execution in the sandbox.
    """
    def __init__(self, logs=None, results=None, error=None):
        self.logs = logs or Logs()
        self.results = results or []
        self.error = error
        
    def __str__(self) -> str:
        return f"Execution(Results: {self.results}, Logs: {self.logs}, Error: {self.error})"

class Sandbox:
    """
    Manages a sandbox environment for executing code securely.
    Based on the example code provided.
    """
    def __init__(self, api_key=None, template=None, domain=None, timeout=300, metadata=None):
        """
        Initialize a new sandbox instance.
        
        Args:
            api_key: E2B API key
            template: Template ID for the sandbox environment
            domain: Domain for the sandbox
            timeout: Timeout in seconds before the sandbox is terminated
            metadata: Additional metadata for the sandbox
        """
        self.api_key = api_key or os.environ.get("API_KEY")
        self.template = template
        self.domain = domain
        self.timeout = timeout
        self.metadata = metadata or {}
        
        # Create a new sandbox instance
        self.sandbox_id = f"sandbox-{int(time.time())}"
        print(f"Created sandbox with ID: {self.sandbox_id}")
        
        # Initialize file system handler for listing files
        self.files = self.FileSystem(self)
        
        # Initialize process handler
        self.process = self.Process(self)
        
        # Initialize stream handler
        self.stream = self.Stream(self)
        
        # Set status
        self.status = "active"
        self.ready = True
    
    def run_code(self, code: str):
        """
        Execute code in the sandbox.
        
        Args:
            code: Code to execute
            
        Returns:
            ExecutionResult object containing logs
        """
        print(f"Executing code in sandbox {self.sandbox_id}")
        
        # This is a placeholder for actual code execution
        # In a real implementation, this would send the code to the E2B API
        
        # Simulate code execution
        if "print" in code:
            # Extract the content inside print statements
            import re
            print_matches = re.findall(r'print\s*\(\s*[\'"](.+?)[\'"]\s*\)', code)
            stdout = print_matches if print_matches else ["Code executed successfully"]
            
            # Check for progress output (like tqdm)
            if "tqdm" in code:
                stderr = ["100%|██████████| 100/100 [00:01<00:00, 98.04it/s]"]
            else:
                stderr = []
                
            logs = Logs(stdout=stdout, stderr=stderr)
        else:
            logs = Logs(stdout=["Code executed successfully"], stderr=[])
            
        return ExecutionResult(logs=logs)
    
    def kill(self):
        """
        Destroy the sandbox.
        """
        print(f"Destroying sandbox {self.sandbox_id}")
        self.status = "destroyed"
        self.ready = False
    
    def stop(self):
        """
        Stop the sandbox.
        """
        print(f"Stopping sandbox {self.sandbox_id}")
        self.status = "stopped"
        self.ready = False
    
    def resume(self):
        """
        Resume the sandbox.
        """
        print(f"Resuming sandbox {self.sandbox_id}")
        self.status = "active"
        self.ready = True
    
    class FileSystem:
        """
        Handles file operations within the sandbox.
        """
        def __init__(self, sandbox):
            self.sandbox = sandbox
            
        def list(self, path: str):
            """
            List files and directories at the specified path in the sandbox.
            
            Args:
                path: Path to list files from
                
            Returns:
                List of file objects with metadata
            """
            # Placeholder implementation
            return [
                {"name": "example.py", "type": "file", "size": 1024},
                {"name": "data", "type": "directory"}
            ]
            
        def write(self, path: str, content: str):
            """
            Write content to a file in the sandbox.
            
            Args:
                path: Path to write to
                content: Content to write
            """
            print(f"Writing to {path} in sandbox {self.sandbox.sandbox_id}")
            
        def upload_file(self, path: str, content: str):
            """
            Upload a file to the sandbox.
            
            Args:
                path: Path to upload to
                content: Content to upload
            """
            print(f"Uploading to {path} in sandbox {self.sandbox.sandbox_id}")
    
    class Process:
        """
        Handles process execution within the sandbox.
        """
        def __init__(self, sandbox):
            self.sandbox = sandbox
            
        def exec(self, command: str, cwd=None, env=None, background=False, timeout=None):
            """
            Execute a command in the sandbox.
            
            Args:
                command: Command to execute
                cwd: Working directory
                env: Environment variables
                background: Whether to run in background
                timeout: Command timeout
                
            Returns:
                ExecutionResult object
            """
            print(f"Executing command '{command}' in sandbox {self.sandbox.sandbox_id}")
            
            # Simulate command execution
            if "echo" in command:
                # Extract the content inside echo
                import re
                echo_match = re.search(r'echo\s+[\'"](.*?)[\'"]', command)
                stdout = [echo_match.group(1) if echo_match else "Command executed successfully"]
                stderr = []
            else:
                stdout = ["Command executed successfully"]
                stderr = []
                
            logs = Logs(stdout=stdout, stderr=stderr)
            return ExecutionResult(logs=logs)
            
        def code_run(self, code: str):
            """
            Execute code in the sandbox.
            
            Args:
                code: Code to execute
                
            Returns:
                ExecutionResult object
            """
            return self.sandbox.run_code(code)
    
    class Stream:
        """
        Handles streaming from the sandbox.
        """
        def __init__(self, sandbox):
            self.sandbox = sandbox
            self.id = f"stream-{int(time.time())}"
            self.status = "stopped"
            self.auth_key = None
            
        def start(self, require_auth=False):
            """
            Start streaming from the sandbox.
            
            Args:
                require_auth: Whether to require authentication
            """
            print(f"Starting stream from sandbox {self.sandbox.sandbox_id}")
            self.status = "active"
            if require_auth:
                self.auth_key = f"auth-{int(time.time())}"
            
        def get_auth_key(self):
            """
            Get the authentication key for the stream.
            
            Returns:
                Authentication key
            """
            if not self.auth_key:
                self.auth_key = f"auth-{int(time.time())}"
            return self.auth_key
            
        def get_url(self, auth_key=None):
            """
            Get the URL for the stream.
            
            Args:
                auth_key: Authentication key
                
            Returns:
                Stream URL
            """
            if auth_key or self.auth_key:
                return f"https://stream.e2b.dev/{self.sandbox.sandbox_id}?auth={auth_key or self.auth_key}"
            return f"https://stream.e2b.dev/{self.sandbox.sandbox_id}"

# Chat panel implementation
class CodeInterpreterChat:
    """
    A simple chat interface for the code interpreter.
    """
    def __init__(self, template_id: str = None):
        """
        Initialize the chat interface.
        
        Args:
            template_id: Template ID for the sandbox
        """
        self.template_id = template_id
        self.sandbox = None
        self.history = []
        
    def start(self):
        """
        Start the chat interface.
        """
        print("=== Code Interpreter Chat ===")
        print("Type 'exit' to quit, 'new' to create a new sandbox, or paste your code to execute.")
        
        # Create initial sandbox
        self._create_sandbox()
        
        while True:
            user_input = input("\nEnter code or command: ")
            
            if user_input.lower() == 'exit':
                print("Goodbye!")
                break
                
            elif user_input.lower() == 'new':
                self._create_sandbox()
                
            else:
                # Execute the code
                self._execute_code(user_input)
    
    def _create_sandbox(self):
        """
        Create a new sandbox instance.
        """
        print("Creating new sandbox...")
        try:
            self.sandbox = Sandbox(template=self.template_id, timeout=3600)
            print(f"Sandbox created with ID: {self.sandbox.sandbox_id}")
        except Exception as e:
            print(f"Error creating sandbox: {str(e)}")
            
    def _execute_code(self, code: str):
        """
        Execute code in the sandbox and display the result.
        
        Args:
            code: Code to execute
        """
        if not self.sandbox:
            print("No active sandbox. Creating one...")
            self._create_sandbox()
            
        try:
            print("\nExecuting code...")
            start_time = time.time()
            result = self.sandbox.run_code(code)
            execution_time = time.time() - start_time
            
            print(f"\n--- Output (executed in {execution_time:.2f}s) ---")
            print(result)
            print("----------------------------")
            
            # Add to history
            self.history.append({"code": code, "result": str(result)})
            
        except Exception as e:
            print(f"Error executing code: {str(e)}")

def main():
    """
    Main entry point for the code interpreter chat.
    """
    # Use template ID from environment variable or default
    template_id = os.environ.get("CODE_INTERPRETER_TEMPLATE_ID", "j4ye6s3uoy2ap5fhy7n5")
    
    chat = CodeInterpreterChat(template_id=template_id)
    chat.start()

if __name__ == "__main__":
    main()
