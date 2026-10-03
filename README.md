# Video Variant Builder

Tool ghép video hàng loạt theo **preset**: chọn thư mục dự án → bấm **Bắt đầu** → ra đủ mọi biến thể
(ví dụ 10 ngôn ngữ × 12 clip = 120 video). Có giao diện web chạy ngay trên máy bạn, kèm dòng lệnh (CLI) cho người dùng nâng cao.

- Thay **nửa dưới / nửa trên / toàn khung / ô nhỏ (PiP)** của video bằng clip khác, **giữ nguyên tiếng** và **giữ dải caption**.
- Nối đúng phần thân video **theo cùng ngôn ngữ** (Arab ↔ Arab, French ↔ French…), tự hiểu `Arabic = Arab = AR`, `Por = Portuguese`…
- Thay hook 3 giây đầu, chèn clip vào giữa, chỉ nối theo nhóm… **chỉ bằng preset**, không sửa code.
- Xem trước từng khung hình, **kéo thả khung vùng thay trực tiếp trên ảnh**, xem thử 5 giây.
- Chạy song song, tạm dừng / tiếp tục, tự chạy tiếp sau khi mất điện, bỏ qua video đã có.

> Video được xử lý **hoàn toàn trên máy của bạn** — không tải lên đâu cả.

---

## 1. Cài đặt

### Cách A — Bản đóng gói (không cần cài gì)
1. Vào mục **Releases** của repo, tải file `VideoVariantBuilder-windows.zip` (hoặc `-macos.zip`).
2. Giải nén ra một thư mục (ví dụ `D:\VideoVariantBuilder`).
3. Mở `VideoVariantBuilder.exe` (macOS: `VideoVariantBuilder.app`).
   Một cửa sổ đen nhỏ hiện ra và trình duyệt tự mở giao diện. **Giữ cửa sổ đen đó mở** trong lúc dùng; đóng nó là thoát tool.

**macOS lần đầu mở:** chuột phải vào `VideoVariantBuilder.app` → **Open** → **Open** (vì ứng dụng chưa ký số với Apple).
**Windows / antivirus:** một số phần mềm diệt virus có thể chặn `ffmpeg.exe` đi kèm. Nếu bị chặn, thêm thư mục tool vào danh sách loại trừ.
**Windows SmartScreen:** bấm **More info → Run anyway**.

### Cách B — Chạy từ mã nguồn (cần Python 3.10+)
```bash
git clone https://github.com/<tài-khoản>/video-variant-builder.git
cd video-variant-builder
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -e .
python scripts/get_ffmpeg.py    # tải ffmpeg vào thư mục bin/
vvb-web                         # mở giao diện
```

---

## 2. Dùng giao diện — 4 bước

```
① NGUỒN  →  ② XEM TRƯỚC  →  ③ TUỲ CHỌN  →  ④ CHẠY
```

**Chuẩn bị thư mục dự án** (ví dụ cho preset *Thay nửa dưới + giữ caption*):
```
Dot 1/
├── Intro/     Arab.mov, French.mov, Hindi.mov …   (mỗi ngôn ngữ 1 file)
├── Source/    Arab.mov, French.mov, Hindi.mov …   (cùng tên ngôn ngữ với Intro)
├── Video/     clip01.mp4, clip02.mp4 …            (các clip mới để thay vào)
└── Outtro.mov                                     (dùng chung cho mọi video)
```

1. **Nguồn** — bấm **Chọn thư mục**, chọn `Dot 1`. Tool tự nhận Intro / Source / Video / Outtro và hiện **bảng ghép nhóm**:
   - ✓ xanh = có file; ô vàng = thiếu (chọn tay trong danh sách); ô đỏ = trùng tên (chọn 1 file).
   - Bỏ tick nhóm hoặc clip nào không muốn chạy.
2. **Xem trước** — chọn nhóm, clip, thời điểm. **Kéo khung tím** (vùng thay) và **khung cam** (vùng bảo vệ, ví dụ caption) ngay trên ảnh.
   Có thể bấm vào khung rồi dùng phím mũi tên (Shift = bước lớn, Alt = co giãn). Bấm **Xem thử 5s** để xem video ngắn.
3. **Tuỳ chọn** — chỉnh nếu cần (cách lấp clip, âm thanh, độ phân giải, chất lượng…). Rê chuột vào biểu tượng **?** để xem giải thích.
4. **Chạy** — bấm **Kiểm tra** để soát lỗi trước, rồi **Bắt đầu**. Video ra ở `Dot 1/Output/<ngôn ngữ>/…`.
   Có thể **Tạm dừng**, **Dừng**; xong sẽ có thông báo và nút **Mở Output**. Video lỗi có nút **Chạy lại video lỗi**.

