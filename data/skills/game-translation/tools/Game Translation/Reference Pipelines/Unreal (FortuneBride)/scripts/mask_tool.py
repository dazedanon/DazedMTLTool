# -*- coding: utf-8 -*-
"""Interactive mask tool for the tutorial images.

Draw over every Japanese text region you want replaced. Two tools:
  * RECTANGLE (default) - click-drag a box. Best for text blocks; each box is
    saved with exact full-res coordinates, which double as the placement box
    for the English typesetting later.
  * BRUSH - hold-drag to paint irregular bits (glow tails, stray strokes).
  * ERASE - hold-drag to remove paint / delete boxes under the cursor.

Per image it writes:
  work/tut_masks/<name>.png      full-res white-on-black mask (for Qwen erase)
  work/tut_regions/<name>.json   {"size":[W,H], "rects":[[x0,y0,x1,y1],...]}

Controls (also on the toolbar):
  R rectangle   B brush   E erase
  [ / ]  brush smaller / bigger
  Ctrl+Z undo    Shift+C clear all
  A / Left  prev image     D / Right  next image
  S save   (saving also happens automatically when you change image)
  Esc quit

Run:  python scripts/mask_tool.py
"""
import json
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageDraw, ImageTk

SRC_DIR = Path(r"C:/Users/sw/Desktop/Tools/C++/FModel/Output/Exports/NoEcstasyNoLife/Content/_IkaseruGame/UI/Tutorial/TutorialPagePics")
TOOLING = Path(__file__).resolve().parent.parent
MASK_DIR = TOOLING / "work" / "tut_masks"
REG_DIR = TOOLING / "work" / "tut_regions"
MAX_W, MAX_H = 1320, 740          # display canvas cap
OVERLAY = (255, 40, 40)          # mask tint
OVERLAY_A = 110


