"""友链申请的字段校验与默认值，供账号中心与主站两条申请路径共用。

规则（用户 2026-09-26 明确）：

| 字段 | 必填 | 留空时 |
| --- | --- | --- |
| 站点名称 site_name | 是 | —— |
| 站点地址 website_url | 是 | —— |
| 描述 description | 否 | 留空 |
| RSS rss_url | 否 | 用站点根目录下的 `/rss.xml` |
| 图标 avatar_url | 否 | 留空，由前端显示默认图 |
| 语言 language | 否 | 留空 |

原先 account.py 与 public.py 各有一份同样的实现，改一处容易漏另一处，所以合并到这里。
"""

from typing import Any

from app.api.v1.validation import text_field, url_field
from app.services.rss import default_rss_url


def friend_application_payload(payload: dict[str, Any]) -> dict[str, str]:
    website_url = url_field(
        payload.get("website_url"), field="website_url", required=True
    )
    rss_url = url_field(payload.get("rss_url"), field="rss_url")
    if not rss_url:
        # 没填 RSS 就按惯例用站点根目录下的 /rss.xml（用于抓"最新文章"）。
        # 这里就落库成具体地址，而不是留空到使用时再推导 —— 账号中心能看到、
        # 两条申请路径的行为也一致。
        rss_url = default_rss_url(website_url)
    return {
        "site_name": text_field(
            payload.get("site_name"), field="site_name", max_length=120, required=True
        ),
        "website_url": website_url,
        "avatar_url": url_field(payload.get("avatar_url"), field="avatar_url"),
        "language": text_field(payload.get("language"), field="language", max_length=80),
        "rss_url": rss_url,
        "description": text_field(
            payload.get("description"), field="description", max_length=500
        ),
        "applicant_note": text_field(
            payload.get("applicant_note"), field="applicant_note", max_length=1000
        ),
    }
