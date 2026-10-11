"""Self-owned privacy routes; service tokens and guild-manager rights grant no access."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, StrictBool

from src.api.auth import Principal, current_user
from src.services import privacy_service

router = APIRouter(prefix='/me', tags=['privacy'])


class PrivacyUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    presence_tracking: StrictBool


@router.get('/privacy')
async def get_privacy(principal: Principal = Depends(current_user)) -> dict:
    assert principal.user_id is not None
    return await privacy_service.get_privacy(principal.user_id)


@router.put('/privacy')
async def update_privacy(body: PrivacyUpdate, principal: Principal = Depends(current_user)) -> dict:
    assert principal.user_id is not None
    changed_at = await privacy_service.set_presence_opt_in(
        principal.user_id, body.presence_tracking, source='dashboard'
    )
    return {'presence_tracking': body.presence_tracking, 'changed_at': changed_at}


@router.delete('/activity', status_code=204)
async def delete_activity(principal: Principal = Depends(current_user)) -> Response:
    assert principal.user_id is not None
    await privacy_service.delete_activity_data(principal.user_id, source='dashboard')
    return Response(status_code=204)