class MaskTool:
    def __init__(self, root):
        self.root = root
        self.files = sorted(SRC_DIR.glob("tutorial_*.png"))
        if not self.files:
            raise SystemExit(f"No images in {SRC_DIR}")
        MASK_DIR.mkdir(parents=True, exist_ok=True)
        REG_DIR.mkdir(parents=True, exist_ok=True)
        self.idx = 0
        self.mode = "rect"
        self.brush = 22

        # toolbar
        bar = tk.Frame(root, bg="#222")
        bar.pack(side="top", fill="x")
        self.info = tk.Label(bar, text="", fg="#eee", bg="#222", font=("Consolas", 11))
        self.info.pack(side="left", padx=8)
        for txt, cmd in [("Rect(R)", lambda: self.set_mode("rect")),
                         ("Brush(B)", lambda: self.set_mode("brush")),
                         ("Erase(E)", lambda: self.set_mode("erase")),
                         ("Undo", self.undo), ("Clear", self.clear),
                         ("< Prev(A)", self.prev), ("Next(D) >", self.nxt),
                         ("SAVE(S)", self.save)]:
            tk.Button(bar, text=txt, command=cmd).pack(side="left", padx=2, pady=3)

        self.canvas = tk.Canvas(root, bg="#111", highlightthickness=0,
                                width=MAX_W, height=MAX_H, cursor="crosshair")
        self.canvas.pack(side="top")

        # mouse
        self.canvas.bind("<ButtonPress-1>", self.down)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.up)
        # keys
        root.bind("r", lambda e: self.set_mode("rect"))
        root.bind("b", lambda e: self.set_mode("brush"))
        root.bind("e", lambda e: self.set_mode("erase"))
        root.bind("[", lambda e: self.set_brush(-4))
        root.bind("]", lambda e: self.set_brush(+4))
        root.bind("<Control-z>", lambda e: self.undo())
        root.bind("C", lambda e: self.clear())
        root.bind("a", lambda e: self.prev())
        root.bind("d", lambda e: self.nxt())
        root.bind("<Left>", lambda e: self.prev())
        root.bind("<Right>", lambda e: self.nxt())
        root.bind("s", lambda e: self.save())
        root.bind("<Escape>", lambda e: root.destroy())

        self.load()

    # ---------- image / mask state ----------
    def load(self):
        self.path = self.files[self.idx]
        self.name = self.path.stem
        self.full = Image.open(self.path).convert("RGB")
        self.W, self.H = self.full.size
        self.scale = min(MAX_W / self.W, MAX_H / self.H)
        self.dw, self.dh = int(self.W * self.scale), int(self.H * self.scale)
        self.disp_base = self.full.resize((self.dw, self.dh), Image.LANCZOS).convert("RGBA")
        # brush mask kept at display res; rects kept at full res
        self.bmask = Image.new("L", (self.dw, self.dh), 0)
        self.rects = []          # full-res [x0,y0,x1,y1]
        self.strokes = []        # list of stroke = list of (dx,dy,r,erase)
        self.actions = []        # ('rect',i) | ('stroke',i) chronological
        self.cur_stroke = None
        self.temp = None         # temp rect drag (display coords)
        self._load_existing()
        self.refresh()

    def _load_existing(self):
        jp = REG_DIR / f"{self.name}.json"
        mp = MASK_DIR / f"{self.name}.png"
        if jp.exists():
            data = json.loads(jp.read_text())
            self.rects = [list(map(int, r)) for r in data.get("rects", [])]
            self.actions = [("rect", i) for i in range(len(self.rects))]
        if mp.exists():
            # restore brush-only residue: load saved mask, subtract the rect areas
            m = Image.open(mp).convert("L")
            cut = ImageDraw.Draw(m)
            for (x0, y0, x1, y1) in self.rects:
                cut.rectangle([x0, y0, x1, y1], fill=0)
            self.bmask = m.resize((self.dw, self.dh), Image.LANCZOS)

    # ---------- drawing ----------
    def rebuild_bmask(self):
        self.bmask = Image.new("L", (self.dw, self.dh), 0)
        d = ImageDraw.Draw(self.bmask)
        for stroke in self.strokes:
            for (dx, dy, r, er) in stroke:
                d.ellipse([dx - r, dy - r, dx + r, dy + r], fill=0 if er else 255)

    def refresh(self):
        img = self.disp_base.copy()
        ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        # rects (scaled to display)
        for (x0, y0, x1, y1) in self.rects:
            od.rectangle([x0 * self.scale, y0 * self.scale, x1 * self.scale, y1 * self.scale],
                         fill=OVERLAY + (OVERLAY_A,))
        # brush
        red = Image.new("RGBA", img.size, OVERLAY + (OVERLAY_A,))
        ov.paste(red, (0, 0), self.bmask)
        img.alpha_composite(ov)
        # outlines + numbers for rects
        d2 = ImageDraw.Draw(img)
        for i, (x0, y0, x1, y1) in enumerate(self.rects):
            d2.rectangle([x0 * self.scale, y0 * self.scale, x1 * self.scale, y1 * self.scale],
                         outline=(255, 230, 0, 255))
            d2.text((x0 * self.scale + 3, y0 * self.scale + 1), str(i + 1), fill=(255, 230, 0))
        if self.temp:
            tx0, ty0, tx1, ty1 = self.temp
            d2.rectangle([min(tx0, tx1), min(ty0, ty1), max(tx0, tx1), max(ty0, ty1)],
                         outline=(0, 255, 255))
        self.tkimg = ImageTk.PhotoImage(img)
        self.canvas.config(width=self.dw, height=self.dh)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tkimg)
        saved = (REG_DIR / f"{self.name}.json").exists()
        self.info.config(text=f"[{self.idx+1}/{len(self.files)}] {self.name}  "
                              f"{self.W}x{self.H}  mode={self.mode}  brush={self.brush}  "
                              f"rects={len(self.rects)}  {'SAVED' if saved else '*unsaved*'}")

    # ---------- mouse ----------
    def down(self, e):
        self.sx, self.sy = e.x, e.y
        if self.mode == "rect":
            self.temp = [e.x, e.y, e.x, e.y]
        else:
            er = self.mode == "erase"
            self.cur_stroke = []
            self._stamp(e.x, e.y, er)

    def drag(self, e):
        if self.mode == "rect":
            self.temp = [self.sx, self.sy, e.x, e.y]
            self.refresh()
        else:
            self._stamp(e.x, e.y, self.mode == "erase")
            self.refresh()

    def up(self, e):
        if self.mode == "rect":
            x0, y0, x1, y1 = self.temp
            self.temp = None
            x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1))
            if abs(x1 - x0) > 4 and abs(y1 - y0) > 4:
                fr = [int(x0 / self.scale), int(y0 / self.scale),
                      int(x1 / self.scale), int(y1 / self.scale)]
                self.rects.append(fr)
                self.actions.append(("rect", len(self.rects) - 1))
        else:
            if self.cur_stroke:
                self.strokes.append(self.cur_stroke)
                self.actions.append(("stroke", len(self.strokes) - 1))
            self.cur_stroke = None
        self.refresh()

    def _stamp(self, dx, dy, er):
        r = self.brush
        ImageDraw.Draw(self.bmask).ellipse([dx - r, dy - r, dx + r, dy + r],
                                           fill=0 if er else 255)
        if self.cur_stroke is not None:
            self.cur_stroke.append((dx, dy, r, er))

    # ---------- commands ----------
    def set_mode(self, m):
        self.mode = m
        self.refresh()

    def set_brush(self, dv):
        self.brush = max(4, min(120, self.brush + dv))
        self.refresh()

    def undo(self):
        if not self.actions:
            return
        kind, _ = self.actions.pop()
        if kind == "rect" and self.rects:
            self.rects.pop()
        elif kind == "stroke" and self.strokes:
            self.strokes.pop()
            self.rebuild_bmask()
        self.refresh()

    def clear(self):
        self.rects, self.strokes, self.actions = [], [], []
        self.bmask = Image.new("L", (self.dw, self.dh), 0)
        self.refresh()

    def save(self):
        # full-res mask = rects + upscaled brush, lightly feathered later by pipeline
        mask = Image.new("L", (self.W, self.H), 0)
        d = ImageDraw.Draw(mask)
        for (x0, y0, x1, y1) in self.rects:
            d.rectangle([x0, y0, x1, y1], fill=255)
        if self.bmask.getbbox():
            up = self.bmask.resize((self.W, self.H), Image.LANCZOS).point(lambda v: 255 if v > 60 else 0)
            mask.paste(up, (0, 0), up)
        mask.save(MASK_DIR / f"{self.name}.png")
        (REG_DIR / f"{self.name}.json").write_text(json.dumps(
            {"size": [self.W, self.H], "rects": self.rects}, indent=1))
        self.refresh()
        print("saved", self.name, "rects:", len(self.rects))

    def prev(self):
        self.save()
        self.idx = (self.idx - 1) % len(self.files)
        self.load()

    def nxt(self):
        self.save()
        self.idx = (self.idx + 1) % len(self.files)
        self.load()


if __name__ == "__main__":
    root = tk.Tk()
    root.title("Tutorial Mask Tool")
    MaskTool(root)
    root.mainloop()
