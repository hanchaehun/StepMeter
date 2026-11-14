"""진행 화면 (tkinter 창 하나). 진행 로직은 controller.Controller, 참가자 화면 내용은 views.participant_screen에 있다.

진행자 화면(진행자·코드 → 점검 → C-1 → C-2 → 건네기 / 확인표 → C-5 → 검사)과 참가자 화면(시작 안내 → 과업 →
진행 중 오른쪽 패널 → 돌려주기)을 같은 창에서 바꿔 그린다. 컨트롤러 상태는 0.2초마다 읽어 바뀌면 다시 그린다
(페이지 세션은 다른 스레드에서 돈다).
"""
from __future__ import annotations

import functools
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from . import notes as notes_mod
from .controller import OTHER_FACILITATOR, Controller, Step
from .views import participant_screen, version_line, window_title

if sys.platform == "win32":
    FAMILY = "Malgun Gothic"
elif sys.platform == "darwin":
    FAMILY = "Apple SD Gothic Neo"
else:
    FAMILY = "TkDefaultFont"

SAY_FONT = (FAMILY, 26)
TITLE_FONT = (FAMILY, 22, "bold")
BODY_FONT = (FAMILY, 16)
SMALL_FONT = (FAMILY, 13)
BTN_FONT = (FAMILY, 18, "bold")
PANEL_FONT = (FAMILY, 20)
MONO_FONT = ("Consolas" if sys.platform == "win32" else "Menlo", 12)

BG = "#ffffff"
SAY_BG = "#fff7d6"
OK_FG = "#1b7f3b"
BAD_FG = "#b3261e"
MUTED = "#555555"
CHROMIUM_OUTER_WIDTH = 1296  # 뷰포트 1280 + 창 테두리. Chromium 창은 (0, 0)으로 옮긴다(controller._place_window)


def play_alert(root: tk.Misc) -> None:
    """3분 알림 소리."""
    def run() -> None:
        try:
            if sys.platform == "win32":
                import winsound
                for _ in range(2):
                    winsound.Beep(880, 300)
            elif sys.platform == "darwin":
                subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], check=False)
            else:
                root.bell()
        except Exception:  # noqa: BLE001  소리가 안 나도 화면 문장은 보인다
            pass
    threading.Thread(target=run, daemon=True).start()


