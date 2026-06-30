"""
Users routes — real DB-backed profile management.

Replaces MockDataService usage from Phase 1.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.models import User
from app.schemas import MessageResponse, PasswordChangeRequest, UserResponse, UserUpdateRequest

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/profile", response_model=UserResponse, summary="Get user profile")
async def get_profile(
    current_user: User = Depends(get_current_active_user),
) -> UserResponse:
    """Return the authenticated user's profile."""
    return UserResponse.model_validate(current_user)


@router.put("/profile", response_model=UserResponse, summary="Update user profile")
async def update_profile(
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    """Update mutable profile fields (full_name, username, avatar_url)."""
    updates = payload.model_dump(exclude_unset=True)

    # If username is changing, check uniqueness
    if "username" in updates and updates["username"] != current_user.username:
        conflict = db.query(User).filter(User.username == updates["username"]).first()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username is already taken",
            )

    for field, value in updates.items():
        setattr(current_user, field, value)

    db.commit()
    db.refresh(current_user)
    return UserResponse.model_validate(current_user)


@router.post("/change-password", response_model=MessageResponse, summary="Change password")
async def change_password(
    payload: PasswordChangeRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Verify old password then replace with new bcrypt hash."""
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.hashed_password = hash_password(payload.new_password)
    db.commit()
    return MessageResponse(message="Password changed successfully")
