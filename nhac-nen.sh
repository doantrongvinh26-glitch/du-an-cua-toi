#!/usr/bin/env bash
#
# nhac-nen.sh — Chèn nhạc nền vào video bằng ffmpeg.
#
# Cách dùng:
#   ./nhac-nen.sh output.mp4 video.mp4 nhac.mp3 [tuỳ chọn]
#
# Tuỳ chọn:
#   -m, --mode mix|replace   mix = trộn nhạc với tiếng gốc (mặc định);
#                            replace = thay hẳn tiếng gốc bằng nhạc.
#   -v, --volume V           Âm lượng nhạc nền (mặc định 0.3 cho mix, 1.0 cho replace).
#   -l, --loop               Lặp nhạc cho đủ độ dài video (nếu nhạc ngắn hơn).
#       --fade N             Fade nhạc vào/ra N giây (mặc định 2). Đặt 0 để tắt.
#   -h, --help               Hiện trợ giúp.
#
# Kết quả luôn được cắt đúng bằng độ dài video gốc.
#
set -euo pipefail

MODE="mix"
VOL=""
LOOP=0
FADE=2

usage() { sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -m|--mode)   MODE="$2"; shift 2 ;;
        -v|--volume) VOL="$2"; shift 2 ;;
        -l|--loop)   LOOP=1; shift ;;
        --fade)      FADE="$2"; shift 2 ;;
        -h|--help)   usage 0 ;;
        -*) echo "Không hiểu tuỳ chọn: $1" >&2; usage 1 ;;
        *) ARGS+=("$1"); shift ;;
    esac
done

command -v ffmpeg >/dev/null 2>&1 || { echo "Lỗi: chưa cài ffmpeg." >&2; exit 1; }

if [[ ${#ARGS[@]} -ne 3 ]]; then
    echo "Lỗi: cần đúng 3 tham số: output video nhac." >&2
    usage 1
fi
OUTPUT="${ARGS[0]}"; VIDEO="${ARGS[1]}"; MUSIC="${ARGS[2]}"
for f in "$VIDEO" "$MUSIC"; do
    [[ -f "$f" ]] || { echo "Lỗi: không tìm thấy file '$f'." >&2; exit 1; }
done

if [[ "$MODE" != "mix" && "$MODE" != "replace" ]]; then
    echo "Lỗi: --mode chỉ nhận 'mix' hoặc 'replace'." >&2; exit 1
fi
# Âm lượng mặc định theo chế độ.
[[ -z "$VOL" ]] && { [[ "$MODE" == "mix" ]] && VOL=0.3 || VOL=1.0; }

# Độ dài video (giây) để cắt nhạc và tính thời điểm fade-out.
DUR="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO")"
[[ -z "$DUR" || "$DUR" == "N/A" ]] && { echo "Lỗi: không đọc được độ dài video." >&2; exit 1; }

# Video gốc có tiếng không?
VHAS_AUDIO="$(ffprobe -v error -select_streams a -show_entries stream=index \
    -of csv=p=0 "$VIDEO" 2>/dev/null | head -1)"

echo "==> Chèn nhạc nền: $MUSIC  ->  $VIDEO"
echo "    Chế độ: $MODE | Âm lượng nhạc: $VOL | Lặp: $([[ $LOOP -eq 1 ]] && echo có || echo không) | Fade: ${FADE}s"

# Xử lý track nhạc: chỉnh âm lượng, fade vào/ra, cắt đúng độ dài video.
MUSIC_FILTER="volume=${VOL}"
if [[ "$(echo "$FADE > 0" | bc -l 2>/dev/null || echo 0)" == "1" ]]; then
    FADE_OUT_ST="$(echo "$DUR - $FADE" | bc -l)"
    MUSIC_FILTER+=",afade=t=in:st=0:d=${FADE},afade=t=out:st=${FADE_OUT_ST}:d=${FADE}"
fi
MUSIC_FILTER+=",atrim=0:${DUR},asetpts=PTS-STARTPTS"

# Lặp nhạc nếu cần (đặt trước -i của nhạc).
LOOP_ARGS=()
[[ $LOOP -eq 1 ]] && LOOP_ARGS=(-stream_loop -1)

if [[ "$MODE" == "replace" || -z "$VHAS_AUDIO" ]]; then
    # Thay tiếng gốc (hoặc video vốn không có tiếng): chỉ dùng nhạc.
    [[ "$MODE" == "mix" && -z "$VHAS_AUDIO" ]] && \
        echo "    (video không có tiếng gốc -> chỉ dùng nhạc nền)"
    ffmpeg -y -i "$VIDEO" "${LOOP_ARGS[@]}" -i "$MUSIC" \
        -filter_complex "[1:a]${MUSIC_FILTER}[music]" \
        -map 0:v -map "[music]" -t "$DUR" \
        -c:v copy -c:a aac -b:a 192k -movflags +faststart "$OUTPUT"
else
    # Trộn tiếng gốc với nhạc nền.
    ffmpeg -y -i "$VIDEO" "${LOOP_ARGS[@]}" -i "$MUSIC" \
        -filter_complex \
        "[1:a]${MUSIC_FILTER}[music];[0:a][music]amix=inputs=2:duration=first:dropout_transition=0[aout]" \
        -map 0:v -map "[aout]" -t "$DUR" \
        -c:v copy -c:a aac -b:a 192k -movflags +faststart "$OUTPUT"
fi

echo "==> Xong! File kết quả: $OUTPUT"
ffmpeg -hide_banner -i "$OUTPUT" 2>&1 | grep -E 'Duration|Stream' || true
