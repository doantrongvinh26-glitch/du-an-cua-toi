#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
flow_automation.py — Giao diện dòng lệnh cho `flow_e2e_tool.py`.

Toàn bộ phần việc thật nằm trong `flow_e2e_tool.py` — một file độc lập, chép đi đâu
cũng chạy. File này chỉ lo đọc tham số dòng lệnh, gom prompt và in kết quả, để bạn
dùng ngay mà không phải viết code:

    python3 flow/flow_automation.py --project abc123 --prompt "biển đêm, sóng vỗ"

Muốn gọi từ code Python (Antigravity IDE hay project nào khác) thì import thẳng
`flow_e2e_tool`, không cần file này:

    from flow_e2e_tool import run_flow_batch
    jobs = run_flow_batch(["biển đêm"], project="abc123", resolution="720p")

Script chạy trên phiên trình duyệt mà BẠN ĐÃ TỰ ĐĂNG NHẬP. Nó KHÔNG đăng nhập hộ,
KHÔNG đọc/lưu mật khẩu, KHÔNG vượt qua bất kỳ bước xác thực nào.

Chuẩn bị (làm một lần)
----------------------
    pip install -r flow/requirements.txt && playwright install chromium

    # Mở Chrome kèm cổng gỡ lỗi, dùng profile RIÊNG (Chrome 136+ chặn cổng gỡ lỗi
    # trên profile mặc định), rồi tự tay đăng nhập Google trong cửa sổ đó:
    google-chrome --remote-debugging-port=9222 \
                  --user-data-dir="$HOME/.config/chrome-flow"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from flow_e2e_tool import (
    DEFAULT_BASE_URL,
    FlowConfig,
    FlowError,
    ConnectionFailed,
    JobRecord,
    LOG,
    flow_session,
    generate_batch,
    load_prompts_file,
    setup_logging,
)

EPILOG = """\
Ví dụ:
  # Gửi một prompt vào project đang mở sẵn
  python3 flow/flow_automation.py --project abc123 --prompt "biển đêm, sóng vỗ"

  # Gửi cả loạt từ file, chọn 720p và 8 giây
  python3 flow/flow_automation.py --project abc123 --prompts-file canh.txt \\
      --resolution 720p --duration 8

  # Thử trước, không bấm nút tạo (không tốn credit)
  python3 flow/flow_automation.py --project abc123 --prompt "thử" --dry-run

Chuẩn bị trình duyệt (làm một lần, tự đăng nhập Google trong cửa sổ đó):
  google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.config/chrome-flow"

Chrome 136 trở lên KHÔNG cho mở cổng gỡ lỗi trên profile mặc định, nên phải dùng
--user-data-dir riêng như trên.

Biến môi trường dùng làm giá trị mặc định: FLOW_PROJECT_ID, FLOW_CDP_URL.
"""


