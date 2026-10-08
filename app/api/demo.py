"""Demo-mode and Dataset Replay control API."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.demo.demo_generator import demo_generator
from app.demo.demo_profiles import DEMO_PROFILES
from app.demo.dataset_replay import dataset_replay_engine, DATASET_CONFIGS

router = APIRouter(prefix="/demo", tags=["Demo Mode"])


class DatasetReplayRequest(BaseModel):
    dataset_id: str = Field("elliptic_bitcoin", description="Dataset ID (elliptic_bitcoin or ethereum_fraud)")
    count: int = Field(100, ge=1, le=500, description="Number of transactions to replay")
    speed: float = Field(1.0, ge=0.1, le=10.0, description="Replay speed in transactions per second")


@router.post("/start", status_code=202)
def start_demo():
    if not demo_generator.start():
        return {"status": "already_running", **demo_generator.status()}
    return {"status": "started", **demo_generator.status()}


@router.post("/stop")
def stop_demo():
    if not demo_generator.stop():
        return {"status": "already_stopped", **demo_generator.status()}
    return {"status": "stopping", **demo_generator.status()}


@router.get("/status")
def demo_status():
    return demo_generator.status()


@router.get("/users")
def demo_users():
    return list(DEMO_PROFILES.values())


@router.get("/transactions")
def demo_transactions():
    return demo_generator.transactions


# ================================================================
# REAL HISTORICAL DATASET REPLAY ENDPOINTS
# ================================================================

@router.get("/dataset-replay/datasets")
def list_datasets():
    return list(DATASET_CONFIGS.values())


@router.get("/dataset-replay/analysis")
def dataset_replay_analysis(dataset_id: str = "elliptic_bitcoin"):
    return dataset_replay_engine.dataset_analysis(dataset_id)


@router.post("/dataset-replay/start", status_code=202)
def start_dataset_replay(payload: DatasetReplayRequest):
    success = dataset_replay_engine.start(
        dataset_id=payload.dataset_id,
        count=payload.count,
        speed=payload.speed
    )
    if not success:
        return {"status": "already_running", **dataset_replay_engine.status()}
    return {"status": "started", **dataset_replay_engine.status()}


@router.post("/dataset-replay/stop")
def stop_dataset_replay():
    was_running = dataset_replay_engine.stop()
    return {"status": "stopping" if was_running else "already_stopped", **dataset_replay_engine.status()}


@router.post("/dataset-replay/reset")
def reset_dataset_replay():
    dataset_replay_engine.reset()
    return {"status": "reset", **dataset_replay_engine.status()}


@router.get("/dataset-replay/status")
def dataset_replay_status():
    return dataset_replay_engine.status()

