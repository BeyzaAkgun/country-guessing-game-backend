#endpoints/users.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.base import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.user import UserResponse, PublicUserResponse, UpdateProfileRequest
from app.core.exceptions import NotFoundError, ConflictError

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one()
    await db.refresh(user, ["profile"])
    return user


@router.patch("/me", response_model=UserResponse)
async def update_me(
    body: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.username and body.username != current_user.username:
        existing = await db.execute(select(User).where(User.username == body.username))
        if existing.scalar_one_or_none():
            raise ConflictError("Username already taken")
        current_user.username = body.username

    await db.refresh(current_user, ["profile"])

    if body.avatar_url is not None and current_user.profile:
        current_user.profile.avatar_url = body.avatar_url

    await db.commit()
    await db.refresh(current_user, ["profile"])
    return current_user


@router.get("/{username}", response_model=PublicUserResponse)
async def get_user(username: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError(f"User '{username}' not found")
    await db.refresh(user, ["profile"])
    return user