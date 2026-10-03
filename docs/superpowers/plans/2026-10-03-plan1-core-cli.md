# Plan 1 — Lõi `vvb` + CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lõi xử lý video tổng quát điều khiển bằng preset + CLI, chạy đúng Job A trên dữ liệu thật và các dạng B–G.

**Architecture:** Package `vvb` thuần Python, gọi ffmpeg/ffprobe qua subprocess (list args). Pydantic v2 cho model preset. Mỗi Task render đoạn riêng → concat với asset chuẩn hoá đã cache. EventBus phát sự kiện cho CLI (và web ở Plan 2).

**Tech Stack:** Python ≥3.10, pydantic 2, psutil, pytest, ffmpeg ≥4.4 (bin/ hoặc PATH).

**Spec:** `docs/superpowers/specs/2026-10-03-video-variant-builder-design.md` + spec gốc `../SPEC_Tool_Video.md`.

## Global Constraints
- Không `shell=True`; mọi subprocess Windows dùng `CREATE_NO_WINDOW`.
- Không hard-code tên slot (`intro/source/outtro`) trong `vvb/` — chỉ trong `presets/`.
- Mọi hằng số mặc định ở `vvb/defaults.py`.
- Toạ độ region lưu tỷ lệ 0–1; pixel luôn số chẵn.
- Trung gian: video cùng tham số output, audio `pcm_s16le` stereo trong `.mkv`; output `yuv420p`, `+faststart`.
- Độ dài đoạn = số frame nguyên; audio = video chính xác.
- Docstring tiếng Việt ngắn, type hints.
- Không commit video. Dữ liệu thật qua biến môi trường `VVB_REAL_DATA`.

## File map
| File | Trách nhiệm |
|---|---|
| `vvb/defaults.py` | hằng số, alias mặc định, extensions, resolution presets, CRF |
| `vvb/models.py` | pydantic models Preset/… + Job, Task, MediaInfo (dataclass) |
| `vvb/preset_io.py` | `load_preset(path_or_name)`, `save_preset`, `validate_preset_dict`, `upgrade`, `list_builtin` |
| `vvb/events.py` | `EventBus` (subscribe/emit, thread-safe) + `Event` |
| `vvb/ffmpeg.py` | `find_ffmpeg()`, `FFmpegInfo`, `run_ffmpeg(args, on_progress, cancel)`, `kill_tree`, `available_encoders()` |
| `vvb/probe.py` | `probe(path) -> MediaInfo` (cache) |
| `vvb/scanner.py` | `scan_slot(slot_cfg, path, exclude) -> ScanResult`, `resolve_project(preset, dir) -> dict[slot,str]` |
| `vvb/matcher.py` | `normalize_key`, `extract_key`, `build_match(preset, scans) -> MatchResult` |
| `vvb/combiner.py` | `combine(preset, match, pool, filters) -> list[TaskSpec]` |
| `vvb/naming.py` | `render_template`, `sanitize_filename`, `unique_path` |
| `vvb/geometry.py` | region preset → rect, even rounding, clamp, fit/anchor math |
| `vvb/filters.py` | dựng graph cho từng kind đoạn → `SegmentCmd(args, duration)` |
| `vvb/renderer.py` | `render_segment`, `normalize_asset` (cache), `concat`, `verify_output`, `render_task` |
| `vvb/batch.py` | `BatchRunner` (queue, workers, pause/resume/cancel, journal, lock, manifest) |
| `vvb/system.py` | prevent sleep, free disk, notify, long path |
| `vvb/api.py` | `check_job`, `run_job`, `render_preview` (mặt tiền cho CLI/web) |
| `vvb/__main__.py` | CLI argparse |
| `presets/*.json` | A–G |
| `tests/conftest.py` | fixture media lavfi (cache `tests/fixtures/_generated`) |

## Tasks

### Task 1: Khung project + defaults + models + preset_io + preset A
- Tạo `pyproject.toml` (deps: pydantic>=2.6, psutil; extras dev: pytest; web: fastapi, uvicorn), `vvb/__init__.py`.
- Models theo spec 18.1, field `from` dùng alias `from_`. Validator: split∈(0,1), xywh∈[0,1], speed∈[0.5,2], rotate∈{0,90,180,270}.
- `preset_io.load_preset("palm_bottom")` tìm trong `presets/` rồi `~/.vvb/presets/`; lỗi → `PresetError` liệt kê `loc` dạng `timeline.0.region.split`.
- `upgrade(d)`: thiếu `schema_version` → coi là 1, điền mặc định.
- **Tests** `tests/unit/test_preset_io.py`: nạp preset A; preset thiếu trường → mặc định; `split=1.5` → PresetError có `timeline.0.region.split`; round-trip save/load bằng nhau; preset B rút gọn (spec 18.2) nạp được.

