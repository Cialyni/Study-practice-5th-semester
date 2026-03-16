import asyncio
import logging
import os
import re
import time
from asyncio import Lock, Queue
from pathlib import Path
from typing import Any, Dict, Optional



from dotenv import load_dotenv
from fastapi import FastAPI, Request
from gitlab_scripts.dependency_manager import DependencyManager
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI()
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)


class WebhookQueue:
    def __init__(self):
        self._queue = Queue()
        self._processing_lock = Lock()
        self._dm = None
        self._group_id = os.getenv("GROUP_ID")
        logger.info(f"WebhookQueue initialized with group_id: {self._group_id}")

    @property
    def dm(self):
        if self._dm is None:
            max_retries = 5
            for i in range(max_retries):
                try:
                    self._dm = DependencyManager(group_id=self._group_id)
                    logger.info(f"Connected to GitLab on attempt {i+1}")
                    break
                except Exception as e:
                    if i == max_retries - 1:
                        logger.error(f"Failed to connect to GitLab: {e}")
                        raise
                    logger.warning(f"Retry {i+1}/{max_retries} in 5s...")
                    time.sleep(5)
        return self._dm

    async def process_queue(self):
        while True:
            package_info = await self._queue.get()
            async with self._processing_lock:
                try:
                    if self._dm is None:
                        _ = self.dm
                    
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None, self.dm.update_all_direct_dependencies, package_info
                    )
                    logger.info(f"Processed {package_info['package_name']}")
                except Exception as e:
                    logger.error(f"Failed to process {package_info.get('package_name')}: {e}")
                finally:
                    self._queue.task_done()

    async def add_to_queue(self, package_info: Dict):
        await self._queue.put(package_info)
        logger.info(f"Queued {package_info['package_name']}")


webhook_queue = WebhookQueue()


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(webhook_queue.process_queue())
    logger.info("Queue processor started")


class AssetData(BaseModel):
    id: str
    assetId: str
    format: str
    name: str


class NexusWebhook(BaseModel):
    timestamp: str
    nodeId: str
    initiator: str
    repositoryName: str
    action: str
    asset: AssetData


def parse_wheel_filename(filename: str) -> Optional[Dict[str, str]]:
    basename = filename.split("/")[-1]
    if not basename.endswith('.whl'):
        return None
    
    parts = basename[:-4].split('-')
    
    for i, part in enumerate(parts):
        if re.match(r'\d+\.\d+\.\d+', part):
            name = '-'.join(parts[:i]).replace('_', '-')
            return {"name": name, "version": part}
    
    return None


@app.post("/webhook/nexus")
async def handle_nexus_webhook(payload: NexusWebhook):
    logger.info(f"Webhook received: {payload.action} - {payload.asset.name}")
    
    if payload.action != "CREATED" or not payload.asset.name.endswith(".whl"):
        return {"status": "ignored"}

    parsed = parse_wheel_filename(payload.asset.name)
    if not parsed:
        logger.error(f"Failed to parse filename: {payload.asset.name}")
        return {"status": "error", "reason": "Failed to parse filename"}

    package_info = {
        "package_name": parsed["name"],
        "version": parsed["version"],
        "repository": payload.repositoryName,
        "timestamp": payload.timestamp,
    }

    await webhook_queue.add_to_queue(package_info)
    return {"status": "queued", "package": parsed["name"], "version": parsed["version"]}


@app.get("/queue-status")
async def queue_status():
    return {
        "queue_size": webhook_queue._queue.qsize(),
        "is_processing": webhook_queue._processing_lock.locked()
    }


@app.get("/health")
async def health():
    return {"status": "alive"}

@app.post("/reload-token")
async def reload_token(request: Request):
    data = await request.json()
    new_token = data.get("new_token")
    
    if new_token:
        os.environ['GITLAB_ACCESS_TOKEN'] = new_token
        webhook_queue._dm = None
        logger.info(f"Token updated")
        return {"status": "ok"}
    
    return {"status": "error", "message": "No token"}