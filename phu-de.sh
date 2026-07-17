#!/usr/bin/env bash
#
# phu-de.sh — Thêm phụ đề vào video từ file .srt bằng ffmpeg.
#
# Hai kiểu:
#   - Mặc định: phụ đề MỀM (mux vào MP4) — nhẹ, không mã hoá lại, người xem
#     có thể bật/tắt trong trình phát.
#   - --burn: phụ đề GẮN CỨNG vào hình — luôn hiển thị, xem được ở mọi nơi
#     (kể cả mạng xã hội), nhưng phải mã hoá lại.
#
# Cách dùng:
#   ./phu-de.sh output.mp4 video.mp4 phude.srt [tuỳ chọn]
#
# Tuỳ chọn:
#   -b, --burn            Gắn cứng phụ đề vào hình (mã hoá lại).
#       --size N          Cỡ chữ khi gắn cứng (mặc định 24).
#       --color TÊN       Màu chữ khi gắn cứng (mặc định white). VD: yellow, cyan.
#   -h, --help            Hiện trợ giúp.
#
set -euo pipefail

BURN=0
FONTSIZE=24
COLOR="white"

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -b|--burn) BURN=1; shift ;;
        --size)    FONTSIZE="$2"; shift 2 ;;
        --color)   COLOR="$2"; shift 2 ;;
        -h|--help) usage 0 ;;
        -*) echo "Không hiểu tuỳ chọn: $1" >&2; usage 1 ;;
        *) ARGS+=("$1"); shift ;;
    esac
done

command -v ffmpeg >/dev/null 2>&1 || { echo "Lỗi: chưa cài ffmpeg." >&2; exit 1; }

if [[ ${#ARGS[@]} -ne 3 ]]; then
    echo "Lỗi: cần đúng 3 tham số: output video phude.srt" >&2
    usage 1
fi
OUTPUT="${ARGS[0]}"; VIDEO="${ARGS[1]}"; SUB="${ARGS[2]}"
for f in "$VIDEO" "$SUB"; do
    [[ -f "$f" ]] || { echo "Lỗi: không tìm thấy file '$f'." >&2; exit 1; }
done

if [[ $BURN -eq 1 ]]; then
    echo "==> Gắn CỨNG phụ đề vào hình (cỡ $FONTSIZE, màu $COLOR): $SUB"
    # Đổi tên màu -> mã ASS &HAABBGGRR (alpha-xanh dương-xanh lá-đỏ).
    case "${COLOR,,}" in
        white)   ASSCOL="&H00FFFFFF" ;;
        yellow)  ASSCOL="&H0000FFFF" ;;
        cyan)    ASSCOL="&H00FFFF00" ;;
        red)     ASSCOL="&H000000FF" ;;
        green)   ASSCOL="&H0000FF00" ;;
        blue)    ASSCOL="&H00FF0000" ;;
        black)   ASSCOL="&H00000000" ;;
        \&H*)    ASSCOL="$COLOR" ;;    # cho phép truyền thẳng mã ASS
        *) echo "Cảnh báo: màu '$COLOR' không rõ, dùng trắng." >&2; ASSCOL="&H00FFFFFF" ;;
    esac
    # Bộ lọc subtitles cần escape các ký tự đặc biệt trong đường dẫn.
    esc_sub="$SUB"
    esc_sub="${esc_sub//\\/\\\\}"      # \  -> \\
    esc_sub="${esc_sub//:/\\:}"        # :  -> \:
    esc_sub="${esc_sub//\'/\\\'}"      # '  -> \'
    ffmpeg -y -i "$VIDEO" \
        -vf "subtitles='${esc_sub}':force_style='FontSize=${FONTSIZE},PrimaryColour=${ASSCOL},Outline=1'" \
        -c:v libx264 -preset medium -crf 23 -c:a copy -movflags +faststart \
        "$OUTPUT"
else
    echo "==> Thêm phụ đề MỀM (bật/tắt được) vào MP4: $SUB"
    # mov_text là định dạng phụ đề chuẩn trong MP4.
    ffmpeg -y -i "$VIDEO" -i "$SUB" \
        -map 0:v -map 0:a? -map 1 \
        -c:v copy -c:a copy -c:s mov_text \
        -metadata:s:s:0 language=vie -movflags +faststart \
        "$OUTPUT"
fi

echo "==> Xong! File kết quả: $OUTPUT"
ffmpeg -hide_banner -i "$OUTPUT" 2>&1 | grep -E 'Duration|Stream' || true
