#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
flow_e2e_tool.py — Thư viện MỘT FILE để tự động hoá Google Flow (https://flow.google.com).

Chép đúng file này vào project của bạn là dùng được: không import gì từ repo này,
phụ thuộc duy nhất là `playwright`. Mọi thứ bày ra dưới dạng HÀM rõ ràng để import
thẳng.

Script chạy trên phiên trình duyệt mà BẠN ĐÃ TỰ ĐĂNG NHẬP. Nó KHÔNG đăng nhập hộ,
KHÔNG đọc/lưu mật khẩu, KHÔNG vượt qua bất kỳ bước xác thực nào.

Cài đặt
-------
    pip install playwright && playwright install chromium

    # Mở Chrome kèm cổng gỡ lỗi, dùng profile RIÊNG (Chrome 136+ chặn cổng gỡ lỗi
    # trên profile mặc định), rồi tự tay đăng nhập Google trong cửa sổ đó:
    google-chrome --remote-debugging-port=9222 \
                  --user-data-dir="$HOME/.config/chrome-flow"

Dùng nhanh nhất — một lệnh
--------------------------
    from flow_e2e_tool import run_flow_batch

    jobs = run_flow_batch(
        ["biển đêm, sóng vỗ", "rừng thông buổi sớm"],
        project="abc123",
        resolution="720p",
    )
    for job in jobs:
        print(job.status, job.task_id, job.media_urls)

Dùng từng bước — khi cần chen thao tác của bạn vào giữa
-------------------------------------------------------
    from flow_e2e_tool import (
        flow_session, open_project, apply_output_settings,
        submit_prompt, wait_for_job, save_jobs,
    )

    with flow_session(project="abc123") as session:
        open_project(session)
        apply_output_settings(session, {"resolution": "720p"})

        job = submit_prompt(session, "biển đêm, sóng vỗ")
        print("đã gửi, mã tác vụ sẽ có sau ít giây:", job.status)
        wait_for_job(session, job)

        save_jobs([job], "jobs_history.json")

Các hàm chính
-------------
    Kết nối      : connect_browser, close_session, flow_session
    Điều hướng   : open_project, wait_until_ready
    Thiết lập    : apply_output_settings
    Sinh video   : submit_prompt, wait_for_job, generate, generate_batch, run_flow_batch
    Phiên đăng nhập: capture_session_state, verify_media_url
    Lịch sử      : save_jobs, load_jobs
    Tìm phần tử  : find_prompt_input, find_submit_button, fill_prompt, click_submit

Mọi hàm đều có type hint và ghi log qua logger tên "flow" — muốn thấy log thì gọi
`setup_logging("INFO")`, hoặc tự cấu hình `logging` theo cách của project bạn.

Lưu ý: Flow không có tài liệu API công khai. Mọi thứ phụ thuộc giao diện/endpoint
của Google gom trong phần "PHẦN PHỤ THUỘC GOOGLE FLOW" ngay dưới đây — giao diện
đổi thì sửa đúng chỗ đó, phần còn lại giữ nguyên.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from typing import (
    TYPE_CHECKING, Any, Callable, Dict, Iterable, Iterator, List, Optional,
    Sequence, Tuple,
)

if TYPE_CHECKING:  # chỉ phục vụ type hint — không cần cài playwright để import
    from playwright.sync_api import (
        Browser, BrowserContext, Locator, Page, Playwright, Request, Response,
    )

__all__ = [
    # Kết nối
    "connect_browser", "close_session", "flow_session", "FlowSession",
    # Điều hướng & thiết lập
    "open_project", "wait_until_ready", "apply_output_settings",
    # Sinh video
    "submit_prompt", "wait_for_job", "generate", "generate_batch", "run_flow_batch",
    # Phiên đăng nhập
    "capture_session_state", "verify_media_url", "SessionState",
    # Lịch sử
    "save_jobs", "load_jobs", "JobRecord", "JobHistory",
    # Tìm phần tử / thao tác trang
    "find_prompt_input", "find_submit_button", "fill_prompt", "click_submit",
    "count_media", "is_busy", "first_visible",
    # Cấu hình, theo dõi mạng, lỗi
    "FlowConfig", "NetworkMonitor", "NetEvent", "setup_logging",
    "FlowError", "ConnectionFailed", "NavigationFailed", "ElementNotFound",
    "SubmitFailed", "GenerationTimeout",
]

LOG = logging.getLogger("flow")

# ===========================================================================
# PHẦN PHỤ THUỘC GOOGLE FLOW — sửa ở đây khi Google đổi giao diện / endpoint
# ===========================================================================

DEFAULT_BASE_URL = "https://flow.google.com"

# Lấy id project từ URL dạng https://flow.google.com/project/{id}
PROJECT_PATH_RE = re.compile(r"/project/([A-Za-z0-9_\-]+)")

# Nhận diện request theo CHUỖI CON trong URL (không khớp cứng cả đường dẫn) để
# vẫn đúng khi Google đổi số phiên bản hay tên miền phụ.
GENERATE_URL_HINTS: Tuple[str, ...] = (
    "batchasyncgenerate", "asyncgenerate", "generatevideo", "video:generate",
    "texttovideo", "runworkflow", "createmedia", "media:generate", "generate",
)
STATUS_URL_HINTS: Tuple[str, ...] = (
    "checkasyncvideogenerationstatus", "batchcheckasync", "generationstatus",
    "getoperation", "/operations", "checkstatus", "pollstatus", "status",
)
# Chỉ soi body của request đi tới các host này (tránh đọc nhầm request quảng cáo).
API_HOST_HINTS: Tuple[str, ...] = (
    "aisandbox-pa.googleapis.com", "googleapis.com", "labs.google", "flow.google.com",
)

# Tên khoá hay gặp trong JSON trả về. Tra theo nhiều tên để không vỡ khi đổi tên khoá.
TASK_ID_KEYS: Tuple[str, ...] = (
    "operationName", "operation", "mediaGenerationId", "sceneId", "videoId",
    "taskId", "task_id", "jobId", "workflowId", "requestId", "name", "id",
)
STATUS_KEYS: Tuple[str, ...] = (
    "mediaGenerationStatus", "operationStatus", "taskStatus", "status", "state", "done",
)
MEDIA_URL_KEYS: Tuple[str, ...] = (
    "videoUri", "video_uri", "videoUrl", "servingUri", "servingUrl", "downloadUri",
    "downloadUrl", "fifeUrl", "mediaUrl", "signedUrl", "uri", "url",
)
ERROR_KEYS: Tuple[str, ...] = (
    "errorMessage", "failureReason", "statusMessage", "error", "message",
)

# Chữ xuất hiện trên ô nhập prompt / nút tạo. Có cả tiếng Anh lẫn tiếng Việt vì
# giao diện Flow đổi theo ngôn ngữ tài khoản.
PROMPT_TEXT_RE = re.compile(
    r"what do you want to create|describe your|type a prompt|prompt|"
    r"bạn muốn tạo|mô tả|nhập",
    re.I,
)
SUBMIT_TEXT_RE = re.compile(
    r"^(create|generate|submit|send|run|tạo|gửi|chạy)\b|arrow_forward|send",
    re.I,
)
SETTINGS_TEXT_RE = re.compile(r"settings|options|tune|cài đặt|tuỳ chọn|tùy chọn", re.I)
BUSY_TEXT_RE = re.compile(r"generating|creating|loading|đang tạo|đang xử lý", re.I)

# Nhãn của từng thiết lập đầu ra trong bảng cài đặt của Flow.
SETTING_LABEL_RE: Dict[str, "re.Pattern[str]"] = {
    "model": re.compile(r"model|mô hình|veo", re.I),
    "resolution": re.compile(r"resolution|quality|độ phân giải|chất lượng", re.I),
    "duration": re.compile(r"duration|length|thời lượng|độ dài", re.I),
    "outputs": re.compile(r"outputs? per prompt|number of|outputs|số lượng|số đầu ra", re.I),
    "aspect": re.compile(r"aspect ratio|tỉ lệ|tỷ lệ|khung hình", re.I),
}

# ===========================================================================
# Lỗi
# ===========================================================================


class FlowError(Exception):
    """Lỗi có ngữ cảnh, để phần gọi bắt và hiển thị cho người dùng."""

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.context: Dict[str, Any] = context


class ConnectionFailed(FlowError):
    """Không gắn được vào trình duyệt (CDP không mở, sai cổng, profile đang bị khoá)."""


class NavigationFailed(FlowError):
    """Không mở được trang project, hoặc trang không phải Flow."""


class ElementNotFound(FlowError):
    """Không tìm thấy thành phần giao diện — thường là do Flow đổi giao diện."""


class SubmitFailed(FlowError):
    """Điền được prompt nhưng không kích hoạt được lệnh tạo."""


class GenerationTimeout(FlowError):
    """Hết thời gian chờ mà tác vụ chưa báo xong."""


# ===========================================================================
# Tiện ích thuần (không đụng tới Playwright — kiểm thử được offline)
# ===========================================================================


def now_iso() -> str:
    """Thời điểm hiện tại theo ISO-8601, có múi giờ, để ghi vào lịch sử."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def pick(obj: Any, keys: Sequence[str]) -> Any:
    """Lấy giá trị đầu tiên tìm được trong dict theo danh sách tên khoá."""
    if not isinstance(obj, dict):
        return None
    for key in keys:
        value = obj.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def deep_find(node: Any, keys: Sequence[str], *, max_depth: int = 8) -> Any:
    """
    Tìm đệ quy giá trị đầu tiên ứng với một trong các khoá `keys`.

    Response của Flow lồng nhau nhiều tầng và đổi cấu trúc theo thời gian, nên
    tra sâu theo tên khoá an toàn hơn là bám vào một đường dẫn cố định.
    """
    if max_depth < 0 or node is None:
        return None
    direct = pick(node, keys)
    if direct is not None and not isinstance(direct, (dict, list)):
        return direct
    children: Iterable[Any]
    if isinstance(node, dict):
        children = node.values()
    elif isinstance(node, list):
        children = node
    else:
        return None
    for child in children:
        found = deep_find(child, keys, max_depth=max_depth - 1)
        if found is not None:
            return found
    return None


def deep_collect(node: Any, keys: Sequence[str], *, max_depth: int = 8) -> List[Any]:
    """Gom TẤT CẢ giá trị vô hướng ứng với `keys` ở mọi tầng (không trùng lặp)."""
    found: List[Any] = []

    def walk(current: Any, depth: int) -> None:
        if depth < 0 or current is None:
            return
        if isinstance(current, dict):
            for key, value in current.items():
                if key in keys and not isinstance(value, (dict, list)) and value not in (None, ""):
                    if value not in found:
                        found.append(value)
                walk(value, depth - 1)
        elif isinstance(current, list):
            for item in current:
                walk(item, depth - 1)

    walk(node, max_depth)
    return found


def normalize_status(raw: Any) -> Optional[str]:
    """
    Quy mọi kiểu trạng thái của Google về 3 giá trị: "done" / "failed" / "pending".

    So khớp theo chuỗi con nên vẫn đúng với các enum dài kiểu
    MEDIA_GENERATION_STATUS_SUCCESSFUL. Trả None nếu không nhận ra.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        # Long-running operation của Google dùng cờ done: true/false.
        return "done" if raw else "pending"
    text = str(raw).strip().upper()
    if not text:
        return None
    if any(k in text for k in ("FAIL", "ERROR", "CANCEL", "REJECT", "DENIED", "ABORT")):
        return "failed"
    if any(k in text for k in ("SUCCE", "COMPLETE", "DONE", "FINISH", "READY", "SERVED")):
        return "done"
    if any(k in text for k in ("PEND", "RUN", "QUEUE", "PROCESS", "ACTIVE", "START", "PROGRESS")):
        return "pending"
    return None


def backoff_delays(
    initial: float, factor: float, maximum: float, *, jitter: float = 0.25
) -> Iterable[float]:
    """
    Sinh dãy thời gian chờ tăng dần (có nhiễu nhẹ) cho vòng hỏi trạng thái.

    Nhiễu để nhiều tiến trình chạy song song không cùng hỏi vào một thời điểm.
    """
    delay = max(0.1, initial)
    while True:
        spread = delay * jitter
        yield max(0.1, delay + random.uniform(-spread, spread))
        delay = min(maximum, delay * factor)


def strip_xssi_prefix(text: str) -> str:
    """Bỏ tiền tố chống XSSI )]}' mà API Google hay chèn trước JSON."""
    cleaned = text.lstrip()
    for prefix in (")]}'\n", ")]}'", "while(1);", "for(;;);"):
        if cleaned.startswith(prefix):
            return cleaned[len(prefix):].lstrip()
    return text


def parse_json_loose(text: str) -> Any:
    """Cố đọc JSON kể cả khi có tiền tố chống XSSI. Không đọc được thì trả None."""
    if not text:
        return None
    try:
        return json.loads(strip_xssi_prefix(text))
    except (ValueError, TypeError):
        return None


_MEDIA_URL_RE = re.compile(r"https?://[^\s\"'\\<>]+?\.(?:mp4|webm|mov|png|jpg|jpeg)\b[^\s\"'\\<>]*")


def scrape_media_urls(text: str, limit: int = 10) -> List[str]:
    """Vét link media bằng regex khi body không phải JSON đọc được."""
    urls: List[str] = []
    for match in _MEDIA_URL_RE.finditer(text or ""):
        url = match.group(0)
        if url not in urls:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def parse_prompts(text: str) -> List[str]:
    """
    Đọc danh sách prompt từ nội dung file văn bản.

    - Mỗi dòng một prompt.
    - Dòng bắt đầu bằng `#` là ghi chú, bỏ qua.
    - Dòng chỉ có `---` để tách các prompt DÀI NHIỀU DÒNG.
    """
    if "---" in text:
        blocks = re.split(r"^\s*---\s*$", text, flags=re.M)
        if len(blocks) > 1:
            prompts = []
            for block in blocks:
                lines = [
                    line for line in block.splitlines()
                    if line.strip() and not line.lstrip().startswith("#")
                ]
                joined = "\n".join(lines).strip()
                if joined:
                    prompts.append(joined)
            return prompts
    return [
        line.strip() for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def load_prompts_file(path: Path) -> List[str]:
    """Đọc prompt từ file .txt (mỗi dòng một prompt) hoặc .json (mảng)."""
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(raw)
        if not isinstance(data, list):
            raise FlowError(f"File {path} phải chứa một mảng JSON các prompt.")
        prompts: List[str] = []
        for item in data:
            if isinstance(item, str):
                prompts.append(item.strip())
            elif isinstance(item, dict) and isinstance(item.get("prompt"), str):
                prompts.append(item["prompt"].strip())
            else:
                raise FlowError(f"Phần tử không hợp lệ trong {path}: {item!r}")
        return [p for p in prompts if p]
    return parse_prompts(raw)


def host_of(url: str) -> str:
    """Lấy tên miền của một URL (không có cổng). Không phân tích được thì trả chuỗi rỗng."""
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def resolve_project_url(value: Optional[str], base_url: str = DEFAULT_BASE_URL) -> Optional[str]:
    """Nhận id project trần hoặc cả URL, trả về URL project đầy đủ."""
    if not value:
        return None
    value = value.strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value.rstrip("/")
    return f"{base_url.rstrip('/')}/project/{value}"


def project_id_from_url(url: Optional[str]) -> Optional[str]:
    """Rút id project ra khỏi URL, không có thì trả None."""
    if not url:
        return None
    match = PROJECT_PATH_RE.search(url)
    return match.group(1) if match else None


def setup_logging(level: str = "INFO", log_file: Optional[Path] = None) -> None:
    """Bật log ra màn hình (và ra file nếu có), định dạng gọn dễ đọc."""
    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )


# ===========================================================================
# Cấu hình
# ===========================================================================


@dataclass
class FlowConfig:
    """Toàn bộ tham số điều khiển một lần chạy."""

    # --- Kết nối trình duyệt ---
    cdp_url: str = "http://localhost:9222"
    user_data_dir: Optional[Path] = None
    channel: str = "chrome"
    executable_path: Optional[Path] = None
    headless: bool = False
    browser_args: List[str] = field(default_factory=list)

    # --- Đích đến ---
    base_url: str = DEFAULT_BASE_URL
    project: Optional[str] = None

    # --- Thiết lập đầu ra mong muốn (bỏ trống = giữ nguyên thiết lập trên giao diện) ---
    model: Optional[str] = None
    resolution: Optional[str] = None
    duration: Optional[str] = None
    outputs: Optional[str] = None
    aspect: Optional[str] = None
    apply_settings: bool = True

    # --- Thời gian ---
    action_timeout_ms: int = 20_000
    ready_timeout_ms: int = 45_000
    generation_timeout_s: float = 900.0
    poll_initial_s: float = 2.0
    poll_factor: float = 1.6
    poll_max_s: float = 30.0
    delay_between_s: float = 5.0

    # --- Đầu ra ---
    history_path: Path = field(default_factory=lambda: Path("jobs_history.json"))
    session_out: Optional[Path] = None
    verify_media: bool = False

    # --- Hành vi ---
    capture_bodies: bool = True
    close_tab: bool = False
    dry_run: bool = False

    @property
    def host(self) -> str:
        """Tên miền của Flow, suy ra từ --base-url."""
        return host_of(self.base_url) or "flow.google.com"

    def desired_settings(self) -> Dict[str, str]:
        """Các thiết lập người dùng thật sự yêu cầu đổi (bỏ qua cái để trống)."""
        wanted = {
            "model": self.model,
            "resolution": self.resolution,
            "duration": self.duration,
            "outputs": self.outputs,
            "aspect": self.aspect,
        }
        return {k: str(v) for k, v in wanted.items() if v not in (None, "")}


# ===========================================================================
# Phiên đăng nhập: lấy cookie/header từ chính trình duyệt đã đăng nhập
# ===========================================================================


@dataclass
class SessionState:
    """
    Ảnh chụp phiên đăng nhập hiện có, để gọi API bằng đúng quyền của người dùng.

    Cookie và header xác thực là thông tin nhạy cảm: mặc định chúng chỉ nằm
    trong bộ nhớ, log chỉ in bản rút gọn, và chỉ ghi ra đĩa khi bạn tự yêu cầu.
    """

    cookies: List[Dict[str, Any]] = field(default_factory=list, repr=False)
    headers: Dict[str, str] = field(default_factory=dict, repr=False)
    user_agent: Optional[str] = None
    captured_at: str = field(default_factory=now_iso)

    # Header cần cho request API; các header điều khiển của HTTP/2 thì bỏ.
    _FORWARD_HEADERS = (
        "authorization", "cookie", "x-goog-authuser", "x-goog-api-key",
        "x-client-data", "x-goog-visitor-id", "user-agent", "referer", "origin",
        "content-type", "accept", "accept-language",
    )
    _SECRET_HEADERS = ("authorization", "cookie", "x-goog-api-key")

    @classmethod
    def capture(
        cls, context: "BrowserContext", observed_headers: Optional[Dict[str, str]] = None,
        base_url: str = DEFAULT_BASE_URL,
    ) -> "SessionState":
        """Đọc cookie từ context và gộp với header bắt được từ request thật."""
        cookies: List[Dict[str, Any]] = []
        try:
            cookies = list(context.cookies([base_url, "https://google.com"]))
        except Exception as exc:  # pragma: no cover - phụ thuộc trình duyệt
            LOG.debug("Không đọc được cookie từ context: %s", exc)

        headers: Dict[str, str] = {}
        for name, value in (observed_headers or {}).items():
            lowered = name.lower()
            if lowered in cls._FORWARD_HEADERS:
                headers[lowered] = value

        return cls(cookies=cookies, headers=headers, user_agent=headers.get("user-agent"))

    def cookie_header(self) -> str:
        """Chuỗi Cookie: ... dựng từ cookie của context."""
        return "; ".join(f"{c['name']}={c['value']}" for c in self.cookies if c.get("name"))

    def request_headers(self) -> Dict[str, str]:
        """Header dùng để gọi API thay cho người dùng (ưu tiên header bắt được thật)."""
        headers = dict(self.headers)
        if "cookie" not in headers and self.cookies:
            headers["cookie"] = self.cookie_header()
        return headers

    def summary(self) -> Dict[str, Any]:
        """Bản rút gọn, AN TOÀN để ghi log và lưu vào lịch sử — không chứa bí mật."""
        domains = sorted({str(c.get("domain", "")) for c in self.cookies if c.get("domain")})
        return {
            "captured_at": self.captured_at,
            "cookie_count": len(self.cookies),
            "cookie_domains": domains[:8],
            "auth_headers_present": sorted(
                name for name in self.headers if name in self._SECRET_HEADERS
            ),
            "header_names": sorted(self.headers),
        }

    def save(self, path: Path) -> None:
        """
        Ghi cả cookie/header thật ra đĩa. CHỈ gọi khi người dùng yêu cầu rõ ràng.

        File được đặt quyền 0600 vì nội dung đủ để mạo danh phiên đăng nhập.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "captured_at": self.captured_at,
            "user_agent": self.user_agent,
            "cookies": self.cookies,
            "headers": self.headers,
        }
        # Tạo file với quyền chặt NGAY TỪ ĐẦU, tránh khoảnh khắc file mở rộng quyền.
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        LOG.warning(
            "Đã ghi cookie/header phiên đăng nhập vào %s (quyền 0600). "
            "File này đủ để mạo danh bạn — đừng commit, đừng gửi cho ai.", path,
        )


# ===========================================================================
# Theo dõi mạng: bắt mã tác vụ và trạng thái từ chính request của trang
# ===========================================================================


@dataclass
class NetEvent:
    """Một response đáng quan tâm đã bắt được."""

    kind: str                      # "generate" | "status"
    url: str
    status_code: int
    at: float
    task_ids: List[str] = field(default_factory=list)
    state: Optional[str] = None    # "done" | "failed" | "pending" | None
    media_urls: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def short_url(self, limit: int = 90) -> str:
        return self.url if len(self.url) <= limit else self.url[:limit] + "…"


def classify_url(url: str, hosts: Sequence[str] = API_HOST_HINTS) -> Optional[str]:
    """Xếp loại một URL: request tạo video, request hỏi trạng thái, hay không quan tâm."""
    lowered = url.lower()
    if not any(host in lowered for host in hosts):
        return None
    # Hỏi trạng thái xét trước, vì URL loại này thường chứa cả chữ "generate".
    if any(hint in lowered for hint in STATUS_URL_HINTS):
        return "status"
    if any(hint in lowered for hint in GENERATE_URL_HINTS):
        return "generate"
    return None


class NetworkMonitor:
    """
    Nghe `page.on("response", ...)` để biết Flow đã nhận tác vụ nào và tác vụ xong chưa.

    Playwright bản đồng bộ phát sự kiện trên chính luồng đang chạy (chỉ trong lúc
    bạn gọi một hàm Playwright khác), nên danh sách sự kiện ở đây không cần khoá.
    Đổi lại: muốn nhận sự kiện thì phải chờ bằng `page.wait_for_timeout()`,
    KHÔNG dùng `time.sleep()` — xem hàm `_sleep()` ở cuối file.
    """

    def __init__(
        self, *, capture_bodies: bool = True, max_events: int = 500,
        extra_hosts: Sequence[str] = (),
    ) -> None:
        self.capture_bodies = capture_bodies
        # Thêm host của --base-url để chạy thử được với máy chủ giả lập.
        self.hosts: Tuple[str, ...] = tuple(API_HOST_HINTS) + tuple(h for h in extra_hosts if h)
        self.max_events = max_events
        self.events: List[NetEvent] = []
        self.observed_headers: Dict[str, str] = {}
        self.seen_api_calls: int = 0
        self._page: Optional["Page"] = None

    # --- gắn / gỡ ---------------------------------------------------------

    def attach(self, page: "Page") -> None:
        """Bắt đầu nghe request/response của trang."""
        self.detach()
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        self._page = page
        LOG.debug("Đã gắn bộ theo dõi mạng vào trang %s", page.url)

    def detach(self) -> None:
        """Ngừng nghe (bỏ qua lỗi nếu trang đã đóng)."""
        if self._page is None:
            return
        try:
            self._page.remove_listener("request", self._on_request)
            self._page.remove_listener("response", self._on_response)
        except Exception as exc:  # pragma: no cover - trang có thể đã đóng
            LOG.debug("Không gỡ được listener: %s", exc)
        self._page = None

    # --- xử lý sự kiện ----------------------------------------------------

    def _on_request(self, request: "Request") -> None:
        """Ghi lại header xác thực của request API đầu tiên bắt gặp."""
        try:
            if classify_url(request.url, self.hosts) is None:
                return
            self.seen_api_calls += 1
            if self.observed_headers:
                return
            headers = dict(request.headers or {})
            self.observed_headers = {k.lower(): v for k, v in headers.items()}
            LOG.debug("Đã lấy header phiên từ request %s", request.url[:80])
        except Exception as exc:  # pragma: no cover - listener không được phép ném lỗi
            LOG.debug("Bỏ qua lỗi khi đọc request: %s", exc)

    def _on_response(self, response: "Response") -> None:
        """Đọc response API, rút mã tác vụ / trạng thái / link media."""
        try:
            kind = classify_url(response.url, self.hosts)
            if kind is None:
                return
            event = NetEvent(
                kind=kind, url=response.url, status_code=response.status, at=time.monotonic()
            )
            body = self._read_body(response)
            if body is not None:
                self._fill_from_body(event, body)
            self._record(event)
        except Exception as exc:  # pragma: no cover - listener không được phép ném lỗi
            LOG.debug("Bỏ qua lỗi khi đọc response: %s", exc)

    def _read_body(self, response: "Response") -> Optional[Any]:
        """
        Lấy nội dung response, chấp nhận cả JSON lẫn văn bản thô.

        Đọc body là một lượt hỏi ngược lại trình duyệt nên có thể thất bại
        (response chuyển hướng, body đã bị giải phóng...). Thất bại thì bỏ qua:
        vẫn còn tín hiệu từ URL, mã HTTP và từ giao diện.
        """
        if not self.capture_bodies:
            return None
        if response.status in (204, 301, 302, 303, 304, 307, 308):
            return None
        try:
            text = response.text()
        except Exception as exc:
            LOG.debug("Không đọc được body của %s: %s", response.url[:60], exc)
            return None
        if not text or len(text) > 2_000_000:
            return None
        parsed = parse_json_loose(text)
        return parsed if parsed is not None else text

    @staticmethod
    def _fill_from_body(event: NetEvent, body: Any) -> None:
        """Rút thông tin từ body đã đọc được vào sự kiện."""
        if isinstance(body, str):
            # Không phải JSON: ít nhất vét lấy link media.
            event.media_urls = scrape_media_urls(body)
            return

        ids = [str(v) for v in deep_collect(body, TASK_ID_KEYS) if isinstance(v, (str, int))]
        # Id thật thường dài; bỏ những giá trị ngắn kiểu "1", "ok" cho đỡ nhiễu.
        event.task_ids = [i for i in ids if len(i) >= 6][:10]

        event.state = normalize_status(deep_find(body, STATUS_KEYS))
        event.media_urls = [
            str(u) for u in deep_collect(body, MEDIA_URL_KEYS)
            if isinstance(u, str) and u.startswith("http")
        ][:10]
        if event.state == "failed" or event.status_code >= 400:
            error = deep_find(body, ERROR_KEYS)
            event.error = str(error)[:500] if error else None

    def _record(self, event: NetEvent) -> None:
        self.events.append(event)
        if len(self.events) > self.max_events:
            del self.events[: len(self.events) - self.max_events]
        LOG.debug(
            "Bắt được [%s] HTTP %s ids=%s state=%s %s",
            event.kind, event.status_code, event.task_ids[:2], event.state, event.short_url(60),
        )

    # --- truy vấn ---------------------------------------------------------

    def mark(self) -> int:
        """Đánh dấu vị trí hiện tại để sau này chỉ đọc sự kiện mới."""
        return len(self.events)

    def since(self, mark: int) -> List[NetEvent]:
        """Các sự kiện phát sinh sau mốc đã đánh dấu."""
        return self.events[mark:]


# ===========================================================================
# Lịch sử tác vụ
# ===========================================================================


@dataclass
class JobRecord:
    """Một lần gửi prompt — đúng những gì sẽ ghi vào jobs_history.json."""

    prompt: str
    index: int
    status: str = "pending"      # pending|submitted|done|failed|timeout|error|dry-run
    task_id: Optional[str] = None
    task_ids: List[str] = field(default_factory=list)
    project_id: Optional[str] = None
    project_url: Optional[str] = None
    submitted_at: str = field(default_factory=now_iso)
    finished_at: Optional[str] = None
    duration_s: Optional[float] = None
    settings: Dict[str, str] = field(default_factory=dict)
    settings_applied: Dict[str, str] = field(default_factory=dict)
    media_urls: List[str] = field(default_factory=list)
    error: Optional[str] = None
    signals: List[str] = field(default_factory=list)

    # Trạng thái nội bộ nối submit_prompt() với wait_for_job(): mốc sự kiện mạng và
    # số media có trên khung vẽ ngay trước lúc gửi. Không ghi ra jobs_history.json.
    watch_mark: int = field(default=0, repr=False)
    baseline_media: int = field(default=0, repr=False)

    def note(self, signal: str) -> None:
        """Ghi lại vì sao kết luận như vậy (bắt được từ mạng hay từ giao diện)."""
        if signal not in self.signals:
            self.signals.append(signal)

    def finish(self, status: str, *, error: Optional[str] = None) -> None:
        """Chốt trạng thái và tính thời gian chạy."""
        self.status = status
        self.error = error
        self.finished_at = now_iso()
        try:
            started = datetime.fromisoformat(self.submitted_at)
            ended = datetime.fromisoformat(self.finished_at)
            self.duration_s = round((ended - started).total_seconds(), 1)
        except ValueError:  # pragma: no cover - chỉ xảy ra nếu chuỗi giờ hỏng
            self.duration_s = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "prompt": self.prompt,
            "status": self.status,
            "task_id": self.task_id,
            "task_ids": self.task_ids,
            "project_id": self.project_id,
            "project_url": self.project_url,
            "submitted_at": self.submitted_at,
            "finished_at": self.finished_at,
            "duration_s": self.duration_s,
            "settings": self.settings,
            "settings_applied": self.settings_applied,
            "media_urls": self.media_urls,
            "error": self.error,
            "signals": self.signals,
        }


class JobHistory:
    """
    Sổ ghi các tác vụ đã gửi, lưu ở `jobs_history.json`.

    Ghi kiểu thay thế nguyên tử (ghi file tạm rồi đổi tên) để lỡ có ngắt giữa
    chừng thì file cũ vẫn còn nguyên, không bị cụt.
    """

    VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> List[Dict[str, Any]]:
        """Đọc các bản ghi cũ; file hỏng thì đổi tên giữ lại rồi bắt đầu lại từ đầu."""
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            LOG.warning("File lịch sử %s không đọc được (%s); bỏ qua nội dung cũ.", self.path, exc)
            try:
                backup = self.path.with_suffix(self.path.suffix + ".bak")
                self.path.replace(backup)
                LOG.warning("Đã giữ lại bản cũ ở %s", backup)
            except (OSError, ValueError):
                pass
            return []
        if isinstance(data, dict) and isinstance(data.get("jobs"), list):
            return data["jobs"]
        if isinstance(data, list):  # dạng cũ: mảng phẳng
            return data
        return []

    def append(self, records: Sequence[JobRecord]) -> Path:
        """Thêm bản ghi mới vào cuối lịch sử và lưu xuống đĩa."""
        jobs = self.load()
        jobs.extend(record.to_dict() for record in records)
        payload = {
            "version": self.VERSION,
            "updated_at": now_iso(),
            "jobs": jobs,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        tmp.replace(self.path)  # đổi tên trong cùng thư mục là thao tác nguyên tử
        return self.path


# ===========================================================================
# Tìm phần tử trên giao diện Flow
# ===========================================================================

# Một "cách tìm" gồm tên gọi dễ hiểu và hàm dựng locator.
LocatorBuilder = Tuple[str, Callable[[], "Locator"]]


def first_visible(
    what: str, builders: Sequence[LocatorBuilder], timeout_ms: int
) -> "Locator":
    """
    Trả về locator đầu tiên nhìn thấy được trong danh sách cách tìm.

    Đây là chỗ chống vỡ khi Google đổi giao diện: mỗi thành phần đều có NHIỀU cách
    tìm, xếp từ bền nhất (vai trò + nhãn hiển thị) đến tạm bợ nhất (thẻ HTML thô).
    Quay vòng lại từ đầu cho tới khi hết giờ, vì giao diện Flow dựng dần — cách tìm
    bền nhất có thể chưa sẵn sàng ở vòng đầu. Tuyệt đối không dùng XPath cứng.

    :raises ElementNotFound: hết giờ mà không cách nào thấy phần tử.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    tried: List[str] = []
    while True:
        for name, build in builders:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                locator = build().first
                locator.wait_for(state="visible", timeout=max(250, min(1500, remaining * 1000)))
                LOG.debug("Tìm thấy %s bằng cách: %s", what, name)
                return locator
            except Exception:
                if name not in tried:
                    tried.append(name)
        if time.monotonic() >= deadline:
            break
    raise ElementNotFound(
        f"Không tìm thấy {what} sau {timeout_ms / 1000:.0f}s. "
        f"Nhiều khả năng Flow đã đổi giao diện — sửa phần 'PHẦN PHỤ THUỘC GOOGLE FLOW' "
        f"ở đầu file. Đã thử: {', '.join(tried) or 'không có cách nào'}.",
        what=what, tried=tried,
    )


def find_prompt_input(
    page: "Page", config: Optional[FlowConfig] = None, timeout_ms: Optional[int] = None
) -> "Locator":
    """Tìm ô nhập prompt chính ("What do you want to create?")."""
    config = config or FlowConfig()
    builders: List[LocatorBuilder] = [
        ("vai trò textbox + nhãn", lambda: page.get_by_role("textbox", name=PROMPT_TEXT_RE)),
        ("placeholder", lambda: page.get_by_placeholder(PROMPT_TEXT_RE)),
        ("aria-label", lambda: page.locator(
            "textarea[aria-label], input[aria-label]"
        ).filter(has_not=page.locator("[aria-hidden='true']"))),
        ("contenteditable", lambda: page.locator("[contenteditable='true'][role='textbox']")),
        ("textarea bất kỳ", lambda: page.locator("textarea:not([disabled])")),
        ("textbox bất kỳ", lambda: page.get_by_role("textbox")),
    ]
    return first_visible("ô nhập prompt", builders, timeout_ms or config.ready_timeout_ms)


def find_submit_button(
    page: "Page", config: Optional[FlowConfig] = None, timeout_ms: int = 4000
) -> Optional["Locator"]:
    """Tìm nút gửi (mũi tên / Create). Không thấy thì trả None để chuyển sang nhấn Enter."""
    builders: List[LocatorBuilder] = [
        ("nút theo tên", lambda: page.get_by_role("button", name=SUBMIT_TEXT_RE)),
        ("nút submit", lambda: page.locator("button[type='submit']:not([disabled])")),
        ("icon mũi tên", lambda: page.locator(
            "button:has-text('arrow_forward'), button:has([class*='arrow'])"
        )),
        ("aria-label gửi", lambda: page.locator(
            "button[aria-label*='end' i], button[aria-label*='reate' i], "
            "button[aria-label*='ửi' i], button[aria-label*='ạo' i]"
        )),
    ]
    try:
        return first_visible("nút gửi", builders, timeout_ms)
    except ElementNotFound:
        LOG.debug("Không thấy nút gửi; sẽ gửi bằng phím Enter.")
        return None


def count_media(page: "Page") -> int:
    """Đếm số media đang hiện trên khung vẽ — tín hiệu phụ để biết tác vụ đã xong."""
    try:
        return page.locator("video, video source[src]").count()
    except Exception:
        return 0


def is_busy(page: "Page") -> bool:
    """Giao diện có đang báo "đang tạo" không."""
    for build in (
        lambda: page.get_by_text(BUSY_TEXT_RE),
        lambda: page.locator("[role='progressbar'], progress"),
    ):
        try:
            if build().first.is_visible(timeout=800):
                return True
        except Exception:
            continue
    return False


# ===========================================================================
# Điền prompt và bấm gửi
# ===========================================================================


def _prompt_matches(field_locator: "Locator", prompt: str) -> bool:
    """So nội dung ô nhập với prompt (chỉ cần khớp phần đầu là đủ)."""
    head = prompt.strip()[:40]
    for read in (
        lambda: field_locator.input_value(timeout=2000),
        lambda: field_locator.inner_text(timeout=2000),
    ):
        try:
            actual = (read() or "").strip()
        except Exception:
            continue
        if actual and head[:20] in actual:
            return True
    return False


def fill_prompt(
    page: "Page", prompt: str, config: Optional[FlowConfig] = None
) -> "Locator":
    """
    Điền prompt vào ô nhập và kiểm tra lại là chữ đã vào thật.

    :raises SubmitFailed: ô nhập không nhận được nội dung (bị khoá hoặc bị che).
    """
    config = config or FlowConfig()
    field_locator = find_prompt_input(page, config)
    field_locator.click(timeout=config.action_timeout_ms)
    try:
        field_locator.fill(prompt, timeout=config.action_timeout_ms)
    except Exception as exc:
        # Ô contenteditable đôi khi không nhận fill() — gõ từng phím thay thế.
        LOG.debug("fill() không được (%s), chuyển sang gõ phím.", exc)
        try:
            field_locator.press("Control+A")
            page.keyboard.press("Delete")
        except Exception:
            pass
        page.keyboard.type(prompt, delay=8)

    if not _prompt_matches(field_locator, prompt):
        raise SubmitFailed(
            "Điền prompt xong nhưng ô nhập không chứa đúng nội dung — "
            "có thể ô đang bị khoá hoặc bị thành phần khác che.",
            prompt=prompt,
        )
    return field_locator


def click_submit(
    page: "Page", field_locator: "Locator", config: Optional[FlowConfig] = None
) -> str:
    """Kích hoạt lệnh tạo. Trả về cách đã dùng ("nút gửi" hay "phím Enter")."""
    config = config or FlowConfig()
    button = find_submit_button(page, config)
    if button is not None:
        try:
            button.click(timeout=config.action_timeout_ms)
            return "nút gửi"
        except Exception as exc:
            LOG.debug("Bấm nút gửi không được (%s), thử phím Enter.", exc)
    try:
        field_locator.press("Enter", timeout=config.action_timeout_ms)
        return "phím Enter"
    except Exception as exc:
        raise SubmitFailed(f"Không kích hoạt được lệnh tạo: {exc}") from exc


# ===========================================================================
# Thiết lập đầu ra (mô hình, độ phân giải, thời lượng...)
# ===========================================================================


def _open_settings_panel(page: "Page", config: FlowConfig) -> bool:
    """Mở bảng thiết lập đầu ra. Trả True nếu mở được."""
    builders: List[LocatorBuilder] = [
        ("nút theo tên", lambda: page.get_by_role("button", name=SETTINGS_TEXT_RE)),
        ("aria-label", lambda: page.locator(
            "button[aria-label*='etting' i], button[aria-label*='ption' i], "
            "button[aria-label*='ài đặt' i]"
        )),
        ("icon tune", lambda: page.locator(
            "button:has-text('tune'), button:has-text('settings')"
        )),
    ]
    try:
        button = first_visible("nút thiết lập", builders, 4000)
        button.click(timeout=config.action_timeout_ms)
        page.wait_for_timeout(600)
        return True
    except Exception as exc:
        LOG.debug("Không mở được bảng thiết lập: %s", exc)
        return False


def _click_value_directly(page: "Page", config: FlowConfig, value_re: "re.Pattern[str]") -> bool:
    """Bấm thẳng vào chip/nút mang đúng giá trị (ví dụ nút "720p")."""
    for build in (
        lambda: page.get_by_role("button", name=value_re),
        lambda: page.get_by_role("radio", name=value_re),
        lambda: page.get_by_text(value_re),
    ):
        try:
            target = build().first
            target.wait_for(state="visible", timeout=1200)
            target.click(timeout=config.action_timeout_ms)
            return True
        except Exception:
            continue
    return False


def _set_one_setting(page: "Page", config: FlowConfig, name: str, value: str) -> bool:
    """Đặt một thiết lập: mở ô chọn theo nhãn rồi bấm giá trị mong muốn."""
    label_re = SETTING_LABEL_RE.get(name, re.compile(re.escape(name), re.I))
    value_re = re.compile(re.escape(str(value)), re.I)

    control_builders: List[LocatorBuilder] = [
        ("combobox theo nhãn", lambda: page.get_by_role("combobox", name=label_re)),
        ("button theo nhãn", lambda: page.get_by_role("button", name=label_re)),
        ("aria-label", lambda: page.locator(f"[aria-label*='{name}' i]")),
    ]
    try:
        control = first_visible(f"ô chọn {name}", control_builders, 2500)
    except ElementNotFound:
        # Không có ô chọn: có thể giá trị hiện thẳng thành nút/chip (ví dụ "720p").
        return _click_value_directly(page, config, value_re)

    # Thử <select> thật trước — nhanh và chắc chắn nhất.
    try:
        if (control.evaluate("el => el.tagName") or "").upper() == "SELECT":
            control.select_option(label=str(value), timeout=config.action_timeout_ms)
            return True
    except Exception:
        pass

    control.click(timeout=config.action_timeout_ms)
    page.wait_for_timeout(400)
    option_builders: List[LocatorBuilder] = [
        ("option", lambda: page.get_by_role("option", name=value_re)),
        ("menuitem", lambda: page.get_by_role("menuitemradio", name=value_re)),
        ("menu", lambda: page.get_by_role("menuitem", name=value_re)),
        ("radio", lambda: page.get_by_role("radio", name=value_re)),
        ("văn bản trong danh sách", lambda: page.locator(
            "[role='listbox'], [role='menu'], [role='dialog']"
        ).get_by_text(value_re)),
    ]
    try:
        option = first_visible(f"giá trị {value}", option_builders, 2500)
        option.click(timeout=config.action_timeout_ms)
        page.wait_for_timeout(300)
        return True
    except ElementNotFound:
        # Ô nhập số (thời lượng chẳng hạn) thay vì danh sách chọn.
        try:
            control.fill(str(value), timeout=config.action_timeout_ms)
            return True
        except Exception:
            page.keyboard.press("Escape")
            return False


# ===========================================================================
# Phiên làm việc: gói trình duyệt + trang + bộ theo dõi mạng vào một chỗ
# ===========================================================================


@dataclass
class FlowSession:
    """
    Mọi thứ cần để thao tác với Flow. Hầu hết các hàm dưới đây nhận nó làm tham số đầu.

    Đừng dựng tay: hãy dùng `connect_browser()` hoặc `flow_session()`.
    """

    config: FlowConfig
    page: "Page"
    context: "BrowserContext"
    monitor: NetworkMonitor
    playwright: Optional["Playwright"] = None
    browser: Optional["Browser"] = None

    # Trình duyệt/tab do script tự mở thì mới được phép đóng lúc kết thúc.
    owns_browser: bool = False
    owns_page: bool = False

    # Nhớ việc đã làm để gọi lại không bị lặp.
    project_url: Optional[str] = None
    applied_settings: Optional[Dict[str, str]] = None
    state: Optional[SessionState] = None


def _merge_config(config: Optional[FlowConfig], overrides: Dict[str, Any]) -> FlowConfig:
    """Gộp FlowConfig có sẵn với các tham số truyền lẻ, báo lỗi rõ nếu sai tên."""
    if not overrides:
        return config or FlowConfig()
    valid = set(FlowConfig.__dataclass_fields__)
    unknown = sorted(set(overrides) - valid)
    if unknown:
        raise FlowError(
            f"Không có tham số cấu hình: {', '.join(unknown)}. "
            f"Các tên hợp lệ: {', '.join(sorted(valid))}.",
            unknown=unknown,
        )
    return replace(config, **overrides) if config else FlowConfig(**overrides)


def _sleep(session: FlowSession, seconds: float) -> None:
    """
    Chờ mà VẪN nhận được sự kiện mạng.

    Playwright bản đồng bộ chỉ phát sự kiện trong lúc đang ở trong một lệnh
    Playwright, nên phải chờ bằng wait_for_timeout chứ không phải time.sleep.
    """
    try:
        session.page.wait_for_timeout(max(0, seconds) * 1000)
    except Exception:  # pragma: no cover - tab có thể đã đóng
        time.sleep(max(0, seconds))


def connect_browser(config: Optional[FlowConfig] = None, **overrides: Any) -> FlowSession:
    """
    Gắn vào Chrome đang chạy qua CDP; không được thì mở profile có sẵn trên máy.

    Cả hai lối đều dựa trên phiên bạn đã tự đăng nhập — hàm này không tự đăng nhập.

        session = connect_browser(project="abc123", resolution="720p")

    :param config: FlowConfig dựng sẵn (không bắt buộc).
    :param overrides: đặt lẻ từng tham số của FlowConfig, ví dụ ``cdp_url="..."``.
    :raises ConnectionFailed: không gắn được vào trình duyệt nào.
    """
    config = _merge_config(config, overrides)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - phụ thuộc môi trường
        raise ConnectionFailed(
            "Chưa cài Playwright. Chạy:  pip install playwright && playwright install chromium"
        ) from exc

    playwright = sync_playwright().start()
    browser: Optional["Browser"] = None
    owns_browser = False
    try:
        browser, context = _connect_over_cdp(playwright, config)
    except ConnectionFailed as cdp_error:
        if not config.user_data_dir:
            playwright.stop()
            raise
        LOG.warning("Không gắn được qua CDP (%s). Chuyển sang mở profile có sẵn.", cdp_error)
        try:
            context = _launch_persistent(playwright, config)
        except ConnectionFailed:
            playwright.stop()
            raise
        owns_browser = True

    page, owns_page = _pick_page(context, config)
    monitor = NetworkMonitor(
        capture_bodies=config.capture_bodies, extra_hosts=(config.host,)
    )
    monitor.attach(page)
    return FlowSession(
        config=config, page=page, context=context, monitor=monitor,
        playwright=playwright, browser=browser,
        owns_browser=owns_browser, owns_page=owns_page,
    )


def _connect_over_cdp(
    playwright: "Playwright", config: FlowConfig
) -> Tuple["Browser", "BrowserContext"]:
    """Gắn vào cửa sổ Chrome đang mở sẵn cổng gỡ lỗi."""
    LOG.info("==> Gắn vào Chrome qua CDP: %s", config.cdp_url)
    try:
        browser = playwright.chromium.connect_over_cdp(config.cdp_url)
    except Exception as exc:
        raise ConnectionFailed(
            f"Không gắn được vào {config.cdp_url}: {exc}\n"
            "Hãy mở Chrome kèm cổng gỡ lỗi, dùng profile RIÊNG (Chrome 136+ chặn cổng "
            "gỡ lỗi trên profile mặc định):\n"
            '  google-chrome --remote-debugging-port=9222 '
            '--user-data-dir="$HOME/.config/chrome-flow"\n'
            "rồi tự đăng nhập Google trong cửa sổ đó.",
            cdp_url=config.cdp_url,
        ) from exc

    contexts = browser.contexts
    if not contexts:
        raise ConnectionFailed(
            "Gắn được vào Chrome nhưng không thấy cửa sổ nào đang mở. "
            "Hãy mở một tab trong cửa sổ đó rồi chạy lại."
        )
    LOG.info("    Đã gắn. Số context: %d, số tab: %d",
             len(contexts), sum(len(c.pages) for c in contexts))
    return browser, contexts[0]


def _launch_persistent(playwright: "Playwright", config: FlowConfig) -> "BrowserContext":
    """Mở trình duyệt bằng profile có sẵn trên máy (lối dự phòng khi không có CDP)."""
    user_data_dir = config.user_data_dir
    assert user_data_dir is not None
    LOG.info("==> Mở trình duyệt với profile: %s", user_data_dir)
    try:
        return playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            channel=config.channel or None,
            executable_path=str(config.executable_path) if config.executable_path else None,
            headless=config.headless,
            args=["--disable-blink-features=AutomationControlled", *config.browser_args],
        )
    except Exception as exc:
        raise ConnectionFailed(
            f"Không mở được profile {user_data_dir}: {exc}\n"
            "Thường là do profile đang bị một cửa sổ Chrome khác giữ — đóng Chrome rồi thử lại.",
            user_data_dir=str(user_data_dir),
        ) from exc


