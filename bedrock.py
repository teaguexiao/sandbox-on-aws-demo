import argparse
import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import boto3  # type: ignore
from botocore.config import Config
from langchain_aws import ChatBedrockConverse  # type: ignore

from browser_use import Agent
from browser_use.controller.service import Controller


def get_llm():
	config = Config(retries={'max_attempts': 10, 'mode': 'adaptive'})
	bedrock_client = boto3.client('bedrock-runtime', region_name='us-west-2', config=config)

	return ChatBedrockConverse(
		model_id="us.anthropic.claude-3-5-sonnet-20241022-v2:0",
		temperature=0.0,
		max_tokens=None,
		client=bedrock_client,
	)

extend_system_message = """
Always follow the below rule.
1. Think step by step before you take any action.
2. When performing a search task, prioritize opening https://www.bing.com for searching.
3. If an Ad is shown, you should click the "Skip/Close/Cancel" button to close it.
4. The final output should answer the user's question in English.
"""

# Define the task for the agent
task = "Predict the weather conditions in Wuxi, Jiangsu, China within the next 2 weeks, Using China's temperature measurement units."

parser = argparse.ArgumentParser()
parser.add_argument('--query', type=str, help='The query for the agent to execute', default=task)
args = parser.parse_args()

llm = get_llm()

agent = Agent(
	task=args.query,
	llm=llm,
	controller=Controller(),
	use_vision=True,
	message_context=extend_system_message,
	validate_output=True
)

async def main():
	await agent.run(max_steps=30)

asyncio.run(main())
