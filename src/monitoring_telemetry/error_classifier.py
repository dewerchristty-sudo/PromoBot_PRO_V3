import re
from urllib.parse import urlsplit


ERROR_MESSAGE_LIMIT = 300


def sanitize_error_message(error):
    text = str(error or "").replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(
        r"https?://[^\s\"'<>]+",
        lambda match: _safe_url(match.group(0)),
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?i)\b(token|authorization|password|senha|api[_-]?key|cookie)"
        r"\s*[:=]\s*\S+",
        r"\1=***",
        text,
    )
    text = re.sub(
        r"(?i)data:[^;\s]+;base64,[a-z0-9+/=]+",
        "[BASE64 OMITIDO]",
        text,
    )
    text = re.sub(r"\b\d{10,22}(?:@g\.us)?\b", "***DADO OMITIDO***", text)
    text = re.sub(
        r"\b[A-Za-z0-9+/]{120,}={0,2}\b",
        "[CONTEÚDO OMITIDO]",
        text,
    )
    return text[:ERROR_MESSAGE_LIMIT]


def _safe_url(value):
    try:
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.hostname:
            return "[URL OMITIDA]"
        return f"{parsed.scheme}://{parsed.hostname}/[CAMINHO OMITIDO]"
    except ValueError:
        return "[URL OMITIDA]"


def classify_error(error):
    if error is None:
        return None
    text = f"{type(error).__name__} {error}".casefold()
    if re.search(r"\b(?:http\s*)?503\b|service unavailable", text):
        return "http_503"
    if "captcha" in text:
        return "captcha"
    if "robot check" in text or "robot_check" in text:
        return "robot_check"
    if "verify" in text and "page" in text:
        return "verify_page"
    if (
        "traffic/error" in text
        or "traffic error" in text
        or "página de tráfego" in text
        or "pagina de trafego" in text
    ):
        return "traffic_error"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if any(marker in text for marker in (
        "navigation",
        "page.goto",
        "net::err_",
        "navegação",
        "navegacao",
    )):
        return "navigation_error"
    return "unknown_error"
