# Công cụ tạo & xử lý video

Gồm hai phần:

- **Tạo** ảnh/video bằng AI qua [TopView](https://www.topview.ai) — thư mục `topview/`.
- **Dựng** video bằng [ffmpeg](https://ffmpeg.org/) — các script `.sh` ghép nối,
  chuyển cảnh, nhạc nền, phụ đề.

Hai phần nối thẳng được với nhau: tạo từng cảnh bằng AI rồi dựng thành video hoàn chỉnh.

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
