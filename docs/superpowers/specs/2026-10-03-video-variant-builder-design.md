# Design — Video Variant Builder (bản Web)

- Ngày: 2026-10-03
- Trạng thái: Đã duyệt từng phần trong buổi brainstorming, chờ duyệt bản viết
- Spec gốc: `../SPEC_Tool_Video.md` (nằm **ngoài** repo vì chứa thông tin khách hàng — không commit).
  Tài liệu này mô tả các **quyết định thiết kế** và **chỗ khác so với spec gốc**. Mọi yêu cầu
  chức năng không nhắc tới ở đây giữ nguyên theo spec gốc (mục 1–14, 16–18).

---

## 0. Quyết định đã chốt

| # | Quyết định | Lý do |
|---|---|---|
| D1 | Giao diện **web local** (FastAPI + HTML/CSS/JS thuần + Alpine.js) thay cho PySide6 | Người dùng yêu cầu web Python; không cần Node; đóng gói gọn |
| D2 | Phân phối: **repo GitHub public** + bản đóng gói trên GitHub Releases; chạy trên máy người dùng, UI mở trong trình duyệt ở `127.0.0.1` | GitHub Pages không chạy được Python/ffmpeg; render local nhanh, batch lớn được |
| D3 | Không có `tool_video.py` cũ → viết logic FFmpeg mới từ spec | File không tồn tại |
| D4 | Kiểm thử bằng fixture lavfi + dữ liệu thật của khách (10 nhóm × 12 clip, nằm ngoài repo, trỏ qua `VVB_REAL_DATA`) | Có dữ liệu khách để xác nhận cuối |
| D5 | Làm **toàn bộ spec** một lần, theo thứ tự mục 15 | Người dùng chọn |
| D6 | UI áp design system từ skill **ui-ux-pro-max** (mục 4) | Yêu cầu người dùng |
| D7 | Code giấy phép MIT; ffmpeg đóng kèm bản Release là GPL, phát hành kèm LICENSE + link nguồn | Tuân thủ GPL |
| D8 | Python yêu cầu ≥ 3.10; test/đóng gói trên 3.12; dev chạy được 3.14 | PyInstaller ổn định trên 3.12 |

---

## 1. Kiến trúc

```
video-variant-builder/
├── vvb/                  LÕI – không import gì từ web/
│   ├── __init__.py       export run_job, check_job, render_preview
│   ├── __main__.py       CLI: run | check | preview | resume | presets
│   ├── defaults.py       mọi hằng số mặc định (1 chỗ)
│   ├── models.py         pydantic v2: Preset, Slot, Segment, Region, Protect, Job, Task, MediaInfo…
│   ├── preset_io.py      đọc/ghi/validate/nâng cấp schema_version, báo lỗi theo đường dẫn trường
│   ├── ffmpeg.py         tìm ffmpeg (bin/ → PATH), kiểm phiên bản ≥4.4, thử encoder, chạy có progress, kill cây process
│   ├── probe.py          ffprobe → MediaInfo; cache theo (path, size, mtime)
│   ├── scanner.py        quét slot, lọc rác, natural sort, loại thư mục Output
│   ├── matcher.py        khoá nhóm (stem/regex/prefix/suffix/subfolder), chuẩn hoá, alias, bảng ghép
│   ├── combiner.py       cartesian/zip/per_group_subset/no_pool/limit, lọc nhóm/clip, seed
│   ├── filters.py        dựng filter_complex: chuẩn hoá nền, region, fit/anchor, protect, duration_mode, audio
│   ├── renderer.py       render đoạn, cache asset chuẩn hoá, concat, kiểm tra output
│   ├── batch.py          hàng đợi, worker, tạm dừng/huỷ/resume, watchdog, journal, manifest, lock
│   ├── naming.py         template tên, làm sạch tên Windows, chống trùng
│   ├── system.py         chặn ngủ, thông báo OS, dung lượng ổ, đường dẫn dài
│   └── events.py         EventBus: sự kiện tiến trình/log dùng chung cho CLI và web
├── web/
│   ├── server.py         FastAPI app, bind 127.0.0.1, token, mở trình duyệt, khay hệ thống
│   ├── api/              fs.py, sources.py, preview.py, presets.py, jobs.py, system.py
│   ├── ws.py             WebSocket /ws: phát lại sự kiện EventBus
│   └── static/
│       ├── index.html
│       ├── css/          tokens.css, base.css, components.css, layout.css
│       ├── js/           app.js (Alpine store), api.js, ws.js, i18n.js,
│       │                 components/{folder-browser, match-table, region-editor,
│       │                 schema-form, log-view, run-bar, preset-menu, toast}.js
│       ├── vendor/       alpine.min.js, lucide icons (SVG sprite)
│       ├── fonts/        Fira Sans, Fira Code (woff2, tự host)
│       └── i18n/         vi.json, en.json
├── presets/              palm_bottom (A), hook3s (B), hook_keep_voice (C), top_half (D),
│                         insert_middle (E), concat_only (F), pip_corner (G)
├── scripts/get_ffmpeg.py
├── bin/                  ffmpeg, ffprobe (không commit)
├── tests/                unit/, integration/, web/, ui/, fixtures (sinh bằng lavfi)
├── build/                vvb.spec (PyInstaller), icon
├── .github/workflows/    test.yml, release.yml
├── docs/PRESET.md, README.md, CONTRIBUTING.md, LICENSE
└── pyproject.toml        entry points: vvb (CLI), vvb-web (server)
```

