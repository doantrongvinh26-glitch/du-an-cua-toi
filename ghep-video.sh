#!/usr/bin/env bash
#
# ghep-video.sh — Ghép nhiều video thành một file duy nhất bằng ffmpeg.
#
# Cách dùng:
#   ./ghep-video.sh output.mp4 video1.mp4 video2.mp4 [video3.mp4 ...]
#   ./ghep-video.sh output.mp4 thu-muc/            # ghép mọi video trong thư mục
#
# Tuỳ chọn:
#   -f, --fast        Ghép nhanh KHÔNG mã hoá lại (chỉ dùng khi các video
#                     cùng codec/độ phân giải/khung hình — ví dụ cùng máy quay).
#   -r, --res WxH     Độ phân giải đích khi mã hoá lại (mặc định: 1280x720).
#   --fps N           Khung hình/giây đích khi mã hoá lại (mặc định: 30).
#   -h, --help        Hiện trợ giúp.
#
# Mặc định (không có -f): script mã hoá lại và CHUẨN HOÁ mọi video về cùng
# độ phân giải/fps/codec rồi mới ghép, nên chạy được với video bất kỳ nguồn nào.
#
set -euo pipefail

FAST=0
RES="1280x720"
FPS=30

usage() {
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

# --- Phân tích tham số ---
ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -f|--fast) FAST=1; shift ;;
        -r|--res)  RES="$2"; shift 2 ;;
        --fps)     FPS="$2"; shift 2 ;;
        -h|--help) usage 0 ;;
        -*) echo "Không hiểu tuỳ chọn: $1" >&2; usage 1 ;;
        *) ARGS+=("$1"); shift ;;
    esac
done

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "Lỗi: chưa cài ffmpeg. Cài bằng: sudo apt-get install -y ffmpeg" >&2
    exit 1
fi

if [[ ${#ARGS[@]} -lt 2 ]]; then
    echo "Lỗi: cần ít nhất 1 file output và 1 video input." >&2
    usage 1
fi

OUTPUT="${ARGS[0]}"
INPUTS=("${ARGS[@]:1}")

# Nếu input là một thư mục -> lấy mọi video trong đó (theo thứ tự tên).
if [[ ${#INPUTS[@]} -eq 1 && -d "${INPUTS[0]}" ]]; then
    DIR="${INPUTS[0]%/}"
    mapfile -t INPUTS < <(find "$DIR" -maxdepth 1 -type f \
        \( -iname '*.mp4' -o -iname '*.mov' -o -iname '*.mkv' \
           -o -iname '*.avi' -o -iname '*.webm' -o -iname '*.m4v' \) | sort)
    if [[ ${#INPUTS[@]} -eq 0 ]]; then
        echo "Lỗi: không tìm thấy video nào trong thư mục '$DIR'." >&2
        exit 1
    fi
fi

# Kiểm tra mọi file input tồn tại.
for f in "${INPUTS[@]}"; do
    if [[ ! -f "$f" ]]; then
        echo "Lỗi: không tìm thấy file '$f'." >&2
        exit 1
    fi
done

echo "==> Sẽ ghép ${#INPUTS[@]} video thành: $OUTPUT"
for i in "${!INPUTS[@]}"; do
    printf "    %2d. %s\n" "$((i+1))" "${INPUTS[$i]}"
done

# Thư mục tạm để chứa danh sách / file trung gian.
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

if [[ $FAST -eq 1 ]]; then
    # --- Cách 1: ghép nhanh, không mã hoá lại (concat demuxer) ---
    echo "==> Chế độ NHANH: ghép không mã hoá lại (yêu cầu cùng định dạng)."
    LIST="$TMPDIR/list.txt"
    : > "$LIST"
    for f in "${INPUTS[@]}"; do
        # Dùng đường dẫn tuyệt đối, escape dấu nháy đơn.
        abs="$(cd "$(dirname "$f")" && pwd)/$(basename "$f")"
        printf "file '%s'\n" "${abs//\'/\'\\\'\'}" >> "$LIST"
    done
    ffmpeg -y -f concat -safe 0 -i "$LIST" -c copy "$OUTPUT"
else
    # --- Cách 2: chuẩn hoá + ghép (concat filter, mã hoá lại) ---
    W="${RES%x*}"; H="${RES#*x}"
    echo "==> Chế độ CHUẨN HOÁ: mã hoá lại về ${W}x${H} @ ${FPS}fps rồi ghép."

    # Xây filter_complex: scale + pad mỗi video về đúng khung, chuẩn hoá SAR/fps,
    # thêm audio (tạo audio im lặng nếu video không có tiếng) rồi concat.
    n=${#INPUTS[@]}
    inputs_args=()
    audio_labels=()      # nhãn nguồn audio cho từng video (thật hoặc im lặng)
    silence_idx=$n       # chỉ số input tiếp theo cho nguồn im lặng

    # Thêm mọi video làm input trước (chỉ số 0..n-1), đồng thời xác định
    # video nào không có audio để chèn nguồn im lặng bằng độ dài tương ứng.
    for f in "${INPUTS[@]}"; do
        inputs_args+=(-i "$f")
    done
    for i in "${!INPUTS[@]}"; do
        f="${INPUTS[$i]}"
        has_audio="$(ffprobe -v error -select_streams a \
            -show_entries stream=index -of csv=p=0 "$f" 2>/dev/null | head -1)"
        if [[ -n "$has_audio" ]]; then
            audio_labels+=("[${i}:a]")
        else
            dur="$(ffprobe -v error -show_entries format=duration \
                -of csv=p=0 "$f" 2>/dev/null)"
            [[ -z "$dur" || "$dur" == "N/A" ]] && dur=1
            inputs_args+=(-f lavfi -t "$dur" \
                -i "anullsrc=channel_layout=stereo:sample_rate=44100")
            audio_labels+=("[${silence_idx}:a]")
            silence_idx=$((silence_idx+1))
        fi
    done

    filter=""
    concat_labels=""
    for i in "${!INPUTS[@]}"; do
        filter+="[${i}:v]scale=${W}:${H}:force_original_aspect_ratio=decrease,"
        filter+="pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2:color=black,"
        filter+="setsar=1,fps=${FPS},format=yuv420p[v${i}];"
        filter+="${audio_labels[$i]}aresample=44100,asetpts=N/SR/TB[a${i}];"
        concat_labels+="[v${i}][a${i}]"
    done
    filter+="${concat_labels}concat=n=${n}:v=1:a=1[outv][outa]"

    ffmpeg -y "${inputs_args[@]}" \
        -filter_complex "$filter" \
        -map "[outv]" -map "[outa]" \
        -c:v libx264 -preset medium -crf 23 \
        -c:a aac -b:a 192k -movflags +faststart \
        "$OUTPUT"
fi

echo "==> Xong! File kết quả: $OUTPUT"
ffmpeg -hide_banner -i "$OUTPUT" 2>&1 | grep -E 'Duration|Stream' || true