def build_parser() -> argparse.ArgumentParser:
    """Khai báo toàn bộ tuỳ chọn dòng lệnh."""
    parser = argparse.ArgumentParser(
        prog="flow_automation.py",
        description="Gửi prompt hàng loạt lên Google Flow trên phiên trình duyệt đã đăng nhập sẵn.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    group = parser.add_argument_group("Kết nối trình duyệt")
    group.add_argument(
        "--cdp-url", default=os.environ.get("FLOW_CDP_URL", "http://localhost:9222"),
        help="Địa chỉ CDP của Chrome đang chạy (mặc định: http://localhost:9222).",
    )
    group.add_argument(
        "--user-data-dir", type=Path, default=None,
        help="Thư mục profile Chrome, dùng khi không gắn được qua CDP.",
    )
    group.add_argument(
        "--channel", default="chrome",
        help="Kênh trình duyệt khi mở bằng profile: chrome, chromium, msedge (mặc định: chrome).",
    )
    group.add_argument(
        "--executable-path", type=Path, metavar="FILE",
        help="Đường dẫn tới file chạy của trình duyệt, khi nó không nằm ở chỗ mặc định.",
    )
    group.add_argument(
        "--headless", action="store_true",
        help="Chạy ẩn giao diện (chỉ áp dụng khi tự mở bằng --user-data-dir).",
    )
    group.add_argument(
        "--browser-arg", action="append", default=[], metavar="ARG",
        help="Tham số truyền thẳng cho trình duyệt khi tự mở, ví dụ: "
             "--browser-arg=--no-sandbox. Lặp lại được.",
    )

    group = parser.add_argument_group("Đích đến")
    group.add_argument(
        "--project", default=os.environ.get("FLOW_PROJECT_ID"),
        help="Id project hoặc URL đầy đủ. Bỏ trống thì dùng tab Flow đang mở.",
    )
    group.add_argument(
        "--base-url", default=DEFAULT_BASE_URL,
        help=f"Địa chỉ gốc của Flow (mặc định: {DEFAULT_BASE_URL}).",
    )

    group = parser.add_argument_group("Prompt")
    group.add_argument(
        "--prompt", action="append", default=[], metavar="TEXT",
        help="Nội dung cần tạo. Lặp lại tuỳ chọn này để gửi nhiều prompt.",
    )
    group.add_argument(
        "--prompts-file", type=Path, metavar="FILE",
        help="File .txt (mỗi dòng một prompt, `#` là ghi chú, `---` tách prompt nhiều dòng) "
             "hoặc .json (mảng chuỗi).",
    )

    group = parser.add_argument_group("Thiết lập đầu ra (bỏ trống = giữ nguyên trên giao diện)")
    group.add_argument("--model", help="Tên mô hình, ví dụ: 'Veo 3'.")
    group.add_argument("--resolution", help="Độ phân giải, ví dụ: 720p, 1080p.")
    group.add_argument("--duration", help="Thời lượng video, ví dụ: 8.")
    group.add_argument("--outputs", help="Số bản tạo cho mỗi prompt, ví dụ: 1.")
    group.add_argument("--aspect", help="Tỉ lệ khung hình, ví dụ: 16:9.")
    group.add_argument(
        "--no-settings", action="store_true",
        help="Không đụng vào bảng thiết lập, dùng nguyên thiết lập sẵn có.",
    )

    group = parser.add_argument_group("Thời gian")
    group.add_argument(
        "--timeout", type=float, default=900.0, metavar="GIÂY",
        help="Thời gian chờ tối đa cho mỗi tác vụ (mặc định: 900).",
    )
    group.add_argument(
        "--delay", type=float, default=5.0, metavar="GIÂY",
        help="Nghỉ giữa hai prompt liên tiếp (mặc định: 5).",
    )
    group.add_argument(
        "--poll-initial", type=float, default=2.0, metavar="GIÂY",
        help="Khoảng hỏi trạng thái lần đầu (mặc định: 2).",
    )
    group.add_argument(
        "--poll-max", type=float, default=30.0, metavar="GIÂY",
        help="Khoảng hỏi trạng thái tối đa sau khi tăng dần (mặc định: 30).",
    )

    group = parser.add_argument_group("Đầu ra & nhật ký")
    group.add_argument(
        "--history", type=Path, default=Path("jobs_history.json"),
        help="File lịch sử tác vụ (mặc định: jobs_history.json).",
    )
    group.add_argument(
        "--session-out", type=Path, metavar="FILE",
        help="Ghi cookie/header phiên ra file (quyền 0600). Chỉ dùng khi bạn thật sự cần — "
             "file này đủ để mạo danh phiên đăng nhập của bạn.",
    )
    group.add_argument(
        "--verify-media", action="store_true",
        help="Sau khi xong, thử mở link media bằng chính phiên đăng nhập để kiểm tra.",
    )
    group.add_argument(
        "--no-body-capture", action="store_true",
        help="Không đọc nội dung response (chỉ nhìn URL và mã HTTP). Nhẹ hơn, ít tín hiệu hơn.",
    )
    group.add_argument(
        "--close-tab", action="store_true",
        help="Đóng tab mà script tự mở khi chạy xong (mặc định để nguyên cho bạn xem kết quả).",
    )
    group.add_argument(
        "--dry-run", action="store_true",
        help="Làm mọi bước trừ bấm nút tạo. Dùng để kiểm tra locator mà không tốn credit.",
    )
    group.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Mức chi tiết của nhật ký (mặc định: INFO).",
    )
    group.add_argument("--log-file", type=Path, help="Ghi nhật ký ra file này nữa.")

    return parser