**Nguyên tắc:** lõi dùng độc lập (`from vvb import run_job`); không `shell=True`; mọi lệnh ffmpeg
ghi log dạng copy chạy tay được; không hard-code tên slot trong lõi; type hints + docstring
tiếng Việt ngắn.

### 1.1 Luồng chạy web
1. `vvb-web` (hoặc `VideoVariantBuilder.exe`) chọn cổng trống, sinh token ngẫu nhiên, mở
   `http://127.0.0.1:<port>/?t=<token>`. Token lưu vào cookie HttpOnly; mọi API/WS kiểm token
   + kiểm `Origin`/`Host` (chống DNS rebinding và trang khác gọi lén).
2. REST cho thao tác (quét, ghép, preview, preset, khởi chạy job).
3. Job chạy trong thread nền của server; sự kiện → EventBus → WebSocket. Đóng tab **không** dừng
   job; mở lại tab → `GET /api/jobs/current` + WS phát lại trạng thái.
4. Chỉ 1 job chạy tại một thời điểm trong 1 server.

### 1.2 Thay đổi so với spec gốc (mục 13) do chuyển sang web
| Spec desktop | Bản web |
|---|---|
| QThread / signal | Thread pool + EventBus + WebSocket |
| Kéo thả folder từ Explorer | Trình duyệt không lộ đường dẫn tuyệt đối → **hộp duyệt thư mục trong app** (ổ đĩa, breadcrumb, gần đây) + ô dán đường dẫn + nút hộp chọn gốc của OS (tkinter, chạy trong process server) |
| QMediaPlayer | `<video>` HTML5 |
| Hỏi khi đóng app | `beforeunload` khi có thay đổi chưa lưu; job vẫn chạy ở server; thoát server qua khay hệ thống/nút Thoát (hỏi nếu đang chạy) |
| Thông báo hệ thống | Web Notification + âm báo; dự phòng thông báo OS từ server |
| settings.json | `~/.vvb/settings.json` (job gần nhất, theme, ngôn ngữ, dự án gần đây); preset người dùng ở `~/.vvb/presets/` |

---

## 2. Lõi xử lý video

### 2.1 Pipeline một job
1. **Probe** song song mọi file (cache). MediaInfo gồm: kích thước sau xoay, rotation, fps
   (r vs avg → VFR), độ dài luồng video (fallback `-count_packets`), HDR (`color_transfer`
   smpte2084/arib-std-b67), interlaced (`field_order`), alpha (pix_fmt), SAR, audio (kênh,
   sample rate, track default), `start_time`, codec + khả năng decode.
