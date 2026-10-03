"""Model dữ liệu: preset (pydantic) và các đối tượng chạy (dataclass)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import defaults as D


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------- nhóm & slot
class GroupsCfg(_M):
    key_from_slot: Optional[str] = Field(None, title="Slot xác định nhóm",
        description="Slot per_group dùng để lấy danh sách nhóm. Bỏ trống = slot per_group đầu tiên.")
    key_mode: Literal["stem", "regex", "prefix", "suffix", "subfolder"] = Field("stem",
        title="Cách lấy khoá nhóm", description="stem: tên file bỏ đuôi; regex: nhóm bắt đầu tiên; "
        "prefix/suffix: tách theo ký tự phân cách; subfolder: tên thư mục con.")
    regex: Optional[str] = Field(None, title="Regex", description="Dùng khi key_mode = regex. Lấy nhóm bắt (…) đầu tiên.")
    separator: str = Field(" - ", title="Ký tự phân cách", description="Dùng khi key_mode = prefix/suffix.")
    case_insensitive: bool = Field(True, title="Không phân biệt hoa thường")
    strip_accents: bool = Field(True, title="Bỏ dấu", description="Bỏ dấu tiếng Việt/Unicode khi so khớp.")
    strip_chars: bool = Field(True, title="Bỏ ký tự thừa", description="Bỏ khoảng trắng, - _ . ở hai đầu.")
    use_aliases: bool = Field(True, title="Dùng bảng alias", description="Arabic = Arab = AR …")
    aliases: dict[str, list[str]] = Field(default_factory=dict, title="Alias bổ sung",
        description="Thêm vào bảng alias mặc định. Khoá chuẩn -> danh sách tên khác.")
    display_name: Literal["original", "canonical"] = Field("original", title="Tên hiển thị",
        description="original: tên file gốc ở slot chính; canonical: tên chuẩn theo alias.")


class SlotCfg(_M):
    type: Literal["per_group", "shared", "pool"]
    default_dir: Optional[str] = Field(None, description="Tên thư mục mặc định trong thư mục dự án.")
    default_file: Optional[list[str]] = Field(None, description="Mẫu tên file (shared), ví dụ Outtro.*")
    required: bool = True
    recursive: bool = False
    extensions: Optional[list[str]] = None
    allow_images: bool = False
    image_duration: float = Field(3.0, gt=0)
    ken_burns: bool = Field(False, description="Ảnh tĩnh: hiệu ứng zoom nhẹ.")
    label: Optional[str] = None


class CombineCfg(_M):
    mode: Literal["cartesian", "zip", "per_group_subset", "no_pool"] = Field("cartesian",
        title="Chế độ tổ hợp", description="cartesian: mọi nhóm × mọi clip; zip: clip i đi với nhóm i; "
        "per_group_subset: mỗi nhóm K clip; no_pool: mỗi nhóm 1 video.")
    subset_k: Optional[int] = Field(None, ge=1, title="K clip mỗi nhóm")
    subset_strategy: Literal["random", "rotate"] = Field("rotate", title="Cách chọn K clip")
    seed: int = Field(42, title="Seed ngẫu nhiên", description="Cùng seed = cùng kết quả.")
    limit: Optional[int] = Field(None, ge=1, title="Giới hạn tổng số video", description="Để chạy thử.")
    pool_match_group: bool = Field(False, title="Chỉ ghép clip cùng nhóm",
        description="Clip pool có tên nhóm (Arab_clip1) chỉ ghép với nhóm đó.")


# ---------------------------------------------------------------- timeline
TimeVal = Union[float, str]  # giây, "50%", hoặc số âm = tính từ cuối


class Trim(_M):
    start: TimeVal = Field(0.0, title="Bắt đầu", description="Giây, % (ví dụ 50%) hoặc số âm = tính từ cuối.")
    end: Optional[TimeVal] = Field(None, title="Kết thúc",
        description="Bỏ trống = đến hết file. Số âm = tính từ cuối, ví dụ -0.2.")


class TimeRange(_M):
    start: float = Field(0.0, ge=0, title="Từ giây")
    end: Optional[float] = Field(None, ge=0, title="Đến giây", description="Bỏ trống = đến hết đoạn.")


class Transition(_M):
    type: Literal["cut", "fade", "crossfade", "fade_black"] = Field("cut", title="Kiểu chuyển cảnh")
    duration: float = Field(0.5, ge=0, le=5, title="Thời lượng chuyển (s)")


class XY(_M):
    x: float = Field(0, ge=-1, le=1, title="Ngang")
    y: float = Field(0, ge=-1, le=1, title="Dọc")


class Border(_M):
    width: int = Field(0, ge=0, le=100, title="Độ dày viền (px)")
    color: str = Field("#FFFFFF", title="Màu viền")
    radius: int = Field(0, ge=0, le=500, title="Bo góc (px)")


class ColorMatch(_M):
    brightness: float = Field(0.0, ge=-1, le=1, title="Độ sáng")
    contrast: float = Field(1.0, ge=0, le=3, title="Tương phản")
    saturation: float = Field(1.0, ge=0, le=3, title="Bão hoà màu")


class Region(_M):
    preset: Optional[Literal["bottom", "top", "full", "left", "right", "center_box", "pip_corner"]] = Field(
        "bottom", title="Vùng mẫu", description="Bỏ trống để dùng x, y, w, h tuỳ chỉnh.")
    split: float = Field(0.5, gt=0, lt=1, title="Điểm chia", description="Tỷ lệ chiều cao/rộng cho bottom/top/left/right.")
    corner: Literal["top_left", "top_right", "bottom_left", "bottom_right"] = Field("bottom_right", title="Góc đặt ô")
    size: float = Field(0.35, gt=0, le=1, title="Kích thước ô", description="Tỷ lệ so với chiều rộng khung.")
    margin: float = Field(0.04, ge=0, le=0.5, title="Lề", description="Khoảng cách tới mép, tỷ lệ chiều rộng khung.")
    x: Optional[float] = Field(None, ge=0, le=1)
    y: Optional[float] = Field(None, ge=0, le=1)
    w: Optional[float] = Field(None, gt=0, le=1)
    h: Optional[float] = Field(None, gt=0, le=1)
    fit: Literal["cover", "contain", "stretch"] = Field("cover", title="Cách đặt clip",
        description="cover: lấp đầy, cắt thừa; contain: vừa khít, có nền; stretch: kéo giãn.")
    anchor: Union[Literal["center", "top", "bottom", "left", "right"], XY] = Field("center", title="Neo khi cắt")
    zoom: float = Field(1.0, ge=1.0, le=4.0, title="Phóng to")
    offset: XY = Field(default_factory=XY, title="Dịch clip")
    background: str = Field("blur", title="Nền khi contain", description="blur / mã màu #hex / base")
    flip: Literal["none", "horizontal", "vertical"] = Field("none", title="Lật")
    rotate: Literal[0, 90, 180, 270] = Field(0, title="Xoay")
    border: Border = Field(default_factory=Border, title="Viền")
    feather: int = Field(0, ge=0, le=200, title="Làm mềm mép (px)")
    opacity: float = Field(1.0, ge=0, le=1, title="Độ mờ đục")
    color_match: Optional[ColorMatch] = Field(None, title="Chỉnh màu clip")


class Protect(_M):
    from_: str = Field("base", alias="from", description="base / tên slot / đường dẫn PNG")
    x: float = Field(0.0, ge=0, le=1)
    y: float = Field(0.0, ge=0, le=1)
    w: float = Field(1.0, gt=0, le=1)
    h: float = Field(0.04, gt=0, le=1)
    label: Optional[str] = None


class SegAudio(_M):
    mode: Literal["base", "overlay", "mix", "mute"] = Field("base", title="Âm thanh đoạn",
        description="base: giữ tiếng video nền (voice); overlay: tiếng clip pool; mix: trộn; mute: tắt.")
    base_volume: float = Field(1.0, ge=0, le=2, title="Âm lượng nền")
    overlay_volume: float = Field(1.0, ge=0, le=2, title="Âm lượng clip")


DurationMode = Literal["match_base", "match_base_freeze", "match_base_boomerang", "match_base_speed", "match_clip"]


class Segment(_M):
    kind: Literal["asset", "composite", "pool", "blank"]
    slot: Optional[str] = None
    base: Optional[str] = None
    overlay: str = "pool"
    region: Region = Field(default_factory=Region)
    protect: list[Protect] = Field(default_factory=list)
    active_time: Optional[TimeRange] = Field(None, title="Chỉ thay trong khoảng",
        description="Ví dụ chỉ thay 3 giây đầu. Ngoài khoảng này hiện video nền gốc.")
    duration_mode: DurationMode = Field("match_base", title="Khớp thời lượng",
        description="Cách xử lý khi clip pool dài/ngắn hơn video nền.")
    max_speed: float = Field(1.5, ge=1, le=4, title="Tốc độ tối đa", description="Cho chế độ đổi tốc độ.")
    min_speed: float = Field(0.75, gt=0, le=1, title="Tốc độ tối thiểu", description="Cho chế độ đổi tốc độ.")
    clip_start: Union[float, Literal["center", "random"]] = Field(0.0, title="Bắt đầu clip từ",
        description="Số giây, 'center' (lấy đoạn giữa) hoặc 'random' (ngẫu nhiên theo seed).")
    audio: SegAudio = Field(default_factory=SegAudio, title="Âm thanh")
    trim: Trim = Field(default_factory=Trim, title="Cắt đoạn")
    optional: bool = Field(False, title="Không bắt buộc",
        description="Nhóm thiếu file thì bỏ đoạn này thay vì báo lỗi.")
    transition_in: Transition = Field(default_factory=Transition, title="Chuyển cảnh vào")
    speed: float = Field(1.0, ge=0.5, le=2.0, title="Tốc độ phát")
    duration: Optional[float] = Field(None, gt=0, title="Thời lượng (s)", description="Cho màn trống hoặc ảnh tĩnh.")
    color: str = Field("#000000", title="Màu nền")
    image: Optional[str] = Field(None, title="Ảnh nền")
    voice_slot: Optional[str] = Field(None, title="Thay tiếng bằng slot",
        description="Slot per_group chứa audio thay thế cho đoạn này (ví dụ Voice/<nhóm>.mp3).")

    @model_validator(mode="after")
    def _check(self) -> "Segment":
        if self.kind == "asset" and not self.slot:
            raise ValueError("đoạn asset cần 'slot'")
        if self.kind == "composite" and not self.base:
            raise ValueError("đoạn composite cần 'base'")
        if self.kind == "blank" and not self.duration:
            raise ValueError("đoạn blank cần 'duration'")
        return self


# ---------------------------------------------------------------- audio / output / run
class Music(_M):
    path: str = Field("", title="File nhạc")
    volume: float = Field(0.25, ge=0, le=2, title="Âm lượng nhạc")
    ducking: bool = Field(True, title="Tự giảm nhạc khi có giọng nói")


class AudioCfg(_M):
    normalize_lufs: Optional[float] = Field(None, ge=-40, le=-5, title="Chuẩn hoá loudness (LUFS)",
        description="Bỏ trống = tắt. TikTok/Reels: -14.")
    normalize_final: bool = Field(False, title="Chuẩn hoá thêm cả video")
    micro_fade_ms: int = Field(D.MICRO_FADE_MS, ge=0, le=100, title="Micro fade (ms)",
        description="Làm mượt điểm nối, tránh tiếng bụp.")
    fade_in: float = Field(0, ge=0, le=10, title="Fade in đầu video (s)")
    fade_out: float = Field(0, ge=0, le=10, title="Fade out cuối video (s)")
    sample_rate: Literal[44100, 48000] = Field(44100, title="Sample rate")
    bitrate_k: Literal[128, 192, 256] = Field(192, title="Bitrate audio (kbps)")
    music: Optional[Music] = Field(None, title="Nhạc nền")


class Watermark(_M):
    path: str = Field("", title="File PNG")
    x: float = Field(0.04, ge=0, le=1, title="Vị trí ngang")
    y: float = Field(0.04, ge=0, le=1, title="Vị trí dọc")
    w: float = Field(0.2, gt=0, le=1, title="Độ rộng")
    opacity: float = Field(1.0, ge=0, le=1, title="Độ mờ đục")
    start: float = Field(0.0, ge=0, title="Hiện từ giây")
    end: Optional[float] = Field(None, title="Đến giây")


class TextOverlay(_M):
    csv: str = Field("", title="File texts.csv", description="Cột = nhóm (hoặc 2 cột 'group' + 'text').")
    x: float = Field(0.5, ge=0, le=1, title="Vị trí ngang")
    y: float = Field(0.1, ge=0, le=1, title="Vị trí dọc")
    size: int = Field(56, ge=8, le=400, title="Cỡ chữ")
    color: str = Field("#FFFFFF", title="Màu chữ")
    border_color: str = Field("#000000", title="Màu viền chữ")
    border_width: int = Field(3, ge=0, le=20, title="Độ dày viền chữ")
    font: Optional[str] = Field(None, title="File font (.ttf)")


class OutputCfg(_M):
    resolution: str = Field("1080x1920", title="Độ phân giải",
        description="1080x1920, 720x1280, 1080x1080, 1080x1350, 1920x1080, 2160x3840 hoặc same_as_base.")
    fps: Union[Literal[24, 25, 30, 60], Literal["same_as_base"]] = Field(30, title="FPS")
    video_codec: Literal["h264", "h265", "h264_nvenc", "hevc_nvenc", "h264_videotoolbox", "h264_qsv", "h264_amf"] = Field(
        "h264", title="Codec video", description="Encoder phần cứng tự quay về CPU nếu không có.")
    quality: Literal["fast", "high", "max", "bitrate"] = Field("high", title="Chất lượng",
        description="fast CRF 24 / high CRF 20 / max CRF 17 / bitrate cố định.")
    bitrate_mbps: float = Field(8.0, gt=0, le=200, title="Bitrate (Mbps)")
    preset_speed: Literal["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"] = Field(
        "veryfast", title="Tốc độ encode")
    container: Literal["mp4", "mov"] = Field("mp4", title="Định dạng file")
    folder_template: str = Field("{group}", title="Mẫu thư mục")
    name_template: str = Field("{group}_{clip}", title="Mẫu tên file",
        description="Biến: {group} {group_raw} {clip} {clip_index} {index} {date} {time} {preset} {w}x{h}")
    manifest: bool = Field(True, title="Ghi manifest")
    thumbnails: bool = Field(False, title="Tạo thumbnail")
    thumbnail_at: float = Field(1.0, ge=0, title="Thumbnail ở giây")
    copy_preset: bool = Field(True, title="Lưu bản sao preset")
    max_file_size_mb: Optional[float] = Field(None, gt=0, title="Dung lượng tối đa (MB)")
    hdr_to_sdr: bool = Field(True, title="Tự chuyển HDR → SDR")
    skip_black_start: bool = Field(False, title="Bỏ khung đen đầu clip pool")
    alpha_background: str = Field("#000000", title="Nền cho video có alpha")
    watermark: Optional[Watermark] = Field(None, title="Logo / watermark")
    text: Optional[TextOverlay] = Field(None, title="Chữ theo nhóm")
    subtitles_slot: Optional[str] = Field(None, title="Slot phụ đề .srt theo nhóm")

    @field_validator("resolution")
    @classmethod
    def _res(cls, v: str) -> str:
        if v == "same_as_base":
            return v
        try:
            w, h = (int(p) for p in v.lower().split("x"))
        except Exception as e:  # noqa: BLE001
            raise ValueError("độ phân giải dạng WxH, ví dụ 1080x1920") from e
        if w < 16 or h < 16 or w > 8192 or h > 8192:
            raise ValueError("độ phân giải ngoài khoảng cho phép")
        return f"{w}x{h}"


class RunCfg(_M):
    workers: Optional[int] = Field(None, ge=1, le=16, title="Số video song song",
        description="Bỏ trống = tự gợi ý theo CPU.")
    existing: Literal["skip", "overwrite", "rename"] = Field("skip", title="Khi file đã có")
    stop_on_error: bool = Field(False, title="Dừng khi gặp lỗi đầu tiên")
    retry: int = Field(1, ge=0, le=5, title="Số lần thử lại")
    temp_dir: Optional[str] = Field(None, title="Thư mục tạm")
    keep_temp: bool = Field(False, title="Giữ file tạm")
    cache_normalized: bool = Field(True, title="Cache asset đã chuẩn hoá")
    min_free_disk_gb: float = Field(2, ge=0, title="Dung lượng trống tối thiểu (GB)")
    prevent_sleep: bool = Field(True, title="Không cho máy ngủ")
    notify_done: bool = Field(True, title="Thông báo khi xong")
    log_level: Literal["info", "debug"] = Field("info", title="Mức log")
    stall_timeout: int = Field(D.STALL_TIMEOUT_S, ge=10, title="Timeout treo ffmpeg (s)")


class Preset(_M):
    schema_version: int = D.SCHEMA_VERSION
    name: str = "Preset mới"
    description: str = ""
    groups: GroupsCfg = Field(default_factory=GroupsCfg)
    slots: dict[str, SlotCfg]
    combine: CombineCfg = Field(default_factory=CombineCfg)
    timeline: list[Segment]
    audio: AudioCfg = Field(default_factory=AudioCfg)
    output: OutputCfg = Field(default_factory=OutputCfg)
    run: RunCfg = Field(default_factory=RunCfg)

    @model_validator(mode="after")
    def _refs(self) -> "Preset":
        names = set(self.slots)
        for i, s in enumerate(self.timeline):
            for ref in (s.slot, s.base, s.voice_slot):
                if ref and ref not in names:
                    raise ValueError(f"timeline[{i}] tham chiếu slot không tồn tại: '{ref}'")
            if s.overlay != "pool" and s.overlay not in names:
                raise ValueError(f"timeline[{i}].overlay không tồn tại: '{s.overlay}'")
        if not self.timeline:
            raise ValueError("timeline rỗng")
        k = self.groups.key_from_slot
        if k and (k not in names or self.slots[k].type != "per_group"):
            raise ValueError("groups.key_from_slot phải là slot per_group")
        return self

    # tiện ích
    def key_slot(self) -> Optional[str]:
        if self.groups.key_from_slot:
            return self.groups.key_from_slot
        return next((n for n, s in self.slots.items() if s.type == "per_group"), None)

    def pool_slot(self) -> Optional[str]:
        return next((n for n, s in self.slots.items() if s.type == "pool"), None)

    def uses_pool(self) -> bool:
        return self.combine.mode != "no_pool" and self.pool_slot() is not None

    def out_size(self) -> Optional[tuple[int, int]]:
        if self.output.resolution == "same_as_base":
            return None
        w, h = self.output.resolution.split("x")
        return int(w), int(h)


# ---------------------------------------------------------------- đối tượng chạy
@dataclass
class MediaInfo:
    path: Path
    width: int = 0
    height: int = 0
    rotation: int = 0
    fps: float = 0.0
    avg_fps: float = 0.0
    vfr: bool = False
    video_duration: float = 0.0
    duration: float = 0.0
    vcodec: str = ""
    pix_fmt: str = ""
    has_alpha: bool = False
    hdr: bool = False
    interlaced: bool = False
    sar: str = "1:1"
    start_time: float = 0.0
    has_video: bool = True
    has_audio: bool = False
    audio_index: Optional[int] = None
    audio_channels: int = 0
    audio_rate: int = 0
    audio_duration: float = 0.0
    is_image: bool = False
    size_bytes: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["path"] = str(self.path)
        return d


@dataclass
class TaskSpec:
    """1 video đầu ra."""
    index: int
    group: str            # khoá chuẩn
    group_display: str    # tên hiển thị (folder)
    group_raw: str        # tên file gốc
    assets: dict[str, Path]          # slot -> file (per_group + shared)
    clip: Optional[Path] = None      # file pool
    clip_index: int = 0
    seed: int = 0
    out_path: Optional[Path] = None

    @property
    def clip_name(self) -> str:
        return self.clip.stem if self.clip else ""

    @property
    def id(self) -> str:
        return f"{self.group}|{self.clip_name}"


@dataclass
class Job:
    """1 lần chạy = preset + đường dẫn thực tế."""
    preset: Preset
    paths: dict[str, str]
    out_dir: Path
    groups_filter: Optional[list[str]] = None
    clips_filter: Optional[list[str]] = None
    manual_match: dict[str, dict[str, str]] = field(default_factory=dict)  # group -> slot -> file
    dry_run: bool = False
    preset_name: str = ""
