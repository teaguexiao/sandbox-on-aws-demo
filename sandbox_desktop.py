from e2b_desktop import Sandbox
from botocore.exceptions import ClientError
import webbrowser
import os
import sys
import boto3
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logger
logger = logging.getLogger(__name__)

def open_desktop_stream(open_browser=False):
    # Create a new desktop sandbox
    logger.info("Creating new desktop sandbox...")
    try:
        # Log environment variables (redacting sensitive values)
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
        
        # Check if sandbox has required attributes
        logger.info(f"Sandbox status: {getattr(desktop, 'status', 'unknown')}")
        logger.info(f"Sandbox ready: {getattr(desktop, 'ready', False)}")
    except Exception as e:
        logger.error(f"Error creating sandbox: {e}", exc_info=True)
        raise

    # Stream the application's window
    # Note: There can be only one stream at a time
    # You need to stop the current stream before streaming another application
    try:
        logger.info("Starting stream...")
        desktop.stream.start(
            require_auth=True
        )
        logger.info("Stream started successfully")

        # Get the stream auth key
        logger.info("Getting stream auth key...")
        auth_key = desktop.stream.get_auth_key()
        logger.info("Auth key retrieved successfully")

        # Get and log the stream URL
        logger.info("Getting stream URL...")
        stream_url = desktop.stream.get_url(auth_key=auth_key)
        logger.info(f'Stream URL generated: {stream_url}')
    except Exception as e:
        logger.error(f"Error setting up stream: {e}", exc_info=True)
        raise
    
    # Open in browser if requested
    if open_browser:
        try:
            # Try the default Chrome browser
            webbrowser.get("chrome").open(stream_url)
        except webbrowser.Error:
            # Fallback for macOS: use 'open -a "Google Chrome"'
            if sys.platform == "darwin":
                os.system(f'open -a "Google Chrome" "{stream_url}"')
            else:
                # Fallback to default browser
                webbrowser.open(stream_url)
    
    return desktop

def create_sts():
    try:
        logger.info("Creating STS session...")
        access_key_id = os.environ.get("AWS_ACCESS_KEY_ID")
        secret_access_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
        if not access_key_id or not secret_access_key:
            error_msg = "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set in .env file"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        sts_client = boto3.client('sts',
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key
        )
        response = sts_client.get_caller_identity()
        account_id = response['Account']
        
        role_arn = f"arn:aws:iam::{account_id}:role/Bedrock-Role"
        role_session_name = "e2b-desktop"
        
        response = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName=role_session_name,
            DurationSeconds=900
        )
        
        credentials = response['Credentials']
        
        logger.info(f"Successfully created STS session, valid until {credentials['Expiration']}")
        return credentials

    except ClientError as e:
        error_msg = f"Failed to create STS session: {e}"
        logger.error(error_msg)
        return None

def setup_environment(desktop):
    logger.info("Setting up sandbox environment...")
    # Copy files to sandbox
    try:
        logger.info("Copying files to sandbox...")
        with open('bedrock.py', 'r') as f1, open('.env', 'r') as f2:
            _code = f1.read()
            desktop.files.write('/tmp/bedrock.py', _code)
            logger.info("Copied bedrock.py to /tmp/bedrock.py")
            _env = f2.read()
            desktop.files.write('~/.env', _env)
            logger.info("Copied .env to ~/.env")
    except Exception as e:
        logger.error(f"Error copying files: {e}")
        
    credentials = create_sts()
    creds_content = f"""[default]
    aws_access_key_id={credentials['AccessKeyId']}
    aws_secret_access_key={credentials['SecretAccessKey']}
    aws_session_token={credentials['SessionToken']}
    """
    desktop.files.write('~/.aws/credentials', creds_content)

    # Install uv package manager
    logger.info("Installing uv package manager...")
    desktop.commands.run('curl -LsSf https://astral.sh/uv/install.sh | sh; source $HOME/.local/bin/env; uv venv --python 3.11;')
    
    # Install required packages
    logger.info("Installing required Python packages...")
    desktop.commands.run('uv pip install boto3 langchain-aws pydantic browser_use==0.3.2 browser-use[memory] playwright')
    
    # Install Playwright browser
    logger.info("Installing Playwright browser...")
    desktop.commands.run('uv run playwright install chromium --with-deps --no-shell')
    
    logger.info("Environment setup completed successfully")


def main(query):
    logger.info(f"Starting main workflow with query: {query}")
    desktop = open_desktop_stream()
    setup_environment(desktop)
    
    logger.info(f"Running bedrock.py with query: {query}")
    result = desktop.commands.run(
        f"uv run python3 /tmp/bedrock.py --query '{query}'", 
        on_stdout=lambda data: logger.info(f"[BEDROCK] {data}"), 
        on_stderr=lambda data: logger.error(f"[BEDROCK] {data}"), 
        timeout=1200
    )
    logger.info(f"Task completed with result: {result}")
    
    logger.info("Killing desktop sandbox...")
    desktop.kill()
    logger.info("Desktop sandbox killed successfully")

if __name__ == "__main__":
    main("Predict the weather conditions in Wuxi, Jiangsu, China within the next 2 weeks, Use China temperature measurement units.")