def _pick_page(context: "BrowserContext", config: FlowConfig) -> Tuple["Page", bool]:
    """Chọn tab đang ở Flow; không có thì mở tab mới. Trả (tab, có phải tab mình mở)."""
    for page in context.pages:
        try:
            if config.host in (page.url or ""):
                LOG.info("    Dùng tab Flow đang mở: %s", page.url)
                page.bring_to_front()
                return page, False
        except Exception:
            continue
    if context.pages and not config.project:
        # Không biết mở project nào thì dùng tab hiện có, để open_project báo lỗi rõ.
        return context.pages[0], False
    LOG.info("    Mở tab mới cho Flow.")
    return context.new_page(), True


def close_session(session: FlowSession) -> None:
    """Nhả mọi thứ. Tuyệt đối không tắt trình duyệt mà người dùng đang dùng."""
    session.monitor.detach()
    if session.owns_page and session.config.close_tab:
        try:
            session.page.close()
        except Exception as exc:  # pragma: no cover
            LOG.debug("Không đóng được tab: %s", exc)
    if session.owns_browser:
        try:
            session.context.close()
        except Exception as exc:  # pragma: no cover
            LOG.debug("Không đóng được context: %s", exc)
    elif session.browser is not None:
        try:
            # Với CDP, close() chỉ ngắt kết nối — cửa sổ của người dùng vẫn còn.
            session.browser.close()
        except Exception as exc:  # pragma: no cover
            LOG.debug("Không ngắt được kết nối trình duyệt: %s", exc)
    if session.playwright is not None:
        try:
            session.playwright.stop()
        except Exception as exc:  # pragma: no cover
            LOG.debug("Không dừng được Playwright: %s", exc)
        session.playwright = None


