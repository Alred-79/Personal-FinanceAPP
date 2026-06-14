"""Learned-memory router (Pillar 1A — transparency).

Lets the user see, correct, and delete what the Clerk has learned about them.
This is the trust contract for long-term memory: nothing the agent remembers is
hidden or permanent. Edits go in through the trusted ``user`` lane; any change
evicts the cached executor so the next chat turn reflects it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.src.db.session import get_db
from server.src.models import UserInDB
from server.src.services.auth_service import AuthService
from server.src.services import user_memory
from server.src.routers.assistant import assistant_service

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryFactIn(BaseModel):
    value: str
    pinned: bool = False


@router.get("/")
def list_memory(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """All facts the assistant has learned, with their source and confidence."""
    facts = user_memory.get_facts(db, current_user.id)
    return {
        "items": [
            {
                "key": f.key,
                "value": f.value,
                "source": f.source,
                "confidence": f.confidence,
                "pinned": bool(f.pinned),
                "updated_at": f.updated_at,
            }
            for f in facts
        ]
    }


@router.put("/{key}/")
def upsert_memory(
    key: str,
    payload: MemoryFactIn,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """Set or correct a fact via the trusted ``user`` lane.

    A user edit always wins over a derived/LLM fact and is recorded as
    ``source='user'``. Rejects keys outside the closed memory enum.
    """
    try:
        user_memory.set_user_fact(
            db,
            current_user.id,
            key,
            payload.value,
            source="user",
            pinned=payload.pinned,
        )
    except user_memory.MemoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    assistant_service.invalidate_agent(current_user.id)
    return {"message": "Memory updated", "key": key}


@router.delete("/{key}/")
def delete_memory(
    key: str,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """Forget a learned fact."""
    if not user_memory.forget(db, current_user.id, key):
        raise HTTPException(status_code=404, detail="Memory fact not found")
    db.commit()
    assistant_service.invalidate_agent(current_user.id)
    return {"message": "Memory forgotten", "key": key}
