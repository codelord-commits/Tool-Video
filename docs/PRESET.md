# Viết preset

Preset là 1 file JSON mô tả **toàn bộ cách ghép** của một loại job. Làm dạng job mới = viết preset mới, không sửa code.
Preset **không chứa đường dẫn tuyệt đối** (đường dẫn thuộc về từng lần chạy). Lưu ở `presets/` (có sẵn) hoặc
`~/.vvb/presets/` (của bạn — giao diện tự lưu vào đây).

Kiểm tra preset: `vvb presets validate <tên hoặc đường dẫn>`. Lỗi sẽ chỉ rõ trường, ví dụ `timeline.0.region.split`.

## Khung tổng quát
```json
{
  "schema_version": 1,
  "name": "Tên hiển thị",
  "description": "Mô tả ngắn",
  "groups":   { … },   // cách xác định nhóm (thường là ngôn ngữ)
  "slots":    { … },   // các nguồn đầu vào
  "combine":  { … },   // tổ hợp nhóm × clip pool
  "timeline": [ … ],   // các đoạn nối theo thứ tự
  "audio":    { … },   // âm thanh toàn video
  "output":   { … },   // định dạng, đặt tên
  "run":      { … }    // tuỳ chọn chạy
}
```
Trường nào bỏ trống sẽ dùng giá trị mặc định ghi trong bảng dưới.

---

## `slots` — nguồn đầu vào
Mỗi slot có 1 tên (tự đặt, ví dụ `intro`, `body`, `voice`) và:

| Trường | Mặc định | Ý nghĩa |
|---|---|---|
| `type` | — | `per_group` (mỗi nhóm 1 file), `shared` (1 file cho mọi video), `pool` (danh sách clip thay thế) |
| `default_dir` | — | Tên thư mục trong dự án để tự nhận (không phân biệt hoa thường) |
| `default_file` | — | Mẫu tên file cho slot `shared`, ví dụ `["Outtro.*", "Outro.*"]` |
| `required` | `true` | Thiếu thì nhóm bị bỏ (`per_group`) hoặc không chạy được (`shared`, `pool`) |
| `recursive` | `false` | Quét cả thư mục con |
| `extensions` | video thường gặp | Ví dụ `[".mp4", ".mov"]` |
| `allow_images` | `false` | Cho phép ảnh `.png .jpg .webp` (thành video theo độ dài cần dùng) |
| `ken_burns` | `false` | Ảnh tĩnh trong pool: zoom nhẹ |
| `label` | tên slot | Tên hiển thị trên giao diện |

## `groups` — xác định nhóm
| Trường | Mặc định | Ý nghĩa |
|---|---|---|
| `key_from_slot` | slot `per_group` đầu tiên | Slot quyết định danh sách nhóm |
| `key_mode` | `stem` | `stem` (tên file bỏ đuôi), `regex`, `prefix`/`suffix` (tách theo `separator`), `subfolder` |
| `regex` | — | Với `regex`: lấy nhóm bắt `(…)` đầu tiên. Ví dụ `intro_(\\w+?)_` |
| `separator` | `" - "` | Với `prefix`/`suffix` |
| `case_insensitive`, `strip_accents`, `strip_chars` | `true` | Chuẩn hoá khi so khớp |
| `use_aliases` | `true` | Dùng bảng alias có sẵn (arab = arabic = ar…, portuguese = por = pt…, thai = thailand…) |
| `aliases` | `{}` | Alias thêm: `{"arab": ["عربي"], "vietnamese": ["tieng viet"]}` |
| `display_name` | `original` | Tên thư mục output: `original` (tên file gốc) hoặc `canonical` (tên chuẩn theo alias) |

Trùng khoá (ví dụ `Arab.mp4` và `arabic.mov`) → báo lỗi, phải chọn 1 file (giao diện) — tool không tự đoán.

## `combine` — tổ hợp
| Trường | Mặc định | Ý nghĩa |
|---|---|---|
| `mode` | `cartesian` | `cartesian` (mọi nhóm × mọi clip), `zip` (clip i ↔ nhóm i), `per_group_subset` (mỗi nhóm K clip), `no_pool` |
| `subset_k`, `subset_strategy` | —, `rotate` | Cho `per_group_subset`; `random` dùng `seed` |
| `seed` | `42` | Cùng seed = cùng kết quả (ghi vào manifest) |
| `limit` | — | Giới hạn tổng số video (chạy thử) |
| `pool_match_group` | `false` | Clip có tên nhóm (`Arab_clip1.mp4`) chỉ đi với nhóm đó |

