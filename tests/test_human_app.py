"""사람 실험 진행 프로그램(human-study/app) 테스트. 화면(tkinter) 없이 controller와 views로 진행한다.

기대값의 출처:
  - 진행 순서·문장(진행자용·참가자용)·끝난 시점·진행자 범위·화면 높이: human-study/session-procedure.md를 이 파일이 직접 읽는다
  - 과업 문장: session-procedure.md (pages.md, benchmark/tasks.json, session_plan.json이 같은지 비교)
  - page_id 6개와 포트·경로: benchmark/variants.json
  - 3분 자동 종료·창 닫힘 = 미완료: session-procedure.md C-4·C-5, session.py 규칙
페이지는 합성 HTML(tests/fixtures/human-study/page.html), 저장은 임시 폴더, 코드는 P00·가짜 범위 코드만 쓴다.
"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import http.server
import json
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HS = ROOT / "human-study"
if str(HS) not in sys.path:
    sys.path.insert(0, str(HS))

from app import build_exe, notes  # noqa: E402
from app.controller import PARTICIPANT_STEPS, Controller, Deps, Step  # noqa: E402
from app.plan import load_plan  # noqa: E402
from app.resources import Resources, detect  # noqa: E402,F401
from app.sites import Check, SiteServers  # noqa: E402
from app.views import participant_screen  # noqa: E402

PROCEDURE = (HS / "session-procedure.md").read_text(encoding="utf-8")
PAGES_MD = (HS / "pages.md").read_text(encoding="utf-8")
VARIANTS = json.loads((ROOT / "benchmark" / "variants.json").read_text(encoding="utf-8"))
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "human-study"
RES = detect(frozen=False)
PLAN = load_plan(RES.plan_path)
SESSION = RES.load("session")
CHECK = RES.load("check_sessions")


def strip_md(text: str) -> str:
    return text.replace("**", "").replace("`", "").strip()


def block(text: str, heading: str) -> str:
    """heading으로 시작하는 줄부터 같은 수준 이상의 다음 제목 전까지."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(heading))
    level = len(heading) - len(heading.lstrip("#"))
    out = []
    for line in lines[start + 1:]:
        m = re.match(r"^(#+) ", line)
        if m and len(m.group(1)) <= level:
            break
        out.append(line)
    return "\n".join(out)


def quotes(text: str) -> list[str]:
    return re.findall(r'^\s*> "(.+)"\s*$', text, re.M)


class PlanMatchesProcedureTests(unittest.TestCase):
    def test_page_ids_are_the_six_variants_pages(self):
        self.assertEqual(len(PLAN.pages), 6)
        self.assertEqual({p.page_id for p in PLAN.pages}, {p["page_id"] for p in VARIANTS["pages"]})

    def test_order_is_c4_table(self):
        row = next(line for line in block(PROCEDURE, "### C-4.").splitlines() if line.startswith("| 과업 #"))
        order = [int(x) for x in row.strip("|").split("|")[1:]]
        self.assertEqual(order, [1, 3, 5, 2, 4, 6])
        self.assertEqual([p.task_no for p in PLAN.pages], order)
        self.assertEqual([p.order for p in PLAN.pages], [1, 2, 3, 4, 5, 6])

    def test_task_no_to_page_id_matches_pages_md(self):
        rows = re.findall(r"^\| (\d) \| (?:정상|결함) \| `([^`]+)` \|", PAGES_MD, re.M)
        self.assertEqual(len(rows), 6)
        self.assertEqual({int(n): pid for n, pid in rows}, {p.task_no: p.page_id for p in PLAN.pages})

    def test_each_page_sentence_done_and_values_match_procedure(self):
        for p in PLAN.pages:
            with self.subTest(page=p.label):
                sec = block(PROCEDURE, f"#### {p.mark} 과업 {p.task_no}")
                self.assertIn(f"- `page_id`: `{p.page_id}`", sec)
                q = quotes(sec)
                self.assertEqual(p.task_say, q[-1])
                if p.task_no == 2:  # ④만 과업 문장 앞에 데모 안내가 먼저 나온다
                    self.assertEqual(len(q), 2)
                    self.assertEqual(p.preface_say, q[0])
                else:
                    self.assertEqual(len(q), 1)
                    self.assertIsNone(p.preface_say)
                done = re.search(r"^- \*\*끝난 시점:\*\* (.+)$", sec, re.M)
                self.assertEqual(p.done_when, strip_md(done.group(1)))
                values = re.search(r"^- 화면에 보여 줄 값: (.+)$", sec, re.M)
                expected = [strip_md(v) for v in values.group(1).split(" / ")] if values else []
                self.assertEqual(list(p.show_values), expected)

    def test_task_sentence_is_identical_in_all_four_places(self):
        """ADR 0011 1번: 사람과 에이전트가 같은 문장. 기준은 절차서."""
        tasks = json.loads((ROOT / "benchmark" / "tasks.json").read_text(encoding="utf-8"))["cases"]
        table = dict(re.findall(r"^\| (\d) \| (.+?) \| [^|]+ \|$", block(PAGES_MD, "## 참가자에게 주는 과업 문장"), re.M))
        for p in PLAN.pages:
            with self.subTest(page=p.label):
                expected = quotes(block(PROCEDURE, f"#### {p.mark} 과업 {p.task_no}"))[-1]
                self.assertEqual(p.task_say, expected)  # session_plan.json
                self.assertEqual(strip_md(table[str(p.task_no)]), expected)  # pages.md (굵게·코드 표시만 뺀다)
                app, page, variant = p.page_id.split("/")
                case = [c for c in tasks if (c["app_id"], c["id"], c["variant"]) == (app, page, variant)]
                self.assertEqual(len(case), 1, p.page_id)
                self.assertEqual(case[0]["description"], expected)  # benchmark/tasks.json
                # 같은 과업의 다른 변이(에이전트 측정)도 같은 문장
                same_task = {c["description"] for c in tasks if (c["app_id"], c["id"]) == (app, page)}
                self.assertEqual(same_task, {expected})

    def test_facilitator_lines_match_procedure(self):
        c1 = block(PROCEDURE, "### C-1.")
        self.assertEqual(quotes(c1), [PLAN.text("c1", "say"), PLAN.text("c1", "reject_say")])
        self.assertIn(PLAN.text("c1", "guide"), c1)
        c2 = block(PROCEDURE, "### C-2.")
        self.assertEqual(quotes(c2), [PLAN.text("c2", "say")])
        for g in PLAN.text("c2", "guide"):
            self.assertIn(g, strip_md(c2))
        c3 = block(PROCEDURE, "### C-3.")
        self.assertEqual(quotes(c3), [PLAN.text("handover", "say"), PLAN.text("handover", "answer_say")])
        c6 = block(PROCEDURE, "### C-6.")
        self.assertEqual(quotes(c6), [PLAN.c5_say("P01")])  # 절차서 예시는 P01
        self.assertIn(PLAN.text("c5", "guide"), c6)

    def test_participant_lines_match_procedure(self):
        c4 = block(PROCEDURE, "### C-4.").split("\n---\n")[0]
        keys = ["intro", "hours_question", "task_prompt", "panel_note", "time_up", "window_closed", "browser_error",
                "finished"]
        self.assertEqual(quotes(c4), [PLAN.p(k) for k in keys])
        for key in ("start_button", "done_button", "give_up_button", "next_button", "returned_button"):
            self.assertIn(f"[{PLAN.p(key)}]", c4)
        self.assertEqual(PLAN.page_limit_seconds, 180)
        self.assertIn("3분", c4)

    def test_review_issue_codes_match_procedure(self):
        c5 = strip_md(block(PROCEDURE, "### C-5."))
        for k, text in notes.ISSUE_CODES[notes.SELF_GUIDED].items():
            self.assertIn(f"{k} {text}", c5)
        self.assertEqual(PLAN.procedure_version, notes.SELF_GUIDED)

    def test_facilitator_ranges_match_c2_table(self):
        rows = re.findall(r"^\s*\| @([\w-]+) \| `(P\d\d)`(?: – `(P\d\d)`)? \|", PROCEDURE, re.M)
        self.assertEqual([(g, a, b or a) for g, a, b in rows],
                         [(f.github, f.first, f.last) for f in PLAN.facilitators])
        self.assertEqual(PLAN.practice_code, "P00")  # C-2: 리허설·연습에는 P00만
        self.assertIn("장치는 mouse로 기록", PROCEDURE)
        self.assertEqual(PLAN.device, "mouse")


