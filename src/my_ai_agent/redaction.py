import os
import re


def redact_secrets(text: str) -> str:
    for key, secret in os.environ.items():
        if len(secret) >= 8 and re.search(r"api.?key|password|secret|access.?token", key, re.I):
            text = text.replace(secret, "[已隐藏]")
    return text