2. **Scan → Match → Combine** → danh sách Task (mỗi Task = 1 video output).
3. **Chuẩn hoá asset tái dùng**: đoạn `asset` không phụ thuộc pool (ví dụ Source[nhóm], Outtro)
   render 1 lần → cache `~/.vvb/cache/<hash>.mkv`, hash = (path, size, mtime, tham số đoạn,
   tham số output). Giới hạn dung lượng cache (mặc định 20 GB, LRU).
4. Mỗi Task: render đoạn riêng (composite/pool) → nối → kiểm tra → `xxx.part.mp4` → đổi tên.

### 2.2 Định dạng trung gian (chống trôi tiếng – R1/R2/R3)
- Video: cùng encoder/tham số với output cuối, CFR, timebase cố định `1/(fps*1000)` → concat copy được.
- **Audio PCM s16le** trong `.mkv`, stereo, sample rate output. Không dùng AAC cho trung gian
  (AAC priming ~21ms mỗi đoạn gây lệch/bụp).
- Độ dài đoạn = N frame chính xác; audio `atrim=end=N/fps` + `apad=whole_dur` → bằng video.
- Micro-fade (mặc định 15ms) đầu/cuối audio mỗi đoạn.
- Nối: toàn `cut` → concat demuxer (`-c:v copy`, audio → AAC 1 lần, `-movflags +faststart`);
  có `fade/crossfade/fade_black` → concat filter + `xfade`/`acrossfade` (encode lại).
- Hai đoạn khác tham số (không thể xảy ra nếu đúng thiết kế, nhưng phát hiện được) → tự chuyển concat filter.

### 2.3 Filter graph
**Chuẩn hoá nền / asset:** `setpts=PTS-STARTPTS` → (`yadif` nếu interlaced) → (tonemap
`zscale+tonemap=hable` nếu HDR) → scale theo fit về W×H (mặc định cover, anchor center) →
`setsar=1` → `fps=<fps>` → `format=yuv420p`. Autorotate để mặc định của ffmpeg; kích thước tính sau xoay.
Có alpha → overlay lên nền màu cấu hình (M10). Ảnh tĩnh → `-loop 1 -t <dur>` (+ Ken Burns tuỳ chọn).

**Clip pool (overlay):**
- `clip_start`: số / `center` / `random(seed)`; `-ss` trước input; `-t` giới hạn đọc (M13).
- duration_mode: `match_base` → `-stream_loop -1` + trim; `freeze` → `tpad=stop_mode=clone`;
  `boomerang` → `split,reverse,concat` (giới hạn clip ≤ 15s, dài hơn → cảnh báo, dùng loop);
  `speed` → `setpts` hệ số kẹp [min_speed, max_speed], vượt → loop; `match_clip` → nền
  `tpad clone` + audio `apad`, hoặc cắt nền.
- Đặt vào region: scale (cover/contain/stretch) × zoom → crop theo anchor + offset → flip/rotate →
  `eq` (color_match) → contain: nền blur (`split→scale cover→boxblur`)/màu/base →
  border/radius/feather bằng mask alpha (`geq` sinh 1 lần, `alphamerge`) → opacity.
- `overlay=x:y:enable='between(t,a,b)'` cho active_time.

**Protect zones:** theo thứ tự khai báo; `from=base` → crop từ nhánh nền đã chuẩn hoá (split) rồi
overlay đúng vị trí; `from=<slot>` → nhánh slot đó; `from=<png>` → overlay ảnh alpha. Rút gọn
`{y,h}` = toàn chiều ngang.

**Toạ độ:** tỷ lệ 0–1 → pixel → làm tròn chẵn → kẹp trong khung (tràn → cắt + cảnh báo).

**Audio:** chế độ `base | overlay | mix(base_volume, overlay_volume) | mute(anullsrc)`; thiếu
audio → `anullsrc` (M2); chọn track default (M11); `aformat=channel_layouts=stereo` (mono nhân
đôi, 5.1 downmix); `aresample`; `loudnorm` 1 pass mỗi đoạn nếu bật normalize (+ tuỳ chọn 1 lần toàn video);
fade_in/out toàn video ở bước nối; nhạc nền + ducking (`sidechaincompress`) ở bước nối; Voice/<nhóm> thay audio đoạn.