class ResourcesTests(unittest.TestCase):
    def test_source_mode_uses_repo_paths(self):
        self.assertEqual(RES.mode, "source")
        self.assertEqual(RES.root, ROOT)
        self.assertEqual(RES.collect_bundle, ROOT / "worker" / "collect" / "dist" / "collect.js")
        self.assertEqual(RES.variants_root, ROOT / "benchmark" / "apps" / "variants")
        # 불러온 기존 모듈이 계산한 경로도 같다 (모듈은 고치지 않았다)
        self.assertEqual(Path(SESSION.BUNDLE), RES.collect_bundle)
        self.assertEqual(Path(SESSION.COLLECT), RES.collect_script)
        self.assertEqual(Path(CHECK.VARIANTS), RES.variants_config)
        self.assertEqual(Path(RES.serve_variants().VARIANTS_ROOT), RES.variants_root)

    def test_exe_mode_uses_bundle_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = detect(frozen=True, meipass=tmp)
            self.assertEqual(res.mode, "exe")
            self.assertEqual(res.collect_bundle, Path(tmp) / "worker" / "collect" / "dist" / "collect.js")
            self.assertEqual(res.variants_root, Path(tmp) / "benchmark" / "apps" / "variants")
            self.assertEqual(res.plan_path, Path(tmp) / "human-study" / "session_plan.json")

    def test_staged_bundle_resolves_module_paths_inside_bundle(self):
        """빌드 스크립트가 만든 내장 폴더에서 기존 모듈이 내장 경로를 쓰는지 (exe처럼 frozen으로 흉내)."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "res"
            build_exe.stage_resources(dest, include_sites=False)
            code = (
                "import sys, json; sys.frozen = True; sys._MEIPASS = sys.argv[1]; sys.path.insert(0, sys.argv[2])\n"
                "from app.resources import detect\n"
                "res = detect(); s = res.load('session'); c = res.load('check_sessions'); h = res.load('schema')\n"
                "print(json.dumps([res.mode, str(s.BUNDLE), str(s.COLLECT), str(c.VARIANTS), str(h.OPENAPI),\n"
                "                  str(res.serve_variants().VARIANTS_ROOT)]))\n"
            )
            out = subprocess.run([sys.executable, "-c", code, str(dest), str(HS)], cwd=tmp, capture_output=True,
                                 text=True, check=True)
            mode, bundle, collect, variants, openapi, variants_root = json.loads(out.stdout.strip().splitlines()[-1])
            self.assertEqual(mode, "exe")
            self.assertEqual(Path(bundle), dest / "worker" / "collect" / "dist" / "collect.js")
            self.assertEqual(Path(collect), dest / "human-study" / "collect.js")
            self.assertEqual(Path(variants), dest / "benchmark" / "variants.json")
            self.assertEqual(Path(openapi), dest / "apps" / "api" / "openapi.yaml")
            self.assertEqual(Path(variants_root), dest / "benchmark" / "apps" / "variants")
            # 기존 파일은 바꾸지 않고 그대로 복사했다
            for rel in ("human-study/session.py", "human-study/check_sessions.py", "benchmark/serve_variants.py"):
                self.assertEqual((dest / rel).read_bytes(), (ROOT / rel).read_bytes())
            hidden = build_exe.hidden_imports(dest)
            for mod in ("playwright.async_api", "jsonschema", "yaml", "http.server"):
                self.assertIn(mod, hidden)
            self.assertFalse([m for m in hidden if m.split(".")[0] in ("benchmark", "schema", "session")])

    def test_source_version_and_dirty_suffix(self):
        from datetime import date

        from app.resources import source_version
        from app.views import version_line, window_title
        commit = "3ef38865e9e3105ab8a30f55f498c69250571152"
        self.assertEqual(source_version(commit, False, date(2026, 11, 15)), "20261115-3ef3886")
        self.assertEqual(source_version(commit, True, date(2026, 11, 15)), "20261115-3ef3886-dirty")
        self.assertEqual(window_title("20261114-3ef3886"), "StepMeter 사람 실험 20261114-3ef3886")
        self.assertEqual(version_line("20261114-3ef3886", "exe-windows"), "버전 20261114-3ef3886 · 실행 방식 exe")
        self.assertEqual(version_line("20261115-3ef3886-dirty", "source-mac"), "버전 20261115-3ef3886-dirty · 실행 방식 소스")
        self.assertEqual(source_version(None, False, date(2026, 11, 15)), "20261115-nogit")
        # 지금 저장소: 실행 시점의 HEAD, 작업 트리에 변경이 있으면 -dirty
        # Docker 테스트 이미지에는 .git이 없다(.dockerignore). 그때는 commit 없음 + -nogit
        head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        info = RES.build_info()
        if not head:
            self.assertIsNone(info["commit"])
            self.assertTrue(info["version"].endswith("-nogit"), info["version"])
            return
        dirty = bool(subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True,
                                    text=True).stdout.strip())
        self.assertEqual(info["commit"], head)
        self.assertTrue(info["version"].endswith(head[:7] + ("-dirty" if dirty else "")), info["version"])

    def test_exe_version_comes_from_build_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "app_build.json").write_text(json.dumps({"version": "20261114-3ef3886", "commit": "3ef3886"}),
                                                      encoding="utf-8")
            self.assertEqual(detect(frozen=True, meipass=tmp).build_info()["version"], "20261114-3ef3886")

    def test_version_is_date_and_commit7(self):
        self.assertEqual(build_exe.version_string(datetime(2026, 11, 14), "7325d3a4d2692baae92fa7be5e5601b16f910718"),
                         "20261114-7325d3a")


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _builds_ready(sites: SiteServers) -> bool:
    return all(b.manifest_path.exists() for b in sites.builds) and not sites.sv.stale_builds(sites.config, sites.builds)


class SiteServerTests(unittest.TestCase):
    def setUp(self):
        self.sites = SiteServers(RES)
        self.addCleanup(self.sites.stop)

    def test_urls_and_ports_come_from_variants_json(self):
        ports = {f"{b['app']}/{b['variant']}": b["port"] for b in VARIANTS["builds"]}
        expected = {}
        for p in VARIANTS["pages"]:
            app, _, variant = p["page_id"].split("/")
            expected[p["page_id"]] = f"http://127.0.0.1:{ports[f'{app}/{variant}']}{p['path']}"
        self.assertEqual(self.sites.page_urls(), expected)
        self.assertEqual({b.port for b in self.sites.builds}, {8766, 8767, 8791, 8782, 8785})
        self.assertEqual(self.sites.host, "127.0.0.1")

    def test_busy_port_blocks_start(self):
        if not _port_free(8766):
            self.skipTest("8766을 이미 쓰는 중")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 8766))
            s.listen()
            err = self.sites.start()
        self.assertIsNotNone(err)
        self.assertIn("8766", err)
        self.assertEqual(self.sites.running, [])

    def test_serves_builds_on_fixed_ports_with_spa_fallback(self):
        if not _builds_ready(self.sites):
            self.skipTest("benchmark/apps/variants 빌드가 없다 (serve_variants build 필요, git 제외 폴더)")
        if not all(_port_free(b.port) for b in self.sites.builds):
            self.skipTest("포트를 이미 쓰는 중")
        self.assertIsNone(self.sites.start())
        self.assertEqual(set(self.sites.probe_all().values()), {200})
        # SPA: 확장자 없는 경로는 index.html, 없는 파일은 404 (serve_variants.resolve_path)
        index = urllib.request.urlopen("http://127.0.0.1:8767/").read()
        self.assertEqual(urllib.request.urlopen("http://127.0.0.1:8767/sign-in").read(), index)
        self.assertEqual(urllib.request.urlopen("http://127.0.0.1:8782/tasks/deep/link").read(),
                         urllib.request.urlopen("http://127.0.0.1:8782/").read())
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen("http://127.0.0.1:8767/no-such-file.js")
        self.assertEqual(cm.exception.code, 404)
        self.assertEqual(self.sites.integrity_problems(), [])



# ---------------------------------------------------------------- controller

class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def _serve_fixture():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(FIXTURE_DIR)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


SESSION_INFO = {"app_version": "test", "repo_commit": "0" * 40, "site_manifest_hashes": {"x/baseline": "ab"},
                "os": "test-os", "run_mode": "source-test"}
STABLE = [{"t_ms": 0, "type": "stable", "x": None, "y": None, "target_key": None}]


class ControllerBase(unittest.TestCase):
    limit = 30.0
    env_ok = True
    screen = (1920, 1032)

    @classmethod
    def setUpClass(cls):
        cls.srv = _serve_fixture()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}/page.html"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.data, self.practice = base / "StepMeter-human", base / "StepMeter-human-practice"
        self.opened: list = []
        self.ctrl = self.make()

    def make(self, **over) -> Controller:
        kw = dict(plan=PLAN, session=SESSION, check=CHECK, data_dir=self.data, practice_dir=self.practice,
                  settings_path=Path(self.tmp.name) / "settings" / "settings.json", url_for=lambda pid: self.url,
                  env_checks=lambda: [Check("사이트 서버", self.env_ok, "fake")], screen_size=lambda: self.screen,
                  session_info=SESSION_INFO, headless=True, page_limit_s=self.limit,
                  on_page_open=lambda page, loop: self.opened.append((page, loop)))
        kw.update(over)
        return Controller(Deps(**kw))

    def to_first_task(self, c: Controller, github="hanchaehun", code="P05", practice=False):
        info = c.choose(github, code, practice)
        self.assertIsNone(info.error)
        self.assertEqual(c.step, Step.PREFLIGHT)
        c.run_preflight(True)
        self.assertTrue(c.preflight_ok, c.checks)
        c.start()
        if c.step == Step.C1:
            c.c1_pass()
            c.c2_signed()
        elif c.step == Step.RESUME:
            c.resume_continue()
        self.assertEqual(c.step, Step.HANDOVER)
        c.handed_over()
        self.assertEqual(c.step, Step.P_INTRO)
        self.assertIsNone(c.participant_begin("6"))

    def run_page(self, c: Controller, action: str = "done") -> None:
        self.assertEqual(c.step, Step.P_TASK)
        c.launch_page()
        deadline = time.monotonic() + 30
        while not c.page_visible and c.step == Step.P_RUNNING:
            self.assertLess(time.monotonic(), deadline, "페이지가 뜨지 않음")
            time.sleep(0.05)
        time.sleep(0.7)  # 첫 stable(load 뒤 300ms 안정)이 기록될 시간
        if action == "done":
            c.report_participant(True)
        elif action == "gave_up":
            c.report_participant(False)
        elif action == "close":
            page, loop = self.opened[-1]
            asyncio.run_coroutine_threadsafe(page.close(), loop)
        self.assertTrue(c.wait_page(60))
        self.assertNotIn(c.step, (Step.P_RUNNING, Step.P_ERROR), c.error)

    def saved(self, folder: Path) -> list[dict]:
        return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(folder.glob("human-session-*.json"))]

    def save_fake(self, folder: Path, code: str, page_id: str, completed: bool, minute: int = 0) -> Path:
        meta = SESSION.SessionMeta(code, page_id, "mouse", 4)
        d = SESSION.build_session(meta, STABLE, completed, datetime(2026, 11, 12, 5, minute, tzinfo=timezone.utc))
        return SESSION.save_session(d, folder)


class ControllerFlowTests(ControllerBase):
    def test_full_session_saves_six_pages_review_check_and_zip(self):
        c = self.ctrl
        self.to_first_task(c)
        self.assertEqual(c.current_page.page_id, "sb-admin-2/register/baseline")
        seen = []
        for i in range(6):
            seen.append(c.current_page.page_id)
            self.run_page(c, "gave_up" if i == 1 else "done")
        self.assertEqual(seen, [p.page_id for p in PLAN.pages])
        self.assertEqual(c.step, Step.P_FINISHED)
        c.returned()
        self.assertEqual(c.step, Step.REVIEW)
        rows = c.review_rows()
        self.assertEqual([r.reported for r in rows], ["done", "gave_up", "done", "done", "done", "done"])
        self.assertEqual([r.confirmed for r in rows], [True, False, True, True, True, True])  # 기본값 = 참가자 답
        entries = {r.page.page_id: (r.confirmed, [], "") for r in rows}
        entries[rows[1].page.page_id] = (False, [1, 5], "도움 요청에 답함")
        self.assertEqual(c.submit_review(entries), {})
        self.assertEqual(c.step, Step.C5)
        rep = c.finish_session()
        self.assertEqual(c.step, Step.DONE)
        self.assertTrue(rep.ok, rep.text)
        self.assertEqual(rep.text.strip().splitlines()[-1], "정상")
        self.assertEqual((self.data / "check-P05.txt").read_text(encoding="utf-8"), rep.text)
        with zipfile.ZipFile(self.data / "upload-P05.zip") as z:
            names = sorted(z.namelist())
        self.assertEqual(len([n for n in names if n.startswith("human-session-P05-")]), 6)
        self.assertIn("notes-P05.json", names)
        self.assertIn("check-P05.txt", names)
        self.assertEqual(len(names), 8)
        for d in self.saved(self.data):
            self.assertEqual(d["device"], "mouse")
            self.assertEqual(d["daily_computer_hours"], 6)  # 참가자가 직접 넣은 값
            self.assertNotIn("participant_reported", d)  # 세션 json 형식은 그대로
        n = json.loads((self.data / "notes-P05.json").read_text(encoding="utf-8"))
        self.assertEqual(list(n["session"]), list(notes.SESSION_FIELDS))
        self.assertEqual(n["session"]["procedure_version"], "self_guided_v1")
        self.assertEqual(n["session"]["facilitator"], "hanchaehun")
        self.assertEqual(n["session"]["screen_avail_height"], 1032)
        self.assertEqual([p["order"] for p in n["pages"]], [1, 2, 3, 4, 5, 6])
        for p in n["pages"]:
            self.assertEqual(list(p), list(notes.PAGE_FIELDS))
            self.assertFalse(p["confirmation_changed"])
            self.assertFalse(p["auto_stopped_3min"])
        self.assertEqual(n["pages"][1]["participant_reported"], "gave_up")
        self.assertEqual((n["pages"][1]["completed"], n["pages"][1]["completed_confirmed"]), (False, False))
        self.assertEqual((n["pages"][1]["issue"], n["pages"][1]["issue_codes"]), (True, [1, 5]))
        self.assertEqual(list(self.data.glob(".partial-*")), [])

    def test_done_gave_up_timeout_close_saved_values(self):
        cases = [("done", "done", True, False, Step.P_TASK), ("gave_up", "gave_up", False, False, Step.P_TASK),
                 ("wait", "timeout", False, True, Step.P_BETWEEN), ("close", "closed", False, False, Step.P_BETWEEN)]
        for action, reported, completed, auto, after in cases:
            with self.subTest(action=action):
                self.setUp()
                c = self.make(page_limit_s=1.0) if action == "wait" else self.ctrl
                self.to_first_task(c)
                self.run_page(c, action)
                self.assertEqual(c.step, after)
                self.assertEqual(c.result.reported, reported)
                self.assertEqual(self.saved(self.data)[0]["completed"], completed)
                e = notes.load(self.data, "P05")["pages"][0]
                self.assertEqual((e["participant_reported"], e["completed"], e["auto_stopped_3min"]),
                                 (reported, completed, auto))
                self.assertIsNone(e["issue"])  # 진행자 확인 전
                if after == Step.P_BETWEEN:
                    scr = participant_screen(c)
                    self.assertEqual(scr.texts[0][1], PLAN.p("time_up") if action == "wait" else PLAN.p("window_closed"))
                    c.between_next()
                    self.assertEqual(c.step, Step.P_TASK)
                    self.assertEqual(c.current_page.order, 2)

    def test_facilitator_change_rewrites_only_completed(self):
        c = self.ctrl
        self.to_first_task(c)
        self.run_page(c, "done")
        path = sorted(self.data.glob("human-session-*.json"))[0]
        before = json.loads(path.read_text(encoding="utf-8"))
        # 나머지 5페이지는 이미 했다고 친다(합성 파일)
        for i, p in enumerate(PLAN.pages[1:], start=1):
            self.save_fake(self.data, "P05", p.page_id, True, i)
        self.ctrl._next_task()
        self.assertEqual(c.step, Step.P_FINISHED)
        c.returned()
        rows = c.review_rows()
        entries = {r.page.page_id: (r.confirmed, [], "") for r in rows}
        entries[PLAN.pages[0].page_id] = (False, [3], "다 했어요를 일찍 누름")
        self.assertEqual(c.submit_review(entries), {})
        after = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(after["completed"])
        self.assertEqual({k: v for k, v in after.items() if k != "completed"},
                         {k: v for k, v in before.items() if k != "completed"})
        self.assertEqual(len(list(self.data.glob("human-session-P05-sb-admin-2-register-baseline-*.json"))), 1)
        e = notes.load(self.data, "P05")["pages"][0]
        self.assertEqual((e["participant_reported"], e["completed"], e["completed_confirmed"], e["confirmation_changed"]),
                         ("done", True, False, True))
        self.assertEqual(notes.load(self.data, "P05")["pages"][1]["confirmation_changed"], False)

    def test_timeout_and_closed_are_locked_incomplete(self):
        c = self.make(page_limit_s=1.0)
        self.to_first_task(c)
        self.run_page(c, "wait")
        for i, p in enumerate(PLAN.pages[1:], start=1):
            self.save_fake(self.data, "P05", p.page_id, True, i)
        c.between_next()
        c.returned()
        row = c.review_rows()[0]
        self.assertTrue(row.locked)
        self.assertFalse(row.confirmed)
        entries = {r.page.page_id: (r.confirmed, [], "") for r in c.review_rows()}
        entries[row.page.page_id] = (True, [], "")  # 고정된 페이지는 바꾸려 해도 미완료
        self.assertEqual(c.submit_review(entries), {})
        register = next(self.data.glob("human-session-P05-sb-admin-2-register-baseline-*.json"))
        self.assertFalse(json.loads(register.read_text(encoding="utf-8"))["completed"])
        e = notes.load(self.data, "P05")["pages"][0]
        self.assertEqual((e["completed_confirmed"], e["confirmation_changed"], e["auto_stopped_3min"]), (False, False, True))

    def test_review_rejects_bad_memo(self):
        c = self.ctrl
        for i, p in enumerate(PLAN.pages):
            self.save_fake(self.data, "P05", p.page_id, True, i)
        c.choose("hanchaehun", "P05", False)
        c.run_preflight(True)
        c.start()
        c.resume_continue()
        self.assertEqual(c.step, Step.REVIEW)  # 남은 과업이 없으면 바로 확인표
        entries = {r.page.page_id: (r.confirmed, [], "") for r in c.review_rows()}
        entries[PLAN.pages[0].page_id] = (True, [5], "")  # 기타는 메모 필요
        errors = c.submit_review(entries)
        self.assertIn(PLAN.pages[0].page_id, errors)
        self.assertEqual(c.step, Step.REVIEW)

    def test_resume_skips_saved_pages(self):
        self.save_fake(self.data, "P05", "sb-admin-2/register/baseline", True)
        c = self.ctrl
        self.assertEqual(c.suggest_code("hanchaehun"), "P06")
        info = c.inspect_code("hanchaehun", "P05", False)
        self.assertEqual(info.saved, ["sb-admin-2/register/baseline"])
        c.choose("hanchaehun", "P05", False)
        c.run_preflight(True)
        c.start()
        self.assertEqual(c.step, Step.RESUME)
        self.assertEqual(c.hours, 4)  # 저장된 파일의 값 → 참가자에게 다시 묻지 않는다
        c.resume_continue()
        c.handed_over()
        self.assertFalse(participant_screen(c).hours_input)
        c.participant_begin(None)
        self.assertEqual(c.current_page.page_id, "material-kit-react/sign-in/baseline")
        c.page_index = 0  # 화면이 잘못 ①을 다시 띄우려 해도 막는다
        with self.assertRaises(RuntimeError):
            c.launch_page()

    def test_interrupted_page_is_skipped_and_preset_in_review(self):
        self.data.mkdir(parents=True)
        (self.data / ".partial-P05-sb-admin-2-register-baseline-20261114-010000.jsonl").write_text(
            json.dumps(STABLE[0]) + "\n", encoding="utf-8")
        for i, p in enumerate(PLAN.pages[1:], start=1):
            self.save_fake(self.data, "P05", p.page_id, True, i)
        c = self.ctrl
        self.assertEqual(c.inspect_code("hanchaehun", "P05", False).interrupted, ["sb-admin-2/register/baseline"])
        c.choose("hanchaehun", "P05", False)
        c.run_preflight(True)
        c.start()
        c.resume_continue()
        self.assertEqual(c.step, Step.REVIEW)
        row = c.review_rows()[0]
        self.assertTrue(row.locked)
        self.assertIsNone(row.confirmed)
        self.assertEqual(row.issue_codes, [4])  # 기술 문제
        self.assertEqual(c.submit_review({r.page.page_id: (r.confirmed, r.issue_codes, r.note) for r in c.review_rows()}), {})
        e = notes.load(self.data, "P05")["pages"][0]
        self.assertEqual((e["completed"], e["completed_confirmed"], e["issue"]), (None, None, True))

    def test_empty_partial_does_not_block_page(self):
        self.data.mkdir(parents=True)
        (self.data / ".partial-P05-sb-admin-2-register-baseline-20261114-010000.jsonl").write_text("", encoding="utf-8")
        self.assertEqual(self.ctrl.inspect_code("hanchaehun", "P05", False).attempted, set())


class ParticipantScreenTests(ControllerBase):
    FORBIDDEN = ("읽어 주", "진행자용", "결함", "끝난 시점", "남은 시간", "page_id", "R01", "R02", "R06",
                 "baseline", "contrast", "below-fold", "small", "3:00", "180")

    def check_screen(self, c: Controller) -> str:
        text = participant_screen(c).all_text()
        for word in self.FORBIDDEN:
            self.assertNotIn(word, text, f"{c.step}: {word}")
        for p in PLAN.pages:
            self.assertNotIn(p.done_when, text)
            self.assertNotIn(p.page_id, text)
        self.assertIsNone(re.search(r"\d:\d\d", text), text)  # 남은 시간 표시
        self.assertNotIn("이름 입력", text)
        return text

    def test_participant_screens_have_no_facilitator_words_or_answers(self):
        c = self.make(page_limit_s=1.0)
        c.choose("hanchaehun", "P05", False)
        c.run_preflight(True)
        c.start()
        c.c1_pass()
        c.c2_signed()
        c.handed_over()
        intro = self.check_screen(c)
        self.assertIn(PLAN.p("intro"), intro)
        self.assertTrue(participant_screen(c).hours_input)
        self.assertIsNotNone(c.participant_begin("25"))  # 0~24
        c.participant_begin("6")
        seen_steps = {Step.P_INTRO}
        for i in range(6):
            task = self.check_screen(c)
            seen_steps.add(c.step)
            p = c.current_page
            self.assertIn(p.task_say, task)
            self.assertIn(PLAN.p("task_prompt"), task)
            if p.preface_say:
                self.assertLess(task.index(p.preface_say), task.index(p.task_say))  # ④ 데모 안내 먼저
            for v in p.show_values:
                self.assertIn(v, task)
            c.launch_page()
            while not c.page_visible:
                time.sleep(0.05)
            panel = participant_screen(c)
            self.assertTrue(panel.panel)
            self.check_screen(c)
            seen_steps.add(c.step)
            self.assertIn(p.task_say, panel.all_text())
            self.assertEqual([a for a, _ in panel.buttons], ["done", "give_up"])
            if i == 0:
                c.wait_page(30)  # 1초 제한 → 3분 종료 화면
                self.assertEqual(c.step, Step.P_BETWEEN)
                self.assertEqual(self.check_screen(c).splitlines()[1], PLAN.p("time_up"))
                seen_steps.add(c.step)
                c.between_next()
            else:
                time.sleep(0.4)
                c.report_participant(True)
                c.wait_page(30)
        self.assertEqual(c.step, Step.P_FINISHED)
        self.assertIn(PLAN.p("finished"), self.check_screen(c))
        seen_steps.add(c.step)
        self.assertEqual(seen_steps, set(PARTICIPANT_STEPS))
        self.assertFalse(any("이름" in PLAN.p(k) and "입력" in PLAN.p(k) for k in PLAN.raw["participant"]))


class ControllerSetupTests(ControllerBase):
    def test_suggests_next_free_code_in_range(self):
        self.assertEqual(self.ctrl.suggest_code("hanchaehun"), "P05")  # C-2 표: P05–P07
        self.assertEqual(self.ctrl.suggest_code("msterk11"), "P14")
        self.assertIsNone(self.ctrl.suggest_code("someone-else"))

    def test_out_of_range_code_needs_confirmation(self):
        c = self.ctrl
        info = c.choose("hanchaehun", "P01", False)
        self.assertIn("밖", info.warning)
        self.assertEqual(c.step, Step.SETUP)
        c.choose("hanchaehun", "P01", False, confirm_out_of_range=True)
        self.assertEqual(c.step, Step.PREFLIGHT)
        self.assertEqual(c.code, "P01")

    def test_other_facilitator_needs_github_id_and_confirmation(self):
        c = self.ctrl
        self.assertIsNotNone(c.choose("", "P05", False).error)
        self.assertIsNotNone(c.choose("홍 길동", "P05", False).error)  # 이름 대신 GitHub 아이디
        self.assertIsNotNone(c.choose("new-helper", "P20", False).warning)
        c.choose("new-helper", "P20", False, confirm_out_of_range=True)
        self.assertEqual(c.step, Step.PREFLIGHT)
        self.assertEqual(self.make().remembered_facilitator(), "new-helper")  # 이 PC에 기억

    def test_practice_uses_p00_and_separate_folder(self):
        c = self.ctrl
        self.assertIsNotNone(c.choose("hanchaehun", "P00", False).error)  # 본 실험에서 P00 금지
        self.to_first_task(c, code="P05", practice=True)
        self.assertEqual(c.code, "P00")
        self.run_page(c, "done")
        self.assertEqual(len(self.saved(self.practice)), 1)
        self.assertFalse(self.data.exists() and any(self.data.iterdir()))
        self.assertTrue(c.reset_practice())
        self.assertEqual(list(self.practice.glob("*P00*")), [])

    def test_abort_at_c1_leaves_no_data(self):
        c = self.ctrl
        c.choose("hanchaehun", "P05", False)
        c.run_preflight(True)
        c.start()
        c.abort()
        self.assertEqual(c.step, Step.ABORTED)
        self.assertFalse(any(self.data.glob("*P05*")))
        self.assertEqual(self.make().suggest_code("hanchaehun"), "P05")  # 코드도 쓰지 않았다

    def test_hours_must_be_0_to_24_number(self):
        c = self.ctrl
        c.choose("hanchaehun", "P05", False)
        c.run_preflight(True)
        c.start()
        c.c1_pass()
        c.c2_signed()
        c.handed_over()
        for bad in ("", "abc", "25", "-1", "6시간", "1e1"):
            self.assertIsNotNone(c.participant_begin(bad), bad)
        self.assertEqual(c.step, Step.P_INTRO)
        self.assertIsNone(c.participant_begin("2.5"))
        self.assertEqual(c.hours, 2.5)


class PreflightTests(ControllerBase):
    def go(self, c: Controller, mouse=True):
        c.choose("hanchaehun", "P05", False)
        return c.run_preflight(mouse)

    def test_all_pass_allows_start(self):
        self.go(self.ctrl)
        self.assertTrue(self.ctrl.preflight_ok)
        self.ctrl.start()
        self.assertEqual(self.ctrl.step, Step.C1)

    def test_failed_site_check_blocks_start(self):
        c = self.make(env_checks=lambda: [Check("사이트 서버", False, "200이 아닌 주소")])
        self.go(c)
        self.assertFalse(c.preflight_ok)
        with self.assertRaises(RuntimeError):
            c.start()

    def test_screen_height_threshold_is_procedure_950(self):
        need = int(re.search(r"논리 해상도 세로 (\d+)px 이상", PROCEDURE).group(1))  # 준비물 표·A-3
        self.assertEqual(need, 950)
        self.assertEqual(PLAN.min_screen_avail_height, need)
        for height, ok in ((need - 1, False), (need, True)):
            with self.subTest(height=height):
                c = self.make(screen_size=lambda h=height: (1920, h))
                checks = self.go(c)
                screen = next(x for x in checks if x.name == "화면 높이")
                self.assertEqual(screen.ok, ok)
                self.assertEqual(c.preflight_ok, ok)
                if not ok:
                    self.assertIn(f"{need}px", screen.detail)
                    self.assertIn("배율을 100%로", screen.detail)
                    self.assertIn("'더 넓게'", screen.detail)

    def test_screen_width_is_viewport_plus_panel(self):
        m = re.search(r"브라우저 1280px \+ 참가자 패널 (\d+)px = \*\*(\d+)px 이상\*\*", PROCEDURE)
        panel, need = int(m.group(1)), int(m.group(2))
        self.assertEqual(need, 1280 + panel)
        self.assertEqual(PLAN.min_screen_avail_width, need)
        for width, ok in ((need - 1, False), (need, True)):
            with self.subTest(width=width):
                c = self.make(screen_size=lambda w=width: (w, 1032))
                checks = self.go(c)
                screen = next(x for x in checks if x.name == "화면 너비")
                self.assertEqual(screen.ok, ok)
                self.assertEqual(c.preflight_ok, ok)
                if not ok:
                    self.assertIn("배율을 100%로", screen.detail)

    def test_short_screen_blocks_start(self):
        c = self.make(screen_size=lambda: (1536, 864))  # FHD 125% (A-3)
        bad = [x.name for x in self.go(c) if not x.ok]
        self.assertEqual(bad, ["화면 높이", "화면 너비"])
        with self.assertRaises(RuntimeError):
            c.start()

    def test_mouse_must_be_confirmed(self):
        self.go(self.ctrl, mouse=False)
        self.assertFalse(self.ctrl.preflight_ok)
        self.ctrl.run_preflight(True)
        self.assertTrue(self.ctrl.preflight_ok)
        self.ctrl.invalidate_preflight()
        self.assertFalse(self.ctrl.preflight_ok)


class NotesTests(ControllerBase):
    def test_note_validation(self):
        self.assertIsNone(notes.check_note([], ""))
        self.assertIsNotNone(notes.check_note([5], ""))  # 기타는 메모 필요 (self_guided_v1)
        self.assertIsNotNone(notes.check_note([6], ""))  # self_guided_v1에는 6이 없다
        self.assertIsNotNone(notes.check_note([1], "두 줄\n메모"))
        self.assertIsNotNone(notes.check_note([1], "가" * 201))
        self.assertIsNotNone(notes.check_note([6], "", notes.READ_ALOUD))  # 읽어 주던 방식의 기타
        self.assertEqual(sorted(notes.ISSUE_CODES[notes.SELF_GUIDED]), [1, 2, 3, 4, 5])
        self.assertEqual(sorted(notes.ISSUE_CODES[notes.READ_ALOUD]), [1, 2, 3, 4, 5, 6])

    def test_before_app_notes_leave_session_files_untouched(self):
        folder = Path(self.tmp.name) / "old"
        self.save_fake(folder, "P02", "sb-admin-2/register/baseline", True, 0)
        self.save_fake(folder, "P02", "shadcn-admin/tasks/contrast", False, 1)
        before = {f: hashlib.sha256(f.read_bytes()).hexdigest() for f in folder.glob("human-session-*.json")}
        c = self.ctrl
        rows, err = c.before_app_pages(folder, "P02")
        self.assertIsNone(err)
        self.assertEqual([r["saved"] for r in rows], [True, False, True, False, False, False])
        path = c.save_before_app_notes(folder, "P02", "bomink1215", {
            "sb-admin-2/register/baseline": ([1], "과업 문장을 줄여 읽음"),
            "shadcn-admin/tasks/contrast": ([], ""),
        })
        self.assertEqual(path.name, "notes-P02.json")
        self.assertEqual({f: hashlib.sha256(f.read_bytes()).hexdigest() for f in before}, before)
        n = json.loads(path.read_text(encoding="utf-8"))
        s = n["session"]
        self.assertEqual(list(s), list(notes.SESSION_FIELDS))
        for k in ("app_version", "repo_commit", "site_manifest_hashes", "run_mode"):
            self.assertEqual(s[k], "before-app")
        self.assertEqual(s["procedure_version"], "read_aloud")
        self.assertEqual(s["started_at"], "2026-11-12T05:00:00Z")
        self.assertEqual(len(n["pages"]), 6)
        p1 = n["pages"][0]
        self.assertEqual(list(p1), list(notes.PAGE_FIELDS))
        self.assertEqual((p1["completed"], p1["completed_confirmed"], p1["issue"], p1["issue_codes"]),
                         (True, True, True, [1]))
        self.assertEqual((n["pages"][2]["completed"], n["pages"][2]["issue"]), (False, False))
        self.assertIsNone(n["pages"][1]["completed"])  # 세션 파일 없음

    def test_before_app_refuses_notes_made_by_app(self):
        folder = Path(self.tmp.name) / "old"
        self.save_fake(folder, "P03", "sb-admin-2/register/baseline", True)
        notes.save(folder, "P03", notes.new({**SESSION_INFO, "participant_code": "P03", "facilitator": "x",
                                             "screen_avail_height": 1000, "started_at": None,
                                             "procedure_version": "self_guided_v1"}))
        rows, err = self.ctrl.before_app_pages(folder, "P03")
        self.assertIn("덮어쓰지", err)
        with self.assertRaises(ValueError):
            self.ctrl.save_before_app_notes(folder, "P03", "bomink1215", {})


# ---------------------------------------------------------------- 저장 위치 · 시작 실패 · 철회 · 확인표 순서

class DataLocationTests(unittest.TestCase):
    """기준: 참가자 기록은 동기화되는 문서 폴더가 아니라 홈 폴더에 둔다(절차서 D-1·D-2)."""

    def test_data_dirs_are_under_home_not_documents(self):
        from unittest import mock

        from app import resources
        with mock.patch.dict("os.environ", {resources.HOME_ENV: ""}):
            self.assertEqual(resources.data_root(), Path.home())
            self.assertEqual(resources.data_dirs(), (Path.home() / "StepMeter-human",
                                                     Path.home() / "StepMeter-human-practice"))
            self.assertEqual(resources.legacy_data_dir(), resources.documents_dir() / "StepMeter-human")
        with mock.patch.dict("os.environ", {resources.HOME_ENV: "/tmp/x"}):
            self.assertEqual(resources.data_root(), Path("/tmp/x"))
            self.assertIsNone(resources.legacy_data_dir())  # 위치를 직접 주면 예전 위치를 보지 않는다

    def test_legacy_location_with_records_blocks_preflight(self):
        from app.resources import legacy_data_problem
        with tempfile.TemporaryDirectory() as tmp:
            legacy, current = Path(tmp) / "docs" / "StepMeter-human", Path(tmp) / "home" / "StepMeter-human"
            self.assertIsNone(legacy_data_problem(None, current))
            self.assertIsNone(legacy_data_problem(legacy, current))  # 폴더 없음
            legacy.mkdir(parents=True)
            (legacy / "desktop.ini").write_text("", encoding="utf-8")
            self.assertIsNone(legacy_data_problem(legacy, current))  # 기록이 아닌 파일만
            (legacy / "human-session-P05-x-20261116-010000.json").write_text("{}", encoding="utf-8")
            (legacy / "notes-P05.json").write_text("{}", encoding="utf-8")
            msg = legacy_data_problem(legacy, current)
            self.assertIsNotNone(msg)
            self.assertIn(str(legacy), msg or "")
            self.assertIn(str(current), msg or "")
            self.assertIn("2개", msg or "")
            self.assertIsNone(legacy_data_problem(legacy, legacy))  # 같은 폴더면 문제 아님


class StartupMessageTests(unittest.TestCase):
    def test_exe_message_says_unzip_again_and_log(self):
        from app.runtime import startup_message
        log = Path("C:/x/app.log")
        text = startup_message(FileNotFoundError("session_plan.json 없음"), True, log)
        self.assertIn("session_plan.json 없음", text)
        self.assertIn("zip을 새 폴더에", text)
        self.assertIn(str(log), text)
        self.assertIn("git pull", startup_message(RuntimeError("x"), False, None))
        self.assertNotIn("로그 파일", startup_message(RuntimeError("x"), False, None))


class WithdrawTests(ControllerBase):
    """기준: 동의서 6절 "그만두시면 그때까지의 기록을 지웁니다", 절차서 C-8(코드는 다시 주지 않는다)."""

    def test_withdraw_mid_session_removes_records_and_retires_code(self):
        c = self.ctrl
        self.assertEqual(c.suggest_code("hanchaehun"), "P05")
        self.to_first_task(c)
        self.run_page(c, "done")
        self.assertEqual(c.step, Step.P_TASK)
        self.assertTrue(list(self.data.glob("human-session-P05-*.json")))
        (self.data / "check-P05.txt").write_text("x", encoding="utf-8")
        (self.data / "upload-P05.zip").write_bytes(b"x")
        (self.data / ".partial-P05-material-kit-react-sign-in-baseline-20261116-010000.jsonl").write_text(
            json.dumps(STABLE[0]) + "\n", encoding="utf-8")
        other = self.save_fake(self.data, "P06", PLAN.pages[0].page_id, True)  # 다른 참가자 것은 남는다
        removed = c.withdraw()
        self.assertEqual(c.step, Step.WITHDRAWN)
        self.assertIn("notes-P05.json", removed)
        self.assertEqual(sorted(f.name for f in self.data.iterdir()), sorted(["withdrawn-P05.txt", other.name]))
        marker = (self.data / "withdrawn-P05.txt").read_text(encoding="utf-8")
        self.assertNotIn("hanchaehun", marker)  # 날짜만, 사람 정보 없음
        c.back_to_setup()
        self.assertEqual(c.suggest_code("hanchaehun"), "P07")  # P05 철회, P06 사용 중
        self.assertIsNotNone(c.inspect_code("hanchaehun", "P05", False).error)
        self.assertEqual(c.choose("hanchaehun", "P05", False).error, c.inspect_code("hanchaehun", "P05", False).error)
        self.assertEqual(c.step, Step.SETUP)

    def test_withdraw_after_session_from_preflight(self):
        for i, p in enumerate(PLAN.pages):
            self.save_fake(self.data, "P06", p.page_id, True, i)
        c = self.ctrl
        c.choose("hanchaehun", "P06", False)
        self.assertTrue(c.info and c.info.attempted)
        self.assertEqual(len(c.withdraw()), 6)
        self.assertEqual([f.name for f in self.data.iterdir()], ["withdrawn-P06.txt"])

    def test_cannot_withdraw_while_page_runs_or_before_consent(self):
        c = self.ctrl
        with self.assertRaises(RuntimeError):
            c.withdraw()  # SETUP
        c.choose("hanchaehun", "P05", False)
        c.run_preflight(True)
        c.start()
        self.assertEqual(c.step, Step.C1)
        with self.assertRaises(RuntimeError):
            c.withdraw()  # C-1·C-2는 [중단]
        c.step = Step.P_RUNNING
        with self.assertRaises(RuntimeError):
            c.withdraw()

    def test_reset_practice_clears_practice_withdrawal(self):
        c = self.ctrl
        c.choose("hanchaehun", "", True)
        c.withdraw()
        self.assertTrue((self.practice / "withdrawn-P00.txt").exists())
        self.assertIsNotNone(c.inspect_code("hanchaehun", "", True).error)
        c.back_to_setup()
        self.assertIn("withdrawn-P00.txt", c.reset_practice())
        self.assertIsNone(c.inspect_code("hanchaehun", "", True).error)


class ReviewOrderAndReportTests(ControllerBase):
    def to_review(self, code: str, pages) -> Controller:
        for i, p in enumerate(pages):
            self.save_fake(self.data, code, p.page_id, True, i)
        c = self.make()
        c.choose("hanchaehun", code, False)
        c.run_preflight(True)
        c.start()
        if c.step == Step.RESUME:
            c.resume_continue()
        if c.step == Step.HANDOVER:  # 남은 페이지가 있으면 오류로 건너뛴 것으로 남긴다
            c.handed_over()
            c.participant_begin(None)
            c.step = Step.P_ERROR
            c.skip_page()
            c.returned()
        self.assertEqual(c.step, Step.REVIEW)
        return c

    def test_crash_during_review_save_keeps_confirmed_value(self):
        from unittest import mock
        c = self.to_review("P05", PLAN.pages)
        first = PLAN.pages[0].page_id
        entries = {r.page.page_id: (r.confirmed, [], "") for r in c.review_rows()}
        entries[first] = (False, [], "")
        with mock.patch.object(SESSION, "save_session", side_effect=OSError("디스크 오류")):
            with self.assertRaises(OSError):
                c.submit_review(entries)
        # 다시 열면(새 controller) 확인표 기본값이 진행자가 고른 값이다
        c2 = self.to_review("P05", [])
        self.assertFalse(c2.review_rows()[0].confirmed)
        self.assertEqual(c2.submit_review({r.page.page_id: (r.confirmed, [], "") for r in c2.review_rows()}), {})
        f = sorted(self.data.glob("human-session-P05-sb-admin-2-register-*.json"))[0]
        self.assertFalse(json.loads(f.read_text(encoding="utf-8"))["completed"])

    def test_report_lists_pages_without_session_file(self):
        c = self.to_review("P05", PLAN.pages[:5])
        self.assertEqual(c.submit_review({r.page.page_id: (r.confirmed, r.issue_codes, r.note)
                                          for r in c.review_rows()}), {})
        rep = c.finish_session()
        self.assertEqual(rep.unsaved, [PLAN.pages[5].page_id])
        self.assertFalse(rep.ok)  # check_sessions는 빠진 페이지를 오류로 본다(절차서 C-7: 이 경우는 예상된 오류)


class BrowserErrorScreenTests(ControllerBase):
    def test_crash_shows_browser_error_line(self):
        from app.controller import PageResult
        c = self.ctrl
        c.step = Step.P_BETWEEN
        for reported, key in (("crashed", "browser_error"), ("closed", "window_closed"), ("timeout", "time_up")):
            c.result = PageResult(PLAN.pages[0], False, reported, path=Path("x"))
            self.assertIn(PLAN.p(key), participant_screen(c).all_text())


if __name__ == "__main__":
    unittest.main()