@contextmanager
def flow_session(
    config: Optional[FlowConfig] = None, **overrides: Any
) -> "Iterator[FlowSession]":
    """
    Mở phiên làm việc và chắc chắn nhả kết nối khi xong.

        with flow_session(project="abc123") as session:
            open_project(session)
            generate(session, "biển đêm")
    """
    session = connect_browser(config, **overrides)
    try:
        yield session
    finally:
        close_session(session)


# ===========================================================================
# Điều hướng và thiết lập
# ===========================================================================


def open_project(session: FlowSession, project: Optional[str] = None) -> str:
    """
    Đưa tab về đúng URL project và chờ giao diện sẵn sàng. Trả về URL cuối cùng.

    Không truyền project (và config cũng không có) thì chấp nhận tab đang mở,
    miễn là đang ở Flow.

    :raises NavigationFailed: không mở được, hoặc phiên chưa đăng nhập Google.
    """
    config = session.config
    page = session.page
    target = resolve_project_url(project or config.project, config.base_url)
    current = page.url or ""

    if target:
        if not current.startswith(target):
            LOG.info("==> Mở project: %s", target)
            try:
                page.goto(target, wait_until="domcontentloaded", timeout=config.ready_timeout_ms)
            except Exception as exc:
                raise NavigationFailed(f"Không mở được {target}: {exc}", url=target) from exc
        else:
            LOG.info("==> Tab đang ở đúng project: %s", current)
    elif config.host not in current:
        raise NavigationFailed(
            "Tab đang mở không phải Google Flow và bạn chưa chỉ định project. "
            "Hãy mở sẵn project trong trình duyệt, hoặc truyền project='<id-hoặc-URL>'.",
            url=current,
        )
    else:
        LOG.info("==> Dùng tab Flow đang mở: %s", current)

    wait_until_ready(session)

    final_url = page.url
    if config.host not in final_url:
        # Chưa đăng nhập thì Google đá sang accounts.google.com.
        raise NavigationFailed(
            f"Trình duyệt bị chuyển sang {final_url}. Nhiều khả năng phiên này chưa "
            "đăng nhập Google. Hãy tự đăng nhập trong chính cửa sổ đó rồi chạy lại — "
            "script không tự đăng nhập hộ.",
            url=final_url,
        )
    session.project_url = final_url
    return final_url