def open_folder(path: Path) -> None:
    try:
        if sys.platform == "win32":
            getattr(os, "startfile")(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        pass


class ScrollFrame(tk.Frame):
    """세로 스크롤되는 본문."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, bg=BG)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.bind_all("<MouseWheel>", self._wheel)

    def _wheel(self, event: Any) -> None:
        delta = event.delta if sys.platform == "darwin" else event.delta // 120
        self.canvas.yview_scroll(-delta, "units")

    def clear(self) -> None:
        for w in self.inner.winfo_children():
            w.destroy()
        self.canvas.yview_moveto(0)


class App:
    def __init__(self, root: tk.Tk, ctrl: Controller, sites: Any, server_error: str | None,
                 auto: Callable[["App", Any], None] | None = None) -> None:
        self.root, self.ctrl, self.sites, self.server_error = root, ctrl, sites, server_error
        self.auto = auto
        info = ctrl.d.session_info
        self.version = str(info.get("app_version") or "?")
        self.run_mode = str(info.get("run_mode") or "")
        root.title(window_title(self.version))
        root.configure(bg=BG)
        self.docked = False
        self.place_mode: str | None = None  # 마지막으로 창을 놓은 방식: "panel" | "normal"
        self.place_log: list[str] = []  # 창 위치를 다시 잡은 기록 (app.log에도 남긴다)
        self._place_normal("시작")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.body = ScrollFrame(root)
        self.body.pack(fill="both", expand=True)
        self.wrap_labels: list[tk.Label] = []
        root.bind("<Configure>", self._rewrap)
        # 화면을 다시 그려도 값이 남아야 하는 입력들
        self.fac_var = tk.StringVar()
        self.other_var = tk.StringVar()
        self.code_var = tk.StringVar()
        self.practice_var = tk.BooleanVar(value=False)
        self.mouse_var = tk.BooleanVar(value=False)
        self.hours_var = tk.StringVar()
        self.review_vars: dict[str, tuple[tk.StringVar, dict[int, tk.BooleanVar], tk.StringVar]] = {}
        self.review_errors: dict[str, str] = {}
        self.preflight_running = False
        self.alerted_for: Any = None
        self.opened_for: Any = None
        self.screen_mode = "flow"  # "flow" | "before_app"
        self.rendered: tuple[Any, Any, Any] = (-1, None, None)
        self.message: tuple[str, str] | None = None  # (글, 색) 한 번 보여 줄 안내
        remembered = ctrl.remembered_facilitator()
        if remembered in ctrl.facilitator_choices():
            self.fac_var.set(remembered or "")
        elif remembered:
            self.fac_var.set(OTHER_FACILITATOR)
            self.other_var.set(remembered)
        self.poll()

    # ------------------------------------------------------------ 공통 위젯

    def width(self) -> int:
        return max(300, self.root.winfo_width() - 90)

    def _rewrap(self, _event: Any = None) -> None:
        w = self.width()
        for lbl in list(self.wrap_labels):
            try:
                lbl.configure(wraplength=w if not getattr(lbl, "_inset", False) else w - 40)
            except tk.TclError:
                self.wrap_labels.remove(lbl)

    def label(self, text: str, font: Any = BODY_FONT, fg: str = "#000", parent: tk.Misc | None = None,
              bg: str = BG, pady: int | tuple[int, int] = 4, inset: bool = False) -> tk.Label:
        lbl = tk.Label(parent or self.body.inner, text=text, font=font, fg=fg, bg=bg, justify="left", anchor="w",
                       wraplength=self.width() - (40 if inset else 0))
        setattr(lbl, "_inset", inset)
        lbl.pack(fill="x", padx=24, pady=pady)
        self.wrap_labels.append(lbl)
        return lbl

    def title(self, text: str) -> None:
        self.label(text, TITLE_FONT, pady=(16, 6))

    def say(self, text: str, heading: str = "읽어 주세요", fg: str = "#000") -> None:
        """진행자가 소리 내어 읽는 문장."""
        box = tk.Frame(self.body.inner, bg=SAY_BG, highlightbackground="#e0c96b", highlightthickness=2)
        box.pack(fill="x", padx=24, pady=8)
        tk.Label(box, text=f"🗣 {heading}", font=SMALL_FONT, fg="#7a5d00", bg=SAY_BG, anchor="w").pack(
            fill="x", padx=12, pady=(8, 0))
        lbl = tk.Label(box, text=text, font=SAY_FONT, fg=fg, bg=SAY_BG, justify="left", anchor="w",
                       wraplength=self.width() - 40)
        setattr(lbl, "_inset", True)
        lbl.pack(fill="x", padx=12, pady=(2, 12))
        self.wrap_labels.append(lbl)

    def buttons(self, specs: list[tuple[str, Callable[[], Any], str]], parent: tk.Misc | None = None,
                font: Any = BTN_FONT) -> list[tk.Button]:
        row = tk.Frame(parent or self.body.inner, bg=BG)
        row.pack(fill="x", padx=24, pady=14)
        out = []
        colors = {"primary": ("#1a5fb4", "#fff"), "ok": ("#1b7f3b", "#fff"), "bad": ("#b3261e", "#fff"),
                  "plain": ("#e8e8e8", "#000")}
        for text, cmd, kind in specs:
            bg, fg = colors[kind]
            b = tk.Button(row, text=text, command=cmd, font=font, bg=bg, fg=fg, activebackground=bg,
                          activeforeground=fg, padx=18, pady=10, relief="flat", disabledforeground="#999")
            b.pack(side="left", padx=(0, 14), pady=4)
            out.append(b)
        return out

    def checks_view(self, checks: list[Any]) -> None:
        for c in checks:
            mark, color = ("✓", OK_FG) if c.ok else ("✗", BAD_FG)
            self.label(f"{mark} {c.name}: {c.detail}", BODY_FONT, color, pady=2)

    def show_message(self) -> None:
        if self.message:
            text, color = self.message
            self.label(text, BODY_FONT, color)
            self.message = None

    def facilitator_banner(self) -> None:
        tk.Label(self.body.inner, text="진행자 화면", font=SMALL_FONT, fg="#fff", bg="#5b5b5b", anchor="w",
                 padx=10).pack(fill="x")

    # ------------------------------------------------------------ 갱신

    def poll(self) -> None:
        c = self.ctrl
        key = (c.version, c.step, self.screen_mode)
        if key != self.rendered:
            self.rendered = key
            self.render()
        self._polls = getattr(self, "_polls", 0) + 1
        if self._polls % 5 == 0:  # 1초마다: 창이 화면 밖에 나가 있으면 다시 넣는다
            self.ensure_on_screen()
        self.root.after(200, self.poll)

    def render(self) -> None:
        self.body.clear()
        self.wrap_labels = []
        step = self.ctrl.step
        mode = "panel" if step == Step.P_RUNNING else ("participant" if self.ctrl.participant_facing else "facilitator")
        if mode == "panel":
            self._dock(True)
        elif mode != getattr(self, "_last_mode", None):
            # 패널 → 일반 화면, 참가자 → 진행자 화면으로 바뀔 때마다 위치·크기를 새로 정한다(이전 상태에 기대지 않는다)
            self._place_normal(f"{getattr(self, '_last_mode', None)}→{mode}")
        self._last_mode = mode
        if self.screen_mode == "before_app":
            self.render_before_app()
        elif self.ctrl.participant_facing:
            self.render_participant()
        else:
            self.facilitator_banner()
            getattr(self, f"render_{step.value}")()
        if self.auto is not None:
            key = self.rendered
            self.root.after(getattr(self.auto, "delay_ms", 800), lambda: self.auto(self, key) if self.auto else None)

    # ------------------------------------------------------------ 창 위치
    # 원래는 패널 → 일반 화면으로 돌아올 때 위치를 한 번만 정하고(-topmost 해제 → geometry → lift → focus_force)
    # 실제로 그 자리에 갔는지 확인하지 않았다. 창 관리자 쪽 사건(Chromium 창이 닫히며 활성 창이 바뀜, -topmost
    # 해제, 사용자 조작)과 겹치면 크기만 바뀌고 위치는 패널 자리(x=1296)에 남을 수 있다. 그래서 매번 명시적으로
    # 놓고, 잠시 뒤 실제 위치를 확인해 다르면 다시 놓으며, 1초마다 화면 밖에 나간 창을 안으로 넣는다.

    def screen_size(self) -> tuple[int, int]:
        return self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def normal_rect(self) -> tuple[int, int, int, int]:
        """(w, h, x, y): 화면 가운데, 일반 크기. 화면보다 크면 화면 안에 맞춘다."""
        sw, sh = self.screen_size()
        w, h = min(1200, max(300, sw - 40)), min(900, max(300, sh - 80))
        return w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 2 - 20)

    def _log_place(self, text: str) -> None:
        line = f"[창] {text}"
        self.place_log.append(line)
        print(line, flush=True)

    def _apply_geometry(self, w: int, h: int, x: int, y: int) -> None:
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.update_idletasks()

    def _place_normal(self, reason: str) -> None:
        self.docked = False
        self.place_mode = "normal"
        # -topmost를 먼저 풀고 그 처리가 끝난 뒤 위치를 준다 (geometry와 -topmost 변경이 겹치면 이동이 취소된다)
        self.root.attributes("-topmost", False)
        self.root.update_idletasks()
        w, h, x, y = self.normal_rect()
        self._apply_geometry(w, h, x, y)
        self.root.lift()
        self._log_place(f"일반 {w}x{h}+{x}+{y} ({reason})")
        for delay in (150, 600):
            self.root.after(delay, self._verify_normal)

    def _dock(self, on: bool) -> None:
        """진행 중에는 창을 Chromium(왼쪽 위 1296px) 오른쪽의 작은 패널로 만들고 위에 둔다."""
        if not on:
            self._place_normal("패널 끝")
            return
        if self.docked:
            return
        self.docked = True
        self.place_mode = "panel"
        sw, sh = self.screen_size()
        # Windows Tk: geometry 바로 뒤에 -topmost를 바꾸면 위치 이동이 취소된다. 순서를 지킨다
        self.root.attributes("-topmost", True)
        self.root.update_idletasks()
        x = min(CHROMIUM_OUTER_WIDTH, max(0, sw - 300))
        self._apply_geometry(sw - x, max(400, sh - 80), x, 0)
        self._log_place(f"패널 {sw - x}x{max(400, sh - 80)}+{x}+0")

    def window_rect(self) -> tuple[int, int, int, int]:
        self.root.update_idletasks()
        return self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width(), self.root.winfo_height()

    def _verify_normal(self) -> None:
        """일반 화면이면 실제 위치·크기가 정한 값인지 확인하고, 다르면 다시 놓는다."""
        if self.docked or self.place_mode != "normal":
            return
        w, h, x, y = self.normal_rect()
        ax, ay, aw, ah = self.window_rect()
        if abs(ax - x) > 12 or abs(ay - y) > 40 or abs(aw - w) > 12:
            self._log_place(f"일반 위치가 어긋남 실제 {aw}x{ah}+{ax}+{ay} → 다시 놓음")
            self.root.attributes("-topmost", False)
            self.root.update_idletasks()
            self._apply_geometry(w, h, x, y)

    def off_screen(self) -> bool:
        sw, sh = self.screen_size()
        x, y, w, h = self.window_rect()
        tol = 16  # 창 테두리
        return x < -tol or y < -tol or x + w > sw + tol or y + h > sh + tol

    def ensure_on_screen(self) -> bool:
        """어느 화면이든 창이 화면 밖으로 나가 있으면 일반 크기로 가운데에 다시 놓는다. 다시 놓았으면 True."""
        if self.docked or not self.off_screen():
            return False
        x, y, w, h = self.window_rect()
        self._log_place(f"화면 밖 {w}x{h}+{x}+{y} → 안으로")
        self._place_normal("화면 밖")
        return True

    def on_close(self) -> None:
        if self.ctrl.step == Step.P_RUNNING:
            messagebox.showwarning("진행 중", "과업 진행 중입니다. 먼저 [다 했어요]나 [그만할게요]를 누르세요.", parent=self.root)
            return
        if self.ctrl.step not in (Step.SETUP, Step.PREFLIGHT, Step.DONE, Step.ABORTED):
            if not messagebox.askyesno("닫기", "세션 도중입니다. 닫아도 저장된 페이지는 남고, 다시 열면 남은 차례부터 "
                                       "이어 할 수 있습니다. 닫을까요?", parent=self.root):
                return
        if self.sites is not None:
            self.sites.stop()
        self.root.destroy()

    # ------------------------------------------------------------ 참가자 화면

    def render_participant(self) -> None:
        c = self.ctrl
        scr = participant_screen(c)
        panel = scr.panel
        big = PANEL_FONT if panel else SAY_FONT
        if scr.heading:
            self.label(scr.heading, BODY_FONT if panel else TITLE_FONT, MUTED if panel else "#000", pady=(16, 4))
        values_box: tk.Frame | None = None
        for kind, text in scr.texts:
            if kind == "big":
                self.label(text, big, pady=(8, 8))
            elif kind == "label":
                values_box = tk.Frame(self.body.inner, bg="#eef4ff", highlightbackground="#9bb7e8", highlightthickness=2)
                values_box.pack(fill="x", padx=24, pady=8)
                tk.Label(values_box, text=text, font=SMALL_FONT, bg="#eef4ff", fg="#1a5fb4", anchor="w").pack(
                    fill="x", padx=12, pady=(6, 0))
            elif kind == "values" and values_box is not None:
                tk.Label(values_box, text=text, font=big, bg="#eef4ff", anchor="w").pack(fill="x", padx=12)
            elif kind == "alert":
                self.label(text, SAY_FONT, BAD_FG, pady=(40, 16))
            elif kind == "small":
                self.label(text, SMALL_FONT, MUTED)
            else:
                self.label(text, PANEL_FONT if panel else BODY_FONT, pady=(8, 4))
        if scr.hours_input:
            row = tk.Frame(self.body.inner, bg=BG)
            row.pack(fill="x", padx=24, pady=8)
            ent = tk.Entry(row, textvariable=self.hours_var, font=SAY_FONT, width=5)
            ent.pack(side="left")
            tk.Label(row, text="시간", font=BODY_FONT, bg=BG).pack(side="left", padx=8)
            ent.focus_set()
            ent.bind("<Return>", lambda e: self.p_action("begin"))
        self.show_message()
        actions = {"begin": "primary", "start": "primary", "done": "ok", "give_up": "plain", "next": "primary",
                   "returned": "primary"}
        specs: list[tuple[str, Callable[[], Any], str]] = [
            (label, functools.partial(self.p_action, action), actions[action]) for action, label in scr.buttons]
        btns = self.buttons(specs, font=BTN_FONT)
        if panel and not c.page_visible:
            for b in btns:
                b.configure(state="disabled")
        r = c.result
        if c.step == Step.P_BETWEEN and r is not None and r.reported == "timeout" and self.alerted_for is not r:
            self.alerted_for = r
            play_alert(self.root)

    def p_action(self, action: str) -> None:
        c = self.ctrl
        if action == "begin":
            err = c.participant_begin(self.hours_var.get())
            if err:
                self.message = (err, BAD_FG)
                self.rendered = (-1, None, None)
        elif action == "start":
            c.launch_page()
        elif action == "done":
            c.report_participant(True)
        elif action == "give_up":
            if messagebox.askyesno(c.plan.p("give_up_button"), c.plan.p("give_up_confirm"), parent=self.root):
                c.report_participant(False)
        elif action == "next":
            c.between_next()
        elif action == "returned":
            c.returned()

    # ------------------------------------------------------------ 진행자: 처음 화면

    def selected_github(self) -> str:
        v = self.fac_var.get()
        return self.other_var.get().strip() if v == OTHER_FACILITATOR else v

    def render_setup(self) -> None:
        c = self.ctrl
        self.title("StepMeter 사람 실험 진행")
        if self.server_error:
            self.label(f"사이트 서버를 띄우지 못했습니다: {self.server_error}", BODY_FONT, BAD_FG)
        self.show_message()
        frm = tk.Frame(self.body.inner, bg=BG)
        frm.pack(fill="x", padx=24, pady=8)
        tk.Label(frm, text="진행자", font=BODY_FONT, bg=BG).grid(row=0, column=0, sticky="w", pady=6)
        labels = {f.github: f"{f.github}  ({f.range_text})" for f in c.plan.facilitators}
        combo = ttk.Combobox(frm, values=c.facilitator_choices(), textvariable=self.fac_var, state="readonly",
                             font=BODY_FONT, width=24)
        combo.grid(row=0, column=1, sticky="w", padx=10)
        range_lbl = tk.Label(frm, text="", font=SMALL_FONT, fg=MUTED, bg=BG)
        range_lbl.grid(row=0, column=2, sticky="w")
        other_lbl = tk.Label(frm, text="GitHub 아이디 (이름 말고)", font=BODY_FONT, bg=BG)
        other_ent = tk.Entry(frm, textvariable=self.other_var, font=BODY_FONT, width=24)
        tk.Label(frm, text="참가자 코드", font=BODY_FONT, bg=BG).grid(row=2, column=0, sticky="w", pady=6)
        code_ent = tk.Entry(frm, textvariable=self.code_var, font=BODY_FONT, width=8)
        code_ent.grid(row=2, column=1, sticky="w", padx=10)
        code_hint = tk.Label(frm, text="", font=SMALL_FONT, fg=MUTED, bg=BG, justify="left")
        code_hint.grid(row=2, column=2, sticky="w")
        practice = tk.Checkbutton(frm, text="연습 모드 (P00, 연습 폴더에 따로 저장)", variable=self.practice_var,
                                  font=BODY_FONT, bg=BG)
        practice.grid(row=3, column=0, columnspan=3, sticky="w", pady=6)
        folder_lbl = tk.Label(frm, text="", font=SMALL_FONT, fg=MUTED, bg=BG)
        folder_lbl.grid(row=4, column=0, columnspan=3, sticky="w")
        reset_btn = tk.Button(frm, text="연습 기록 지우기", font=SMALL_FONT, command=self.reset_practice)

        def refresh(*_: Any) -> None:
            gh = self.selected_github()
            if self.fac_var.get() == OTHER_FACILITATOR:
                other_lbl.grid(row=1, column=0, sticky="w", pady=6)
                other_ent.grid(row=1, column=1, sticky="w", padx=10)
                range_lbl.configure(text="목록에 없는 진행자: 범위가 없어 코드를 직접 넣습니다")
            else:
                other_lbl.grid_remove()
                other_ent.grid_remove()
                range_lbl.configure(text=labels.get(gh, ""))
            if self.practice_var.get():
                code = c.plan.practice_code
                self.code_var.set(code)
                code_ent.configure(state="disabled")
                code_hint.configure(text="연습은 P00만 씁니다")
                folder_lbl.configure(text=f"저장 폴더: {c.d.practice_dir}")
                if c.attempted(code, practice=True):
                    reset_btn.grid(row=5, column=0, columnspan=2, sticky="w", pady=4)
                    code_hint.configure(text="연습 기록이 있습니다. 이어 하거나 [연습 기록 지우기]")
                else:
                    reset_btn.grid_remove()
            else:
                reset_btn.grid_remove()
                code_ent.configure(state="normal")
                folder_lbl.configure(text=f"저장 폴더: {c.d.data_dir}")
                f = c.plan.facilitator(gh)
                if f is None:
                    if self.code_var.get() == c.plan.practice_code:
                        self.code_var.set("")
                    code_hint.configure(text="")
                    return
                nxt = c.suggest_code(gh)
                if nxt:
                    if self.code_var.get() in ("", c.plan.practice_code) or self.code_var.get() not in f.codes() \
                            or c.attempted(self.code_var.get()):
                        self.code_var.set(nxt)
                    code_hint.configure(text=f"범위 {f.range_text} · 다음 빈 번호 {nxt}")
                else:
                    code_hint.configure(text=f"범위 {f.range_text}를 다 썼습니다. 세션 운영 담당에게 더 받으세요", fg=BAD_FG)

        combo.bind("<<ComboboxSelected>>", refresh)
        self.practice_var.trace_add("write", refresh)
        refresh()
        self.buttons([("다음: 시작 전 점검", self.on_setup_next, "primary")])
        self.label("이미 진행한 세션에 진행 이상 메모만 남기려면:", SMALL_FONT, MUTED, pady=(24, 0))
        self.buttons([("이미 끝난 세션 메모 입력", self.open_before_app, "plain")])
        self.version_label = self.label(version_line(self.version, self.run_mode), SMALL_FONT, MUTED, pady=(30, 8))

    def reset_practice(self) -> None:
        if messagebox.askyesno("연습 기록 지우기", f"{self.ctrl.d.practice_dir}의 P00 기록을 지울까요?\n"
                               "(본 데이터 폴더는 건드리지 않습니다)", parent=self.root):
            removed = self.ctrl.reset_practice()
            self.message = (f"연습 기록 {len(removed)}개를 지웠습니다.", OK_FG)
            self.rendered = (-1, None, None)

    def on_setup_next(self) -> None:
        c = self.ctrl
        gh, code, practice = self.selected_github(), self.code_var.get(), self.practice_var.get()
        info = c.choose(gh, code, practice)
        if info.error:
            messagebox.showerror("확인", info.error, parent=self.root)
            return
        if info.warning and c.step == Step.SETUP:
            if not messagebox.askyesno("범위 밖 코드", info.warning + "\n\n이 코드로 진행할까요?", parent=self.root):
                return
            info = c.choose(gh, code, practice, confirm_out_of_range=True)
        if info.attempted:
            marks = [p.mark for p in c.plan.pages if p.page_id in info.attempted]
            messagebox.showinfo("이어 하기", f"{info.code}는 {' '.join(marks)} 차례를 이미 했습니다. "
                                "같은 페이지는 다시 하지 않고 남은 차례만 진행합니다.", parent=self.root)

    # ------------------------------------------------------------ 진행자: 점검

    def render_preflight(self) -> None:
        c = self.ctrl
        mode = "연습" if c.practice else "본 실험"
        self.title(f"시작 전 점검 — {c.code} ({mode}, 진행자 {c.facilitator})")
        tk.Checkbutton(self.body.inner, text="외장 마우스를 연결했습니다 (트랙패드·터치는 쓰지 않습니다)",
                       variable=self.mouse_var, font=BODY_FONT, bg=BG,
                       command=c.invalidate_preflight).pack(anchor="w", padx=24, pady=8)
        if self.preflight_running:
            self.label("점검 중… Chromium 창이 잠깐 떴다가 닫힙니다.", BODY_FONT, MUTED)
        elif c.checks:
            self.checks_view(c.checks)
            if not c.preflight_ok:
                self.label("통과하지 못한 항목을 고친 뒤 [다시 점검]을 누르세요.", BODY_FONT, BAD_FG)
        btns = self.buttons([("다시 점검" if c.checks else "점검하기", self.run_preflight, "primary"),
                             ("시작", c.start, "ok"),
                             ("처음으로", c.back_to_setup, "plain")])
        if self.preflight_running:
            btns[0].configure(state="disabled")
        if not c.preflight_ok or self.preflight_running:
            btns[1].configure(state="disabled")

    def run_preflight(self) -> None:
        self.preflight_running = True
        self.rendered = (-1, None, None)
        mouse = self.mouse_var.get()

        def work() -> None:
            try:
                self.ctrl.run_preflight(mouse)
            finally:
                self.preflight_running = False
                self.rendered = (-1, None, None)

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ 진행자: C-1 · C-2 · 건네기

    def render_c1(self) -> None:
        p = self.ctrl.plan
        self.title("1. 참가 조건 확인 (과업 설명보다 먼저)")
        self.say(p.text("c1", "say"))
        self.label(p.text("c1", "guide"), BODY_FONT, MUTED)
        self.label(f"“{p.text('c1', 'reject_say')}”", BODY_FONT, MUTED, inset=True)
        self.buttons([("통과 (써 본 적 없음)", self.ctrl.c1_pass, "ok"),
                      ("중단 (써 본 적 있음)", self.confirm_abort, "bad")])

    def confirm_abort(self) -> None:
        if messagebox.askyesno("중단", "중단하면 데이터 없이 끝나고 참가자 코드도 쓰지 않습니다. 중단할까요?", parent=self.root):
            self.ctrl.abort()

    def render_aborted(self) -> None:
        c = self.ctrl
        self.title("중단했습니다")
        if c.aborted_at == Step.C1:
            self.say(c.plan.text("c1", "reject_say"))
        self.label(f"데이터를 저장하지 않았습니다. 참가자 코드 {c.code}는 쓰지 않았습니다.", BODY_FONT)
        self.buttons([("처음으로", c.back_to_setup, "primary")])

    def render_c2(self) -> None:
        c, p = self.ctrl, self.ctrl.plan
        self.title("2. 동의서와 참가자 코드")
        self.label(f"참가자 코드: {c.code}  (동의서에 적습니다)", TITLE_FONT, "#1a5fb4")
        guide = p.text("c2", "guide")
        self.label(f"• {guide[0]}", BODY_FONT, MUTED)
        self.say(p.text("c2", "say"))
        for g in guide[1:]:
            self.label(f"• {g}", BODY_FONT, MUTED)
        self.buttons([("서명 받음", c.c2_signed, "ok"), ("중단 (서명하지 않음)", self.confirm_abort, "bad")])

    def render_resume(self) -> None:
        c = self.ctrl
        assert c.info is not None
        self.title(f"이어 하기 — {c.code}")
        self.label("조건 확인·동의서는 이미 했습니다. 같은 페이지는 다시 하지 않고 남은 차례만 진행합니다.")
        for p in c.plan.pages:
            if p.page_id in c.info.saved:
                state, color = "저장됨", OK_FG
            elif p.page_id in c.info.interrupted:
                state, color = "진행 중 프로그램이 끝나 저장되지 않음 (다시 하지 않음)", BAD_FG
            elif p.page_id in c.info.noted:
                state, color = "오류로 건너뜀 (다시 하지 않음)", BAD_FG
            else:
                state, color = "남음", "#000"
            self.label(f"{p.label}: {state}", BODY_FONT, color, pady=1)
        nxt = "노트북 건네기" if c.remaining_pages() else "확인표로"
        self.buttons([(f"이어 하기 — {nxt}", c.resume_continue, "primary")])

    def render_handover(self) -> None:
        c, p = self.ctrl, self.ctrl.plan
        self.title("노트북을 참가자에게 건네주세요")
        self.say(p.text("handover", "say"), "건네며 말해 주세요")
        self.label(p.text("handover", "guide"), BODY_FONT, MUTED)
        self.label(f"“{p.text('handover', 'answer_say')}”", BODY_FONT, MUTED, inset=True)
        self.label("어느 페이지에 결함이 있는지 말하지 않습니다. 창을 대신 닫거나 버튼을 대신 누르지 않습니다.",
                   BODY_FONT, MUTED)
        self.buttons([("건넸어요", c.handed_over, "primary")])

    # ------------------------------------------------------------ 오류 (참가자 → 진행자)

    def render_p_error(self) -> None:
        c = self.ctrl
        self.label("문제가 생겼습니다. 진행자를 불러 주세요.", SAY_FONT, BAD_FG, pady=(20, 10))
        self.label(f"[진행자] {c.current_page.label}", BODY_FONT, MUTED)
        self.label(c.error or "", SMALL_FONT)
        specs: list[tuple[str, Callable[[], Any], str]] = []
        if c.retry_allowed:
            self.label("페이지가 뜨기 전에 멈춰 참가자는 페이지를 보지 않았습니다. 다시 띄울 수 있습니다.", BODY_FONT, MUTED)
            specs.append(("다시 띄우기", c.retry_page, "primary"))
        else:
            self.label("참가자가 이미 페이지를 봤으므로 같은 페이지를 다시 하지 않습니다.", BODY_FONT, MUTED)
        specs.append(("이 페이지 건너뛰기 (기술 문제로 메모)", c.skip_page, "plain"))
        self.buttons(specs)

    # ------------------------------------------------------------ 진행자: 확인표

    def render_review(self) -> None:
        c = self.ctrl
        codes = notes_mod.ISSUE_CODES[c.version_name]
        self.title(f"페이지별 확인 — {c.code}")
        self.label("완료 여부를 확정하고(기본값은 참가자 답, 3분 종료·창 닫힘은 미완료 고정), 진행에 이상이 있었으면 체크합니다. "
                   "참가자는 이 화면을 보지 않습니다.", BODY_FONT, MUTED)
        rows = c.review_rows()
        if not self.review_vars or set(self.review_vars) != {r.page.page_id for r in rows}:
            self.review_vars = {}
            for r in rows:
                state = {True: "완료", False: "미완료", None: ""}[r.confirmed]
                self.review_vars[r.page.page_id] = (tk.StringVar(value=state),
                                                    {k: tk.BooleanVar(value=k in r.issue_codes) for k in codes},
                                                    tk.StringVar(value=r.note))
        for r in rows:
            done_var, issue_vars, note_var = self.review_vars[r.page.page_id]
            box = tk.Frame(self.body.inner, bg="#f6f6f6", highlightbackground="#ddd", highlightthickness=1)
            box.pack(fill="x", padx=24, pady=6)
            tk.Label(box, text=r.page.label, font=(FAMILY, 16, "bold"), bg="#f6f6f6", anchor="w").pack(fill="x", padx=10)
            tk.Label(box, text=f"참가자: {r.reported_text}    끝난 시점: {r.page.done_when}", font=SMALL_FONT,
                     bg="#f6f6f6", fg=MUTED, anchor="w", justify="left", wraplength=self.width() - 60).pack(fill="x", padx=10)
            line = tk.Frame(box, bg="#f6f6f6")
            line.pack(fill="x", padx=10, pady=2)
            tk.Label(line, text="완료 확정:", font=BODY_FONT, bg="#f6f6f6").pack(side="left")
            for val in ("완료", "미완료"):
                rb = tk.Radiobutton(line, text=val, value=val, variable=done_var, font=BODY_FONT, bg="#f6f6f6")
                rb.pack(side="left", padx=4)
                if r.locked:
                    rb.configure(state="disabled")
            if r.locked:
                why = "저장 파일 없음" if r.path is None else ("검증 실패 파일" if r.invalid else "고정")
                tk.Label(line, text=f"({why})", font=SMALL_FONT, fg=MUTED, bg="#f6f6f6").pack(side="left", padx=6)
            checks = tk.Frame(box, bg="#f6f6f6")
            checks.pack(fill="x", padx=10)
            for k, text in codes.items():
                tk.Checkbutton(checks, text=f"{k} {text}", variable=issue_vars[k], font=SMALL_FONT,
                               bg="#f6f6f6").pack(side="left")
            nrow = tk.Frame(box, bg="#f6f6f6")
            nrow.pack(fill="x", padx=10, pady=(2, 8))
            tk.Label(nrow, text="한 줄 메모", font=SMALL_FONT, bg="#f6f6f6").pack(side="left")
            tk.Entry(nrow, textvariable=note_var, font=SMALL_FONT, width=60).pack(side="left", padx=6)
            tk.Label(nrow, text="이름·연락처는 적지 않기", font=SMALL_FONT, fg=BAD_FG, bg="#f6f6f6").pack(side="left")
            if r.page.page_id in self.review_errors:
                tk.Label(box, text=self.review_errors[r.page.page_id], font=SMALL_FONT, fg=BAD_FG, bg="#f6f6f6",
                         anchor="w").pack(fill="x", padx=10)
        self.buttons([("확인 저장 — 마지막 안내로", self.submit_review, "primary")])

    def review_entries(self) -> dict[str, tuple[bool | None, list[int], str]]:
        out = {}
        for pid, (done_var, issue_vars, note_var) in self.review_vars.items():
            v = done_var.get()
            out[pid] = ({"완료": True, "미완료": False}.get(v), [k for k, b in issue_vars.items() if b.get()],
                        note_var.get())
        return out

    def submit_review(self) -> None:
        errors = self.ctrl.submit_review(self.review_entries())
        self.review_errors = errors
        if errors:
            self.rendered = (-1, None, None)
        else:
            self.review_vars = {}

    # ------------------------------------------------------------ 진행자: C-5 · 검사

    def render_c5(self) -> None:
        c = self.ctrl
        self.title("마지막 안내")
        self.say(c.plan.c5_say(c.code or ""))
        tk.Label(self.body.inner, text=c.code or "", font=(FAMILY, 96, "bold"), fg="#1a5fb4", bg=BG).pack(pady=8)
        self.label(c.plan.text("c5", "guide"), BODY_FONT, MUTED)
        self.label("참가자가 간 뒤 아래 버튼으로 바로 검사합니다.", BODY_FONT, MUTED)
        self.buttons([("검사하고 zip 만들기", c.finish_session, "primary")])

    def render_done(self) -> None:
        c = self.ctrl
        rep = c.report
        assert rep is not None
        self.title(f"세션 직후 검사 — {c.code}")
        self.label("정상" if rep.ok else "오류가 있습니다. 파일을 지우지 말고 수집 스크립트 담당(리포트 UI)에게 출력 전체를 보냅니다.",
                   TITLE_FONT, OK_FG if rep.ok else BAD_FG)
        txt = tk.Text(self.body.inner, font=MONO_FONT, height=14, wrap="word")
        txt.insert("1.0", rep.text)
        txt.configure(state="disabled")
        txt.pack(fill="x", padx=24, pady=6)
        self.label(f"검사 결과: {rep.check_path}", SMALL_FONT, MUTED)
        self.label(f"올릴 파일: {rep.zip_path}  ({len(rep.zipped)}개 파일)", BODY_FONT)
        self.label("팀원 전용 Notion 페이지에 올리세요(저장소·카톡 금지).", TITLE_FONT, BAD_FG)
        self.buttons([("폴더 열기", lambda: open_folder(rep.zip_path.parent), "primary"),
                      ("새 참가자", c.back_to_setup, "plain"), ("끝내기", self.on_close, "plain")])
        if self.opened_for is not rep and self.auto is None:
            self.opened_for = rep
            open_folder(rep.zip_path.parent)

    # ------------------------------------------------------------ 이미 끝난 세션 메모 (읽어 주던 방식)

    def open_before_app(self) -> None:
        self.screen_mode = "before_app"
        self.ba_folder = tk.StringVar(value=str(self.ctrl.d.data_dir))
        self.ba_code = tk.StringVar()
        self.ba_rows: list[dict[str, Any]] | None = None
        self.ba_vars: dict[str, tuple[dict[int, tk.BooleanVar], tk.StringVar]] = {}

    def render_before_app(self) -> None:
        self.facilitator_banner()
        codes = notes_mod.ISSUE_CODES[notes_mod.READ_ALOUD]
        self.title("이미 끝난 세션 메모 입력")
        self.label("진행 프로그램 전에(진행자가 읽어 주는 방식으로) 진행한 세션에, 기억나는 진행 이상을 페이지별로 남깁니다. "
                   "세션 파일은 읽기만 하고 notes-<코드>.json만 만듭니다.", BODY_FONT, MUTED)
        frm = tk.Frame(self.body.inner, bg=BG)
        frm.pack(fill="x", padx=24, pady=6)
        tk.Label(frm, text="세션 파일 폴더", font=BODY_FONT, bg=BG).grid(row=0, column=0, sticky="w")
        tk.Entry(frm, textvariable=self.ba_folder, font=SMALL_FONT, width=60).grid(row=0, column=1, sticky="w", padx=8)
        tk.Button(frm, text="찾아보기", font=SMALL_FONT, command=self.pick_folder).grid(row=0, column=2)
        tk.Label(frm, text="진행자", font=BODY_FONT, bg=BG).grid(row=1, column=0, sticky="w", pady=4)
        tk.Label(frm, text=self.selected_github() or "(처음 화면에서 진행자를 고르세요)", font=BODY_FONT,
                 bg=BG).grid(row=1, column=1, sticky="w", padx=8)
        tk.Label(frm, text="참가자 코드", font=BODY_FONT, bg=BG).grid(row=2, column=0, sticky="w")
        tk.Entry(frm, textvariable=self.ba_code, font=BODY_FONT, width=8).grid(row=2, column=1, sticky="w", padx=8)
        self.show_message()
        self.buttons([("불러오기", self.load_before_app, "primary"), ("돌아가기", self.close_before_app, "plain")])
        if not self.ba_rows:
            return
        for row in self.ba_rows:
            p = row["page"]
            state = ("완료" if row["completed"] else "미완료") if row["saved"] else "세션 파일 없음"
            self.label(f"{p.label} — {state}", BODY_FONT, pady=(10, 0))
            vars_, note = self.ba_vars[p.page_id]
            line = tk.Frame(self.body.inner, bg=BG)
            line.pack(fill="x", padx=40)
            for code, text in codes.items():
                tk.Checkbutton(line, text=f"{code} {text}", variable=vars_[code], font=SMALL_FONT, bg=BG).pack(
                    side="left")
            nrow = tk.Frame(self.body.inner, bg=BG)
            nrow.pack(fill="x", padx=40)
            tk.Entry(nrow, textvariable=note, font=SMALL_FONT, width=70).pack(side="left")
            tk.Label(nrow, text="이름·연락처는 적지 않기", font=SMALL_FONT, fg=BAD_FG, bg=BG).pack(side="left", padx=6)
        self.buttons([("notes 저장", self.save_before_app, "ok")])

    def pick_folder(self) -> None:
        d = filedialog.askdirectory(initialdir=self.ba_folder.get(), parent=self.root)
        if d:
            self.ba_folder.set(d)

    def load_before_app(self) -> None:
        codes = notes_mod.ISSUE_CODES[notes_mod.READ_ALOUD]
        rows, err = self.ctrl.before_app_pages(Path(self.ba_folder.get()), self.ba_code.get().strip().upper())
        if err:
            self.message = (err, BAD_FG)
            if rows and "세션 파일이 없습니다" in err:
                rows = []
        self.ba_rows = rows
        self.ba_vars = {r["page"].page_id: ({k: tk.BooleanVar(value=k in r["issue_codes"]) for k in codes},
                                            tk.StringVar(value=r["note"])) for r in rows}
        self.rendered = (-1, None, None)

    def save_before_app(self) -> None:
        entries = {pid: ([k for k, v in vars_.items() if v.get()], note.get())
                   for pid, (vars_, note) in self.ba_vars.items()}
        try:
            path = self.ctrl.save_before_app_notes(Path(self.ba_folder.get()), self.ba_code.get().strip().upper(),
                                                   self.selected_github(), entries)
        except ValueError as e:
            self.message = (str(e), BAD_FG)
        else:
            self.message = (f"저장했습니다: {path}", OK_FG)
        self.rendered = (-1, None, None)

    def close_before_app(self) -> None:
        self.screen_mode = "flow"


def main(argv: list[str] | None = None) -> int:
    import argparse

    from .resources import detect
    from .runtime import build, prepare_process

    parser = argparse.ArgumentParser(description="StepMeter 사람 실험 진행 프로그램")
    parser.add_argument("--auto", action="store_true", help="개발자 확인용: 연습 모드(P00)로 버튼을 자동으로 누른다")
    parser.add_argument("--auto-limit", type=float, default=None, help="--auto에서 3분 대신 쓸 초")
    parser.add_argument("--auto-timeout-page", type=int, default=3, help="--auto에서 3분 자동 종료를 볼 차례(1~6)")
    parser.add_argument("--auto-done", type=Path, default=None, help="--auto가 끝나면 결과를 쓸 파일")
    args = parser.parse_args(argv)

    res = detect()
    prepare_process(res)
    if sys.platform == "win32":
        try:
            import ctypes
            getattr(ctypes, "windll").shcore.SetProcessDpiAwareness(1)
        except (OSError, AttributeError):
            pass
    ctrl, sites, server_error = build(res)
    root = tk.Tk()
    auto = None
    if args.auto:
        from .autodrive import AutoDriver
        if args.auto_limit:
            ctrl.limit_s = args.auto_limit
        auto = AutoDriver(timeout_page=args.auto_timeout_page, done_path=args.auto_done)
    App(root, ctrl, sites, server_error, auto=auto)
    try:
        root.mainloop()
    finally:
        if sites is not None:
            sites.stop()
    return 0
