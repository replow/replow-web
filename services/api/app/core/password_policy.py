"""Shared password policy: 6-128 chars and at least 3 of 4 classes."""


def valid_new_password(password: str) -> bool:
    if not isinstance(password, str) or not 6 <= len(password) <= 128:
        return False
    kinds = (
        any("A" <= ch <= "Z" for ch in password),
        any("a" <= ch <= "z" for ch in password),
        any("0" <= ch <= "9" for ch in password),
        any(not ch.isalnum() and not ch.isspace() for ch in password),
    )
    return sum(kinds) >= 3