def wait_until_ready(session: FlowSession) -> None:
    """Chờ khung vẽ và ô nhập prompt dựng xong."""
    page, config = session.page, session.config
    try:
        page.wait_for_load_state("domcontentloaded", timeout=config.ready_timeout_ms)
    except Exception as exc:
        LOG.debug("Chờ domcontentloaded không thành: %s", exc)
    # Khung chính (canvas) — không có cũng không sao, chỉ là tín hiệu phụ.
    for selector in ("main", "[role='main']", "canvas", "[class*='canvas']"):
        try:
            page.locator(selector).first.wait_for(state="attached", timeout=3000)
            LOG.debug("Khung chính đã có (%s).", selector)
            break
        except Exception:
            continue
    find_prompt_input(page, config)  # thứ này thì bắt buộc phải có
    LOG.info("==> Giao diện đã sẵn sàng.")


def apply_output_settings(
    session: FlowSession, settings: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    """
    Chọn các thiết lập đầu ra (mô hình, độ phân giải, thời lượng, số bản...).

    Đây là bước "có thì tốt": Flow đổi bảng thiết lập khá thường xuyên, nên hỏng
    bước này chỉ cảnh báo chứ KHÔNG ném lỗi — bạn vẫn tạo được video, chỉ là theo
    thiết lập đang có sẵn trên giao diện.

    :param settings: ví dụ ``{"resolution": "720p", "duration": "8"}``.
        Bỏ trống thì lấy từ FlowConfig của phiên.
    :return: những thiết lập đặt được thật.
    """
    page, config = session.page, session.config
    wanted = settings if settings is not None else config.desired_settings()
    if not wanted:
        session.applied_settings = {}
        return {}

    LOG.info("==> Đặt thiết lập đầu ra: %s", ", ".join(f"{k}={v}" for k, v in wanted.items()))
    if not _open_settings_panel(page, config):
        LOG.warning(
            "Không mở được bảng thiết lập — bỏ qua %s, dùng thiết lập sẵn có trên giao diện.",
            list(wanted),
        )
        session.applied_settings = {}
        return {}

    applied: Dict[str, str] = {}
    for name, value in wanted.items():
        try:
            if _set_one_setting(page, config, name, str(value)):
                applied[name] = str(value)
                LOG.info("    • %s = %s", name, value)
            else:
                LOG.warning("    • Không đặt được %s = %s (bỏ qua).", name, value)
        except Exception as exc:
            LOG.warning("    • Lỗi khi đặt %s = %s: %s (bỏ qua).", name, value, exc)

    try:  # đóng bảng thiết lập để nó không che ô nhập prompt
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception as exc:  # pragma: no cover
        LOG.debug("Không đóng được bảng thiết lập: %s", exc)

    session.applied_settings = applied
    return applied


# ===========================================================================
# Phiên đăng nhập: lấy cookie/header từ chính trình duyệt đã đăng nhập
# ===========================================================================


def capture_session_state(
    session: FlowSession, save_to: Optional[Path] = None
) -> SessionState:
    """
    Chụp cookie/header của phiên đang đăng nhập để gọi API bằng đúng quyền người dùng.

    Mặc định chỉ giữ trong bộ nhớ và log bản rút gọn. Chỉ ghi ra đĩa khi bạn truyền
    `save_to` (hoặc đặt `session_out` trong FlowConfig) — file đó đủ để mạo danh
    phiên đăng nhập của bạn nên được đặt quyền 0600.
    """
    session.state = SessionState.capture(
        session.context, session.monitor.observed_headers, session.config.base_url
    )
    LOG.info("==> Phiên đăng nhập: %s", json.dumps(session.state.summary(), ensure_ascii=False))
    target = save_to or session.config.session_out
    if target:
        session.state.save(Path(target))
    return session.state


def verify_media_url(session: FlowSession, url: str) -> Optional[int]:
    """
    Kiểm tra link media có mở được bằng chính phiên của người dùng không.

    Dùng APIRequestContext của trình duyệt nên cookie đi kèm sẵn — không phải sao
    chép thông tin đăng nhập ra ngoài. Trả mã HTTP, hoặc None nếu không hỏi được.
    """
    try:
        response = session.context.request.head(url, timeout=15_000)
        LOG.debug("Kiểm tra media %s -> HTTP %s", url[:70], response.status)
        return response.status
    except Exception as exc:
        LOG.debug("Không kiểm tra được media %s: %s", url[:70], exc)
        return None


# ===========================================================================
# Gửi prompt và theo dõi tới khi xong
# ===========================================================================


def event_matches(job: JobRecord, event: NetEvent) -> bool:
    """
    Sự kiện mạng này có nói về tác vụ đang theo dõi không?

    Khớp theo mã tác vụ khi đã biết mã. Chưa biết mã thì chấp nhận sự kiện trạng
    thái bất kỳ — vì các prompt chạy tuần tự nên tại một thời điểm chỉ có đúng một
    tác vụ do script này gửi đang chờ.
    """
    if job.task_ids and event.task_ids:
        return bool(set(job.task_ids) & set(event.task_ids))
    return event.kind == "status" or bool(event.media_urls)


def absorb_event(job: JobRecord, event: NetEvent) -> None:
    """Cập nhật bản ghi theo một sự kiện mạng, nếu sự kiện đó thuộc về tác vụ này."""
    if event.kind == "generate" and event.task_ids and not job.task_ids:
        job.task_ids = list(event.task_ids)
        job.task_id = event.task_ids[0]
        job.note("mã tác vụ lấy từ response tạo video")
        LOG.info("    Mã tác vụ: %s", job.task_id)

    # Chính request gửi tác vụ bị từ chối (hết hạn mức, prompt bị chặn...).
    # Xét TRƯỚC bước khớp mã tác vụ, vì response lỗi thường không kèm mã nào cả —
    # mà sự kiện này chắc chắn là của lượt gửi vừa rồi (đã lọc theo mốc thời gian).
    if event.kind == "generate" and event.status_code >= 400:
        job.finish("failed", error=event.error or f"Flow trả về HTTP {event.status_code}")
        job.note(f"mạng: HTTP {event.status_code} khi gửi tác vụ")
        return

    if not event_matches(job, event):
        return

    for url in event.media_urls:
        if url not in job.media_urls:
            job.media_urls.append(url)

    if event.state == "failed":
        job.finish("failed", error=event.error or "Flow báo tác vụ thất bại.")
        job.note("mạng: trạng thái thất bại")
    elif event.state == "done":
        job.finish("done")
        job.note("mạng: trạng thái hoàn tất")


def submit_prompt(session: FlowSession, prompt: str, index: int = 1) -> JobRecord:
    """
    Điền prompt rồi bấm tạo. KHÔNG chờ kết quả — dùng `wait_for_job()` để chờ.

    Bản ghi trả về đã mang sẵn mốc theo dõi mạng, nên có thể làm việc khác rồi
    mới quay lại chờ.

    :raises SubmitFailed: không điền được prompt hoặc không bấm được nút tạo.
    """
    page, config = session.page, session.config
    job = JobRecord(
        prompt=prompt, index=index,
        project_id=project_id_from_url(session.project_url),
        project_url=session.project_url,
        settings=config.desired_settings(),
        settings_applied=session.applied_settings or {},
    )
    job.baseline_media = count_media(page)
    job.watch_mark = session.monitor.mark()

    field_locator = fill_prompt(page, prompt, config)

    if config.dry_run:
        LOG.info("    [dry-run] Đã điền prompt, KHÔNG bấm nút tạo.")
        job.note("dry-run: chỉ điền prompt")
        job.finish("dry-run")
        return job

    how = click_submit(page, field_locator, config)
    job.submitted_at = now_iso()
    job.status = "submitted"
    job.note(f"đã gửi bằng {how}")
    LOG.info("    Đã gửi (%s). Đang chờ kết quả...", how)
    return job


def wait_for_job(session: FlowSession, job: JobRecord) -> JobRecord:
    """
    Chờ tác vụ chạy xong, khoảng cách hỏi tăng dần (exponential backoff).

    Hai nguồn tín hiệu, cái nào tới trước dùng cái đó:

    1. Mạng — response của Flow báo mã tác vụ và trạng thái (chính xác nhất).
    2. Giao diện — có thêm video mới trên khung vẽ và không còn báo "đang tạo"
       (phòng khi Google đổi endpoint khiến tín hiệu mạng không nhận ra được).

    :raises GenerationTimeout: hết thời gian chờ (`job.status` cũng thành "timeout").
    """
    config = session.config
    if job.status in ("done", "failed", "dry-run"):
        return job  # đã xong từ trước, không cần chờ

    deadline = time.monotonic() + config.generation_timeout_s
    delays = backoff_delays(config.poll_initial_s, config.poll_factor, config.poll_max_s)
    cursor = job.watch_mark
    last_log = 0.0
    started = time.monotonic()

    while True:
        # --- 1. tín hiệu mạng ---
        events = session.monitor.events[cursor:]
        cursor = len(session.monitor.events)
        for event in events:
            absorb_event(job, event)
            if job.status in ("done", "failed"):
                _finalize_job(session, job)
                return job

        # --- 2. tín hiệu giao diện ---
        current_media = count_media(session.page)
        if current_media > job.baseline_media and not is_busy(session.page):
            job.note(f"giao diện: số media tăng {job.baseline_media} → {current_media}")
            job.finish("done")
            _finalize_job(session, job)
            return job

        # --- 3. hết giờ ---
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            job.finish(
                "timeout",
                error=(
                    f"Quá {config.generation_timeout_s:.0f}s mà chưa thấy báo xong. "
                    "Tác vụ có thể vẫn đang chạy — mở lại project để xem, hoặc tăng "
                    "generation_timeout_s."
                ),
            )
            _finalize_job(session, job)
            raise GenerationTimeout(str(job.error), task_id=job.task_id)

        delay = min(next(delays), remaining)
        elapsed = time.monotonic() - started
        if elapsed - last_log >= 15:  # báo tiến độ 15s một lần cho đỡ ồn
            LOG.info("    ... đang chạy %.0fs (mã tác vụ: %s)",
                     elapsed, job.task_id or "chưa bắt được")
            last_log = elapsed
        _sleep(session, delay)


def _finalize_job(session: FlowSession, job: JobRecord) -> None:
    """Việc dọn cuối: kiểm tra link media nếu người dùng yêu cầu."""
    if job.status == "done" and job.media_urls:
        LOG.info("    Bắt được %d link media.", len(job.media_urls))
        if session.config.verify_media:
            status = verify_media_url(session, job.media_urls[0])
            job.note(f"kiểm tra link media: HTTP {status}")
    if job.status == "failed":
        LOG.warning("    Tác vụ thất bại: %s", job.error)


def generate(session: FlowSession, prompt: str, index: int = 1) -> JobRecord:
    """
    Gửi một prompt rồi chờ tới khi xong. Bằng `submit_prompt()` + `wait_for_job()`.

    :raises FlowError: các lỗi của hai bước con (xem `generate_batch` nếu muốn
        chạy cả loạt mà một prompt hỏng không làm dừng những prompt còn lại).
    """
    return wait_for_job(session, submit_prompt(session, prompt, index))


def generate_batch(
    session: FlowSession,
    prompts: Sequence[str],
    history_path: Optional[Path] = None,
    save_history: bool = True,
) -> List[JobRecord]:
    """
    Gửi lần lượt cả loạt prompt. Một prompt hỏng KHÔNG làm dừng những prompt còn lại.

    Tự mở project và đặt thiết lập đầu ra nếu phiên chưa làm hai việc đó, nên gọi
    thẳng cũng được:

        with flow_session(project="abc123", resolution="720p") as session:
            jobs = generate_batch(session, ["cảnh 1", "cảnh 2"])

    :param history_path: nơi ghi lịch sử. Bỏ trống thì lấy từ FlowConfig.
    :param save_history: đặt False để không ghi file nào cả.
    :return: danh sách bản ghi theo đúng thứ tự prompt.
    """
    config = session.config
    if session.project_url is None:
        open_project(session)
    if session.applied_settings is None and config.apply_settings:
        apply_output_settings(session)
    if session.state is None:
        capture_session_state(session)

    path = history_path or config.history_path
    history = JobHistory(path) if (save_history and path) else None

    records: List[JobRecord] = []
    total = len(prompts)
    for index, prompt in enumerate(prompts, start=1):
        LOG.info("─" * 62)
        LOG.info("==> [%d/%d] %s", index, total, prompt[:90] + ("…" if len(prompt) > 90 else ""))
        job = JobRecord(prompt=prompt, index=index)
        try:
            job = submit_prompt(session, prompt, index)
            wait_for_job(session, job)
        except FlowError as exc:
            LOG.error("    Lỗi: %s", exc)
            if job.status not in ("failed", "timeout"):
                job.finish("error", error=str(exc))
        except Exception as exc:  # pragma: no cover - lỗi ngoài dự tính
            LOG.exception("    Lỗi không mong đợi:")
            job.finish("error", error=f"{type(exc).__name__}: {exc}")

        records.append(job)
        if history is not None:
            history.append([job])  # ghi ngay sau TỪNG prompt, không đợi hết loạt
        LOG.info("    Kết quả: %s%s", job.status,
                 f" ({job.duration_s}s)" if job.duration_s else "")

        if index < total and config.delay_between_s > 0:
            LOG.debug("Nghỉ %.1fs trước prompt kế tiếp.", config.delay_between_s)
            _sleep(session, config.delay_between_s)

    return records


# ===========================================================================
# Lịch sử tác vụ
# ===========================================================================


def save_jobs(
    jobs: Sequence[JobRecord], path: Path = Path("jobs_history.json")
) -> Path:
    """Ghi thêm các bản ghi vào file lịch sử (thay thế nguyên tử, không mất file cũ)."""
    return JobHistory(Path(path)).append(jobs)


def load_jobs(path: Path = Path("jobs_history.json")) -> List[Dict[str, Any]]:
    """Đọc toàn bộ lịch sử đã ghi. File chưa có thì trả danh sách rỗng."""
    return JobHistory(Path(path)).load()


# ===========================================================================
# Một lệnh làm hết
# ===========================================================================


def run_flow_batch(
    prompts: Sequence[str],
    config: Optional[FlowConfig] = None,
    **overrides: Any,
) -> List[JobRecord]:
    """
    Mở phiên, gửi cả loạt prompt, ghi lịch sử, rồi nhả kết nối. Dùng cho trường hợp
    thường gặp nhất:

        jobs = run_flow_batch(
            ["biển đêm, sóng vỗ", "rừng thông buổi sớm"],
            project="abc123", resolution="720p",
        )

    :param prompts: danh sách prompt cần gửi.
    :param config: FlowConfig dựng sẵn (không bắt buộc).
    :param overrides: đặt lẻ từng tham số của FlowConfig.
    :return: danh sách bản ghi; prompt hỏng có `status` là "failed"/"timeout"/"error".
    """
    if not prompts:
        return []
    with flow_session(config, **overrides) as session:
        return generate_batch(session, prompts)


if __name__ == "__main__":  # pragma: no cover
    print(__doc__)
    print("File này là thư viện để import. Muốn dùng từ dòng lệnh thì chạy:")
    print("    python3 flow_automation.py --help")
