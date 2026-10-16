from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from uuid import UUID

from app.core.security import normalize_email, password_problem


class UserBase(BaseModel):
    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def _canonical_email(cls, value: object) -> object:
        """Store and look up addresses in one casing (see `normalize_email`)."""
        return normalize_email(value) if isinstance(value, str) else value


class UserCreate(UserBase):
    password: str

    @field_validator("password")
    @classmethod
    def _password_policy(cls, value: str) -> str:
        """The policy itself lives in `app.core.security`, next to the hashing."""
        problem = password_problem(value)
        if problem is not None:
            raise ValueError(problem)
        return value


class UserResponse(UserBase):
    id: UUID

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: Optional[str] = None
