"""Demo-mode control API."""

from fastapi import APIRouter, HTTPException

from app.demo.demo_generator import demo_generator
from app.demo.demo_profiles import DEMO_PROFILES

router = APIRouter(prefix="/demo", tags=["Demo Mode"])


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