---

## `timeline` — các đoạn
Mỗi đoạn có `kind`:

| `kind` | Dùng khi | Trường chính |
|---|---|---|
| `asset` | Dùng nguyên 1 file của slot | `slot` |
| `composite` | Nền + clip đặt vào 1 vùng | `base`, `overlay` (`pool` hoặc tên slot), `region`, `protect` |
| `pool` | Clip pool làm 1 đoạn riêng | — |
| `blank` | Màn hình màu / ảnh tĩnh | `duration`, `color` hoặc `image` |

Trường chung cho mọi đoạn:

| Trường | Mặc định | Ý nghĩa |
|---|---|---|
| `trim` | cả file | `{"start": 3}`, `{"start": 0, "end": 5}`, `{"end": -0.2}` (âm = tính từ cuối), `"50%"` |
| `speed` | `1.0` | 0.5–2.0 |
| `optional` | `false` | Nhóm thiếu file → bỏ đoạn này (không bỏ cả nhóm) |
| `transition_in` | `cut` | `{"type": "fade" \| "crossfade" \| "fade_black", "duration": 0.5}` |
| `audio` | `{"mode": "base"}` | `base`, `overlay`, `mix` (+ `base_volume`, `overlay_volume`), `mute` |
| `voice_slot` | — | Thay tiếng của đoạn bằng file của slot này (ví dụ thư mục `Voice/<nhóm>.mp3`) |
| `region.fit/anchor/zoom/…` | | Với `asset`/`pool`: cách đưa video vào khung output |

Riêng `composite`:

| Trường | Mặc định | Ý nghĩa |
|---|---|---|
| `active_time` | — | Chỉ thay trong khoảng `{"start": 0, "end": 3}`; ngoài khoảng hiện nền gốc |
| `duration_mode` | `match_base` | Clip ngắn hơn nền: `match_base` (lặp), `match_base_freeze` (đứng hình), `match_base_boomerang` (xuôi–ngược), `match_base_speed` (đổi tốc độ trong `min_speed`–`max_speed`); `match_clip` (theo độ dài clip) |
| `clip_start` | `0` | Số giây, `"center"` hoặc `"random"` |

### `region` — vùng thay
| Trường | Mặc định | Ý nghĩa |
|---|---|---|
| `preset` | `bottom` | `bottom`, `top`, `left`, `right` (dùng `split`), `full`, `center_box`, `pip_corner` (dùng `size`, `corner`, `margin`). `null` = tuỳ chỉnh `x, y, w, h` |
| `split` | `0.5` | Điểm chia (tỷ lệ chiều cao/rộng) |
| `x, y, w, h` | — | Tỷ lệ 0–1 của khung output (không dùng pixel ⇒ đổi độ phân giải không vỡ preset) |
| `fit` | `cover` | `cover` (lấp đầy, cắt thừa), `contain` (vừa khít, có nền), `stretch` |
| `anchor` | `center` | Khi cover bị cắt: `center/top/bottom/left/right` hoặc `{"x": 0.5, "y": 0.2}` |
| `zoom`, `offset` | `1`, `{0,0}` | Phóng to thêm, dịch clip trong vùng |
| `background` | `blur` | Khi `contain`: `blur`, mã màu `#000000`, `base` (lộ nền gốc) |
| `flip`, `rotate` | `none`, `0` | Lật gương; xoay 0/90/180/270 |
| `border` | không | `{"width": 6, "color": "#FFFFFF", "radius": 24}` — cho PiP |
| `feather`, `opacity` | `0`, `1` | Làm mềm mép (px), độ mờ đục |
| `color_match` | — | `{"brightness": 0, "contrast": 1, "saturation": 1}` |

Toạ độ sau quy đổi luôn là **số chẵn** và được kẹp trong khung (tràn ra ngoài sẽ bị cắt và có cảnh báo).

