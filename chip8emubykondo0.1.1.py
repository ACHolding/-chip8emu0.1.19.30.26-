#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
chip8kondo.py - CHIP-8 Kondo
A.C Holdings / Team Flames

Single-file CHIP-8 emulator with an mGBA-inspired dark GUI.
  * Tkinter only (stdlib), fixed 600x400 window, 60 FPS fixed-step timing
  * CPU, 4 KB RAM, V0-VF, I, 16-level stack, delay/sound timers, 16-key pad
  * 64x32 framebuffer rendered through a zoomed PhotoImage (fast path)
  * Generated square-wave buzzer (winsound in-memory on Windows,
    aplay/pacat stdin stream on Linux, Tk bell fallback elsewhere)
  * Built-in demo ROM, so no external assets are needed

FILES_OFF = True  -> the emulator never writes anything to disk
                     (no temp WAVs, no configs, no screenshots).
                     Loading a ROM you pick is still allowed.

Keypad:            CHIP-8:
  1 2 3 4            1 2 3 C
  Q W E R            4 5 6 D
  A S D F            7 8 9 E
  Z X C V            A 0 B F

Hotkeys: Ctrl+O open | Ctrl+P pause | Ctrl+R reset | Ctrl+N step frame
         Ctrl+M mute | Ctrl+Q quit

