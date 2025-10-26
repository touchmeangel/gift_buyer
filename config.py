from dotenv import load_dotenv
import random
import json
import os

load_dotenv()

NGROK_HOST = os.environ.get("NGROK_HOST")
AMQP_QUEUE_NAME = os.getenv("AMQP_QUEUE_NAME")
AMQP_URL = os.getenv("AMQP_URL")

config_file = "config.json"
if not os.path.exists(config_file):
  raise RuntimeError(f"{config_file} file is required.")

with open(config_file) as f:
  config = json.load(f)

proxies = config["proxies"]
creds = config["api_credentials"]
if len(creds) <= 0:
  raise RuntimeError("at least 1 pair of api_id and api_hash is required.")

def random_creds() -> tuple[int, str]:
  choice = random.choice(creds)
  return choice["api_id"], choice["api_hash"]

def random_proxy() -> str | None:
  if len(proxies) <= 0:
    return None
  
  return random.choice(proxies)