"""Storage routing and safe downloadable file types, shared by direct and relayed uploads."""
import os
import secrets

FILE_TYPES = {
    ".pdf": "application/pdf", ".txt": "text/plain", ".epub": "application/epub+zip",
    ".zip": "application/zip", ".mp3": "audio/mpeg", ".mp4": "video/mp4",
    ".webm": "video/webm", ".ogg": "audio/ogg", ".wav": "audio/wav",
    ".flac": "audio/flac",
}
MODES = {"od_first", "r2_first", "balanced"}


def od_ready():
    return len(os.getenv("OD_BRIDGE_KEY", "")) >= 32


def backend_order(mode, od_weight, r2_weight, od_available, r2_available, fallback=True):
    if mode not in MODES:
        raise ValueError("invalid_storage_mode")
    available = {"od": od_available, "r2": r2_available}
    if mode == "balanced":
        choices = [(name, weight) for name, weight in (("od", od_weight), ("r2", r2_weight))
                   if available[name] and weight > 0]
        if not choices:
            return []
        draw = secrets.randbelow(sum(weight for _, weight in choices))
        primary = choices[-1][0]
        for name, weight in choices:
            if draw < weight:
                primary = name
                break
            draw -= weight
    else:
        primary = "od" if mode == "od_first" else "r2"
    order = [primary]
    if fallback:
        order += ["r2" if primary == "od" else "od"]
    return [name for name in order if available[name]]
