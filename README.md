# Công cụ tạo & xử lý video

Gồm ba phần:

- **Tạo** ảnh/video bằng AI qua [TopView](https://www.topview.ai) — thư mục `topview/`.
- **Tự động hoá** [Google Flow](https://flow.google.com) trên trình duyệt của bạn —
  thư mục `flow/`, gửi prompt hàng loạt thay vì ngồi bấm từng cái.
- **Dựng** video bằng [ffmpeg](https://ffmpeg.org/) — các script `.sh` ghép nối,
  chuyển cảnh, nhạc nền, phụ đề.

Ba phần nối thẳng được với nhau: tạo từng cảnh bằng AI rồi dựng thành video hoàn chỉnh.

## Yêu cầu

Cài `ffmpeg` (bao gồm cả `ffprobe`):

```bash
sudo apt-get update && sudo apt-get install -y ffmpeg
```

---

# Phần 1 — Tạo ảnh & video bằng AI (`topview/`)

Module gọi API TopView để sinh ảnh và video. Viết bằng JavaScript thuần,
**không phụ thuộc thư viện ngoài** (dùng `fetch` có sẵn của Node 18+), nên chép
nguyên thư mục `topview/` vào app nào cũng chạy: Node, Electron, Next.js...

### Chuẩn bị

```bash
cp .env.example .env      # rồi điền TOPVIEW_API_KEY
export TOPVIEW_API_KEY="khoá-của-bạn"
```

Lấy API key tại <https://www.topview.ai/api-settings>.

> **Cần đối chiếu một lần:** trang tài liệu `docs.topview.ai` chặn truy cập tự
> động, nên địa chỉ endpoint và tên header xác thực trong `topview/config.js`
> đặt theo mô tả API công khai và **chưa được kiểm chứng với API thật**. Mở
> `topview/config.js`, so với tài liệu trong tài khoản của bạn và sửa lại nếu
> khác — mọi thứ phụ thuộc nhà cung cấp đều gom trong đúng file đó.

### Dùng từ dòng lệnh

```bash
# Tạo ảnh
node topview/cli.js anh "một ly cà phê trên bàn gỗ" -o anh.png

# Tạo video từ mô tả
node topview/cli.js video "quảng cáo cà phê 10 giây" -o video.mp4

# Tạo video từ ảnh có sẵn
node topview/cli.js video "sản phẩm xoay tròn" --anh https://.../a.png -o v.mp4
```

| Tuỳ chọn | Ý nghĩa |
|----------|---------|
| `-o, --out FILE` | Tên file kết quả (bắt buộc). |
| `-n, --so-luong N` | Số ảnh cần tạo (mặc định 1). |
| `-k, --khung TỈ_LỆ` | Tỉ lệ khung: `1:1`, `16:9`, `9:16`... |
| `-d, --thoi-luong N` | Độ dài video mong muốn, giây. |
| `--anh A,B` | Danh sách URL ảnh đầu vào để dựng video. |

### Dùng trong code app

```js
const { TopViewClient } = require('./topview/client');

const tv = new TopViewClient({
  apiKey: process.env.TOPVIEW_API_KEY,
  onProgress: (e) => console.log(e.phase, e.progress ?? ''),
});

const anh = await tv.generateImage({ prompt: 'ly cà phê', aspectRatio: '1:1' });
await tv.downloadTo(anh.url, 'anh.png');

const video = await tv.generateVideo({ prompt: 'quảng cáo 10 giây', duration: 10 });
await tv.downloadTo(video.url, 'video.mp4');
```

Module tự lo phần khó: gửi tác vụ → hỏi trạng thái định kỳ đến khi xong →
tải file về. Có sẵn thử lại khi lỗi mạng/429/5xx, giới hạn thời gian chờ,
và lỗi `TopViewError` kèm `taskId` để tra cứu.

### Kiểm thử không tốn credit

```bash
node topview/test-mock.js
```

Chạy client với server giả lập, kiểm tra 12 tình huống (chờ tác vụ, tải file,
hết credit, tác vụ lỗi, thiếu key, quá thời gian chờ). Không gọi API thật nên
không mất credit và không cần API key.

---

# Phần 1b — Tự động hoá Google Flow (`flow/`)

Gắn vào **cửa sổ Chrome bạn đã tự đăng nhập**, rồi thao tác trên
[Google Flow](https://flow.google.com) đúng như khi bạn ngồi bấm: điền prompt, chọn
thiết lập đầu ra, bấm nút tạo, theo dõi tới khi xong. Hợp khi cần gửi **nhiều prompt
liên tiếp** mà không muốn ngồi canh.

| File | Vai trò |
|------|---------|
| `flow/flow_e2e_tool.py` | **Thư viện một file.** Toàn bộ phần việc thật nằm ở đây, bày ra dưới dạng hàm. Chép đúng file này vào project nào cũng chạy — phụ thuộc duy nhất là `playwright`. |
| `flow/flow_automation.py` | Giao diện dòng lệnh mỏng, gọi lại thư viện trên. Dùng khi không muốn viết code. |
| `flow/test_mock.py` | Kiểm thử với trình duyệt giả lập. |

> Script **không** đăng nhập hộ, **không** đọc hay lưu mật khẩu, **không** vượt qua
> bước xác thực nào. Bạn tự đăng nhập trước; nó chỉ dùng lại phiên đang mở sẵn.
> Dùng cho tài khoản của chính bạn và theo điều khoản sử dụng của Google.

### Chuẩn bị

```bash
pip install -r flow/requirements.txt
playwright install chromium

# Mở Chrome kèm cổng gỡ lỗi, dùng profile RIÊNG, rồi TỰ ĐĂNG NHẬP Google trong đó:
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.config/chrome-flow"
```

> Chrome 136 trở lên **chặn cổng gỡ lỗi trên profile mặc định**, nên bắt buộc phải
> có `--user-data-dir` riêng như trên. Đăng nhập một lần, profile đó nhớ luôn.

### Dùng trong code app

Chép `flow/flow_e2e_tool.py` vào project của bạn rồi import thẳng:

```python
from flow_e2e_tool import run_flow_batch

jobs = run_flow_batch(
    ["biển đêm, sóng vỗ", "rừng thông buổi sớm"],
    project="abc123",
    resolution="720p",
)
for job in jobs:
    print(job.status, job.task_id, job.media_urls)
```

Cần chen thao tác của mình vào giữa thì đi từng bước:

```python
from flow_e2e_tool import (
    flow_session, open_project, apply_output_settings,
    submit_prompt, wait_for_job, save_jobs,
)

with flow_session(project="abc123") as session:
    open_project(session)
    apply_output_settings(session, {"resolution": "720p"})

    job = submit_prompt(session, "biển đêm, sóng vỗ")   # trả về ngay
    wait_for_job(session, job)                          # chờ tới khi xong

    save_jobs([job], "jobs_history.json")
```

| Nhóm | Hàm |
|------|-----|
| Kết nối | `connect_browser`, `close_session`, `flow_session` |
| Điều hướng | `open_project`, `wait_until_ready` |
| Thiết lập | `apply_output_settings` |
| Sinh video | `submit_prompt`, `wait_for_job`, `generate`, `generate_batch`, `run_flow_batch` |
| Phiên đăng nhập | `capture_session_state`, `verify_media_url` |
| Lịch sử | `save_jobs`, `load_jobs` |
| Tìm phần tử | `find_prompt_input`, `find_submit_button`, `fill_prompt`, `click_submit` |

Mọi tham số của `FlowConfig` đều truyền lẻ được vào `flow_session(...)`,
`connect_browser(...)` và `run_flow_batch(...)` — ví dụ `cdp_url=`, `duration=`,
`generation_timeout_s=`, `dry_run=True`. Sai tên tham số thì báo lỗi kèm danh sách
tên hợp lệ.

### Dùng từ dòng lệnh

```bash
# Một prompt
python3 flow/flow_automation.py --project abc123 --prompt "biển đêm, sóng vỗ"

# Cả loạt, lấy từ file (mỗi dòng một prompt)
python3 flow/flow_automation.py --project abc123 --prompts-file canh.txt \
    --resolution 720p --duration 8

# Thử trước mà KHÔNG bấm nút tạo — kiểm tra script bám đúng giao diện, không tốn credit
python3 flow/flow_automation.py --project abc123 --prompt "thử" --dry-run
```

`--project` nhận id trần hoặc cả URL `https://flow.google.com/project/...`. Bỏ trống
thì script dùng luôn tab Flow đang mở.

| Tuỳ chọn | Ý nghĩa |
|----------|---------|
| `--prompt TEXT` | Nội dung cần tạo. Lặp lại để gửi nhiều prompt. |
| `--prompts-file FILE` | File `.txt` (mỗi dòng một prompt, `#` là ghi chú, `---` tách prompt nhiều dòng) hoặc `.json`. |
| `--resolution`, `--duration`, `--model`, `--outputs`, `--aspect` | Thiết lập đầu ra. Bỏ trống = giữ nguyên thiết lập đang có trên giao diện. |
| `--timeout GIÂY` | Chờ tối đa mỗi tác vụ (mặc định 900). |
| `--delay GIÂY` | Nghỉ giữa hai prompt (mặc định 5). |
| `--history FILE` | File lịch sử (mặc định `jobs_history.json`). |
| `--dry-run` | Làm mọi bước trừ bấm nút tạo. |
| `--cdp-url` / `--user-data-dir` | Hai cách nối trình duyệt (xem dưới). |
| `--verify-media` | Thử mở link kết quả bằng chính phiên đăng nhập để kiểm tra. |

Xem đầy đủ bằng `python3 flow/flow_automation.py --help`.

### Hai cách nối vào trình duyệt

| Cách | Khi nào dùng |
|------|--------------|
| **CDP** (mặc định) | Chrome đã mở sẵn kèm `--remote-debugging-port=9222`. Script gắn vào cửa sổ đang chạy, **không** tắt trình duyệt của bạn khi xong. |
| **Profile có sẵn** | Thêm `--user-data-dir ~/.config/chrome-flow`. Dùng khi không mở được cổng CDP — script tự mở trình duyệt bằng profile đó. |

### Kết quả ghi ở đâu

Mỗi prompt được ghi ngay vào `jobs_history.json` (ghi sau **từng** prompt, nên
lỡ dừng giữa chừng vẫn còn dữ liệu):

```json
{
  "index": 1,
  "prompt": "biển đêm, sóng vỗ",
  "status": "done",
  "task_id": "projects/.../operations/op-123",
  "submitted_at": "2026-05-04T21:10:33+07:00",
  "duration_s": 96.4,
  "media_urls": ["https://.../clip.mp4"],
  "signals": ["đã gửi bằng nút gửi", "mạng: trạng thái hoàn tất"]
}
```

Trường `signals` cho biết script dựa vào đâu để kết luận — tín hiệu mạng hay tín hiệu
giao diện — tiện khi cần dò lại lúc có gì đó không như ý.

### Khi Google đổi giao diện

Mọi thứ phụ thuộc Flow (mẫu URL API, tên khoá JSON, chữ trên nút và ô nhập) gom hết
trong khối **`PHẦN PHỤ THUỘC GOOGLE FLOW`** ở đầu `flow/flow_e2e_tool.py` — sửa ở
đó là xong, không phải lần mò cả file. Mỗi thành phần giao diện đều có nhiều cách tìm
xếp từ bền tới tạm (vai trò → placeholder → aria-label → thẻ HTML), không dùng XPath
cứng. Chạy `--dry-run` để kiểm tra nhanh xem script còn bám đúng giao diện không.

### Kiểm thử không cần trình duyệt

```bash
cd flow && python3 test_mock.py
```

61 trường hợp chạy với trình duyệt giả lập: tìm phần tử, gửi prompt, đọc mã tác vụ,
chờ tới khi xong, hết giờ, tác vụ lỗi, một prompt hỏng không làm dừng cả loạt, ghi
lịch sử, không lộ cookie. Không mở trình duyệt thật, không gọi Google, không tốn credit.

---

# Phần 2 — Dựng video bằng ffmpeg

## `ghep-video.sh` — Ghép nhiều video thành một

Ghép nhiều video nối tiếp nhau thành một file duy nhất.

### Cách dùng

```bash
# Ghép các video theo thứ tự liệt kê
./ghep-video.sh ket-qua.mp4 video1.mp4 video2.mp4 video3.mp4

# Ghép mọi video trong một thư mục (sắp theo tên file)
./ghep-video.sh ket-qua.mp4 thu-muc-video/
```

### Hai chế độ ghép

| Chế độ | Lệnh | Khi nào dùng |
|--------|------|--------------|
| **Chuẩn hoá** (mặc định) | `./ghep-video.sh out.mp4 a.mp4 b.mov` | Video **khác nhau** về độ phân giải, codec, fps, có/không tiếng. Script mã hoá lại và đưa tất cả về cùng khung hình rồi ghép. An toàn cho mọi nguồn video. |
| **Nhanh** | `./ghep-video.sh --fast out.mp4 a.mp4 b.mp4` | Video **giống nhau** (cùng máy quay/cùng cài đặt). Ghép tức thì, **không mã hoá lại**, không giảm chất lượng. |

### Tuỳ chọn

```
-f, --fast        Ghép nhanh không mã hoá lại (yêu cầu video cùng định dạng).
-r, --res WxH     Độ phân giải đích khi chuẩn hoá (mặc định 1280x720).
    --fps N       Khung hình/giây đích khi chuẩn hoá (mặc định 30).
-h, --help        Hiện trợ giúp.
```

### Ví dụ

```bash
# Ghép và xuất Full HD, 60fps
./ghep-video.sh -r 1920x1080 --fps 60 out.mp4 clip1.mp4 clip2.mp4

# Ghép nhanh 3 clip cùng máy quay
./ghep-video.sh --fast full.mp4 GOPR001.mp4 GOPR002.mp4 GOPR003.mp4
```

### Đặc điểm

- Tự động chèn **audio im lặng** cho video không có tiếng (để không lỗi khi ghép).
- Tự động **scale + pad** (thêm viền đen) giữ đúng tỉ lệ khung hình, không bị méo.
- Nhận **danh sách file** hoặc **cả thư mục**.
- Xuất MP4 (H.264 + AAC) tương thích rộng, có `+faststart` để phát trực tuyến.

---

## `chuyen-canh.sh` — Ghép clip với hiệu ứng chuyển cảnh (fade)

Giống `ghep-video.sh` nhưng các clip **hoà vào nhau mượt mà** ở điểm giao,
thay vì cắt cứng. Hình dùng `xfade`, tiếng dùng `acrossfade`.

```bash
# Ghép với fade mờ 1 giây (mặc định)
./chuyen-canh.sh ket-qua.mp4 clip1.mp4 clip2.mp4 clip3.mp4

# Đổi kiểu chuyển cảnh và thời lượng
./chuyen-canh.sh -t wipeleft -d 0.5 ket-qua.mp4 clip1.mp4 clip2.mp4
```

| Tuỳ chọn | Ý nghĩa |
|----------|---------|
| `-d, --duration N` | Thời lượng mỗi lần chuyển cảnh, giây (mặc định 1). |
| `-t, --transition T` | Kiểu: `fade`, `dissolve`, `wipeleft`, `wiperight`, `slideup`, `slidedown`, `circleopen`, `radial`, `smoothleft`... |
| `-r, --res WxH` | Độ phân giải đích (mặc định 1280x720). |
| `--fps N` | Khung hình/giây (mặc định 30). |

> Lưu ý: mỗi clip phải **dài hơn** thời lượng chuyển cảnh. Xem đầy đủ các kiểu
> bằng `ffmpeg -h filter=xfade`.

---

## `nhac-nen.sh` — Chèn nhạc nền

```bash
# Trộn nhạc với tiếng gốc (mặc định, nhạc nhỏ ở mức 0.3)
./nhac-nen.sh ket-qua.mp4 video.mp4 nhac.mp3

# Thay hẳn tiếng gốc, lặp nhạc cho đủ độ dài video
./nhac-nen.sh --mode replace --loop ket-qua.mp4 video.mp4 nhac.mp3
```

| Tuỳ chọn | Ý nghĩa |
|----------|---------|
| `-m, --mode mix\|replace` | `mix` = trộn với tiếng gốc; `replace` = thay hẳn. |
| `-v, --volume V` | Âm lượng nhạc (mặc định 0.3 cho mix, 1.0 cho replace). |
| `-l, --loop` | Lặp nhạc nếu ngắn hơn video. |
| `--fade N` | Fade nhạc vào/ra N giây (mặc định 2, đặt 0 để tắt). |

- Kết quả luôn **cắt đúng bằng độ dài video**.
- Video không có tiếng gốc: tự động chỉ dùng nhạc nền.

---

## `phu-de.sh` — Thêm phụ đề (từ file `.srt`)

```bash
# Phụ đề MỀM: bật/tắt được trong trình phát (nhẹ, không mã hoá lại)
./phu-de.sh ket-qua.mp4 video.mp4 phude.srt

# Phụ đề GẮN CỨNG vào hình (xem được ở mọi nơi, kể cả mạng xã hội)
./phu-de.sh --burn --color yellow --size 28 ket-qua.mp4 video.mp4 phude.srt
```

| Tuỳ chọn | Ý nghĩa |
|----------|---------|
| `-b, --burn` | Gắn cứng phụ đề vào hình (mã hoá lại). Mặc định là phụ đề mềm. |
| `--size N` | Cỡ chữ khi gắn cứng (mặc định 24). |
| `--color TÊN` | Màu chữ: `white`, `yellow`, `cyan`, `red`, `green`, `blue`, `black`. |

- Hỗ trợ **tiếng Việt có dấu** (font DejaVu, viền đen dễ đọc).
- Định dạng file phụ đề `.srt` ví dụ:

  ```
  1
  00:00:00,500 --> 00:00:02,000
  Xin chào các bạn
  ```

---

## Kết hợp các công cụ

Các script nối tiếp được với nhau. Ví dụ quy trình dựng một video hoàn chỉnh:

```bash
# 1) Ghép các clip với chuyển cảnh mượt
./chuyen-canh.sh buoc1.mp4 canh1.mp4 canh2.mp4 canh3.mp4

# 2) Chèn nhạc nền
./nhac-nen.sh buoc2.mp4 buoc1.mp4 nhac.mp3

# 3) Gắn phụ đề
./phu-de.sh video-hoan-chinh.mp4 buoc2.mp4 phude.srt --burn --color white
```

---

# Quy trình đầy đủ: AI tạo cảnh → ffmpeg dựng phim

Tạo cảnh bằng TopView (dưới đây) hoặc bằng Google Flow
(`python3 flow/flow_automation.py --prompts-file canh.txt`, rồi tải video từ Flow về),
sau đó dựng bằng các script ffmpeg.


```bash
export TOPVIEW_API_KEY="khoá-của-bạn"

# 1) Tạo từng cảnh bằng AI
node topview/cli.js video "cảnh mở đầu: ly cà phê bốc khói" -o canh1.mp4
node topview/cli.js video "cảnh 2: rót cà phê vào ly"      -o canh2.mp4
node topview/cli.js video "cảnh 3: logo thương hiệu"        -o canh3.mp4

# 2) Ghép với chuyển cảnh mượt
./chuyen-canh.sh buoc1.mp4 canh1.mp4 canh2.mp4 canh3.mp4

# 3) Chèn nhạc nền
./nhac-nen.sh buoc2.mp4 buoc1.mp4 nhac.mp3

# 4) Gắn phụ đề
./phu-de.sh quang-cao.mp4 buoc2.mp4 phude.srt --burn --color white
```
