"""主站友链页内嵌申请用到的请求体。

面向匿名访客：只需要一个邮箱收验证码，站点资料在提交时一并带上。
"""

from typing import Optional

from pydantic import BaseModel, Field


class FriendLinkCodeRequest(BaseModel):
    email: str = Field(min_length=3, max_length=190)


class FriendLinkApplyRequest(BaseModel):
    email: str = Field(min_length=3, max_length=190)
    code: str = Field(min_length=6, max_length=6)

    site_name: str = Field(min_length=1, max_length=120)
    website_url: str = Field(min_length=4, max_length=2048)
    avatar_url: Optional[str] = Field(default=None, max_length=2048)
    language: Optional[str] = Field(default=None, max_length=80)
    rss_url: Optional[str] = Field(default=None, max_length=2048)
    description: Optional[str] = Field(default=None, max_length=500)
    applicant_note: Optional[str] = Field(default=None, max_length=1000)