**Lớp phủ thêm (8.4):** watermark PNG, chữ theo nhóm từ `texts.csv` (`drawtext`, font đóng kèm có
tiếng Việt), phụ đề `.srt` theo nhóm (`subtitles`) — áp ở bước nối (cần encode lại → tự chuyển concat filter).

### 2.4 Batch
- Hàng đợi + N worker (thread, mỗi worker 1 process ffmpeg). Gợi ý: `min(4, cpu//4)`, ≥1;
  GPU encode → 1; output ≥ 4K → giảm 1/2 (R7).
- Encoder: lúc khởi động thử encode 1 frame cho từng encoder phần cứng có trong `-encoders`;
  chỉ báo encoder chạy được. Lỗi giữa chừng → retry bằng libx264 (R4).
- Progress: `-progress pipe:1 -nostats`; watchdog không tiến triển > 120s → kill + retry (R6).
- Tạm dừng: ngừng phát task + `psutil.Process.suspend()` cả cây; Tiếp tục: `resume()`.
- Dừng: kill cây process, xoá `.part` và temp của task (O1).
- Journal `Output/.vvb/job.json` (ghi nguyên tử mỗi lần đổi trạng thái): preset đã dùng, đường dẫn,
  seed, danh sách task + trạng thái. Mở lại → phát hiện dở → hỏi Tiếp tục (O2): file đích tồn tại
  + probe hợp lệ → done; `.part` → xoá, làm lại.
- `Output/.vvb/lock` chứa PID + host; PID còn sống → cảnh báo, không chạy (O4).
- `existing`: skip / overwrite / rename. File đích bị khoá (F11) → `_2` + cảnh báo.
- Kiểm dung lượng trước và mỗi 10s trong khi chạy; thiếu → tạm dừng an toàn, báo cần thêm bao nhiêu GB (F9).
- Kiểm tra sau render (R8): kích thước, có audio, độ dài lệch ≤ 1 frame + 0.05s.
- Đầu ra kèm: `manifest.csv/json`, `errors.log` (lệnh + 30 dòng stderr cuối), thumbnail, `preset.json`.
- `max_file_size_mb`: vượt → encode lại với bitrate tính từ kích thước đích.
- Chặn ngủ: Windows `SetThreadExecutionState`, macOS `caffeinate`, Linux `systemd-inhibit` nếu có.
- Windows: `CREATE_NO_WINDOW` cho mọi subprocess (O6); đường dẫn > 260 → tiền tố `\\?\` (F4).

### 2.5 Preview
- Frame: cùng filter graph, `-ss t -frames:v 1`, scale 540p, PNG trả qua HTTP. Client debounce 300ms;
  request mới huỷ process preview cũ.
- Xem thử 5s: ultrafast, 540p, MP4 phát bằng `<video>`.
- So sánh trước/sau: render thêm frame nền gốc cùng thời điểm, thanh trượt chia đôi ở client.

### 2.6 Bảng alias bổ sung (từ dữ liệu thật)
Thêm vào mặc định: `portuguese = por`, `thai = thailand`, `urdu = ur`.

---

## 3. Preset & CLI

- Schema theo spec 18.1, `schema_version: 1`, pydantic v2 → sinh JSON Schema → dùng cho **form tự động** ở web.
- Mỗi trường có `title`, `description` (tooltip) tiếng Việt qua key i18n trong `json_schema_extra`.
- Preset không chứa đường dẫn tuyệt đối. Job = preset + đường dẫn.
- Ưu tiên: CLI > preset > mặc định.
- CLI theo spec 18.4 (`run`, `check`, `preview`, `resume`) + `presets list|show|validate`.

---

## 4. UI/UX (design system từ ui-ux-pro-max)

Kết quả skill (query "video editing production tool dashboard", density 8, motion 3, variance 4):
style **Soft UI Evolution**, bảng màu indigo, Fira Sans/Fira Code. Đã điều chỉnh:

### 4.1 Tokens
| Token | Tối (mặc định) | Sáng |
|---|---|---|
| `--bg` | `#0B0B14` | `#F5F3FF` |
| `--surface` | `#13131F` | `#FFFFFF` |
| `--surface-2` | `#1B1B2B` | `#EEF0FB` |
| `--border` | `#2A2A40` | `#E0E7FF` |
| `--text` | `#E7E7F5` | `#1E1B4B` |
| `--text-muted` | `#A3A3C2` | `#475569` |
| `--primary` | `#818CF8` (chữ `#0B0B14`) | `#4F46E5` (chữ `#FFFFFF`) |
| `--accent-gradient` | `linear-gradient(135deg,#7C3AED,#2563EB)` | như tối |
| `--success` / `--warning` / `--danger` / `--neutral` | `#34D399` / `#FBBF24` / `#F87171` / `#94A3B8` | `#047857` / `#9A4507` / `#B91C1C` / `#64748B` |
| `--text-faint` | `#8A8AAE` | `#55607A` |
| `--region` / `--protect` | `#A78BFA` / `#FB923C` | `#7C3AED` / `#EA580C` |

