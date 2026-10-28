"""Exact email-domain allowlist; never treat a suffix as a substring."""
import re

DEFAULT_DOMAINS = [
    "qq.com", "foxmail.com", "163.com", "126.com", "yeah.net", "188.com",
    "vip.163.com", "vip.126.com", "sina.com", "sina.cn", "vip.sina.com",
    "sohu.com", "139.com", "138.com", "189.cn", "21cn.com", "aliyun.com",
    "gmail.com", "googlemail.com", "outlook.com", "outlook.cn", "hotmail.com",
    "live.com", "live.cn", "msn.com", "icloud.com", "me.com", "mac.com",
    "yahoo.com", "yahoo.co.jp", "proton.me", "protonmail.com",
]
DOMAIN = re.compile(r"(?=.{3,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z")


def normalize_domains(value):
    if isinstance(value, str):
        value = re.split(r"[\s,，;；]+", value.strip())
    if not isinstance(value, list) or len(value) > 200:
        raise ValueError("邮箱后缀必须为列表，最多 200 项")
    result = []
    for raw in value:
        domain = str(raw).strip().lower().removeprefix("@")
        if not domain:
            continue
        if not DOMAIN.fullmatch(domain):
            raise ValueError("无效的邮箱后缀：" + domain[:80])
        if domain not in result:
            result.append(domain)
    if not result:
        raise ValueError("请至少保留一个允许注册的邮箱后缀")
    return result


def allowed(email, domains):
    return email.strip().lower().rsplit("@", 1)[-1] in domains