Usage: python chip8kondo.py [rom.ch8]
"""

import io
import os
import sys
import time
import wave
import random
import shutil
import threading
import subprocess
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
FILES_OFF = True

APP_NAME = "CHIP-8 Kondo"
VERSION = "1.0"
WIN_W, WIN_H = 600, 400
SCR_W, SCR_H = 64, 32
SCALE = 9                     # 64x32 -> 576x288
FPS = 60
FRAME = 1.0 / FPS
DEFAULT_IPF = 12              # instructions per frame (~720 Hz)
SPEEDS = (1, 7, 12, 20, 30, 60, 120, 500)

TOOLBAR_H = 30
BOTTOM_H = 54
SCREEN_AREA_H = WIN_H - TOOLBAR_H - BOTTOM_H   # 316

# mGBA-ish dark theme
BG = "#16171d"
PANEL = "#20222b"
BTN = "#2c2f3a"
BTN_HOT = "#3b4051"
FG = "#d7dae3"
DIM = "#8a90a2"
ACC = "#8f6bff"
BORDER = "#343846"
ERR = "#ff5c7a"
OK = "#5cffa8"

PALETTES = {
    "mGBA Slate": ("#e6e8ef", "#101218"),
    "Classic B/W": ("#ffffff", "#000000"),
    "DMG Green": ("#c4f0a2", "#1f3a2c"),
    "Amber CRT": ("#ffb000", "#1a0f00"),
    "Cyan Phosphor": ("#6ff7ff", "#041a20"),
    "Kondo Purple": ("#d9c8ff", "#1a1030"),
}
DEFAULT_PALETTE = "mGBA Slate"

KEYMAP = {
    "1": 0x1, "2": 0x2, "3": 0x3, "4": 0xC,
    "q": 0x4, "w": 0x5, "e": 0x6, "r": 0xD,
    "a": 0x7, "s": 0x8, "d": 0x9, "f": 0xE,
    "z": 0xA, "x": 0x0, "c": 0xB, "v": 0xF,
}

FONT_ADDR = 0x50
FONT = bytes([
    0xF0, 0x90, 0x90, 0x90, 0xF0,  # 0
    0x20, 0x60, 0x20, 0x20, 0x70,  # 1
    0xF0, 0x10, 0xF0, 0x80, 0xF0,  # 2
    0xF0, 0x10, 0xF0, 0x10, 0xF0,  # 3
    0x90, 0x90, 0xF0, 0x10, 0x10,  # 4
    0xF0, 0x80, 0xF0, 0x10, 0xF0,  # 5
    0xF0, 0x80, 0xF0, 0x90, 0xF0,  # 6
    0xF0, 0x10, 0x10, 0x10, 0x10,  # 7
    0xF0, 0x90, 0xF0, 0x90, 0xF0,  # 8
    0xF0, 0x90, 0xF0, 0x10, 0xF0,  # 9
    0xF0, 0x90, 0xF0, 0x90, 0x90,  # A
    0xE0, 0x90, 0xE0, 0x90, 0xE0,  # B
    0xF0, 0x80, 0x80, 0x80, 0xF0,  # C
    0xE0, 0x90, 0x90, 0x90, 0xE0,  # D
    0xF0, 0x80, 0xF0, 0x80, 0xF0,  # E
    0xF0, 0x80, 0xF0, 0x80, 0x80,  # F
])

# Built-in demo: draws "C8" and bounces a pixel, beeping on side walls.
DEMO_ROM = bytes([
    0x6A, 0x08, 0x6B, 0x08, 0x6C, 0x01, 0x6D, 0x01,   # 200 VA,VB=pos VC,VD=dir
    0x60, 0x1A, 0x61, 0x0D, 0xA0, 0x8C, 0xD0, 0x15,   # 208 draw 'C'
    0x60, 0x20, 0xA0, 0x78, 0xD0, 0x15,               # 210 draw '8'
    0xA2, 0x50, 0xDA, 0xB1,                           # 216 draw ball
    0x6E, 0x02, 0xFE, 0x15,                           # 21A loop: DT=2
    0xFE, 0x07, 0x3E, 0x00, 0x12, 0x1E,               # 21E wait DT==0
    0xA2, 0x50, 0xDA, 0xB1,                           # 224 erase ball
    0x8A, 0xC4, 0x8B, 0xD4,                           # 228 move
    0x4A, 0x00, 0x22, 0x40,                           # 22C x==0  -> LEFT
    0x4A, 0x3F, 0x22, 0x48,                           # 230 x==63 -> RIGHT
    0x4B, 0x00, 0x6D, 0x01,                           # 234 y==0  -> dy=+1
    0x4B, 0x1F, 0x6D, 0xFF,                           # 238 y==31 -> dy=-1
    0xDA, 0xB1, 0x12, 0x1A,                           # 23C draw, loop
    0x6C, 0x01, 0x6E, 0x03, 0xFE, 0x18, 0x00, 0xEE,   # 240 LEFT : dx=+1, beep
    0x6C, 0xFF, 0x6E, 0x03, 0xFE, 0x18, 0x00, 0xEE,   # 248 RIGHT: dx=-1, beep
    0x80,                                             # 250 ball sprite
])


# ----------------------------------------------------------------------------
# CHIP-8 core
# ----------------------------------------------------------------------------
class ChipError(Exception):
    pass


class Chip8:
    MAX_ROM = 4096 - 0x200

    def __init__(self):
        self.quirks = {
            "vf_reset": False,   # 8XY1/2/3 clear VF (COSMAC)
            "mem_inc": False,    # FX55/FX65 advance I (COSMAC)
            "shift_vy": False,   # 8XY6/8XYE shift VY (COSMAC)
            "jump_vx": False,    # BXNN uses VX (SCHIP)
            "clip": True,        # sprites clip at edges instead of wrapping
            "disp_wait": False,  # DXYN ends the frame (COSMAC)
        }
        self.rom = b""
        self.reset()

    def reset(self):
        self.mem = bytearray(4096)
        self.mem[FONT_ADDR:FONT_ADDR + len(FONT)] = FONT
        self.mem[0x200:0x200 + len(self.rom)] = self.rom
        self.V = [0] * 16
        self.I = 0
        self.pc = 0x200
        self.stack = []
        self.dt = 0
        self.st = 0
        self.keys = [False] * 16
        self.fb = bytearray(SCR_W * SCR_H)
        self.dirty = True
        self.wait_key = -1
        self.last_op = 0
        self.cycles = 0

    def load(self, data):
        data = bytes(data)
        if not data:
            raise ChipError("ROM is empty")
        if len(data) > self.MAX_ROM:
            raise ChipError(f"ROM too large ({len(data)} bytes, max {self.MAX_ROM})")
        self.rom = data
        self.reset()

    def run_frame(self, ipf):
        step = self.step
        for _ in range(ipf):
            if step():
                break
        if self.dt:
            self.dt -= 1
        if self.st:
            self.st -= 1

    def step(self):
        """Execute one opcode. Returns True if the frame should end (display wait)."""
        m = self.mem
        V = self.V
        pc = self.pc
        op = (m[pc] << 8) | m[(pc + 1) & 0xFFF]
        self.last_op = op
        self.pc = (pc + 2) & 0xFFF
        self.cycles += 1

        hi = op >> 12
        x = (op >> 8) & 0xF
        y = (op >> 4) & 0xF
        n = op & 0xF
        nn = op & 0xFF
        nnn = op & 0xFFF

        if hi == 0x0:
            if op == 0x00E0:
                self.fb[:] = bytes(SCR_W * SCR_H)
                self.dirty = True
            elif op == 0x00EE:
                if not self.stack:
                    raise ChipError(f"Stack underflow at {pc:03X}")
                self.pc = self.stack.pop()
            # 0NNN (SYS) ignored
        elif hi == 0x1:
            self.pc = nnn
        elif hi == 0x2:
            if len(self.stack) >= 16:
                raise ChipError(f"Stack overflow at {pc:03X}")
            self.stack.append(self.pc)
            self.pc = nnn
        elif hi == 0x3:
            if V[x] == nn:
                self.pc = (self.pc + 2) & 0xFFF
        elif hi == 0x4:
            if V[x] != nn:
                self.pc = (self.pc + 2) & 0xFFF
        elif hi == 0x5:
            if V[x] == V[y]:
                self.pc = (self.pc + 2) & 0xFFF
        elif hi == 0x6:
            V[x] = nn
        elif hi == 0x7:
            V[x] = (V[x] + nn) & 0xFF
        elif hi == 0x8:
            q = self.quirks
            if n == 0x0:
                V[x] = V[y]
            elif n == 0x1:
                V[x] |= V[y]
                if q["vf_reset"]:
                    V[15] = 0
            elif n == 0x2:
                V[x] &= V[y]
                if q["vf_reset"]:
                    V[15] = 0
            elif n == 0x3:
                V[x] ^= V[y]
                if q["vf_reset"]:
                    V[15] = 0
            elif n == 0x4:
                s = V[x] + V[y]
                V[x] = s & 0xFF
                V[15] = 1 if s > 0xFF else 0
            elif n == 0x5:
                vx, vy = V[x], V[y]
                V[x] = (vx - vy) & 0xFF
                V[15] = 1 if vx >= vy else 0
            elif n == 0x6:
                src = V[y] if q["shift_vy"] else V[x]
                V[x] = src >> 1
                V[15] = src & 1
            elif n == 0x7:
                vx, vy = V[x], V[y]
                V[x] = (vy - vx) & 0xFF
                V[15] = 1 if vy >= vx else 0
            elif n == 0xE:
                src = V[y] if q["shift_vy"] else V[x]
                V[x] = (src << 1) & 0xFF
                V[15] = (src >> 7) & 1
            else:
                raise ChipError(f"Unknown opcode {op:04X} at {pc:03X}")
        elif hi == 0x9:
            if V[x] != V[y]:
                self.pc = (self.pc + 2) & 0xFFF
        elif hi == 0xA:
            self.I = nnn
        elif hi == 0xB:
            off = V[x] if self.quirks["jump_vx"] else V[0]
            self.pc = (nnn + off) & 0xFFF
        elif hi == 0xC:
            V[x] = random.getrandbits(8) & nn
        elif hi == 0xD:
            self._draw(V[x], V[y], n)
            return self.quirks["disp_wait"]
        elif hi == 0xE:
            if nn == 0x9E:
                if self.keys[V[x] & 0xF]:
                    self.pc = (self.pc + 2) & 0xFFF
            elif nn == 0xA1:
                if not self.keys[V[x] & 0xF]:
                    self.pc = (self.pc + 2) & 0xFFF
            else:
                raise ChipError(f"Unknown opcode {op:04X} at {pc:03X}")
        else:  # 0xF
            I = self.I
            if nn == 0x07:
                V[x] = self.dt
            elif nn == 0x0A:
                keys = self.keys
                if self.wait_key < 0:
                    for k in range(16):
                        if keys[k]:
                            self.wait_key = k
                            break
                    self.pc = pc
                elif keys[self.wait_key]:
                    self.pc = pc          # wait for release
                else:
                    V[x] = self.wait_key
                    self.wait_key = -1
            elif nn == 0x15:
                self.dt = V[x]
            elif nn == 0x18:
                self.st = V[x]
            elif nn == 0x1E:
                self.I = (I + V[x]) & 0xFFFF
            elif nn == 0x29:
                self.I = FONT_ADDR + (V[x] & 0xF) * 5
            elif nn == 0x33:
                v = V[x]
                m[I & 0xFFF] = v // 100
                m[(I + 1) & 0xFFF] = (v // 10) % 10
                m[(I + 2) & 0xFFF] = v % 10
            elif nn == 0x55:
                for i in range(x + 1):
                    m[(I + i) & 0xFFF] = V[i]
                if self.quirks["mem_inc"]:
                    self.I = (I + x + 1) & 0xFFFF
            elif nn == 0x65:
                for i in range(x + 1):
                    V[i] = m[(I + i) & 0xFFF]
                if self.quirks["mem_inc"]:
                    self.I = (I + x + 1) & 0xFFFF
            else:
                raise ChipError(f"Unknown opcode {op:04X} at {pc:03X}")
        return False

    def _draw(self, vx, vy, n):
        fb = self.fb
        m = self.mem
        I = self.I
        clip = self.quirks["clip"]
        x0 = vx % SCR_W
        y0 = vy % SCR_H
        hit = 0
        for row in range(n):
            py = y0 + row
            if py >= SCR_H:
                if clip:
                    break
                py %= SCR_H
            bits = m[(I + row) & 0xFFF]
            if not bits:
                continue
            base = py * SCR_W
            for col in range(8):
                if bits & (0x80 >> col):
                    px = x0 + col
                    if px >= SCR_W:
                        if clip:
                            break
                        px %= SCR_W
                    idx = base + px
                    if fb[idx]:
                        fb[idx] = 0
                        hit = 1
                    else:
                        fb[idx] = 1
        self.V[15] = hit
        self.dirty = True


# ----------------------------------------------------------------------------
# Buzzer (procedural square wave, no asset files)
# ----------------------------------------------------------------------------
class Buzzer:
    RATE = 22050
    PERIOD = 50        # 441 Hz, integer period -> seamless chunk looping
    CYCLES = 22        # ~50 ms chunk
    AMP = 34

    def __init__(self):
        self.active = False
        self.muted = False
        self.kind = "bell"
        self._alive = True
        self._proc = None
        self._tmp = None
        self._ws = None

        half = self.PERIOD // 2
        one = bytes([128 + self.AMP]) * half + bytes([128 - self.AMP]) * (self.PERIOD - half)
        self._pcm = one * self.CYCLES
        self._dur = len(self._pcm) / self.RATE
        self._wav = self._make_wav(self._pcm)

        try:
            if sys.platform.startswith("win"):
                import winsound
                self._ws = winsound
                self.kind = "winsound"
            elif sys.platform.startswith("linux") or "bsd" in sys.platform:
                for cmd in (
                    ["aplay", "-q", "-t", "raw", "-f", "U8", "-r", str(self.RATE),
                     "-c", "1", "-B", "60000"],
                    ["pacat", "--format=u8", f"--rate={self.RATE}", "--channels=1",
                     "--latency-msec=50"],
                ):
                    if shutil.which(cmd[0]):
                        self._proc = subprocess.Popen(
                            cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        self.kind = cmd[0]
                        break
            elif sys.platform == "darwin" and not FILES_OFF and shutil.which("afplay"):
                import tempfile
                fd, path = tempfile.mkstemp(prefix="chip8kondo_", suffix=".wav")
                os.write(fd, self._make_wav(self._pcm * 3))
                os.close(fd)
                self._tmp = path
                self.kind = "afplay"
        except Exception:
            self.kind = "bell"

        if self.kind != "bell":
            threading.Thread(target=self._loop, daemon=True).start()

    def _make_wav(self, pcm):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(1)
            w.setframerate(self.RATE)
            w.writeframes(pcm)
        return buf.getvalue()

    def _loop(self):
        next_due = 0.0
        while self._alive:
            if not (self.active and not self.muted):
                time.sleep(0.008)
                continue
            try:
                if self.kind == "winsound":
                    ws = self._ws
                    ws.PlaySound(self._wav, ws.SND_MEMORY | ws.SND_NODEFAULT)
                elif self.kind == "afplay":
                    subprocess.run(["afplay", self._tmp],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    now = time.monotonic()
                    if next_due < now - 0.1:
                        next_due = now
                    if next_due - now < 0.03:   # keep lead tiny -> low latency stop
                        self._proc.stdin.write(self._pcm)
                        self._proc.stdin.flush()
                        next_due += self._dur
                    else:
                        time.sleep(0.004)
            except Exception:
                self.kind = "bell"
                return

    def close(self):
        self._alive = False
        if self._proc:
            try:
                self._proc.stdin.close()
                self._proc.terminate()
            except Exception:
                pass
        if self._tmp:
            try:
                os.remove(self._tmp)
            except OSError:
                pass


# ----------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------
class App:
    def __init__(self, root, rom_path=None):
        self.root = root
        self.chip = Chip8()
        self.buzzer = Buzzer()

        self.running = True
        self.fault = None
        self.rom_name = "Built-in demo"
        self.ipf = tk.IntVar(value=DEFAULT_IPF)
        self.palette = tk.StringVar(value=DEFAULT_PALETTE)
        self.muted = tk.BooleanVar(value=False)
        self.qvars = {}
        for k, v in self.chip.quirks.items():
            var = tk.BooleanVar(value=v)
            var.trace_add("write", lambda *_a, key=k: self._set_quirk(key))
            self.qvars[k] = var
        self.colors = PALETTES[DEFAULT_PALETTE]
        self._row_cache = {}
        self._rel_jobs = {}
        self._prev_beep = False

        self._acc = 0.0
        self._last = time.perf_counter()
        self._fps_t = self._last
        self._fps_frames = 0
        self._fps = 0.0
        self._ui_div = 0
        self._tick_job = None

        self.ui_font = tkfont.nametofont("TkDefaultFont").copy()
        self.ui_font.configure(size=9)
        self.mono = tkfont.nametofont("TkFixedFont").copy()
        self.mono.configure(size=8)
        self.big = tkfont.nametofont("TkDefaultFont").copy()
        self.big.configure(size=20, weight="bold")

        self._build_window()
        self._build_menu()
        self._build_toolbar()
        self._build_bottom()
        self._build_screen()
        self._bind_keys()

        self.chip.load(DEMO_ROM)
        if rom_path:
            self.load_rom(rom_path)
        self._update_title()
        self._refresh_ui()
        self._tick_job = root.after(10, self._tick)

    # ---------------- construction ----------------
    def _build_window(self):
        r = self.root
        r.title(APP_NAME)
        r.geometry(f"{WIN_W}x{WIN_H}")
        r.minsize(WIN_W, WIN_H)
        r.maxsize(WIN_W, WIN_H)
        r.resizable(False, False)
        r.configure(bg=BG)
        r.protocol("WM_DELETE_WINDOW", self.quit)

    def _menu(self, parent):
        return tk.Menu(parent, tearoff=0, bg=PANEL, fg=FG, activebackground=ACC,
                       activeforeground="#ffffff", selectcolor=ACC, bd=0)

    def _build_menu(self):
        mb = self._menu(self.root)

        fm = self._menu(mb)
        fm.add_command(label="Load ROM...", accelerator="Ctrl+O", command=self.open_rom)
        fm.add_command(label="Load Built-in Demo", command=self.load_demo)
        fm.add_separator()
        fm.add_command(label="Exit", accelerator="Ctrl+Q", command=self.quit)
        mb.add_cascade(label="File", menu=fm)

        em = self._menu(mb)
        em.add_command(label="Pause", accelerator="Ctrl+P", command=self.toggle_pause)
        em.add_command(label="Reset", accelerator="Ctrl+R", command=self.reset)
        em.add_command(label="Step Frame", accelerator="Ctrl+N", command=self.step_frame)
        em.add_separator()
        sm = self._menu(em)
        for s in SPEEDS:
            tag = " (default)" if s == DEFAULT_IPF else ""
            sm.add_radiobutton(label=f"{s} IPF  (~{s * FPS} Hz){tag}", value=s,
                               variable=self.ipf)
        em.add_cascade(label="Speed", menu=sm)
        qm = self._menu(em)
        labels = {
            "vf_reset": "VF reset on AND/OR/XOR",
            "mem_inc": "FX55/FX65 increment I",
            "shift_vy": "Shift uses VY",
            "jump_vx": "BXNN jump uses VX",
            "clip": "Clip sprites at edges",
            "disp_wait": "Wait for VBlank on draw",
        }
        for k, lbl in labels.items():
            qm.add_checkbutton(label=lbl, variable=self.qvars[k])
        qm.add_separator()
        qm.add_command(label="Preset: Modern (default)", command=lambda: self._preset("modern"))
        qm.add_command(label="Preset: COSMAC VIP", command=lambda: self._preset("cosmac"))
        qm.add_command(label="Preset: SUPER-CHIP", command=lambda: self._preset("schip"))
        em.add_cascade(label="Quirks", menu=qm)
        em.add_separator()
        em.add_checkbutton(label="Mute Audio", accelerator="Ctrl+M",
                           variable=self.muted, command=self._apply_mute)
        mb.add_cascade(label="Emulation", menu=em)
        self.emu_menu = em

        vm = self._menu(mb)
        pm = self._menu(vm)
        for name in PALETTES:
            pm.add_radiobutton(label=name, value=name, variable=self.palette,
                               command=self._apply_palette)
        vm.add_cascade(label="Palette", menu=pm)
        mb.add_cascade(label="View", menu=vm)

        hm = self._menu(mb)
        hm.add_command(label="Controls", command=self.show_controls)
        hm.add_command(label="About", command=self.show_about)
        mb.add_cascade(label="Help", menu=hm)

        self.root.config(menu=mb)

    def _btn(self, parent, text, cmd):
        b = tk.Label(parent, text=text, bg=BTN, fg=FG, font=self.ui_font,
                     padx=10, pady=2, cursor="hand2")
        b.bind("<Enter>", lambda e: b.configure(bg=BTN_HOT))
        b.bind("<Leave>", lambda e: b.configure(bg=BTN))
        b.bind("<ButtonRelease-1>", lambda e: cmd())
        b.pack(side="left", padx=(6, 0), pady=4)
        return b

    def _build_toolbar(self):
        top = tk.Frame(self.root, bg=PANEL, height=TOOLBAR_H)
        top.pack(side="top", fill="x")
        top.pack_propagate(False)
        self._btn(top, "Open", self.open_rom)
        self.pause_btn = self._btn(top, "Pause", self.toggle_pause)
        self._btn(top, "Reset", self.reset)
        self._btn(top, "Step", self.step_frame)
        self.mute_btn = self._btn(top, "Mute", self._toggle_mute_btn)
        self.fps_lbl = tk.Label(top, text="0.0 FPS", bg=PANEL, fg=OK, font=self.mono)
        self.fps_lbl.pack(side="right", padx=8)
        self.ipf_lbl = tk.Label(top, text="", bg=PANEL, fg=DIM, font=self.mono)
        self.ipf_lbl.pack(side="right", padx=4)

    def _build_bottom(self):
        bot = tk.Frame(self.root, bg=PANEL, height=BOTTOM_H)
        bot.pack(side="bottom", fill="x")
        bot.pack_propagate(False)
        tk.Frame(bot, bg=BORDER, height=1).pack(side="top", fill="x")
        self.status_lbl = tk.Label(bot, text="", bg=PANEL, fg=FG, font=self.ui_font,
                                   anchor="w")
        self.status_lbl.pack(side="top", fill="x", padx=8)
        self.cpu_lbl = tk.Label(bot, text="", bg=PANEL, fg=DIM, font=self.mono, anchor="w")
        self.cpu_lbl.pack(side="top", fill="x", padx=8)
        self.reg_lbl = tk.Label(bot, text="", bg=PANEL, fg=DIM, font=self.mono, anchor="w")
        self.reg_lbl.pack(side="top", fill="x", padx=8)

    def _build_screen(self):
        mid = tk.Frame(self.root, bg=BG, height=SCREEN_AREA_H)
        mid.pack(side="top", fill="both", expand=True)
        mid.pack_propagate(False)
        frame = tk.Frame(mid, bg=BORDER, padx=2, pady=2)
        frame.place(relx=0.5, rely=0.5, anchor="center")
        w, h = SCR_W * SCALE, SCR_H * SCALE
        self.canvas = tk.Canvas(frame, width=w, height=h, bg=self.colors[1],
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        self._base = tk.PhotoImage(width=SCR_W, height=SCR_H)
        self._scaled = tk.PhotoImage(width=w, height=h)
        self._img_id = self.canvas.create_image(0, 0, anchor="nw", image=self._scaled)
        self._shadow_id = self.canvas.create_text(w // 2 + 2, h // 2 + 2, text="PAUSED",
                                                  fill="#000000", font=self.big,
                                                  state="hidden")
        self._paused_id = self.canvas.create_text(w // 2, h // 2, text="PAUSED",
                                                  fill=ACC, font=self.big, state="hidden")

    def _bind_keys(self):
        r = self.root
        r.bind("<KeyPress>", self._key_down)
        r.bind("<KeyRelease>", self._key_up)
        r.bind("<FocusOut>", self._clear_keys)
        for seq, fn in (("o", self.open_rom), ("p", self.toggle_pause),
                        ("r", self.reset), ("n", self.step_frame),
                        ("m", self._toggle_mute_btn), ("q", self.quit)):
            r.bind_all(f"<Control-{seq}>", lambda e, f=fn: (f(), "break")[1])
            r.bind_all(f"<Control-{seq.upper()}>", lambda e, f=fn: (f(), "break")[1])

    # ---------------- input ----------------
    def _key_down(self, e):
        if e.state & 0x4:          # Control held -> hotkey, not keypad
            return
        k = KEYMAP.get(e.keysym.lower())
        if k is None:
            return
        job = self._rel_jobs.pop(k, None)
        if job:
            self.root.after_cancel(job)   # swallow X11 autorepeat release
        self.chip.keys[k] = True

    def _key_up(self, e):
        k = KEYMAP.get(e.keysym.lower())
        if k is None:
            return
        job = self._rel_jobs.pop(k, None)
        if job:
            self.root.after_cancel(job)
        self._rel_jobs[k] = self.root.after(20, self._release_key, k)

    def _release_key(self, k):
        self._rel_jobs.pop(k, None)
        self.chip.keys[k] = False

    def _clear_keys(self, _e=None):
        for job in self._rel_jobs.values():
            self.root.after_cancel(job)
        self._rel_jobs.clear()
        for i in range(16):
            self.chip.keys[i] = False

    # ---------------- actions ----------------
    def open_rom(self):
        path = filedialog.askopenfilename(
            title="Load CHIP-8 ROM",
            filetypes=[("CHIP-8 ROMs", "*.ch8 *.c8 *.rom *.bin"), ("All files", "*.*")])
        if path:
            self.load_rom(path)

    def load_rom(self, path):
        try:
            with open(path, "rb") as f:
                data = f.read()
            self.chip.load(data)
        except (OSError, ChipError) as ex:
            messagebox.showerror(APP_NAME, f"Could not load ROM:\n{ex}")
            return
        self.rom_name = os.path.basename(path)
        self._after_load()

    def load_demo(self):
        self.chip.load(DEMO_ROM)
        self.rom_name = "Built-in demo"
        self._after_load()

    def _after_load(self):
        self._clear_keys()
        self.fault = None
        self._set_running(True)
        self._update_title()
        self._refresh_ui()

    def reset(self):
        self.chip.reset()
        self._clear_keys()
        self.fault = None
        self._set_running(True)
        self._refresh_ui()

    def toggle_pause(self):
        self._set_running(not self.running)
        if self.running:
            self.fault = None
        self._refresh_ui()

    def step_frame(self):
        if self.running:
            self._set_running(False)
        else:
            self._emulate_frame()
            self._render()
        self._refresh_ui()

    def _set_running(self, on):
        self.running = on
        self._acc = 0.0
        self._last = time.perf_counter()
        self.emu_menu.entryconfigure(0, label="Pause" if on else "Resume")
        self.pause_btn.configure(text="Pause" if on else "Resume")
        st = "hidden" if on else "normal"
        self.canvas.itemconfigure(self._paused_id, state=st,
                                  text="FAULT" if self.fault else "PAUSED")
        self.canvas.itemconfigure(self._shadow_id, state=st,
                                  text="FAULT" if self.fault else "PAUSED")
        if not on:
            self.buzzer.active = False

    def _toggle_mute_btn(self):
        self.muted.set(not self.muted.get())
        self._apply_mute()

    def _apply_mute(self):
        m = self.muted.get()
        self.buzzer.muted = m
        self.mute_btn.configure(text="Unmute" if m else "Mute")

    def _apply_palette(self):
        self.colors = PALETTES[self.palette.get()]
        self._row_cache.clear()
        self.canvas.configure(bg=self.colors[1])
        self.chip.dirty = True
        self._render()

    def _set_quirk(self, key):
        self.chip.quirks[key] = bool(self.qvars[key].get())

    def _preset(self, name):
        presets = {
            "modern": dict(vf_reset=False, mem_inc=False, shift_vy=False,
                           jump_vx=False, clip=True, disp_wait=False),
            "cosmac": dict(vf_reset=True, mem_inc=True, shift_vy=True,
                           jump_vx=False, clip=True, disp_wait=True),
            "schip": dict(vf_reset=False, mem_inc=False, shift_vy=False,
                          jump_vx=True, clip=True, disp_wait=False),
        }
        for k, v in presets[name].items():
            self.qvars[k].set(v)

    def show_controls(self):
        messagebox.showinfo(APP_NAME + " - Controls",
                            "Keyboard      CHIP-8\n"
                            "1 2 3 4   ->  1 2 3 C\n"
                            "Q W E R   ->  4 5 6 D\n"
                            "A S D F   ->  7 8 9 E\n"
                            "Z X C V   ->  A 0 B F\n\n"
                            "Ctrl+O  Load ROM\n"
                            "Ctrl+P  Pause / Resume\n"
                            "Ctrl+R  Reset\n"
                            "Ctrl+N  Step one frame\n"
                            "Ctrl+M  Mute\n"
                            "Ctrl+Q  Quit")

    def show_about(self):
        messagebox.showinfo(APP_NAME,
                            f"{APP_NAME} v{VERSION}\n"
                            "A.C Holdings / Team Flames\n\n"
                            "Single-file Tkinter CHIP-8 emulator.\n"
                            f"Audio backend: {self.buzzer.kind}\n"
                            f"FILES_OFF: {FILES_OFF}")

    def quit(self):
        if self._tick_job:
            try:
                self.root.after_cancel(self._tick_job)
            except tk.TclError:
                pass
        self.buzzer.close()
        self.root.destroy()

    # ---------------- main loop ----------------
    def _emulate_frame(self):
        try:
            self.chip.run_frame(self.ipf.get())
            return True
        except ChipError as ex:
            self._fault(str(ex))
        except Exception as ex:  # corrupted state from a bad ROM
            self._fault(f"{type(ex).__name__}: {ex}")
        return False

    def _fault(self, msg):
        self.fault = msg
        self._set_running(False)
        self._refresh_ui()

    def _tick(self):
        now = time.perf_counter()
        self._acc += now - self._last
        self._last = now
        if self._acc > 0.2:              # hitch (dialog, drag) -> don't spiral
            self._acc = FRAME

        ran = 0
        while self._acc >= FRAME:
            self._acc -= FRAME
            if self.running and self._emulate_frame():
                ran += 1

        if self.chip.dirty:
            self._render()

        beep = self.running and self.chip.st > 0
        self.buzzer.active = beep
        if beep and not self._prev_beep and self.buzzer.kind == "bell" \
                and not self.buzzer.muted:
            self.root.bell()
        self._prev_beep = beep

        self._fps_frames += ran
        if now - self._fps_t >= 0.5:
            self._fps = self._fps_frames / (now - self._fps_t)
            self._fps_frames = 0
            self._fps_t = now
            self.fps_lbl.configure(text=f"{self._fps:5.1f} FPS",
                                   fg=OK if self._fps >= 57 or not self.running else ERR)

        self._ui_div += 1
        if self._ui_div >= 6:
            self._ui_div = 0
            self._refresh_ui()

        delay = max(1, int((FRAME - self._acc) * 1000))
        self._tick_job = self.root.after(delay, self._tick)

    # ---------------- drawing ----------------
    def _render(self):
        on, off = self.colors
        fb = self.chip.fb
        cache = self._row_cache
        if len(cache) > 4096:
            cache.clear()
        rows = []
        for y in range(SCR_H):
            key = bytes(fb[y * SCR_W:(y + 1) * SCR_W])
            s = cache.get(key)
            if s is None:
                s = "{" + " ".join(on if p else off for p in key) + "}"
                cache[key] = s
            rows.append(s)
        self._base.put(" ".join(rows), to=(0, 0))
        self._scaled.tk.call(self._scaled.name, "copy", self._base.name,
                             "-zoom", SCALE, SCALE)
        self.chip.dirty = False

    def _update_title(self):
        self.root.title(f"{APP_NAME} - {self.rom_name}")

    def _refresh_ui(self):
        c = self.chip
        if self.fault:
            state, color = f"FAULT: {self.fault}", ERR
        elif self.running:
            state, color = "RUNNING", OK
        else:
            state, color = "PAUSED", ACC
        self.status_lbl.configure(
            text=f"{self.rom_name}  ({len(c.rom)} B)   |   {state}", fg=color)
        self.ipf_lbl.configure(text=f"{self.ipf.get()} IPF  audio:{self.buzzer.kind}")
        self.cpu_lbl.configure(
            text=(f"PC {c.pc:03X}  OP {c.last_op:04X}  I {c.I:03X}  SP {len(c.stack):X}  "
                  f"DT {c.dt:02X}  ST {c.st:02X}  "
                  f"KEYS {''.join('%X' % i if c.keys[i] else '.' for i in range(16))}"))
        self.reg_lbl.configure(
            text="V " + " ".join(f"{v:02X}" for v in c.V))


def main():
    root = tk.Tk()
    App(root, sys.argv[1] if len(sys.argv) > 1 else None)
    root.mainloop()


if __name__ == "__main__":
    main()