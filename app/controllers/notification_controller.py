import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.managers.notification_manager import NotificationManager
from app.schemas.notification_request import NotificationCreate
from app.schemas.notification_response import (
    NotificationResponse,
    NotificationDetailResponse,
    NotificationListResponse,
    RetryResponse,
)

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
    notification_id: int,
    manager: NotificationManager = Depends(get_manager),
):
    notification = await manager.get_notification(notification_id)

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    return notification


# ── GET /notifications ────────────────────────────────────────────────────────

@router.get("", response_model=List[NotificationListResponse])
async def list_notifications(
    status: Optional[str] = Query(None, description="pending|queued|sent|failed|retrying"),
    channel: Optional[str] = Query(None, description="email|sms|push"),
    source_service: Optional[str] = Query(None, description="order|payment|shipping"),
    event_type: Optional[str] = Query(None, description="order_created|payment_failed etc"),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    manager: NotificationManager = Depends(get_manager),
):
    return await manager.list_notifications(
        status=status,
        channel=channel,
        source_service=source_service,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )


# ── POST /notifications/{id}/retry ───────────────────────────────────────────

@router.post("/{notification_id}/retry", response_model=RetryResponse)
async def retry_notification(
    notification_id: int,
    manager: NotificationManager = Depends(get_manager),
):
    notification, error = await manager.retry_notification(notification_id)

    if error:
        raise HTTPException(status_code=400, detail=error)

    return RetryResponse(
        id=notification.id,
        status="pending",
        retry_count=notification.retry_count,
        message="Notification requeued successfully",
    )