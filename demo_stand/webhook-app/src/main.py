import asyncio
import logging
import os
import re
from asyncio import Lock, Queue
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from gitlab_scripts.dependency_manager import DependencyManager
from pydantic import BaseModel

app = FastAPI()
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)


class WebhookQueue:
    def __init__(self):
        self._queue = Queue()
        self._processing_lock = Lock()
        self.dm = DependencyManager(group_id=os.getenv("GITLAB_GROUP_ID"))

    async def process_queue(self):
        while True:
            package_info = await self._queue.get()

            async with self._processing_lock:
                logging.info(f"Processing {package_info['package_name']} from queue")
                loop = asyncio.get_event_loop()
                try:
                    await loop.run_in_executor(
                        None, self.dm.update_all_direct_dependencies, package_info
                    )
                    logging.info(f"Completed {package_info['package_name']}")
                except Exception as e:
                    logging.error(f"Failed {package_info['package_name']}: {e}")

            self._queue.task_done()

    async def add_to_queue(self, package_info: Dict):
        await self._queue.put(package_info)
        logging.info(f"Added {package_info['package_name']} to queue")


webhook_queue = WebhookQueue()


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(webhook_queue.process_queue())


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


def get_name(filename: str) -> Optional[str]:
    basename = filename.split("/")[-1]
    match = re.match(r"([\w_]+)-\d+\.\d+\.\d+", basename)
    return match.group(1).replace("_", "-") if match else None


def get_version(filename: str) -> Optional[str]:
    basename = filename.split("/")[-1]
    match = re.match(r"[\w_]+-(\d+\.\d+\.\d+)", basename)
    return match.group(1) if match else None


@app.post("/webhook/nexus")
async def handle_nexus_webhook(payload: NexusWebhook):
    if payload.action != "CREATED":
        return {"status": "ignored", "reason": "Not a CREATE event"}

    if not payload.asset.name.endswith(".whl"):
        return {"status": "ignored", "reason": "Not a wheel file"}

    package_name = get_name(payload.asset.name)
    version = get_version(payload.asset.name)

    package_info = {
        "package_name": package_name,
        "version": version,
        "repository": payload.repositoryName,
        "timestamp": payload.timestamp,
    }

    logging.info(f"New wheel published: {package_info}")

    await webhook_queue.add_to_queue(package_info)

    return {
        "status": "queued",
        "package": package_name,
        "queue_size": webhook_queue._queue.qsize(),
    }


@app.get("/queue-status")
async def queue_status():
    return {
        "queue_size": webhook_queue._queue.qsize(),
        "is_processing": webhook_queue._processing_lock.locked(),
    }
