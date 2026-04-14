import ctypes
import json
import os
import sys
import threading
import time
import tkinter as tk

try:
    import pydirectinput
    import pyautogui
    from pynput import keyboard as pynput_kb
except ImportError:
    print("Run:  pip install pydirectinput pynput pyautogui")
    sys.exit(1)

# ── DPI awareness ─────────────────────────────────────────────────────────────

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

pydirectinput.PAUSE = 0
pyautogui.FAILSAFE = True

# ── Win32 pixel reading ───────────────────────────────────────────────────────

_gdi = ctypes.windll.gdi32
_usr = ctypes.windll.user32


def get_pixel(x, y):
    """Read one pixel from screen via GetPixel. No screenshot needed."""
    hdc = _usr.GetDC(0)
    c = _gdi.GetPixel(hdc, x, y)
    _usr.ReleaseDC(0, hdc)
    if c < 0:
        return None
    return (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF)


# ── Theme ─────────────────────────────────────────────────────────────────────

BG       = "#111111"
BG_CARD  = "#1a1a1a"
BG_CARD2 = "#1f1f1f"
BG_INPUT = "#0d0d0d"
BG_HOVER = "#2a2a2a"
FG       = "#999999"
FG_BRIGHT = "#e0e0e0"
FG_DIM   = "#555555"
ACCENT   = "#ffffff"
GREEN    = "#4caf50"
GREEN_DIM = "#2e7d32"
RED      = "#e53935"

FONT    = ("Segoe UI", 10)
FONT_SM = ("Segoe UI", 9)
FONT_B  = ("Segoe UI", 10, "bold")
FONT_LG = ("Segoe UI", 13, "bold")
FONT_XS = ("Segoe UI", 8)

TARGET_COLOR = (0x1A, 0xCE, 0x6A)  # #1ACE6A


# ── Toggle Widget ─────────────────────────────────────────────────────────────

class Toggle(tk.Canvas):
    def __init__(self, parent, variable=None, command=None, **kw):
        super().__init__(parent, width=40, height=20, highlightthickness=0,
                         cursor="hand2", **kw)
        self.configure(bg=self.master.cget("bg"))
        self.var = variable or tk.BooleanVar(value=False)
        self.cmd = command
        self.bind("<Button-1>", self._click)
        self.var.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _draw(self):
        self.delete("all")
        on = self.var.get()
        tc = GREEN if on else "#333333"
        self.create_oval(0, 0, 20, 20, fill=tc, outline=tc)
        self.create_oval(20, 0, 40, 20, fill=tc, outline=tc)
        self.create_rectangle(10, 0, 30, 20, fill=tc, outline=tc)
        kx = 30 if on else 10
        self.create_oval(kx - 8, 2, kx + 8, 18,
                         fill="#e0e0e0" if on else "#666666", outline="")

    def _click(self, _=None):
        self.var.set(not self.var.get())
        if self.cmd:
            self.cmd()


