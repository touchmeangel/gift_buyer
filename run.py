import pyrogram.errors
from config import AMQP_URL, AMQP_QUEUE_NAME, NGROK_HOST, random_proxy
from utils.proxy import parse_proxy_url
import traceback
import pyrogram
import aio_pika
import aiohttp
import logging
import asyncio
import math
import json

logger = logging.getLogger(__name__)

async def get_ngrok_public_url(ngrok_hostname: str):
  async with aiohttp.ClientSession() as session:
    async with session.get(f"http://{ngrok_hostname}/api/tunnels", timeout=5) as resp:
      resp.raise_for_status()
      data = await resp.json()
      for t in data.get("tunnels", []):
        pub = t.get("public_url", "")
        if pub.startswith("https://"):
          return pub

async def buy_notification(webhook_url: str, data: dict):
  async with aiohttp.ClientSession() as session:
    async with session.post(f"{webhook_url}/buy_notification", json=data) as resp:
      resp.raise_for_status()

class Worker:
  def __init__(self, webhook_url: str):
    self.connection = None
    self.channel = None
    self.queue = None
    self.webhook_url = webhook_url
    self.event_handlers = {}
    self.tasks = []
    self.add_event_handler("snipe", self.handle_snipe)

  async def run(self):
    await self.connect()

    await asyncio.Future()

  async def connect(self):
    if not self.connection or self.connection.is_closed:
      self.connection = await aio_pika.connect_robust(AMQP_URL)
      self.channel = await self.connection.channel()

      self.queue = await self.channel.declare_queue(AMQP_QUEUE_NAME, durable=True)
      await self.queue.consume(self.handle_message)
    return self.channel
  
  def add_event_handler(self, event: str, handler):
    self.event_handlers[event] = handler

  async def handle_snipe(self, data: dict | None):
    if data is None:
      logger.warning(f"invalid snipe data...")
      return
    
    owner = data.get("owner")
    session_string = data.get("session_string")
    api_id = data.get("api_id")
    api_hash = data.get("api_hash")
    amount_stars = data.get("amount_stars")
    recipient = data.get("recipient")
    gifts = data.get("gifts")
    if not all([owner, session_string, api_id, api_hash, amount_stars, recipient, gifts]):
      logger.warning(f"invalid snipe data...")
      return
    
    proxy = random_proxy()
    if proxy is not None:
      proxy = parse_proxy_url(proxy)
    app = pyrogram.Client(":memory:", session_string=session_string, device_model="Snoops Buy", client_platform=pyrogram.enums.ClientPlatform.ANDROID, app_version="Android 11.14.1", api_id=api_id, api_hash=api_hash, in_memory=True, proxy=proxy)
    try:
      await app.connect()
    except pyrogram.errors.AuthKeyInvalid:
      logger.warning(f"[{recipient}] session expired")
      return
    except pyrogram.errors.SessionExpired:
      logger.warning(f"[{recipient}] session expired")
      return
    except Exception as e:
      tb_str = traceback.format_exc()
      logger.warning(f"[{recipient}] failed to connect using session: {e} / {tb_str}")
      return
    
    try:
      remaining_balance = amount_stars
      if amount_stars < 0:
        remaining_balance = await app.get_stars_balance()

      tasks = []
      for gift in gifts:
        gift_id = gift.get("id")
        gift_price = gift.get("price")
        gift_title = gift.get("title")
        gift_supply = gift.get("supply")
        gift_file_id = gift.get("file_id")
        if not all([gift_id, gift_price]):
          logger.warning(f"[{recipient}] invalid gift data, skipping...")
          continue
        
        if gift_price > remaining_balance:
          continue
          
        a = math.floor(remaining_balance / gift_price)
        amount_succeeded, error = await buy_gift(app, recipient, gift_id, a)

        total_amount = gift_price * amount_succeeded
        remaining_balance -= total_amount

        tasks.append(asyncio.create_task(buy_notification(self.webhook_url, {
          "recipient": owner,
          "id": gift_id,
          "price": gift_price,
          "title": gift_title,
          "supply": gift_supply,
          "file_id": gift_file_id,
          "amount_succeeded": amount_succeeded,
          "amount_tried": a,
          "error": error
        })))

        if "BALANCE_TOO_LOW" in error:
          break

      try:
        await asyncio.gather(*tasks)
      except Exception as e:
        logger.warning(f"[{owner}] e: {e}")
    except Exception as e:
      tb_str = traceback.format_exc()
      logger.error(f"unhandled error: {e} / {tb_str}")
      return
    finally:
      await app.disconnect()

  async def handle_message(self, message: aio_pika.IncomingMessage):
    async with message.process():
      msg = json.loads(message.body.decode())

      event = msg["event"]
      data = msg.get("data")
      logger.warning(f"recieved \"{event}\" event: {data}")
      handler = self.event_handlers.get(event)
      if handler is None:
        logger.warning(f"UNHANDLED MESSAGE: {msg}")
        return
      
      self.tasks.append(asyncio.create_task(handler(data)))

  async def close(self):
    if self.connection:
      await self.connection.close()

  async def __aenter__(self) -> "Worker":
    return self

  async def __aexit__(
      self,
      exc_type,
      exc_val,
      exc_tb,
  ) -> None:
    await self.close()

async def buy_gift(app: pyrogram.Client, receiver_id: int, gift_id: int, amount: int) -> tuple[int, str | None]:
  i = 0   
  while True:
    if i >= amount:
      return i, None
    
    try: 
      await app.send_gift(receiver_id, gift_id)
    except pyrogram.errors.StargiftUsageLimited:
      return i, "Gift is sold out"
    except pyrogram.errors.BadRequest as e:
      logger.error(f"[{receiver_id}] send_gift err: {e}")
      return i, str(e.value)
    
    i += 1

async def main():
  public_url = await get_ngrok_public_url(NGROK_HOST)
  async with Worker(public_url) as w:
    await w.run()
  
if __name__ == "__main__":
  asyncio.run(main())