Mọi cặp chữ/nền ≥ 4.5:1 (kiểm bằng script trong test UI). Spacing 4/8/12/16/24/32, radius 8/12,
bóng mềm 2 lớp, motion 150–250ms chỉ `transform/opacity`, tôn trọng `prefers-reduced-motion`.
Font: Fira Sans (toàn bộ chữ), Fira Code (số, timecode, log, lệnh) — tự host, subset có tiếng Việt.
Icon: Lucide SVG, **không dùng emoji**.

### 4.2 Bố cục
```
Thanh trên: logo · Preset [▾] ● chưa lưu · Lưu · Mới · Theme · VI/EN
├ ① NGUỒN (300px) ─┬ ② XEM TRƯỚC (co giãn) ──────────┬ ③ TUỲ CHỌN (340px, thu gọn) ┤
│ Thư mục dự án    │ Khung tỉ lệ output + SVG region │ Tab: Vùng · Thời lượng · Âm   │
│ Thẻ slot         │ Nhóm▾ Clip▾ thanh thời gian      │ thanh · Output · Chạy · Nâng  │
│ Bảng ghép nhóm   │ Lớp: lưới, safe-zone, trước/sau  │ cao — form từ schema, ⓘ, ↺    │
├ ④ CHẠY: tóm tắt số video/ước tính · Kiểm tra · Bắt đầu · Tạm dừng · Dừng ┤
│ Tiến trình tổng + từng worker · Log ảo hoá + lọc · Mở Output              │
```
< 1280px: ③ thành ngăn kéo; < 1024px: ①②③ thành tab. Tối thiểu thiết kế 1100×720.

### 4.3 Hành vi chính
1. Màn hình trống: CTA lớn "Chọn thư mục dự án", dự án gần đây, trạng thái ffmpeg (+ hướng dẫn nếu thiếu).
2. Hộp duyệt thư mục: ổ đĩa, breadcrumb, gần đây, dán đường dẫn, điều khiển bàn phím đầy đủ.
3. Thẻ slot: số file, tổng thời lượng, trạng thái icon+chữ; mở danh sách chi tiết (tên, độ dài, độ phân giải, fps, audio, cảnh báo).
4. Bảng ghép: nhóm × slot, ô ✓/⚠/✕ (icon + chữ), dropdown sửa tay, checkbox chọn nhóm/clip, dòng "không dùng tới".
5. Region editor: SVG phủ ảnh preview, 8 tay nắm, kéo/co giãn, nhãn, mũi tên 1px / Shift 10px, đồng bộ 2 chiều với ô số (WCAG 2.5.7). Ảnh cũ mờ + spinner khi render frame mới.
6. Nút Bắt đầu khoá kèm lý do cụ thể.
7. Pre-flight: danh sách lỗi/cảnh báo bấm được → nhảy tới slot/file. ≥ 500 video → hộp xác nhận + ước tính.
8. Chạy: tiến trình tổng + mini bar từng worker, ETA cập nhật sau video đầu, log ảo hoá (4000+ dòng mượt), lọc Tất cả/Lỗi/Cảnh báo.
9. Xong: Notification + âm báo + bảng thống kê, "Mở Output", "Chạy lại video lỗi".
10. Preset: danh sách, tạo/nhân bản/đổi tên/xoá/xuất/nhập JSON, dấu `●` chưa lưu.

