# Đóng góp

## Môi trường
```bash
python -m venv .venv && .venv\Scripts\activate      # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
python scripts/get_ffmpeg.py
python -m playwright install chromium               # cho test UI
vvb-web --token dev --no-browser                    # mở http://127.0.0.1:8765/?t=dev
```

## Cấu trúc
| Thư mục | Vai trò |
|---|---|
| `vvb/` | Lõi — **không import gì từ `web/`**. models, preset_io, scanner, matcher, combiner, filters, renderer, batch, plan, CLI |
| `web/` | FastAPI (chỉ nghe 127.0.0.1, token + kiểm Host/Origin) + giao diện tĩnh `web/static` (Alpine.js, không có bước build) |
| `presets/` | Preset mẫu A–G |
| `tests/` | `unit/`, `integration/` (cần ffmpeg), `web/`, `ui/` (Playwright) — media giả lập sinh bằng `ffmpeg -f lavfi` |
| `docs/` | `PRESET.md`, thiết kế và kế hoạch triển khai |

## Nguyên tắc
- Không `shell=True`; mọi subprocess Windows dùng `CREATE_NO_WINDOW`; lệnh ffmpeg ghi ra log để chạy tay được.
- Không hard-code tên slot (`intro`, `source`…) trong lõi — chỉ trong preset.
- Hằng số mặc định gom ở `vvb/defaults.py`. Docstring tiếng Việt ngắn, type hints.
- Giao diện: dùng token màu trong `web/static/css/tokens.css` (không mã hex trực tiếp), mọi chuỗi qua `web/static/i18n/*.json`,
  icon Lucide (không emoji), tương phản ≥ 4.5:1, focus ring luôn hiện.
- **Không commit video thật của khách** (`.gitignore` đã chặn các đuôi video).

## Test
```bash
python -m pytest -q                 # tất cả
python -m pytest -q -m "not ui"     # bỏ test trình duyệt
VVB_REAL_DATA="D:/du_an_that" python -m pytest -q -m real
```

## Phát hành
Gắn tag `vX.Y.Z` → GitHub Actions build bản Windows + macOS và đưa lên Releases.
