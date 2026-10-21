from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: Optional[str] = None
    identity: Optional[str] = None
    password: str = Field(min_length=1, max_length=128)

    @property
    def resolved_identity(self) -> str:
        return (self.identity or self.username or "").strip()


class VerificationSendRequest(BaseModel):
    email: str = Field(min_length=3, max_length=190)
    purpose: str = Field(default="login", min_length=4, max_length=16)
    username: Optional[str] = Field(default=None, min_length=3, max_length=32)
    display_name: Optional[str] = Field(default=None, max_length=80)


class CodeLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=190)
    code: str = Field(min_length=6, max_length=6)


class RegisterCodeRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    email: str = Field(min_length=3, max_length=190)
    display_name: Optional[str] = Field(default=None, max_length=80)
    code: str = Field(min_length=6, max_length=6)


class PasswordSetupRequest(BaseModel):
    signup_token: str = Field(min_length=20, max_length=512)
    password: str = Field(min_length=6, max_length=128)


class PasswordResetVerifyRequest(BaseModel):
    email: str = Field(min_length=3, max_length=190)
    code: str = Field(min_length=6, max_length=6)


class PasswordResetConfirmRequest(BaseModel):
    reset_token: str = Field(min_length=20, max_length=512)
    password: str = Field(min_length=6, max_length=128)


class PasswordChangeRequest(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)
    code: str = Field(min_length=6, max_length=6)


class AccountSetupRequest(BaseModel):
    """Finish the account that a first-time code login created."""

    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=80)


class UserSummary(BaseModel):
    uid: int
    username: str
    email: str
    display_name: str
    avatar_url: str = ""
    role: str
    status: str
    setup_completed: bool = True


class TokenData(BaseModel):
    accessToken: str
    refreshToken: str
    expires: datetime
    avatar: str = ""
    username: str
    nickname: str
    roles: list[str]
    permissions: list[str]


class LoginResponse(BaseModel):
    success: bool = True
    data: TokenData
    # True only for accounts created by a first-time code login that have not
    # finished (or skipped) the setup dialog yet.
    requiresSetup: bool = False
