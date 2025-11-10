import re
import logging
from typing import Optional

from fastapi import FastAPI, Request
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI()


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

    package_info = {
        "package_name": get_name(payload.asset.name),
        "version": get_version(payload.asset.name),
        "repository": payload.repositoryName,
        "timestamp": payload.timestamp,
    }

    logger.info(f"New wheel published: {package_info}")

    return {"status": "processed", "package": package_info}

