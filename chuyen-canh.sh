#!/usr/bin/env bash
#
# chuyen-canh.sh — Ghép các clip với hiệu ứng chuyển cảnh (fade/crossfade).
#
# Khác với ghep-video.sh (ghép nối cứng), script này làm các clip
# HOÀ VÀO NHAU mượt mà ở điểm giao (video xfade + audio acrossfade).
#
# Cách dùng:
#   ./chuyen-canh.sh output.mp4 clip1.mp4 clip2.mp4 [clip3.mp4 ...]
#
# Tuỳ chọn:
#   -d, --duration N     Độ dài mỗi lần chuyển cảnh, giây (mặc định 1).
#   -t, --transition T   Kiểu chuyển cảnh (mặc định fade). Ví dụ: fade, dissolve,
#                        wipeleft, wiperight, slideup, slidedown, circleopen,
#                        radial, smoothleft... (xem `ffmpeg -h filter=xfade`).
#   -r, --res WxH        Độ phân giải đích (mặc định 1280x720).
#       --fps N          Khung hình/giây đích (mặc định 30).
#   -h, --help           Hiện trợ giúp.
#
set -euo pipefail

DUR=1
TRANS="fade"
RES="1280x720"
FPS=30

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -d|--duration)   DUR="$2"; shift 2 ;;
        -t|--transition) TRANS="$2"; shift 2 ;;
        -r|--res)        RES="$2"; shift 2 ;;
        --fps)           FPS="$2"; shift 2 ;;
        -h|--help)       usage 0 ;;
        -*) echo "Không hiểu tuỳ chọn: $1" >&2; usage 1 ;;
        *) ARGS+=("$1"); shift ;;
    esac
done

command -v ffmpeg >/dev/null 2>&1 || { echo "Lỗi: chưa cài ffmpeg." >&2; exit 1; }

if [[ ${#ARGS[@]} -lt 3 ]]; then
    echo "Lỗi: cần 1 output và ÍT NHẤT 2 clip để có chuyển cảnh." >&2
    usage 1
fi
OUTPUT="${ARGS[0]}"
INPUTS=("${ARGS[@]:1}")
W="${RES%x*}"; H="${RES#*x}"

for f in "${INPUTS[@]}"; do
    [[ -f "$f" ]] || { echo "Lỗi: không tìm thấy file '$f'." >&2; exit 1; }
done

n=${#INPUTS[@]}
echo "==> Ghép $n clip với chuyển cảnh '$TRANS' (${DUR}s), khung ${W}x${H}@${FPS}fps"

# Lấy độ dài từng clip để tính offset cho xfade.
DURS=()
for f in "${INPUTS[@]}"; do
    d="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")"
    [[ -z "$d" || "$d" == "N/A" ]] && { echo "Lỗi: không đọc được độ dài '$f'." >&2; exit 1; }
    DURS+=("$d")
    # Mỗi clip phải dài hơn thời lượng chuyển cảnh.
    if [[ "$(echo "$d <= $DUR" | bc -l)" == "1" ]]; then
        echo "Lỗi: clip '$f' (${d}s) ngắn hơn thời lượng chuyển cảnh ${DUR}s." >&2
        exit 1
    fi
done

# Chuẩn hoá từng clip + phát hiện/chèn audio im lặng cho clip thiếu tiếng.
inputs_args=()
audio_labels=()
silence_idx=$n
for f in "${INPUTS[@]}"; do inputs_args+=(-i "$f"); done
for i in "${!INPUTS[@]}"; do
    f="${INPUTS[$i]}"
    ha="$(ffprobe -v error -select_streams a -show_entries stream=index \
        -of csv=p=0 "$f" 2>/dev/null | head -1)"
    if [[ -n "$ha" ]]; then
        audio_labels+=("[${i}:a]")
    else
        inputs_args+=(-f lavfi -t "${DURS[$i]}" \
            -i "anullsrc=channel_layout=stereo:sample_rate=44100")
        audio_labels+=("[${silence_idx}:a]")
        silence_idx=$((silence_idx+1))
    fi
done

# Chuẩn hoá video + audio từng clip.
filter=""
for i in "${!INPUTS[@]}"; do
    filter+="[${i}:v]scale=${W}:${H}:force_original_aspect_ratio=decrease,"
    filter+="pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
    filter+="fps=${FPS},format=yuv420p,setpts=PTS-STARTPTS[v${i}];"
    filter+="${audio_labels[$i]}aresample=44100,asetpts=PTS-STARTPTS[a${i}];"
done

# Chuỗi xfade cho video: offset thứ i = tổng độ dài các clip trước - i*DUR.
prev_v="v0"
acc="${DURS[0]}"          # tổng độ dài tích luỹ (chưa trừ overlap)
for ((i=1; i<n; i++)); do
    offset="$(echo "$acc - $i * $DUR" | bc -l)"
    out_v="vx${i}"
    filter+="[${prev_v}][v${i}]xfade=transition=${TRANS}:duration=${DUR}:offset=${offset}[${out_v}];"
    prev_v="$out_v"
    acc="$(echo "$acc + ${DURS[$i]}" | bc -l)"
done

# Chuỗi acrossfade cho audio (tự căn theo điểm giao, không cần offset).
prev_a="a0"
for ((i=1; i<n; i++)); do
    out_a="ax${i}"
    filter+="[${prev_a}][a${i}]acrossfade=d=${DUR}[${out_a}]"
    [[ $i -lt $((n-1)) ]] && filter+=";"
    prev_a="$out_a"
done

ffmpeg -y "${inputs_args[@]}" \
    -filter_complex "$filter" \
    -map "[${prev_v}]" -map "[${prev_a}]" \
    -c:v libx264 -preset medium -crf 23 \
    -c:a aac -b:a 192k -movflags +faststart \
    "$OUTPUT"

echo "==> Xong! File kết quả: $OUTPUT"
ffmpeg -hide_banner -i "$OUTPUT" 2>&1 | grep -E 'Duration|Stream' || true