**Preset:** menu **Preset** ở thanh trên để đổi loại job, lưu cấu hình đã chỉnh (`Ctrl+S`), nhân bản, xuất / nhập file `.json` để gửi máy khác.

**Mất điện / tắt máy giữa chừng:** mở lại tool, chọn lại thư mục dự án → hiện thông báo *"Phát hiện job dang dở"* → bấm **Tiếp tục job**.
Video đã xong được giữ nguyên.

### Preset có sẵn
| Preset | Làm gì |
|---|---|
| Thay nửa dưới + giữ caption | Thay nửa dưới Intro bằng clip, giữ tiếng + dải caption, nối Source cùng ngôn ngữ + Outtro |
| Thay hook 3s đầu | 3 giây đầu là clip pool, sau đó là thân video từ giây thứ 3 |
| Thay hook giữ voice | 3 giây đầu thay hình bằng clip nhưng giữ tiếng gốc |
| Thay nửa trên | Thay nửa trên Intro |
| Chèn clip vào giữa | Thân 0–5s → clip 3s → thân từ 5s (có chuyển cảnh mờ) |
| Chỉ nối theo nhóm | Intro → Source → Outtro theo ngôn ngữ, không dùng clip pool |
| PiP góc | Clip nằm trong ô nhỏ bo góc ở góc dưới phải |

Tạo preset mới: xem [docs/PRESET.md](docs/PRESET.md).

---

## 3. Dòng lệnh (CLI)

```bash
vvb run   --preset palm_bottom --project "D:/Khach A/Dot 1"
vvb run   --preset palm_bottom --intro ./Intro --source ./Source --pool ./Video --outtro ./Outtro.mp4 --out ./Output
vvb check --preset palm_bottom --project "D:/Khach A/Dot 1"        # kiểm tra, không render
vvb run   ... --dry-run | --groups arab,french | --clips clip01,clip02 | --limit 3
vvb run   ... --workers 4 --quality max --existing overwrite --codec h264_nvenc
vvb preview ... --at 1.5 -o preview.png                            # 1 khung hình
vvb resume --out ./Output                                          # chạy tiếp job dang dở
vvb presets list
```
Bản đóng gói: `VideoVariantBuilder.exe cli run --preset …` (cùng tham số).
Thứ tự ưu tiên tuỳ chọn: **dòng lệnh > preset > mặc định**.

Dùng như thư viện Python:
```python
from vvb import make_job, run_job
job = make_job("palm_bottom", project="D:/Khach A/Dot 1")
summary = run_job(job)
```

---

## 4. Kết quả đầu ra

```
Output/
├── Arab/Arab_clip01.mp4 …
├── manifest.csv / manifest.json   mỗi dòng 1 video: nhóm, clip, file nguồn, thời lượng, trạng thái, seed…
├── errors.log                     chi tiết lỗi + lệnh ffmpeg (nếu có)
├── preset.json                    bản sao preset đã dùng (để tạo lại y hệt)
└── .vvb/                          nhật ký job (để tiếp tục khi bị ngắt)
```
Video chuẩn: H.264, yuv420p, AAC stereo, `faststart` — đăng thẳng TikTok / Reels / YouTube Shorts.

---

## 5. Câu hỏi thường gặp

- **"Không tìm thấy ffmpeg"** — bản đóng gói đã có sẵn; bản mã nguồn chạy `python scripts/get_ffmpeg.py`.
- **Tên file khác nhau (Arabic / Arab / AR)** — tool tự hiểu qua bảng alias. Thêm alias riêng trong *Tuỳ chọn → Nâng cao*.
- **Video quay điện thoại bị xoay / HDR iPhone bị nhợt màu** — tool tự xoay đúng và chuyển HDR về SDR.
- **Muốn nhanh hơn** — tăng *Số video song song* (tab Chạy), hoặc chọn encoder GPU (NVIDIA/Intel/AMD/Mac) ở tab Output.
  Phần dùng chung (Source theo nhóm, Outtro) chỉ encode **1 lần** rồi dùng lại.
- **Ổ đầy** — tool kiểm tra trước khi chạy và tự tạm dừng khi ổ sắp đầy.

---

## 6. Giấy phép
Mã nguồn: MIT (xem [LICENSE](LICENSE)). ffmpeg đi kèm bản đóng gói là phần mềm riêng theo GPL —
xem `bin/FFMPEG_LICENSE.txt`, mã nguồn tại <https://ffmpeg.org/download.html>.
Font Fira (SIL OFL 1.1), icon Lucide (ISC), Alpine.js (MIT).