### Task 2: ffmpeg + probe + fixtures
- `find_ffmpeg()` ưu tiên `<repo>/bin`, `sys._MEIPASS/bin`, env `VVB_FFMPEG`, PATH; kiểm version ≥4.4, có libx264.
- `run_ffmpeg`: Popen list, `-progress pipe:1 -nostats`, đọc `out_time_us`, watchdog stall, cancel event, trả `FFResult(returncode, stderr_tail, cmd)`.
- `probe`: ffprobe JSON; rotation từ `side_data_list`/`tags.rotate`; width/height sau xoay; `video_duration` = stream duration → fallback `-count_packets` nb_read_packets/fps → fallback format duration; vfr nếu |r−avg|>0.01·r; hdr nếu color_transfer ∈ {smpte2084, arib-std-b67}; interlaced nếu field_order ∉ {progressive, unknown, None}; has_alpha theo pix_fmt; audio stream default.
- Fixture lavfi: `basic_1080x1920_5s` (testsrc2+sine), `no_audio`, `rotated90` (metadata rotate), `vfr`, `odd_1079x1919`, `mono_48k`, `landscape_1920x1080`, `short_0_3s`, `corrupt.mp4` (bytes rác), `tên có dấu 'nháy'.mp4`.
- **Tests**: probe từng fixture đúng thuộc tính; file hỏng → `ProbeError`.

### Task 3: scanner + matcher + combiner + naming
- Scanner theo spec 4.2; natural sort; loại output dir; `resolve_project` khớp `default_dir`/`default_file` không phân biệt hoa thường + alias tên outtro.
- Matcher: chế độ stem/regex/prefix/suffix/subfolder; chuẩn hoá NFKD, lower, strip `-_. `; alias map; trùng khoá → `conflicts`; thiếu slot bắt buộc → nhóm bị loại + warning; thừa → `unused`.
- Combiner: cartesian, zip, per_group_subset (random seed / rotate), no_pool, limit, filter groups/clips, pool_match_group.
- Naming: biến spec 11.2, sanitize Windows, ≤120 ký tự, tên cấm, `unique_path`.
- **Tests**: ví dụ dữ liệu Palm (Arab/Por/Thailand/Urdu…), `Arab.mp4`+`arabic.mov` → conflict, 10×12=120 tasks, zip lệch, subset không trùng clip trong nhóm, seed tái tạo, sanitize `CON`, `a:b?.mp4`.

### Task 4: geometry + filters + renderer → Job A
- geometry: `region_rect(region, W, H) -> Rect` (even, clamp, warnings); `fit_chain(src_w, src_h, rect, fit, anchor, zoom, offset)` → chuỗi filter scale/crop/pad.
- filters: `build_asset_segment`, `build_composite_segment`, `build_pool_segment`, `build_blank_segment` → args ffmpeg đầy đủ ra file `.mkv` trung gian.
- renderer: `normalize_asset` cache theo hash; `concat(parts, out, cfg)` (demuxer copy+AAC hoặc filter xfade); `verify_output`.
- **Tests unit**: rect bottom split 0.5 trên 1080×1920 = (0,960,1080,960); số lẻ làm chẵn; clamp. **Tích hợp**: Job A trên fixture: output 1080×1920, có audio, độ dài = intro+source+outtro ±(1/fps+0.05); pixel nửa trên ≈ nền; caption band ≈ nền; nửa dưới khác nền.
- **Real** (`VVB_REAL_DATA`): 1 nhóm × 1 clip.

### Task 5: batch + api + CLI
- BatchRunner: workers, existing skip/overwrite/rename, retry (CPU encoder), stop_on_error, pause/resume (psutil suspend), cancel (kill tree, xoá .part), journal + resume, lock, manifest csv/json, errors.log, thumbnails, copy preset, disk check, prevent sleep.
- CLI: `run|check|preview|resume|presets` theo spec 18.4.
- **Tests**: chạy 2 lần → lần 2 skip hết; xoá 1 output → làm lại 1; 1 file hỏng → còn lại ra + errors.log; cancel giữa chừng → không còn .part/process; dry-run không tạo file.

### Task 6: Dạng B–G + preset
- Preset B (pool trim 0–3 → body từ 3), C (composite full active_time 0–3), D (top), E (body 0–X → pool → body từ X: cần `trim` trên asset theo nhóm), F (no_pool concat), G (pip_corner border radius).
- Transitions fade/crossfade/fade_black; duration modes freeze/boomerang/speed/match_clip; audio overlay/mix/mute; blank.
- **Tests tích hợp** cho mỗi preset: chạy với fixture, kiểm độ dài + kích thước + audio.
