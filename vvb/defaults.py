"""Hằng số mặc định dùng chung cho toàn bộ lõi."""
from __future__ import annotations

from pathlib import Path

SCHEMA_VERSION = 1

VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")

# File rác / đang tải dở bị bỏ qua khi quét
JUNK_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
JUNK_PREFIXES = (".", "~$", "._")
PARTIAL_SUFFIXES = (".part", ".crdownload", ".download", ".tmp")

# Alias nhóm mặc định: khoá chuẩn -> các tên khác
DEFAULT_ALIASES: dict[str, list[str]] = {
    "arab": ["arabic", "ar", "ara", "a rap", "arap"],
    "french": ["fr", "fra", "francais"],
    "hindi": ["hi", "hin"],
    "english": ["en", "eng"],
    "spanish": ["es", "esp", "espanol"],
    "portuguese": ["pt", "ptbr", "brazil", "por", "portugues"],
    "indonesian": ["id", "indo"],
    "vietnamese": ["vi", "vn", "viet"],
    "thai": ["th", "thailand"],
    "japanese": ["ja", "jp"],
    "korean": ["ko", "kr"],
    "german": ["de", "deutsch"],
    "italian": ["it", "ita"],
    "russian": ["ru", "rus"],
    "turkish": ["tr", "tur"],
    "urdu": ["ur", "urd"],
}

RESOLUTIONS = {
    "1080x1920": (1080, 1920),
    "720x1280": (720, 1280),
    "1080x1080": (1080, 1080),
    "1080x1350": (1080, 1350),
    "1920x1080": (1920, 1080),
    "2160x3840": (2160, 3840),
}

QUALITY_CRF = {"fast": 24, "high": 20, "max": 17}

# Encoder phần cứng -> tham số chất lượng tương ứng
HW_ENCODERS = ("h264_nvenc", "hevc_nvenc", "h264_videotoolbox", "h264_qsv", "h264_amf")

MIN_FFMPEG_VERSION = (4, 4)
STALL_TIMEOUT_S = 120
MICRO_FADE_MS = 15
PREVIEW_HEIGHT = 540
CACHE_LIMIT_GB = 20

USER_DIR = Path.home() / ".vvb"
CACHE_DIR = USER_DIR / "cache"
USER_PRESET_DIR = USER_DIR / "presets"
SETTINGS_FILE = USER_DIR / "settings.json"

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILTIN_PRESET_DIR = REPO_ROOT / "presets"
