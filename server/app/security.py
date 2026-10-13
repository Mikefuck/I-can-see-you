import hashlib
import re
import secrets


USERNAME = re.compile(r"^[a-zA-Z0-9_.-]{3,40}$")


def valid_username(value: str) -> bool:
    return bool(USERNAME.fullmatch(value))


def password_hash(password: str) -> str:
    if not 12 <= len(password) <= 256:
        raise ValueError("密码长度须为 12–256 个字符")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000)
    return f"pbkdf2_sha256$600000${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or len(password) > 256:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return secrets.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
