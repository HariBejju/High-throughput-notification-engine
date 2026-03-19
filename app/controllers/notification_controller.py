import uuid
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.managers.notification_manager import NotificationManager
from app.schemas.notification_request import NotificationCreate
from app.schemas.notification_response import NotificationResponse, NotificationDetailResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def get_manager(db: AsyncSession = Depends(get_db)) -> NotificationManager:
    return NotificationManager(db)


# ── POST /notifications ───────────────────────────────────────────────────────

@router.post("", response_model=NotificationResponse, status_code=201)
async def create_notification(
    payload: NotificationCreate,
    manager: NotificationManager = Depends(get_manager),
):
    notification, is_duplicate = await manager.create_notification(payload)

    if is_duplicate:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "duplicate request, notification already exists",
                "idempotency_key": payload.idempotency_key,
            }
        )

    return notification


# ── GET /notifications/{id} ───────────────────────────────────────────────────

@router.get("/{notification_id}", response_model=NotificationDetailResponse)
async def get_notification(
    notification_id: uuid.UUID,
    manager: NotificationManager = Depends(get_manager),
):
    notification = await manager.get_notification(notification_id)

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    return notification


# ── GET /notifications ────────────────────────────────────────────────────────

@router.get("", response_model=List[NotificationDetailResponse])
async def list_notifications(
    status: Optional[int] = Query(None, description="1=pending 2=queued 3=sent 4=failed 5=retrying"),
    channel: Optional[int] = Query(None, description="1=email 2=sms 3=push"),
    source_service: Optional[int] = Query(None, description="1=order 2=payment 3=shipping"),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    manager: NotificationManager = Depends(get_manager),
):
    return await manager.list_notifications(
        status=status,
        channel=channel,
        source_service=source_service,
        limit=limit,
        offset=offset,
    )