# ── App ───────────────────────────────────────────────────────────────────────

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Color Clicker")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)

        self.running = False
        self.holding = False

        # Mode
        self.mode_var = tk.StringVar(value="autoclicker")

        # Coordinates (None = not set)
        self.detect1 = None
        self.detect2 = None
        self.home = None

        # Display vars
        self.d1_label = tk.StringVar(value="not set")
        self.d2_label = tk.StringVar(value="not set")
        self.home_label = tk.StringVar(value="not set")

        # Settings
        self.click_interval = tk.IntVar(value=250)     # ms
        self.rehold_sec = tk.DoubleVar(value=10.0)     # seconds
        self.hotkey_var = tk.StringVar(value="F5")
        self.color_on = tk.BooleanVar(value=True)

        self.cfg_path = os.path.join(
            os.path.dirname(os.path.abspath(sys.argv[0])),
            "color_clicker.json")

        self._build()
        self._setup_hotkey()
        self._load_cfg()

    # ── Build UI ──────────────────────────────────────────────────────────

    def _build(self):
        # Header
        hdr = tk.Frame(self.root, bg=BG)
        hdr.pack(fill="x", padx=20, pady=(16, 0))
        tk.Label(hdr, text="COLOR CLICKER", font=FONT_LG, bg=BG,
                 fg=ACCENT).pack(side="left")

        tk.Frame(self.root, bg="#333", height=1).pack(fill="x", padx=20, pady=(10, 8))

        # ── Mode selector ──
        mode_frame = tk.Frame(self.root, bg=BG)
        mode_frame.pack(fill="x", padx=20, pady=(0, 6))

        self.ac_btn = tk.Button(mode_frame, text="AUTO CLICKER", font=FONT_B,
                                relief="flat", bd=0, padx=16, pady=8,
                                cursor="hand2",
                                command=lambda: self._set_mode("autoclicker"))
        self.ac_btn.pack(side="left", expand=True, fill="x", padx=(0, 2))

        self.hc_btn = tk.Button(mode_frame, text="HOLD CLICK", font=FONT_B,
                                relief="flat", bd=0, padx=16, pady=8,
                                cursor="hand2",
                                command=lambda: self._set_mode("holdclick"))
        self.hc_btn.pack(side="left", expand=True, fill="x", padx=(2, 0))
        self._update_mode_btns()

        tk.Frame(self.root, bg="#333", height=1).pack(fill="x", padx=20, pady=(2, 8))

        # ── Coordinates ──
        coords = tk.Frame(self.root, bg=BG)
        coords.pack(fill="x", padx=20)

        self._coord_row(coords, "Detect 1", self.d1_label,
                        lambda: self._mark("detect1"), BG_CARD)
        self._coord_row(coords, "Detect 2", self.d2_label,
                        lambda: self._mark("detect2"), BG_CARD2)
        self._coord_row(coords, "Home", self.home_label,
                        lambda: self._mark("home"), BG_CARD)

        # ── Color detection toggle ──
        tk.Frame(self.root, bg="#333", height=1).pack(fill="x", padx=20, pady=(8, 6))

        feat = tk.Frame(self.root, bg=BG_CARD)
        feat.pack(fill="x", padx=20, pady=(0, 2))
        txt_f = tk.Frame(feat, bg=BG_CARD)
        txt_f.pack(side="left", fill="x", expand=True, padx=(14, 0), pady=10)
        tk.Label(txt_f, text="Color Detection", font=FONT_B, bg=BG_CARD,
                 fg=FG_BRIGHT, anchor="w").pack(anchor="w")
        tk.Label(txt_f, text="Pause & click #1ACE6A when it appears",
                 font=FONT_XS, bg=BG_CARD, fg=FG_DIM, anchor="w").pack(anchor="w")
        Toggle(feat, variable=self.color_on).pack(side="right", padx=14, pady=10)

        # ── Hotkey + Settings ──
        tk.Frame(self.root, bg="#333", height=1).pack(fill="x", padx=20, pady=(6, 6))

        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=20, pady=(0, 6))

        tk.Button(bar, text="⚙  Settings", font=FONT_SM, bg=BG_CARD, fg=FG,
                  relief="flat", bd=0, padx=10, pady=4, cursor="hand2",
                  activebackground=BG_HOVER, activeforeground=FG_BRIGHT,
                  command=self._settings_popup).pack(side="left")

        om = tk.OptionMenu(bar, self.hotkey_var, "F5", "F6", "F7", "F8", "F9")
        om.configure(bg=BG_INPUT, fg=FG_BRIGHT, font=FONT_SM,
                     activebackground=BG_HOVER, activeforeground=FG_BRIGHT,
                     highlightthickness=0, relief="flat", bd=2, width=3)
        om["menu"].configure(bg=BG_INPUT, fg=FG_BRIGHT, font=FONT_SM,
                             activebackground="#444", activeforeground="#fff")
        om.pack(side="right")
        tk.Label(bar, text="HOTKEY", font=FONT_XS, bg=BG, fg=FG_DIM
                 ).pack(side="right", padx=(0, 6))

        # ── Start / Stop ──
        ab = tk.Frame(self.root, bg=BG)
        ab.pack(fill="x", padx=20, pady=(0, 4))

        self.start_btn = tk.Button(ab, text="▶  START", font=FONT_B,
                                   bg=GREEN_DIM, fg="#fff", relief="flat", bd=0,
                                   pady=9, cursor="hand2",
                                   activebackground=GREEN, command=self._start)
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 3))

        self.stop_btn = tk.Button(ab, text="⏹  STOP", font=FONT_B,
                                  bg="#333", fg="#666", relief="flat", bd=0,
                                  pady=9, cursor="hand2", state="disabled",
                                  activebackground=RED, command=self._stop)
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=(3, 0))

        # ── Save / Load ──
        cf = tk.Frame(self.root, bg=BG)
        cf.pack(fill="x", padx=20, pady=(0, 6))
        sb = dict(font=FONT_XS, bg="#1a1a1a", fg=FG_DIM, relief="flat", bd=0,
                  padx=8, pady=3, cursor="hand2", activebackground="#333")
        tk.Button(cf, text="SAVE", command=self._save_cfg, **sb).pack(side="left", padx=(0, 4))
        tk.Button(cf, text="LOAD", command=self._load_cfg, **sb).pack(side="left")

        # ── Status ──
        self.status_var = tk.StringVar(value="Ready  ·  F5")
        tk.Label(self.root, textvariable=self.status_var, font=FONT_XS,
                 bg=BG, fg=FG_DIM, anchor="w").pack(fill="x", padx=20, pady=(0, 2))

        # ── Log ──
        self.log = tk.Text(self.root, height=5, wrap="word", bg=BG_INPUT,
                           fg=FG_DIM, font=("Consolas", 8), relief="flat", bd=0,
                           state="disabled", insertbackground=FG)
        self.log.pack(fill="both", expand=True, padx=20, pady=(0, 14))

    def _coord_row(self, parent, name, label_var, mark_cmd, bg):
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", pady=(0, 2))

        tk.Label(row, text=name, font=FONT_B, bg=bg, fg=FG_BRIGHT, width=8,
                 anchor="w").pack(side="left", padx=(14, 8), pady=8)
        tk.Label(row, textvariable=label_var, font=("Consolas", 9), bg=bg,
                 fg=FG, anchor="w").pack(side="left", fill="x", expand=True, pady=8)
        tk.Button(row, text="🎯", font=("Segoe UI", 11), bg=bg, fg=FG,
                  relief="flat", bd=0, cursor="hand2",
                  activebackground=BG_HOVER, command=mark_cmd
                  ).pack(side="right", padx=(0, 14), pady=4)

    # ── Mode ──────────────────────────────────────────────────────────────

    def _set_mode(self, mode):
        self.mode_var.set(mode)
        self._update_mode_btns()

    def _update_mode_btns(self):
        if self.mode_var.get() == "autoclicker":
            self.ac_btn.configure(bg="#333", fg=ACCENT)
            self.hc_btn.configure(bg=BG_CARD, fg=FG_DIM)
        else:
            self.ac_btn.configure(bg=BG_CARD, fg=FG_DIM)
            self.hc_btn.configure(bg="#333", fg=ACCENT)

    # ── Settings Popup ────────────────────────────────────────────────────

    def _settings_popup(self):
        p = tk.Toplevel(self.root)
        p.title("Settings")
        p.configure(bg=BG_CARD)
        p.resizable(False, False)
        p.transient(self.root)
        p.grab_set()

        w, h = 380, 200
        p.update_idletasks()
        px = self.root.winfo_rootx() + (self.root.winfo_width() - w) // 2
        py = self.root.winfo_rooty() + (self.root.winfo_height() - h) // 2
        p.geometry(f"{w}x{h}+{px}+{py}")

        body = tk.Frame(p, bg=BG_CARD)
        body.pack(fill="both", expand=True, padx=20, pady=16)

        es = dict(font=FONT_SM, bg=BG_INPUT, fg=FG_BRIGHT, relief="flat",
                  bd=5, insertbackground=FG_BRIGHT, width=10)

        def row(label, var, r):
            tk.Label(body, text=label, font=FONT, bg=BG_CARD, fg=FG,
                     anchor="w").grid(row=r, column=0, sticky="w", pady=7, padx=(0, 16))
            tk.Entry(body, textvariable=var, **es).grid(row=r, column=1, sticky="w", pady=7)

        row("Click Interval (ms)", self.click_interval, 0)
        row("Re-hold Every (sec)", self.rehold_sec, 1)

        tk.Button(body, text="Done", font=FONT_B, bg="#333", fg=FG_BRIGHT,
                  relief="flat", bd=0, padx=20, pady=5, cursor="hand2",
                  activebackground="#444", command=p.destroy
                  ).grid(row=2, column=0, columnspan=2, pady=(14, 0))

    # ── Mark Coordinates ──────────────────────────────────────────────────

    def _mark(self, which):
        self._log(f"Mark {which}: hover cursor in 3s…")
        self.root.iconify()

        def go():
            for i in range(3, 0, -1):
                self.root.after(0, lambda s=i: self.status_var.set(f"Marking {s}…"))
                time.sleep(1)

            x, y = pyautogui.position()

            if which == "detect1":
                self.detect1 = (x, y)
                self.root.after(0, lambda: self.d1_label.set(f"({x}, {y})"))
            elif which == "detect2":
                self.detect2 = (x, y)
                self.root.after(0, lambda: self.d2_label.set(f"({x}, {y})"))
            elif which == "home":
                self.home = (x, y)
                self.root.after(0, lambda: self.home_label.set(f"({x}, {y})"))

            self.root.after(0, lambda: (
                self.root.deiconify(),
                self.status_var.set(f"Ready  ·  {self.hotkey_var.get()}"),
                self._log(f"Marked {which} → ({x}, {y})")
            ))

        threading.Thread(target=go, daemon=True).start()

    # ── Color Detection ───────────────────────────────────────────────────

    def _check_color(self):
        """Check detect1 and detect2 for the target color.
        Returns the (x, y) where found, or None."""
        for coord in (self.detect1, self.detect2):
            if coord is None:
                continue
            px = get_pixel(coord[0], coord[1])
            if px == TARGET_COLOR:
                return coord
        return None

    def _handle_color(self, cx, cy):
        """Click the color at (cx, cy), retry until confirmed gone."""
        # Release hold if active
        if self.holding:
            pydirectinput.mouseUp(button="left")
            self.holding = False

        self.root.after(0, lambda: self._log(f"Color found at ({cx},{cy}) — clicking"))

        for attempt in range(10):
            if not self.running:
                return

            pydirectinput.moveTo(cx, cy)
            time.sleep(0.03)
            pydirectinput.click()

            # Poll until color is gone (up to 0.5s per attempt)
            gone = False
            deadline = time.time() + 0.5
            while time.time() < deadline:
                px = get_pixel(cx, cy)
                if px != TARGET_COLOR:
                    gone = True
                    break
                time.sleep(0.015)

            if gone:
                self.root.after(0, lambda a=attempt + 1:
                                self._log(f"Color gone (attempt {a}) — resuming"))
                break
        else:
            self.root.after(0, lambda: self._log("Color persists after 10 tries"))

        # Return to home coordinate
        if self.home:
            time.sleep(0.02)
            pydirectinput.moveTo(self.home[0], self.home[1])
            time.sleep(0.02)

    # ── Start / Stop ──────────────────────────────────────────────────────

    def _start(self):
        if self.running:
            return
        if not self.home:
            self._log("Set a home coordinate first")
            return

        self.running = True
        self.holding = False
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal", bg="#442222", fg=FG_BRIGHT)
        self.status_var.set("Running…")
        self._log(f"Started — {self.mode_var.get()}")

        self.root.iconify()
        self.root.update()

        threading.Thread(target=self._main_loop, daemon=True).start()

    def _stop(self):
        self.running = False
        if self.holding:
            pydirectinput.mouseUp(button="left")
            self.holding = False
        self._log("Stopped")

    def _finish(self):
        self.running = False
        if self.holding:
            pydirectinput.mouseUp(button="left")
            self.holding = False

        def do():
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled", bg="#333", fg="#666")
            self.status_var.set(f"Done  ·  {self.hotkey_var.get()}")
            self.root.deiconify()
        self.root.after(0, do)

    # ── Main Loop ─────────────────────────────────────────────────────────

    def _main_loop(self):
        time.sleep(0.3)
        mode = self.mode_var.get()
        interval = self.click_interval.get() / 1000.0
        rehold = self.rehold_sec.get()
        color_on = self.color_on.get()

        hold_start = 0.0

        # Focus the game window with a regular Windows click,
        # then all subsequent pydirectinput calls will register.
        if self.home:
            pyautogui.click(self.home[0], self.home[1])
            time.sleep(0.1)

        # Initial hold if in hold mode
        if mode == "holdclick":
            pydirectinput.mouseDown(button="left")
            self.holding = True
            hold_start = time.time()
            self.root.after(0, lambda: self._log("Holding"))

        while self.running:
            # ── Color check ──
            if color_on:
                found = self._check_color()
                if found:
                    self._handle_color(found[0], found[1])
                    if not self.running:
                        break
                    # Re-establish hold after color interrupt
                    if mode == "holdclick":
                        pydirectinput.mouseDown(button="left")
                        self.holding = True
                        hold_start = time.time()
                    continue

            # ── Auto Clicker tick ──
            if mode == "autoclicker":
                pydirectinput.moveTo(self.home[0], self.home[1])
                pydirectinput.click()
                time.sleep(interval)

            # ── Hold Click tick ──
            elif mode == "holdclick":
                now = time.time()
                if not self.holding:
                    pydirectinput.moveTo(self.home[0], self.home[1])
                    pydirectinput.mouseDown(button="left")
                    self.holding = True
                    hold_start = now
                    self.root.after(0, lambda: self._log("Re-holding"))
                elif now - hold_start >= rehold:
                    pydirectinput.mouseUp(button="left")
                    self.holding = False
                    time.sleep(0.05)
                else:
                    time.sleep(0.05)

        self._finish()

    # ── Hotkey ─────────────────────────────────────────────────────────────

    def _setup_hotkey(self):
        def on_press(key):
            hk = self.hotkey_var.get()
            try:
                if hasattr(key, "name") and key.name and key.name.upper() == hk.upper():
                    self.root.after(0, self._stop if self.running else self._start)
            except AttributeError:
                pass

        listener = pynput_kb.Listener(on_press=on_press)
        listener.daemon = True
        listener.start()

    # ── Log ────────────────────────────────────────────────────────────────

    def _log(self, m):
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {m}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ── Config ─────────────────────────────────────────────────────────────

    def _save_cfg(self):
        d = {
            "mode": self.mode_var.get(),
            "color_on": self.color_on.get(),
            "detect1": list(self.detect1) if self.detect1 else None,
            "detect2": list(self.detect2) if self.detect2 else None,
            "home": list(self.home) if self.home else None,
            "click_interval": self.click_interval.get(),
            "rehold_sec": self.rehold_sec.get(),
            "hotkey": self.hotkey_var.get(),
        }
        try:
            with open(self.cfg_path, "w") as f:
                json.dump(d, f, indent=2)
            self._log("Config saved")
        except Exception as e:
            self._log(f"Save error: {e}")

    def _load_cfg(self):
        if not os.path.isfile(self.cfg_path):
            return
        try:
            with open(self.cfg_path) as f:
                d = json.load(f)
        except Exception:
            return

        self.mode_var.set(d.get("mode", "autoclicker"))
        self._update_mode_btns()
        self.color_on.set(d.get("color_on", True))
        self.click_interval.set(d.get("click_interval", 250))
        self.rehold_sec.set(d.get("rehold_sec", 10.0))
        self.hotkey_var.set(d.get("hotkey", "F5"))

        if d.get("detect1"):
            self.detect1 = tuple(d["detect1"])
            self.d1_label.set(f"({self.detect1[0]}, {self.detect1[1]})")
        if d.get("detect2"):
            self.detect2 = tuple(d["detect2"])
            self.d2_label.set(f"({self.detect2[0]}, {self.detect2[1]})")
        if d.get("home"):
            self.home = tuple(d["home"])
            self.home_label.set(f"({self.home[0]}, {self.home[1]})")

        self._log("Config loaded")

    # ── Close ──────────────────────────────────────────────────────────────

    def _on_close(self):
        self._save_cfg()
        self.root.destroy()


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app._on_close)
    root.mainloop()
