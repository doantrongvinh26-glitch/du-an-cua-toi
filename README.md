# Công cụ xử lý video

Tập hợp script tiện ích để xử lý video bằng [ffmpeg](https://ffmpeg.org/).

## Yêu cầu

Cài `ffmpeg` (bao gồm cả `ffprobe`):

```bash
sudo apt-get update && sudo apt-get install -y ffmpeg
```

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