### `protect` — vùng bảo vệ (phủ lên trên cùng)
```json
"protect": [ { "from": "base", "x": 0, "y": 0.48, "w": 1, "h": 0.065, "label": "Caption" } ]
```
`from`: `base` (lấy lại từ video nền gốc), tên slot khác, hoặc đường dẫn PNG có nền trong suốt (logo, khung).
Thứ tự lớp: nền → clip → các vùng bảo vệ theo thứ tự khai báo.

---

## `audio` — toàn video
| Trường | Mặc định | Ý nghĩa |
|---|---|---|
| `normalize_lufs` | — | Chuẩn hoá loudness từng đoạn, ví dụ `-14` (TikTok/Reels) |
| `normalize_final` | `false` | Chuẩn hoá thêm 1 lần cho cả video |
| `micro_fade_ms` | `15` | Fade rất ngắn ở mỗi điểm nối, chống tiếng "bụp" |
| `fade_in`, `fade_out` | `0` | Giây, ở đầu/cuối video |
| `sample_rate`, `bitrate_k` | `44100`, `192` | |
| `music` | — | `{"path": "...", "volume": 0.25, "ducking": true}` — nhạc nền, tự giảm khi có giọng |

## `output`
| Trường | Mặc định | Ý nghĩa |
|---|---|---|
| `resolution` | `1080x1920` | Hoặc `720x1280`, `1080x1080`, `1080x1350`, `1920x1080`, `2160x3840`, `same_as_base` |
| `fps` | `30` | `24/25/30/60/same_as_base` |
| `video_codec` | `h264` | `h265`, `h264_nvenc`, `hevc_nvenc`, `h264_videotoolbox`, `h264_qsv`, `h264_amf` (tự về CPU nếu máy không có) |
| `quality` | `high` | `fast` (CRF 24), `high` (CRF 20), `max` (CRF 17), `bitrate` (+ `bitrate_mbps`) |
| `preset_speed` | `veryfast` | `ultrafast` … `slow` |
| `container` | `mp4` | `mov` |
| `folder_template`, `name_template` | `{group}`, `{group}_{clip}` | Biến: `{group} {group_raw} {clip} {clip_index} {index} {date} {time} {preset} {w} {h}` |
| `manifest`, `thumbnails`, `copy_preset` | `true`, `false`, `true` | File kèm theo |
| `max_file_size_mb` | — | Vượt thì encode lại với bitrate thấp hơn |
| `hdr_to_sdr` | `true` | Tự tonemap nguồn HDR/HLG |
| `skip_black_start` | `false` | Bỏ khung đen đầu clip pool |
| `watermark` | — | `{"path": "logo.png", "x": 0.04, "y": 0.04, "w": 0.2, "opacity": 1}` |
| `text` | — | `{"csv": "texts.csv", "y": 0.1, "size": 56}` — chữ theo nhóm (cột = nhóm hoặc `group,text`) |
| `subtitles_slot` | — | Slot `per_group` chứa `.srt` để burn-in |

## `run`
`workers` (bỏ trống = tự gợi ý), `existing` (`skip`/`overwrite`/`rename`), `stop_on_error`, `retry` (lần thử lại dùng CPU),
`temp_dir`, `keep_temp`, `cache_normalized`, `min_free_disk_gb`, `prevent_sleep`, `notify_done`, `log_level`, `stall_timeout`.

---

## Ví dụ

**Thay hook 3 giây đầu**
```json
{
  "name": "Thay hook 3s",
  "slots": {
    "body": { "type": "per_group", "default_dir": "Body" },
    "pool": { "type": "pool", "default_dir": "Hook" }
  },
  "timeline": [
    { "kind": "pool", "trim": { "start": 0, "end": 3 }, "audio": { "mode": "overlay" } },
    { "kind": "asset", "slot": "body", "trim": { "start": 3 } }
  ]
}
```

**Thay hook nhưng giữ voice gốc**
```json
{ "kind": "composite", "base": "body", "overlay": "pool",
  "region": { "preset": "full" }, "active_time": { "start": 0, "end": 3 }, "audio": { "mode": "base" } }
```

**Thay audio theo nhóm bằng thư mục Voice/**
```json
"slots": { "intro": {"type": "per_group", "default_dir": "Intro"},
           "voice": {"type": "per_group", "default_dir": "Voice", "extensions": [".mp3", ".m4a", ".wav"], "required": false}, … },
"timeline": [ { "kind": "asset", "slot": "intro", "voice_slot": "voice" }, … ]
```
