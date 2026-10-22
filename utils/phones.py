import re
from typing import Optional


def normalize_sa_phone(raw: str) -> Optional[str]:
    digits = re.sub(r"\D", "", raw or "")
    if re.fullmatch(r"9665\d{8}", digits):
        return digits
    if re.fullmatch(r"05\d{8}", digits) or re.fullmatch(r"5\d{8}", digits):
        return "9665" + digits[-8:]
    return None