### 4.4 Chất lượng bắt buộc
Focus ring luôn hiện; icon-button có `aria-label` + tooltip; target ≥ 32px (nút chính 40px);
phím tắt `Ctrl+S`, `Ctrl+Enter`, `Space`; mọi chuỗi qua i18n; `aria-live` cho tiến trình;
trước khi giao chạy pre-delivery checklist của ui-ux-pro-max ở 1024/1440/1920 × 2 theme.

---

## 5. Kiểm thử

| Tầng | Công cụ | Nội dung |
|---|---|---|
| Unit | pytest | matcher, combiner, naming, filters (chuỗi filter + toạ độ), preset_io |
| Tích hợp | pytest + ffmpeg | fixture lavfi (spec mục 16) + toàn bộ kiểm tra tích hợp spec mục 16 |
| Web API | FastAPI TestClient | fs, sources, preview, presets, jobs, WS, từ chối thiếu token/Origin lạ |
| UI | Playwright (python) | luồng end-to-end với `--limit 2`; ảnh chụp 2 theme × 3 kích thước; kiểm contrast |
| Dữ liệu thật | `VVB_REAL_DATA` | 10×12 = 120 video; không chạy trên CI |

Marker: `unit`, `integration` (cần ffmpeg), `ui`, `real`.

---

## 6. Repo public, đóng gói, phát hành

- `.gitignore`: `*.mp4 *.mov *.mkv *.m4v *.webm *.avi`, `Output/`, `bin/*` (trừ `.gitkeep`), cache, build.
- **Không** commit video khách, spec gốc, tên app khách. Preset mẫu A đặt tên trung tính "Thay nửa dưới + giữ caption".
- `scripts/get_ffmpeg.py`: Windows gyan.dev essentials, macOS evermeet; kiểm SHA256, phiên bản ≥ 4.4, có libx264.
- PyInstaller onedir: Windows `VideoVariantBuilder.exe` (+ khay hệ thống), macOS `.app`; kèm `bin/` + LICENSE ffmpeg.
- GitHub Actions: `test.yml` (Win/macOS/Ubuntu, Python 3.10 & 3.12) mỗi push; `release.yml` khi tag `v*` → build + upload Releases.
- Tạo repo GitHub / push chỉ khi người dùng yêu cầu.
- Tài liệu: README tiếng Việt cho người không biết code (tải, chạy, Gatekeeper, antivirus, tạo preset), `docs/PRESET.md`, `CONTRIBUTING.md`.

---

## 7. Thứ tự triển khai

1. models + preset_io + preset mẫu A
2. ffmpeg, probe, scanner, matcher, combiner (+ test)
3. filters + renderer → Job A chạy đúng trên dữ liệu Palm thật
4. batch + CLI đầy đủ (dry-run, resume, manifest)
5. Dạng B–G + preset mẫu + test
6. Web khung + tokens + theme + i18n
7. Khu Nguồn + hộp duyệt thư mục + bảng ghép
8. Khu Xem trước + region editor
9. Khu Tuỳ chọn (form sinh từ schema)
10. Khu Chạy + pre-flight + WS + resume
11. Quản lý preset
12. Đóng gói + CI
13. README + PRESET.md
14. Chạy toàn bộ test + rà tiêu chí

## 8. Tiêu chí hoàn thành
Spec gốc mục 17, cộng: 120 video từ dữ liệu thật của khách ra đủ, kiểm ngẫu nhiên voice Intro giữ nguyên,
caption POV không bị che, ngôn ngữ Intro–Source khớp; UI đạt checklist ui-ux-pro-max ở cả 2 theme.