def collect_prompts(args: argparse.Namespace) -> List[str]:
    """Gom prompt từ --prompt và --prompts-file, giữ nguyên thứ tự, bỏ trùng lặp."""
    prompts: List[str] = [p.strip() for p in args.prompt if p and p.strip()]
    if args.prompts_file:
        if not args.prompts_file.exists():
            raise FlowError(f"Không thấy file prompt: {args.prompts_file}")
        prompts.extend(load_prompts_file(args.prompts_file))

    unique: List[str] = []
    for prompt in prompts:
        if prompt not in unique:
            unique.append(prompt)
        else:
            LOG.warning("Bỏ qua prompt trùng: %s", prompt[:60])
    return unique


def config_from_args(args: argparse.Namespace) -> FlowConfig:
    """Chuyển tham số dòng lệnh thành FlowConfig."""
    return FlowConfig(
        cdp_url=args.cdp_url,
        user_data_dir=args.user_data_dir,
        channel=args.channel,
        executable_path=args.executable_path,
        headless=args.headless,
        browser_args=args.browser_arg,
        base_url=args.base_url,
        project=args.project,
        model=args.model,
        resolution=args.resolution,
        duration=args.duration,
        outputs=args.outputs,
        aspect=args.aspect,
        apply_settings=not args.no_settings,
        generation_timeout_s=args.timeout,
        poll_initial_s=args.poll_initial,
        poll_max_s=args.poll_max,
        delay_between_s=args.delay,
        history_path=args.history,
        session_out=args.session_out,
        verify_media=args.verify_media,
        capture_bodies=not args.no_body_capture,
        close_tab=args.close_tab,
        dry_run=args.dry_run,
    )


def summarize(records: Sequence[JobRecord], history_path: Path) -> None:
    """In bảng tổng kết cuối lượt chạy."""
    counts: Dict[str, int] = {}
    for record in records:
        counts[record.status] = counts.get(record.status, 0) + 1

    LOG.info("═" * 62)
    LOG.info("==> Xong %d prompt: %s", len(records),
             ", ".join(f"{status}={n}" for status, n in sorted(counts.items())) or "không có")
    for record in records:
        mark = {"done": "✓", "dry-run": "·"}.get(record.status, "✗")
        LOG.info("    %s [%d] %-8s %s", mark, record.index, record.status,
                 record.prompt[:60] + ("…" if len(record.prompt) > 60 else ""))
    LOG.info("==> Lịch sử đã ghi vào: %s", history_path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Điểm vào. Trả 0 nếu mọi prompt đều ổn, 1 nếu có prompt hỏng, 2 nếu lỗi nặng."""
    args = build_parser().parse_args(argv)
    setup_logging(args.log_level, args.log_file)

    try:
        prompts = collect_prompts(args)
    except (FlowError, ValueError, OSError) as exc:
        LOG.error("Lỗi đọc prompt: %s", exc)
        return 2

    if not prompts:
        LOG.error("Chưa có prompt nào. Thêm --prompt \"...\" hoặc --prompts-file file.txt.")
        return 2

    config = config_from_args(args)
    if config.dry_run:
        LOG.warning("Chế độ --dry-run: sẽ điền prompt nhưng KHÔNG bấm nút tạo.")
    LOG.info("==> %d prompt cần gửi. Lịch sử: %s", len(prompts), config.history_path)

    try:
        with flow_session(config) as session:
            records = generate_batch(session, prompts)
    except KeyboardInterrupt:
        LOG.warning("Đã dừng theo yêu cầu (Ctrl+C). Các prompt đã gửi vẫn nằm trong lịch sử.")
        return 130
    except ConnectionFailed as exc:
        LOG.error("Không kết nối được trình duyệt:\n%s", exc)
        return 2
    except FlowError as exc:
        LOG.error("%s", exc)
        return 2

    summarize(records, config.history_path)
    return 0 if all(r.status in ("done", "dry-run") for r in records) else 1


if __name__ == "__main__":
    sys.exit(main())
