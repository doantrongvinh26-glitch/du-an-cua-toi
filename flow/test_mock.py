#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_mock.py — Kiểm thử flow_e2e_tool.py mà KHÔNG cần trình duyệt, KHÔNG tốn credit.

Thay Playwright bằng trang giả lập: tự dựng ô nhập, nút bấm, và "phát" các
response y như Flow trả về thật. Nhờ vậy kiểm tra được đúng phần dễ vỡ nhất —
tìm phần tử, gửi prompt, đọc mã tác vụ, chờ tới khi xong, ghi lịch sử.

    python3 flow/test_mock.py
"""

from __future__ import annotations

import json
import logging
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import flow_automation as cli
import flow_e2e_tool as fa

# Tắt bớt log cho kết quả kiểm thử dễ đọc.
logging.disable(logging.WARNING)

GEN_URL = "https://aisandbox-pa.googleapis.com/v1/video:batchAsyncGenerate"
STATUS_URL = "https://aisandbox-pa.googleapis.com/v1/video:batchCheckAsyncVideoGenerationStatus"
OP_NAME = "projects/p1/operations/op-abc123456789"


# ===========================================================================
# Trình duyệt giả lập
# ===========================================================================


class FakeTimeout(Exception):
    """Đóng vai TimeoutError của Playwright."""


class FakeLocator:
    """Locator giả: chỉ cần đủ những phương thức mà FlowPage thật sự gọi."""

    def __init__(
        self, page: "FakePage", kind: str, *, visible: bool = False,
        tag: str = "DIV", count: int = 0,
    ) -> None:
        self.page = page
        self.kind = kind
        self.visible = visible
        self.tag = tag
        self._count = count

    @property
    def first(self) -> "FakeLocator":
        return self

    def filter(self, **_kwargs: Any) -> "FakeLocator":
        return self

    def get_by_text(self, pattern: Any) -> "FakeLocator":
        return self.page.get_by_text(pattern)

    def wait_for(self, state: str = "visible", timeout: float = 0) -> None:
        if not self.visible:
            raise FakeTimeout(f"{self.kind} không hiện")

    def is_visible(self, timeout: float = 0) -> bool:
        return self.visible

    def count(self) -> int:
        return self._count

    def evaluate(self, _expression: str) -> str:
        return self.tag

    def click(self, timeout: float = 0) -> None:
        if not self.visible:
            raise FakeTimeout(f"không bấm được {self.kind}")
        self.page.clicked.append(self.kind)

    def fill(self, value: str, timeout: float = 0) -> None:
        if self.kind != "prompt":
            raise FakeTimeout(f"{self.kind} không nhận fill()")
        self.page.value = value

    def select_option(self, **_kwargs: Any) -> None:
        self.page.clicked.append(f"select:{self.kind}")

    def press(self, key: str, timeout: float = 0) -> None:
        self.page.keys.append(key)

    def input_value(self, timeout: float = 0) -> str:
        if self.kind != "prompt":
            raise FakeTimeout("không phải ô nhập")
        return self.page.value

    def inner_text(self, timeout: float = 0) -> str:
        return self.page.value if self.kind == "prompt" else ""


class FakeKeyboard:
    def __init__(self, page: "FakePage") -> None:
        self.page = page

    def press(self, key: str) -> None:
        self.page.keys.append(key)

    def type(self, text: str, delay: float = 0) -> None:
        self.page.value = text


class FakePage:
    """
    Trang Flow giả lập.

    `steps` là kịch bản: mỗi lần script chờ (`wait_for_timeout`) thì một bước
    được thực hiện — thường là phát một response y như Flow trả về thật.
    """

    def __init__(
        self, *, url: str = "https://flow.google.com/project/p1",
        textboxes: Optional[List[str]] = None, buttons: Optional[List[str]] = None,
        texts: Optional[List[str]] = None, media: int = 0,
        steps: Optional[List[Callable[[], None]]] = None,
        redirect_to: Optional[str] = None,
    ) -> None:
        self.url = url
        self.redirect_to = redirect_to  # Google đá sang đây khi chưa đăng nhập
        self.visited: Optional[str] = None
        self.textboxes = textboxes if textboxes is not None else ["What do you want to create?"]
        self.buttons = buttons if buttons is not None else ["Create"]
        self.texts = texts or []
        self.media = media
        self.steps = steps or []
        self.value = ""
        self.clicked: List[str] = []
        self.keys: List[str] = []
        self.handlers: Dict[str, List[Callable[[Any], None]]] = {}
        self.keyboard = FakeKeyboard(self)
        self.waits = 0

    # --- sự kiện ---
    def on(self, event: str, handler: Callable[[Any], None]) -> None:
        self.handlers.setdefault(event, []).append(handler)

    def remove_listener(self, event: str, handler: Callable[[Any], None]) -> None:
        self.handlers.get(event, []).remove(handler)

    def fire(self, event: str, payload: Any) -> None:
        for handler in list(self.handlers.get(event, [])):
            handler(payload)

    # --- chờ ---
    def wait_for_timeout(self, ms: float) -> None:
        self.waits += 1
        time.sleep(min(ms, 20) / 1000)  # vẫn để đồng hồ thật nhích lên
        if self.steps:
            self.steps.pop(0)()

    def goto(self, url: str, wait_until: str = "load", timeout: float = 0) -> None:
        self.url = self.redirect_to or url
        self.visited = url

    def wait_for_load_state(self, state: str, timeout: float = 0) -> None:
        return None

    def bring_to_front(self) -> None:
        return None

    # --- tìm phần tử ---
    @staticmethod
    def _matches(pattern: Any, label: str) -> bool:
        if pattern is None:
            return True
        if isinstance(pattern, str):
            return pattern.lower() in label.lower()
        return bool(pattern.search(label))

    def get_by_role(self, role: str, name: Any = None) -> FakeLocator:
        if role == "textbox":
            hit = any(self._matches(name, label) for label in self.textboxes)
            return FakeLocator(self, "prompt", visible=hit, tag="TEXTAREA")
        if role in ("button", "combobox", "option", "menuitem", "menuitemradio", "radio"):
            for label in self.buttons:
                if self._matches(name, label):
                    return FakeLocator(self, f"{role}:{label}", visible=True, tag="BUTTON")
        return FakeLocator(self, f"{role}:không có", visible=False)

    def get_by_placeholder(self, pattern: Any) -> FakeLocator:
        hit = any(self._matches(pattern, label) for label in self.textboxes)
        return FakeLocator(self, "prompt", visible=hit, tag="TEXTAREA")

    def get_by_text(self, pattern: Any) -> FakeLocator:
        hit = any(self._matches(pattern, text) for text in self.texts)
        return FakeLocator(self, "text", visible=hit)

    def locator(self, selector: str) -> FakeLocator:
        low = selector.lower()
        if "video" in low:
            return FakeLocator(self, "video", visible=self.media > 0, count=self.media)
        if "progressbar" in low or "progress" in low:
            busy = any("đang" in t.lower() or "generat" in t.lower() for t in self.texts)
            return FakeLocator(self, "progress", visible=busy)
        if "textarea" in low or "contenteditable" in low:
            return FakeLocator(self, "prompt", visible=bool(self.textboxes), tag="TEXTAREA")
        if "main" in low or "canvas" in low:
            return FakeLocator(self, "canvas", visible=True)
        return FakeLocator(self, f"sel:{selector}", visible=False)


class FakeResponse:
    """Response giả, có thể trả JSON, văn bản thô, hoặc lỗi khi đọc body."""

    def __init__(
        self, url: str, *, status: int = 200, body: Any = None,
        text: Optional[str] = None, raises: bool = False,
    ) -> None:
        self.url = url
        self.status = status
        self.headers = {"content-type": "application/json"}
        self._body = body
        self._text = text
        self._raises = raises

    def text(self) -> str:
        if self._raises:
            raise RuntimeError("body đã bị giải phóng")
        if self._text is not None:
            return self._text
        return json.dumps(self._body)


class FakeRequest:
    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None) -> None:
        self.url = url
        self.headers = headers or {}


class FakeContext:
    def __init__(self, cookies: Optional[List[Dict[str, Any]]] = None) -> None:
        self._cookies = cookies or []

    def cookies(self, urls: Any = None) -> List[Dict[str, Any]]:
        return self._cookies


def gen_body(op_name: str = OP_NAME) -> Dict[str, Any]:
    """Body y như response khi Flow nhận tác vụ."""
    return {"operations": [{"operation": {"name": op_name}, "status": "MEDIA_GENERATION_STATUS_PENDING"}]}


def status_body(state: str, op_name: str = OP_NAME, url: Optional[str] = None) -> Dict[str, Any]:
    """Body y như response khi hỏi trạng thái."""
    entry: Dict[str, Any] = {"operation": {"name": op_name}, "status": state}
    if url:
        entry["video"] = {"servingUri": url}
    return {"operations": [entry]}


def make_session(page: FakePage, config: Optional[fa.FlowConfig] = None) -> fa.FlowSession:
    """Dựng FlowSession gắn vào trang giả lập, bỏ qua bước kết nối trình duyệt thật."""
    config = config or fa.FlowConfig(
        ready_timeout_ms=400, action_timeout_ms=400,
        generation_timeout_s=3.0, poll_initial_s=0.02, poll_max_s=0.05,
    )
    monitor = fa.NetworkMonitor(
        capture_bodies=config.capture_bodies, extra_hosts=(config.host,)
    )
    monitor.attach(page)
    return fa.FlowSession(
        config=config, page=page, context=FakeContext(), monitor=monitor,
    )


# ===========================================================================
# 1. Tiện ích thuần
# ===========================================================================


class TestHelpers(unittest.TestCase):
    def test_normalize_status_nhan_dien_moi_kieu_enum(self) -> None:
        done = ["MEDIA_GENERATION_STATUS_SUCCESSFUL", "SUCCEEDED", "COMPLETED", "done", True]
        for value in done:
            self.assertEqual(fa.normalize_status(value), "done", value)
        for value in ["MEDIA_GENERATION_STATUS_FAILED", "ERROR", "CANCELLED"]:
            self.assertEqual(fa.normalize_status(value), "failed", value)
        for value in ["PENDING", "RUNNING", "IN_PROGRESS", "ACTIVE", False]:
            self.assertEqual(fa.normalize_status(value), "pending", value)
        for value in [None, "", "xyz"]:
            self.assertIsNone(fa.normalize_status(value))

    def test_deep_find_va_deep_collect_tren_json_long_nhau(self) -> None:
        body = status_body("MEDIA_GENERATION_STATUS_SUCCESSFUL", url="https://x/y.mp4")
        self.assertEqual(fa.deep_find(body, fa.STATUS_KEYS), "MEDIA_GENERATION_STATUS_SUCCESSFUL")
        self.assertIn(OP_NAME, fa.deep_collect(body, fa.TASK_ID_KEYS))
        self.assertIn("https://x/y.mp4", fa.deep_collect(body, fa.MEDIA_URL_KEYS))

    def test_classify_url(self) -> None:
        self.assertEqual(fa.classify_url(GEN_URL), "generate")
        self.assertEqual(fa.classify_url(STATUS_URL), "status")
        self.assertIsNone(fa.classify_url("https://fonts.gstatic.com/s/font.woff2"))
        self.assertIsNone(fa.classify_url("https://example.com/generate"))

    def test_strip_xssi_va_parse_json_loose(self) -> None:
        self.assertEqual(fa.parse_json_loose(")]}'\n{\"a\": 1}"), {"a": 1})
        self.assertEqual(fa.parse_json_loose('{"a": 2}'), {"a": 2})
        self.assertIsNone(fa.parse_json_loose("<html>lỗi</html>"))

    def test_backoff_tang_dan_va_co_tran(self) -> None:
        delays = list(
            next(d) for d in [fa.backoff_delays(1, 2, 4)] for _ in range(6)
        )
        self.assertTrue(all(d <= 4 * 1.3 for d in delays), delays)
        self.assertGreater(delays[-1], delays[0])

    def test_parse_prompts_bo_ghi_chu_va_tach_khoi(self) -> None:
        self.assertEqual(
            fa.parse_prompts("# ghi chú\ncảnh 1\n\ncảnh 2\n"), ["cảnh 1", "cảnh 2"]
        )
        self.assertEqual(
            fa.parse_prompts("dòng A\ndòng B\n---\ncảnh 2\n"), ["dòng A\ndòng B", "cảnh 2"]
        )

    def test_resolve_project_url(self) -> None:
        self.assertEqual(
            fa.resolve_project_url("abc123"), "https://flow.google.com/project/abc123"
        )
        self.assertEqual(
            fa.resolve_project_url("https://flow.google.com/project/xyz789/"),
            "https://flow.google.com/project/xyz789",
        )
        self.assertIsNone(fa.resolve_project_url(None))
        self.assertEqual(
            fa.project_id_from_url("https://flow.google.com/project/xyz789?a=1"), "xyz789"
        )

    def test_bieu_thuc_nhan_dien_nhan_giao_dien(self) -> None:
        for label in ["Create", "Generate", "Tạo", "Send"]:
            self.assertTrue(fa.SUBMIT_TEXT_RE.search(label), label)
        for label in ["What do you want to create?", "Nhập mô tả"]:
            self.assertTrue(fa.PROMPT_TEXT_RE.search(label), label)


# ===========================================================================
# 2. Theo dõi mạng
# ===========================================================================


class TestNetworkMonitor(unittest.TestCase):
    def setUp(self) -> None:
        self.page = FakePage()
        self.monitor = fa.NetworkMonitor()
        self.monitor.attach(self.page)

    def test_bat_ma_tac_vu_trang_thai_va_link_media(self) -> None:
        self.page.fire("response", FakeResponse(GEN_URL, body=gen_body()))
        self.page.fire("response", FakeResponse(
            STATUS_URL, body=status_body("MEDIA_GENERATION_STATUS_SUCCESSFUL", url="https://x/y.mp4")
        ))
        self.assertEqual([e.kind for e in self.monitor.events], ["generate", "status"])
        self.assertIn(OP_NAME, self.monitor.events[0].task_ids)
        self.assertEqual(self.monitor.events[1].state, "done")
        self.assertEqual(self.monitor.events[1].media_urls, ["https://x/y.mp4"])

    def test_bo_qua_request_khong_lien_quan(self) -> None:
        self.page.fire("response", FakeResponse("https://fonts.gstatic.com/a.woff2", body={}))
        self.assertEqual(self.monitor.events, [])

    def test_body_khong_doc_duoc_thi_van_ghi_nhan_su_kien(self) -> None:
        self.page.fire("response", FakeResponse(STATUS_URL, raises=True))
        self.assertEqual(len(self.monitor.events), 1)
        self.assertIsNone(self.monitor.events[0].state)

    def test_body_khong_phai_json_thi_vet_link_bang_regex(self) -> None:
        self.page.fire("response", FakeResponse(
            STATUS_URL, text="rác rác https://cdn.example/v/clip.mp4?x=1 rác"
        ))
        self.assertEqual(
            self.monitor.events[0].media_urls, ["https://cdn.example/v/clip.mp4?x=1"]
        )

    def test_lay_header_phien_tu_request_api(self) -> None:
        self.page.fire("request", FakeRequest(GEN_URL, {"Authorization": "Bearer T", "X-Goog-AuthUser": "0"}))
        self.assertEqual(self.monitor.observed_headers["authorization"], "Bearer T")
        self.assertEqual(self.monitor.seen_api_calls, 1)

    def test_khong_doc_body_khi_tat_capture(self) -> None:
        monitor = fa.NetworkMonitor(capture_bodies=False)
        page = FakePage()
        monitor.attach(page)
        page.fire("response", FakeResponse(STATUS_URL, body=status_body("SUCCEEDED")))
        self.assertEqual(len(monitor.events), 1)
        self.assertIsNone(monitor.events[0].state)

    def test_listener_khong_bao_gio_nem_loi_ra_ngoai(self) -> None:
        class Exploding:
            url = STATUS_URL

            @property
            def status(self) -> int:
                raise RuntimeError("nổ")

        self.page.fire("response", Exploding())  # không được ném lỗi


# ===========================================================================
# 3. Phiên đăng nhập
# ===========================================================================


class TestSessionState(unittest.TestCase):
    def setUp(self) -> None:
        self.context = FakeContext([
            {"name": "SID", "value": "bi-mat-cua-toi", "domain": ".google.com"},
        ])
        self.session = fa.SessionState.capture(
            self.context, {"Authorization": "Bearer BI-MAT", "X-Random": "bỏ"}
        )

    def test_chi_giu_header_can_thiet(self) -> None:
        self.assertIn("authorization", self.session.headers)
        self.assertNotIn("x-random", self.session.headers)

    def test_ban_rut_gon_khong_lo_bi_mat(self) -> None:
        dumped = json.dumps(self.session.summary(), ensure_ascii=False)
        self.assertNotIn("bi-mat-cua-toi", dumped)
        self.assertNotIn("BI-MAT", dumped)
        self.assertIn("authorization", dumped)
        self.assertEqual(self.session.summary()["cookie_count"], 1)

    def test_cookie_header_va_request_headers(self) -> None:
        self.assertEqual(self.session.cookie_header(), "SID=bi-mat-cua-toi")
        self.assertIn("cookie", self.session.request_headers())

    def test_ghi_ra_dia_thi_dat_quyen_0600(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "phien.json"
            self.session.save(path)
            mode = stat.S_IMODE(os.stat(path).st_mode)
            self.assertEqual(mode, 0o600, oct(mode))
            self.assertIn("bi-mat-cua-toi", path.read_text(encoding="utf-8"))


# ===========================================================================
# 4. Lịch sử tác vụ
# ===========================================================================


class TestJobHistory(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "jobs_history.json"
        self.history = fa.JobHistory(self.path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_ghi_them_khong_de_len_ban_ghi_cu(self) -> None:
        self.history.append([fa.JobRecord(prompt="cảnh 1", index=1)])
        self.history.append([fa.JobRecord(prompt="cảnh 2", index=2)])
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], fa.JobHistory.VERSION)
        self.assertEqual([j["prompt"] for j in data["jobs"]], ["cảnh 1", "cảnh 2"])

    def test_ban_ghi_co_du_truong_bat_buoc(self) -> None:
        record = fa.JobRecord(prompt="p", index=1, task_id="op-1")
        record.finish("done")
        self.history.append([record])
        job = json.loads(self.path.read_text(encoding="utf-8"))["jobs"][0]
        for key in ("task_id", "prompt", "submitted_at", "status", "finished_at", "duration_s"):
            self.assertIn(key, job)
        self.assertEqual(job["status"], "done")
        self.assertIsNotNone(job["duration_s"])

    def test_file_hong_thi_giu_lai_ban_sao_roi_lam_lai(self) -> None:
        self.path.write_text("{ không phải json", encoding="utf-8")
        self.assertEqual(self.history.load(), [])
        self.assertTrue(self.path.with_suffix(".json.bak").exists())

    def test_doc_duoc_dinh_dang_mang_phang_cu(self) -> None:
        self.path.write_text('[{"prompt": "cũ"}]', encoding="utf-8")
        self.assertEqual(self.history.load(), [{"prompt": "cũ"}])

    def test_khong_de_lai_file_tam(self) -> None:
        self.history.append([fa.JobRecord(prompt="p", index=1)])
        self.assertEqual([p.name for p in Path(self.tmp.name).iterdir()], ["jobs_history.json"])



# ===========================================================================
# 5. Thao tác giao diện (các hàm tìm phần tử / điền / bấm)
# ===========================================================================


class TestPageFunctions(unittest.TestCase):
    def setUp(self) -> None:
        self.config = fa.FlowConfig(ready_timeout_ms=300, action_timeout_ms=300)

    def test_tim_duoc_o_nhap_prompt(self) -> None:
        locator = fa.find_prompt_input(FakePage(), self.config)
        self.assertEqual(locator.kind, "prompt")

    def test_khong_tim_thay_thi_bao_loi_ro_rang(self) -> None:
        with self.assertRaises(fa.ElementNotFound) as ctx:
            fa.find_prompt_input(FakePage(textboxes=[]), self.config)
        self.assertIn("đổi giao diện", str(ctx.exception))

    def test_dien_prompt_va_gui_bang_nut(self) -> None:
        page = FakePage(buttons=["Create"])
        how = fa.click_submit(page, fa.fill_prompt(page, "biển đêm", self.config), self.config)
        self.assertEqual(page.value, "biển đêm")
        self.assertEqual(how, "nút gửi")
        self.assertIn("button:Create", page.clicked)

    def test_khong_co_nut_thi_gui_bang_enter(self) -> None:
        page = FakePage(buttons=[])
        how = fa.click_submit(page, fa.fill_prompt(page, "biển đêm", self.config), self.config)
        self.assertEqual(how, "phím Enter")
        self.assertIn("Enter", page.keys)

    def test_dem_media_va_nhan_biet_dang_ban(self) -> None:
        self.assertEqual(fa.count_media(FakePage(media=3)), 3)
        self.assertTrue(fa.is_busy(FakePage(texts=["Generating…"])))
        self.assertFalse(fa.is_busy(FakePage()))

    def test_thiet_lap_hong_thi_chi_canh_bao_chu_khong_vo(self) -> None:
        session = make_session(FakePage(buttons=["Create"]))  # không có nút Settings
        self.assertEqual(fa.apply_output_settings(session, {"resolution": "720p"}), {})

    def test_chon_thiet_lap_bang_cach_bam_thang_gia_tri(self) -> None:
        page = FakePage(buttons=["Create", "Settings", "720p"])
        session = make_session(page)
        applied = fa.apply_output_settings(session, {"resolution": "720p"})
        self.assertEqual(applied, {"resolution": "720p"})
        self.assertIn("button:720p", page.clicked)
        self.assertEqual(session.applied_settings, {"resolution": "720p"})

    def test_thiet_lap_lay_tu_config_khi_khong_truyen(self) -> None:
        page = FakePage(buttons=["Create", "Settings", "1080p"])
        session = make_session(page, fa.FlowConfig(
            ready_timeout_ms=300, action_timeout_ms=300, resolution="1080p",
        ))
        self.assertEqual(fa.apply_output_settings(session), {"resolution": "1080p"})


# ===========================================================================
# 6. Điều hướng
# ===========================================================================


class TestOpenProject(unittest.TestCase):
    def test_mo_dung_url_project(self) -> None:
        session = make_session(FakePage(url="about:blank"), fa.FlowConfig(
            ready_timeout_ms=300, project="abc123"))
        url = fa.open_project(session)
        self.assertEqual(url, "https://flow.google.com/project/abc123")
        self.assertEqual(session.project_url, url)

    def test_project_truyen_thang_vao_ham(self) -> None:
        session = make_session(FakePage(url="about:blank"), fa.FlowConfig(ready_timeout_ms=300))
        self.assertEqual(
            fa.open_project(session, "xyz789"), "https://flow.google.com/project/xyz789"
        )

    def test_bao_loi_khi_bi_da_ve_trang_dang_nhap(self) -> None:
        # Chưa đăng nhập thì Google đá sang accounts.google.com.
        page = FakePage(url="about:blank", redirect_to="https://accounts.google.com/signin")
        session = make_session(page, fa.FlowConfig(ready_timeout_ms=300, project="p1"))
        with self.assertRaises(fa.NavigationFailed) as ctx:
            fa.open_project(session)
        self.assertIn("chưa đăng nhập", str(ctx.exception).lower())

    def test_bao_loi_khi_khong_biet_mo_gi(self) -> None:
        session = make_session(FakePage(url="https://example.com"),
                               fa.FlowConfig(ready_timeout_ms=300))
        with self.assertRaises(fa.NavigationFailed) as ctx:
            fa.open_project(session)
        self.assertIn("project", str(ctx.exception))


# ===========================================================================
# 7. Gửi prompt và chờ kết quả
# ===========================================================================


class TestGenerate(unittest.TestCase):
    def test_xong_nho_tin_hieu_mang(self) -> None:
        page = FakePage()
        page.steps = [
            lambda: page.fire("response", FakeResponse(GEN_URL, body=gen_body())),
            lambda: page.fire("response", FakeResponse(
                STATUS_URL,
                body=status_body("MEDIA_GENERATION_STATUS_SUCCESSFUL", url="https://x/y.mp4"),
            )),
        ]
        job = fa.generate(make_session(page), "biển đêm")

        self.assertEqual(job.status, "done")
        self.assertEqual(job.task_id, OP_NAME)
        self.assertEqual(job.media_urls, ["https://x/y.mp4"])
        self.assertTrue(any("mạng" in s for s in job.signals), job.signals)
        self.assertIsNotNone(job.duration_s)

    def test_gui_va_cho_la_hai_buoc_roi_nhau(self) -> None:
        # submit_prompt() trả về ngay, wait_for_job() mới là bước chờ.
        page = FakePage()
        page.steps = [
            lambda: page.fire("response", FakeResponse(
                STATUS_URL, body=status_body("SUCCEEDED", url="https://x/y.mp4"),
            )),
        ]
        session = make_session(page)
        job = fa.submit_prompt(session, "biển đêm")
        self.assertEqual(job.status, "submitted")
        self.assertIsNone(job.finished_at)

        fa.wait_for_job(session, job)
        self.assertEqual(job.status, "done")

    def test_that_bai_thi_ghi_ly_do(self) -> None:
        page = FakePage()
        page.steps = [
            lambda: page.fire("response", FakeResponse(GEN_URL, body=gen_body())),
            lambda: page.fire("response", FakeResponse(STATUS_URL, body={
                "operations": [{
                    "operation": {"name": OP_NAME},
                    "status": "MEDIA_GENERATION_STATUS_FAILED",
                    "error": "vi phạm chính sách nội dung",
                }],
            })),
        ]
        job = fa.generate(make_session(page), "x")
        self.assertEqual(job.status, "failed")
        self.assertIn("chính sách", job.error or "")

    def test_request_gui_bi_tu_choi_thi_bao_hong_ngay(self) -> None:
        # Hết hạn mức / prompt bị chặn: response lỗi thường KHÔNG kèm mã tác vụ nào,
        # nên không được chờ tới lúc hết giờ mới biết.
        page = FakePage()
        page.steps = [
            lambda: page.fire("response", FakeResponse(
                GEN_URL, status=429, body={"error": {"message": "hết hạn mức"}}
            )),
        ]
        job = fa.generate(make_session(page), "x")
        self.assertEqual(job.status, "failed")
        self.assertIn("hạn mức", job.error or "")

    def test_xong_nho_tin_hieu_giao_dien_khi_mang_im_lang(self) -> None:
        page = FakePage()

        def them_video() -> None:
            page.media = 1

        page.steps = [lambda: None, them_video]
        job = fa.generate(make_session(page), "x")
        self.assertEqual(job.status, "done")
        self.assertTrue(any("giao diện" in s for s in job.signals), job.signals)

    def test_het_gio_thi_bao_timeout_kem_goi_y(self) -> None:
        config = fa.FlowConfig(
            ready_timeout_ms=300, action_timeout_ms=300,
            generation_timeout_s=0.3, poll_initial_s=0.02, poll_max_s=0.05,
        )
        session = make_session(FakePage(), config)
        job = fa.submit_prompt(session, "x")
        with self.assertRaises(fa.GenerationTimeout):
            fa.wait_for_job(session, job)
        self.assertEqual(job.status, "timeout")
        self.assertIn("generation_timeout_s", job.error or "")

    def test_dry_run_khong_bam_nut(self) -> None:
        page = FakePage()
        config = fa.FlowConfig(ready_timeout_ms=300, action_timeout_ms=300, dry_run=True)
        job = fa.generate(make_session(page, config), "thử")
        self.assertEqual(job.status, "dry-run")
        self.assertEqual(page.value, "thử")
        self.assertEqual(page.clicked, ["prompt"])  # chỉ bấm vào ô nhập
        self.assertNotIn("Enter", page.keys)

    def test_cho_lai_tac_vu_da_xong_thi_tra_ve_ngay(self) -> None:
        session = make_session(FakePage())
        job = fa.JobRecord(prompt="x", index=1)
        job.finish("done")
        self.assertIs(fa.wait_for_job(session, job), job)

    def test_khop_su_kien_theo_ma_tac_vu(self) -> None:
        job = fa.JobRecord(prompt="x", index=1, task_ids=["op-A"])
        khop = fa.NetEvent(kind="status", url=STATUS_URL, status_code=200, at=0, task_ids=["op-A"])
        lech = fa.NetEvent(kind="status", url=STATUS_URL, status_code=200, at=0, task_ids=["op-B"])
        self.assertTrue(fa.event_matches(job, khop))
        self.assertFalse(fa.event_matches(job, lech))


# ===========================================================================
# 8. Chạy cả loạt
# ===========================================================================


class TestGenerateBatch(unittest.TestCase):
    def test_ghi_lich_su_sau_tung_prompt(self) -> None:
        page = FakePage()
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "jobs_history.json"
            config = fa.FlowConfig(
                ready_timeout_ms=300, action_timeout_ms=300, dry_run=True,
                delay_between_s=0, history_path=history, resolution="720p",
            )
            jobs = fa.generate_batch(make_session(page, config), ["cảnh 1", "cảnh 2"])

            self.assertEqual([j.status for j in jobs], ["dry-run", "dry-run"])
            data = json.loads(history.read_text(encoding="utf-8"))
            self.assertEqual([j["prompt"] for j in data["jobs"]], ["cảnh 1", "cảnh 2"])
            self.assertEqual(data["jobs"][0]["settings"], {"resolution": "720p"})
            self.assertEqual(data["jobs"][0]["project_id"], "p1")

    def test_mot_prompt_hong_khong_lam_dung_ca_loat(self) -> None:
        page = FakePage()
        config = fa.FlowConfig(
            ready_timeout_ms=300, action_timeout_ms=300, delay_between_s=0,
            generation_timeout_s=0.3, poll_initial_s=0.02, poll_max_s=0.05,
        )
        session = make_session(page, config)

        # Prompt "hỏng" không có tín hiệu nào nên hết giờ; prompt "ổn" hiện video ra
        # ngay. Bám theo nội dung prompt chứ không đếm số nhịp chờ, để khỏi phụ thuộc
        # vào việc vòng lặp quay được bao nhiêu vòng.
        def video_khi_den_prompt_on() -> None:
            if page.value == "ổn":
                page.media += 1

        page.steps = [video_khi_den_prompt_on] * 60
        jobs = fa.generate_batch(session, ["hỏng", "ổn"], save_history=False)
        self.assertEqual([j.status for j in jobs], ["timeout", "done"])

    def test_khong_ghi_lich_su_khi_tat_co(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = fa.FlowConfig(
                ready_timeout_ms=300, action_timeout_ms=300, dry_run=True,
                delay_between_s=0, history_path=Path(tmp) / "khong-duoc-tao.json",
            )
            fa.generate_batch(make_session(FakePage(), config), ["a"], save_history=False)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_tu_mo_project_va_chup_phien(self) -> None:
        session = make_session(FakePage(), fa.FlowConfig(
            ready_timeout_ms=300, action_timeout_ms=300, dry_run=True,
            delay_between_s=0, project="p1",
        ))
        self.assertIsNone(session.project_url)
        fa.generate_batch(session, ["a"], save_history=False)
        self.assertIsNotNone(session.project_url)
        self.assertIsNotNone(session.state)

    def test_run_flow_batch_khong_co_prompt_thi_khong_mo_trinh_duyet(self) -> None:
        self.assertEqual(fa.run_flow_batch([]), [])


# ===========================================================================
# 9. Cấu hình và API import
# ===========================================================================


class TestConfigApi(unittest.TestCase):
    def test_tham_so_le_bao_loi_ro_khi_sai_ten(self) -> None:
        with self.assertRaises(fa.FlowError) as ctx:
            fa._merge_config(None, {"resolutionn": "720p"})
        self.assertIn("resolutionn", str(ctx.exception))

    def test_tham_so_le_gop_vao_config_co_san(self) -> None:
        base = fa.FlowConfig(project="p1", resolution="720p")
        merged = fa._merge_config(base, {"resolution": "1080p"})
        self.assertEqual(merged.project, "p1")
        self.assertEqual(merged.resolution, "1080p")
        self.assertEqual(base.resolution, "720p")  # bản gốc không bị sửa

    def test_host_suy_ra_tu_base_url(self) -> None:
        self.assertEqual(fa.FlowConfig().host, "flow.google.com")
        self.assertEqual(fa.FlowConfig(base_url="http://127.0.0.1:8899").host, "127.0.0.1")

    def test_moi_ten_trong_all_deu_ton_tai(self) -> None:
        for name in fa.__all__:
            self.assertTrue(hasattr(fa, name), f"__all__ nhắc tới {name} nhưng không có")

    def test_import_khong_keo_theo_playwright(self) -> None:
        # Import thư viện phải nhẹ: playwright chỉ được nạp lúc thật sự mở trình
        # duyệt, nhờ vậy project của bạn import file này ở đâu cũng được.
        out = subprocess.run(
            [sys.executable, "-c",
             "import flow_e2e_tool, sys; print('playwright' in sys.modules)"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent),
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "False", "import đã kéo theo playwright")

    def test_luu_va_doc_lai_lich_su(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.json"
            job = fa.JobRecord(prompt="x", index=1, task_id="op-1")
            job.finish("done")
            fa.save_jobs([job], path)
            loaded = fa.load_jobs(path)
            self.assertEqual(loaded[0]["prompt"], "x")
            self.assertEqual(loaded[0]["task_id"], "op-1")
            self.assertEqual(fa.load_jobs(Path(tmp) / "chua-co.json"), [])

    def test_truong_noi_bo_khong_ghi_ra_file(self) -> None:
        job = fa.JobRecord(prompt="x", index=1, watch_mark=7, baseline_media=2)
        self.assertNotIn("watch_mark", job.to_dict())
        self.assertNotIn("baseline_media", job.to_dict())


# ===========================================================================
# 10. Dòng lệnh (flow_automation.py)
# ===========================================================================


class TestCli(unittest.TestCase):
    def test_gom_prompt_va_bo_trung(self) -> None:
        parser = cli.build_parser()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "canh.txt"
            path.write_text("# ghi chú\ncảnh 1\ncảnh 2\ncảnh 1\n", encoding="utf-8")
            args = parser.parse_args(["--prompt", "cảnh 0", "--prompts-file", str(path)])
            self.assertEqual(cli.collect_prompts(args), ["cảnh 0", "cảnh 1", "cảnh 2"])

    def test_doc_prompt_tu_file_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "canh.json"
            path.write_text('["a", {"prompt": "b"}]', encoding="utf-8")
            self.assertEqual(fa.load_prompts_file(path), ["a", "b"])

    def test_khong_co_prompt_thi_thoat_ma_2(self) -> None:
        self.assertEqual(cli.main(["--project", "p1"]), 2)

    def test_config_tu_tham_so(self) -> None:
        args = cli.build_parser().parse_args(
            ["--project", "p1", "--resolution", "720p", "--duration", "8", "--no-settings"]
        )
        config = cli.config_from_args(args)
        self.assertEqual(config.desired_settings(), {"resolution": "720p", "duration": "8"})
        self.assertFalse(config.apply_settings)


if __name__ == "__main__":
    print("Chạy kiểm thử flow_e2e_tool với trình duyệt giả lập (không tốn credit)...\n")
    unittest.main(verbosity=2)
