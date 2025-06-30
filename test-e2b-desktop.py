from e2b_desktop import Sandbox
from botocore.exceptions import ClientError
import webbrowser
import os
import sys
import boto3
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def open_desktop_stream():
    # Create a new desktop sandbox
    desktop = Sandbox(
            api_key=os.environ.get("API_KEY"),
            template=os.environ.get("TEMPLATE"),
            domain=os.environ.get("DOMAIN"),
            timeout=int(os.environ.get("TIMEOUT", 1200)),
            metadata={
                "purpose": "e2b-desktop-test"
            }
        )
    print(f"Sandbox ID: {desktop.sandbox_id}")

    # Stream the application's window
    # Note: There can be only one stream at a time
    # You need to stop the current stream before streaming another application
    desktop.stream.start(
        require_auth=True
    )

    # Get the stream auth key
    auth_key = desktop.stream.get_auth_key()

    # Print the stream URL
    stream_url = desktop.stream.get_url(auth_key=auth_key)
    print('Stream URL:', stream_url)
    # Try to open in Chrome
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
        access_key_id = os.environ.get("AWS_ACCESS_KEY_ID")
        secret_access_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
        if not access_key_id or not secret_access_key:
            raise Exception("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set in .env file")
        
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
        
        print(f"Successfully created STS session, valid until {credentials['Expiration']}")
        return credentials

    except ClientError as e:
        print(f"Failed to create STS session: {e}")
        return None

def setup_environment(desktop):
    # Copy files to sandbox
    with open('bedrock.py', 'r') as f1, open('.env', 'r') as f2:
        _code = f1.read()
        desktop.files.write('/tmp/bedrock.py', _code)
        _env = f2.read()
        desktop.files.write('~/.env', _env)
        
    credentials = create_sts()
    creds_content = f"""[default]
    aws_access_key_id={credentials['AccessKeyId']}
    aws_secret_access_key={credentials['SecretAccessKey']}
    aws_session_token={credentials['SessionToken']}
    """
    desktop.files.write('~/.aws/credentials', creds_content)

    # Install uv package manager
    desktop.commands.run('curl -LsSf https://astral.sh/uv/install.sh | sh; source $HOME/.local/bin/env; uv venv --python 3.11;')
    # Install required packages
    desktop.commands.run('uv pip install boto3 langchain-aws pydantic browser_use==0.3.2 browser-use[memory] playwright')
    # Install Playwright browser
    desktop.commands.run('uv run playwright install chromium --with-deps --no-shell')


def main(query):
    desktop = open_desktop_stream()
    setup_environment(desktop)
    result = desktop.commands.run(f"uv run python3 /tmp/bedrock.py --query '{query}'", on_stdout=lambda data: print(data), on_stderr=lambda data: print(data), timeout=1200)
    print(result)
    desktop.kill()

if __name__ == "__main__":
    main("Predict the weather conditions in Wuxi, Jiangsu, China within the next 2 weeks, Use China temperature measurement units.")
    # main("Tell me what is vibe coding and summarize its future trend.")