# Sandbox on AWS Demo

This project demonstrates how to leverage different sandbox environment on AWS (E2B, AWS Lambda, and AWS Elastic Compute Cloud/EC2) to run AI agents safely and efficiently. By isolating Browser-use Agents powered by Claude 3.7/4 Sonnet within containerized sandboxes, this solution provides:

- **Enhanced Security**: Complete isolation prevents AI agents from affecting your local system
- **Scalable Infrastructure**: AWS-backed sandboxes that can handle multiple concurrent users
- **Reliable Performance**: Dedicated compute resources ensure consistent agent execution
- **Easy Management**: Streamlined sandbox lifecycle management with automated provisioning
- **Cost Efficiency**: Pay-per-use model with automatic resource cleanup

## Frontend Interface

The web application provides a tabbed interface for accessing different sandbox functionalities. The navigation tabs are organized in the following order:

1. **Home** - Main dashboard and overview
2. **Sandbox Lifecycle** - Sandbox creation, management, and lifecycle operations
3. **Browser Use** - Browser automation and web interaction capabilities
4. **Code Interpreter** - Code execution and interpretation features
5. **Computer Use** - Desktop automation and computer interaction
6. **AI Search** - AI-powered search functionality *(Coming Soon)*
7. **AI PPT** - AI-powered presentation generation *(Coming Soon)*

Each tab provides access to specific sandbox capabilities while maintaining a consistent navigation experience across all pages.

## Pre-requisites

### AWS Setup

1. **Create IAM Role for Bedrock Access**:
   - Create an IAM role named `Bedrock-Role` with permissions to access AWS Bedrock
   - Attach the `AmazonBedrockFullAccess` managed policy to this role
   - Configure a trust relationship to allow your IAM user to assume this role

2. **Configure Trust Relationship**:
   - Add the following policy to your IAM role (replace `ACCOUNT_ID` with your AWS account ID and `your_iam_user_name` with your IAM user name):
   ```json
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "AWS": "arn:aws:iam::ACCOUNT_ID:user/your_iam_user_name"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }
   ```

3. **Enable Bedrock Model Access**:
   - Make sure you have access to Claude 3.7/4 Sonnet in AWS Bedrock
   - Navigate to AWS Bedrock console and subscribe to the model if needed

### Local Environment Setup

1. **Create and activate Python virtual environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirement.txt
   ```

3. **Configure environment variables**:
   Create a `.env` file with the following variables:
   ```
   API_KEY=your_e2b_api_key
   TEMPLATE=your_e2b_template_id_here
   DOMAIN=your_e2b_domain_here
   MODEL_ID=your_aws_bedrock_model_id_here
   AWS_ACCESS_KEY_ID=your_aws_access_key_id_for_your_iam_user_name
   AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key_for_your_iam_user_name
   TIMEOUT=1200
   ```

## Running the Application

```bash
python app.py
```

