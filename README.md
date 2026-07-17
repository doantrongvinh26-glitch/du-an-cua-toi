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
