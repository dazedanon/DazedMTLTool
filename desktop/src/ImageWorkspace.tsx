import { useEffect, useRef, useState } from "react";
import {
  Check,
  Eraser,
  FolderOpen,
  Hand,
  MousePointer2,
  Paintbrush,
  Plus,
  Redo2,
  Trash2,
  Undo2,
  ZoomIn,
} from "lucide-react";
import { api } from "./bridge";
import { saveBeforeClose } from "./lifecycle";
import {
  boxFromPoints,
  clamp,
  fitZoom,
  imageTransform,
  toImage,
  type PixelBox,
  type Point,
  type Transform,
} from "./canvasGeometry";
import type {
  ImageBlock,
  ImageDocument,
  ImageStroke,
  ImageSummary,
  Job,
} from "./types";

type Doc = { blocks: ImageBlock[]; strokes: ImageStroke[] };
type Tool = "select" | "region" | "pan" | "paint" | "erase-paint" | "cut";
type Drag = {
  kind: "move" | "resize" | "region" | "pan" | "stroke";
  start: Point;
  screen: Point;
  pan: Point;
  box?: PixelBox;
  preview?: PixelBox;
  stroke?: ImageStroke;
};
const selectedImages = new Map<string, string>();
const pendingImageSaves = new Map<string, () => Promise<void>>();
export async function flushImageProject(projectId: string) {
  await pendingImageSaves.get(projectId)?.();
}

const newStyle = () => ({
  background: "auto",
  fill: "#20242c",
  text_color: "#ffffff",
  cap_height: 20,
  align: "center",
  bold: false,
  italic: false,
});

export default function ImageWorkspace({
  projectId,
  active,
  imageJob,
  onStarted,
  report,
  focusImage,
  fonts = [],
}: {
  projectId: string;
  active: boolean;
  imageJob?: Job;
  onStarted: (job: Job) => void;
  report: (error: unknown) => void;
  focusImage?: { id: string; key: number };
  fonts?: { path: string; name: string }[];
}) {
  const [images, setImages] = useState<ImageSummary[]>([]);
  const [asset, setAsset] = useState<ImageDocument | null>(null);
  const [doc, setDoc] = useState<Doc>({ blocks: [], strokes: [] });
  const [group, setGroup] = useState<string[]>([]);
  const [showBoxes, setShowBoxes] = useState(true);
  const [selected, setSelected] = useState("");
  const [tool, setTool] = useState<Tool>("select");
  const [zoom, setZoom] = useState(100);
  const [pan, setPan] = useState<Point>([0, 0]);
  const [view, setView] = useState<"original" | "preview">("original");
  const [brushSize, setBrushSize] = useState(12);
  const [brushColor, setBrushColor] = useState("#20242c");
  const [saved, setSaved] = useState(true);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [exportPath, setExportPath] = useState("");
  const [historyVersion, setHistoryVersion] = useState(0);
  const [layerEpoch, setLayerEpoch] = useState(0);
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const canvas = useRef<HTMLCanvasElement>(null);
  const assetRef = useRef<ImageDocument | null>(null);
  const docRef = useRef<Doc>(doc);
  const savedText = useRef("");
  const saves = useRef<Promise<void>>(Promise.resolve());
  const undo = useRef<Doc[]>([]),
    redo = useRef<Doc[]>([]);
  const drag = useRef<Drag | null>(null);
  const pictures = useRef<Record<string, HTMLImageElement>>({});
  const paintLayer = useRef<HTMLCanvasElement | null>(null);
  const cutLayer = useRef<HTMLCanvasElement | null>(null);
  const frame = useRef<number | null>(null);
  const drawRef = useRef(() => {});
  const mounted = useRef(true);
  const fitMode = useRef(true);
  const initialLoad = useRef(false);
  const loadingGeneration = useRef(0);
  const focusRef = useRef(focusImage);
  focusRef.current = focusImage;
  const pose = useRef({ zoom, pan, viewport });
  pose.current = { zoom, pan, viewport };
  const block = doc.blocks.find((item) => item.id === selected);
  const currentPreview =
    !!asset && asset.preview_revision === asset.revision && saved;
  const approved =
    !!asset && asset.approved_revision === asset.revision && currentPreview;
  const history = () => setHistoryVersion((value) => value + 1);
  function requestDraw() {
    if (frame.current === null)
      frame.current = requestAnimationFrame(() => {
        frame.current = null;
        drawRef.current();
      });
  }
  function accept(value: ImageDocument, replaceDoc = false) {
    assetRef.current = value;
    setAsset(value);
    if (replaceDoc) {
      const next = { blocks: value.blocks, strokes: value.strokes };
      docRef.current = next;
      setDoc(next);
      savedText.current = JSON.stringify(next);
      setSaved(true);
      undo.current = [];
      redo.current = [];
      history();
      setSelected(value.blocks[0]?.id || "");
    }
  }
  async function flush() {
    saves.current = saves.current
      .catch(() => {})
      .then(async () => {
        const current = assetRef.current;
        if (!current) return;
        let serialized = JSON.stringify(docRef.current);
        while (serialized !== savedText.current) {
          const snapshot = docRef.current;
          if (mounted.current) setSaving(true);
          try {
            const response = await api.imageSave({
              project_id: projectId,
              image_id: current.id,
              revision: assetRef.current!.revision,
              ...snapshot,
            });
            if (assetRef.current?.id !== current.id) return;
            const merged = { ...assetRef.current, ...response };
            assetRef.current = merged;
            savedText.current = JSON.stringify(snapshot);
            if (mounted.current) {
              setAsset(merged);
              setSaved(JSON.stringify(docRef.current) === savedText.current);
            }
            serialized = JSON.stringify(docRef.current);
          } finally {
            if (mounted.current) setSaving(false);
          }
        }
      });
    return saves.current;
  }
  useEffect(() => {
    pendingImageSaves.set(projectId, flush);
    return () => {
      pendingImageSaves.delete(projectId);
    };
  }, [projectId]);
  function commit(next: Doc, record = true) {
    if (JSON.stringify(next) === JSON.stringify(docRef.current)) return;
    if (record) {
      undo.current = [...undo.current.slice(-29), docRef.current];
      redo.current = [];
      history();
    }
    docRef.current = next;
    setDoc(next);
    setSaved(JSON.stringify(next) === savedText.current);
    setExportPath("");
  }
  function undoEdit() {
    const previous = undo.current.pop();
    if (!previous) return;
    redo.current.push(docRef.current);
    commit(previous, false);
    history();
  }
  function redoEdit() {
    const next = redo.current.pop();
    if (!next) return;
    undo.current.push(docRef.current);
    commit(next, false);
    history();
  }
  async function load(identity: string) {
    const ticket = ++loadingGeneration.current;
    setBusy(true);
    try {
      await flush();
      const value = await api.imageGet({
        project_id: projectId,
        image_id: identity,
      });
      if (ticket !== loadingGeneration.current || !mounted.current) return;
      accept(value, true);
      selectedImages.set(projectId, identity);
      setView(
        value.preview_revision === value.revision ? "preview" : "original",
      );
      fitMode.current = true;
      setPan([0, 0]);
      setZoom(
        fitZoom(
          value.width,
          value.height,
          viewport.width || 700,
          viewport.height || 420,
        ),
      );
      setExportPath("");
    } catch (error) {
      report(error);
    } finally {
      if (ticket === loadingGeneration.current && mounted.current)
        setBusy(false);
    }
  }
  async function choose() {
    setBusy(true);
    try {
      await flush();
      const file = await api.chooseImage();
      if (!file) return;
      const value = await api.imageImport({
        project_id: projectId,
        name: file.name,
        data_url: file.url,
        source_path: file.source_path,
      });
      accept(value, true);
      selectedImages.set(projectId, value.id);
      setImages(await api.imageList(projectId));
      setView("original");
      fitMode.current = true;
      setPan([0, 0]);
      setZoom(
        fitZoom(
          value.width,
          value.height,
          viewport.width || 700,
          viewport.height || 420,
        ),
      );
      setExportPath("");
    } catch (error) {
      report(error);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    mounted.current = true;
    const stopSavingOnClose = saveBeforeClose(flush);
    api
      .imageList(projectId)
      .then((rows) => {
        if (!mounted.current) return;
        initialLoad.current = true;
        setImages(rows);
        const wanted =
          focusRef.current?.id || selectedImages.get(projectId) || rows[0]?.id;
        if (wanted) load(wanted);
      })
      .catch(report);
    return () => {
      mounted.current = false;
      loadingGeneration.current++;
      flush().then(stopSavingOnClose).catch(report);
    };
  }, [projectId]);
  useEffect(() => {
    if (initialLoad.current && focusImage) {
      api.imageList(projectId).then(setImages).catch(report);
      load(focusImage.id);
    }
  }, [focusImage?.key]);
  useEffect(() => {
    if (asset && viewport.width && fitMode.current) {
      setZoom(
        fitZoom(asset.width, asset.height, viewport.width, viewport.height),
      );
      setPan([0, 0]);
    }
  }, [asset?.id, viewport]);
  useEffect(() => {
    if (!asset) return;
    const timer = setTimeout(() => flush().catch(report), 300);
    return () => clearTimeout(timer);
  }, [doc, asset?.id]);
  useEffect(() => {
    const imageId = imageJob?.image?.id;
    if (
      imageId &&
      imageJob?.status === "complete" &&
      imageId === assetRef.current?.id
    ) {
      api
        .imageGet({ project_id: projectId, image_id: imageId })
        .then((value) => {
          if (
            !mounted.current ||
            value.id !== assetRef.current?.id ||
            value.revision < assetRef.current.revision
          )
            return;
          accept(value, JSON.stringify(docRef.current) === savedText.current);
          if (
            JSON.stringify(docRef.current) === savedText.current &&
            value.preview_revision === value.revision
          )
            setView("preview");
        })
        .catch(report);
    }
  }, [imageJob?.id, imageJob?.status]);
  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const observer = new ResizeObserver(() => {
      setViewport({ width: element.clientWidth, height: element.clientHeight });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!asset) return;
    let alive = true;
    const loaded: Record<string, HTMLImageElement> = {};
    Promise.all(
      [
        "original_url",
        "preview_url",
        "base_url",
        "overlay_url",
        "paint_url",
        "cut_url",
      ].map(
        (key) =>
          new Promise<void>((resolve) => {
            const url = asset[key as keyof ImageDocument];
            if (typeof url !== "string") {
              resolve();
              return;
            }
            const image = new Image();
            image.onload = () => {
              loaded[key] = image;
              resolve();
            };
            image.onerror = () => resolve();
            image.src = url;
          }),
      ),
    ).then(() => {
      if (alive) {
        pictures.current = loaded;
        setLayerEpoch((v) => v + 1);
        requestDraw();
      }
    });
    return () => {
      alive = false;
    };
  }, [
    asset?.original_url,
    asset?.preview_url,
    asset?.paint_url,
    asset?.cut_url,
  ]);
  useEffect(() => {
    if (!asset) return;
    for (const ref of [paintLayer, cutLayer]) {
      if (!ref.current) ref.current = document.createElement("canvas");
      ref.current.width = asset.width;
      ref.current.height = asset.height;
    }
    if (pictures.current.paint_url)
      paintLayer
        .current!.getContext("2d")!
        .drawImage(pictures.current.paint_url, 0, 0);
    if (pictures.current.cut_url)
      cutLayer
        .current!.getContext("2d")!
        .drawImage(pictures.current.cut_url, 0, 0);
    for (const stroke of doc.strokes)
      drawStroke(stroke, paintLayer.current!, cutLayer.current!);
    requestDraw();
  }, [asset?.id, doc.strokes, layerEpoch]);
  function drawStroke(
    stroke: ImageStroke,
    paint: HTMLCanvasElement,
    cut: HTMLCanvasElement,
  ) {
    const ctx = (stroke.tool === "cut" ? cut : paint).getContext("2d")!;
    ctx.save();
    ctx.globalCompositeOperation =
      stroke.tool === "erase-paint" ? "destination-out" : "source-over";
    ctx.strokeStyle = stroke.tool === "cut" ? "#000000" : stroke.color;
    ctx.fillStyle = ctx.strokeStyle;
    ctx.lineWidth = stroke.size;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    if (stroke.points.length === 1) {
      ctx.arc(
        stroke.points[0][0],
        stroke.points[0][1],
        stroke.size / 2,
        0,
        Math.PI * 2,
      );
      ctx.fill();
    } else {
      ctx.moveTo(...stroke.points[0]);
      for (const point of stroke.points.slice(1)) ctx.lineTo(...point);
      ctx.stroke();
    }
    ctx.restore();
  }
  function transform(): Transform {
    const value = assetRef.current!;
    const p = pose.current;
    return imageTransform(
      value.width,
      value.height,
      p.viewport.width,
      p.viewport.height,
      p.zoom,
      p.pan,
    );
  }
  function draw() {
    const element = canvas.current,
      value = assetRef.current;
    if (!element) return;
    const ctx = element.getContext("2d")!;
    const { width, height } = pose.current.viewport;
    const ratio = window.devicePixelRatio || 1;
    if (
      element.width !== Math.round(width * ratio) ||
      element.height !== Math.round(height * ratio)
    ) {
      element.width = Math.round(width * ratio);
      element.height = Math.round(height * ratio);
    }
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.fillStyle = "#10151d";
    ctx.fillRect(0, 0, width, height);
    if (!value) return;
    const t = transform();
    ctx.save();
    ctx.translate(t.x, t.y);
    ctx.scale(t.scale, t.scale);
    ctx.clearRect(0, 0, value.width, value.height);
    const usePreview = view === "preview" && pictures.current.preview_url;
    const image = usePreview
      ? pictures.current.base_url || pictures.current.preview_url
      : pictures.current.original_url;
    if (image) ctx.drawImage(image, 0, 0, value.width, value.height);
    if (cutLayer.current) {
      ctx.save();
      ctx.globalCompositeOperation = "destination-out";
      ctx.drawImage(cutLayer.current, 0, 0);
      ctx.restore();
    }
    if (paintLayer.current) ctx.drawImage(paintLayer.current, 0, 0);
    if (usePreview && pictures.current.overlay_url)
      ctx.drawImage(pictures.current.overlay_url, 0, 0);
    for (const item of showBoxes ? docRef.current.blocks : []) {
      const area =
        item.id === selected && drag.current?.preview
          ? drag.current.preview
          : item.box;
      ctx.lineWidth = 1.5 / t.scale;
      ctx.strokeStyle = item.id === selected ? "#bfd3ff" : "#8399b7";
      ctx.fillStyle = item.id === selected ? "#80aaff18" : "#80aaff08";
      ctx.fillRect(...area);
      ctx.strokeRect(...area);
      ctx.fillStyle = "#c7daff";
      ctx.font = `${12 / t.scale}px system-ui`;
      ctx.fillText(
        String(docRef.current.blocks.indexOf(item) + 1),
        area[0] + 5 / t.scale,
        area[1] + 16 / t.scale,
      );
      if (item.id === selected) {
        ctx.fillStyle = "#c6d8ff";
        ctx.fillRect(
          area[0] + area[2] - 4 / t.scale,
          area[1] + area[3] - 4 / t.scale,
          8 / t.scale,
          8 / t.scale,
        );
      }
    }
    if (drag.current?.kind === "region" && drag.current.preview) {
      ctx.strokeStyle = "#c6d8ff";
      ctx.lineWidth = 1.5 / t.scale;
      ctx.setLineDash([4 / t.scale, 3 / t.scale]);
      ctx.strokeRect(...drag.current.preview);
    }
    ctx.restore();
  }
  drawRef.current = draw;
  useEffect(requestDraw, [
    asset,
    doc,
    zoom,
    pan,
    viewport,
    selected,
    view,
    showBoxes,
  ]);
  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const wheel = (event: WheelEvent) => {
      if (!assetRef.current) return;
      event.preventDefault();
      fitMode.current = false;
      const rect = element.getBoundingClientRect();
      const screen: Point = [
        event.clientX - rect.left - element.clientLeft,
        event.clientY - rect.top - element.clientTop,
      ];
      const old = transform();
      const point = toImage(screen, old);
      const next = clamp(
        Math.round(pose.current.zoom * (event.deltaY > 0 ? 0.9 : 1.1)),
        1,
        800,
      );
      const scale = next / 100;
      const value = assetRef.current;
      setZoom(next);
      setPan([
        (screen[0] - (pose.current.viewport.width - value.width * scale) / 2) /
          scale -
          point[0],
        (screen[1] -
          (pose.current.viewport.height - value.height * scale) / 2) /
          scale -
          point[1],
      ]);
    };
    element.addEventListener("wheel", wheel, { passive: false });
    return () => element.removeEventListener("wheel", wheel);
  }, []);
  function pointer(event: React.PointerEvent<HTMLCanvasElement>): {
    screen: Point;
    point: Point;
  } {
    const rect = event.currentTarget.getBoundingClientRect();
    const screen: Point = [
      event.clientX - rect.left - event.currentTarget.clientLeft,
      event.clientY - rect.top - event.currentTarget.clientTop,
    ];
    return { screen, point: toImage(screen, transform()) };
  }
  function down(event: React.PointerEvent<HTMLCanvasElement>) {
    if (!asset || busy || active) return;
    event.currentTarget.focus({ preventScroll: true });
    const { screen, point } = pointer(event);
    if (
      tool !== "pan" &&
      (point[0] < 0 ||
        point[1] < 0 ||
        point[0] > asset.width ||
        point[1] > asset.height)
    )
      return;
    event.currentTarget.setPointerCapture(event.pointerId);
    if (tool === "pan") {
      fitMode.current = false;
      drag.current = { kind: "pan", start: point, screen, pan };
      return;
    }
    if (tool === "region") {
      drag.current = {
        kind: "region",
        start: point,
        screen,
        pan,
        preview: [point[0], point[1], 1, 1],
      };
      return;
    }
    if (tool === "paint" || tool === "erase-paint" || tool === "cut") {
      for (const ref of [paintLayer, cutLayer]) {
        if (!ref.current) ref.current = document.createElement("canvas");
        if (
          ref.current.width !== asset.width ||
          ref.current.height !== asset.height
        ) {
          ref.current.width = asset.width;
          ref.current.height = asset.height;
        }
      }
      const p: Point = [
        clamp(Math.round(point[0]), 0, asset.width - 1),
        clamp(Math.round(point[1]), 0, asset.height - 1),
      ];
      const stroke: ImageStroke = {
        tool,
        points: [p],
        size: brushSize,
        color: brushColor,
      };
      setView("original");
      drag.current = { kind: "stroke", start: point, screen, pan, stroke };
      drawStroke(stroke, paintLayer.current!, cutLayer.current!);
      requestDraw();
      return;
    }
    const chosen = doc.blocks.find((b) => b.id === selected);
    if (
      chosen &&
      Math.abs(point[0] - chosen.box[0] - chosen.box[2]) <
        9 / transform().scale &&
      Math.abs(point[1] - chosen.box[1] - chosen.box[3]) < 9 / transform().scale
    ) {
      drag.current = {
        kind: "resize",
        start: point,
        screen,
        pan,
        box: chosen.box,
        preview: chosen.box,
      };
      return;
    }
    const hit = [...doc.blocks]
      .reverse()
      .find(
        (b) =>
          point[0] >= b.box[0] &&
          point[1] >= b.box[1] &&
          point[0] <= b.box[0] + b.box[2] &&
          point[1] <= b.box[1] + b.box[3],
      );
    setSelected(hit?.id || "");
    if (hit)
      drag.current = {
        kind: "move",
        start: point,
        screen,
        pan,
        box: hit.box,
        preview: hit.box,
      };
  }
  function move(event: React.PointerEvent<HTMLCanvasElement>) {
    const gesture = drag.current;
    if (!gesture || !asset) return;
    const { screen, point } = pointer(event);
    if (gesture.kind === "pan") {
      setPan([
        gesture.pan[0] + (screen[0] - gesture.screen[0]) / transform().scale,
        gesture.pan[1] + (screen[1] - gesture.screen[1]) / transform().scale,
      ]);
      return;
    }
    if (gesture.kind === "region")
      gesture.preview = boxFromPoints(
        gesture.start,
        point,
        asset.width,
        asset.height,
      );
    if (gesture.kind === "move" && gesture.box)
      gesture.preview = [
        clamp(
          Math.round(gesture.box[0] + point[0] - gesture.start[0]),
          0,
          asset.width - gesture.box[2],
        ),
        clamp(
          Math.round(gesture.box[1] + point[1] - gesture.start[1]),
          0,
          asset.height - gesture.box[3],
        ),
        gesture.box[2],
        gesture.box[3],
      ];
    if (gesture.kind === "resize" && gesture.box)
      gesture.preview = [
        gesture.box[0],
        gesture.box[1],
        clamp(
          Math.round(point[0] - gesture.box[0]),
          1,
          asset.width - gesture.box[0],
        ),
        clamp(
          Math.round(point[1] - gesture.box[1]),
          1,
          asset.height - gesture.box[1],
        ),
      ];
    if (gesture.kind === "stroke" && gesture.stroke) {
      const p: Point = [
        clamp(Math.round(point[0]), 0, asset.width - 1),
        clamp(Math.round(point[1]), 0, asset.height - 1),
      ];
      const previous = gesture.stroke.points.at(-1)!;
      if (
        Math.hypot(p[0] - previous[0], p[1] - previous[1]) >=
          Math.max(1, brushSize / 8) &&
        gesture.stroke.points.length < 2000
      ) {
        gesture.stroke.points.push(p);
        drawStroke(
          { ...gesture.stroke, points: [previous, p] },
          paintLayer.current!,
          cutLayer.current!,
        );
      }
    }
    requestDraw();
  }
  function up() {
    const gesture = drag.current;
    drag.current = null;
    if (!gesture) return;
    if (
      gesture.kind === "region" &&
      gesture.preview &&
      gesture.preview[2] >= 4 &&
      gesture.preview[3] >= 4
    ) {
      const item: ImageBlock = {
        id: crypto.randomUUID(),
        box: gesture.preview,
        source: "",
        target: "",
        style: newStyle(),
      };
      commit({ ...docRef.current, blocks: [...docRef.current.blocks, item] });
      setSelected(item.id);
      setTool("select");
    } else if (
      (gesture.kind === "move" || gesture.kind === "resize") &&
      gesture.preview
    ) {
      updateBlock({ box: gesture.preview });
    } else if (gesture.kind === "stroke" && gesture.stroke) {
      commit({
        ...docRef.current,
        strokes: [...docRef.current.strokes, gesture.stroke],
      });
    }
    requestDraw();
  }
  function cancel() {
    drag.current = null;
    setLayerEpoch((value) => value + 1);
    requestDraw();
  }
  function updateBlock(change: Partial<ImageBlock>) {
    if (change.style && change.style.background !== "auto")
      change.style.locked = true;
    commit({
      ...docRef.current,
      blocks: docRef.current.blocks.map((item) =>
        item.id === selected ? { ...item, ...change } : item,
      ),
    });
  }
  function updateBox(index: number, value: number) {
    if (!block || !asset || !Number.isFinite(value)) return;
    const next = [...block.box] as PixelBox;
    const limits = [
      [0, asset.width - next[2]],
      [0, asset.height - next[3]],
      [1, asset.width - next[0]],
      [1, asset.height - next[1]],
    ];
    next[index] = clamp(Math.round(value), limits[index][0], limits[index][1]);
    updateBlock({ box: next });
  }
  function remove() {
    commit({
      ...docRef.current,
      blocks: docRef.current.blocks.filter((item) => item.id !== selected),
    });
    setSelected("");
  }
  function mergeRegions() {
    const members = doc.blocks.filter((b) => group.includes(b.id));
    if (members.length < 2) return;
    const left = Math.min(...members.map((b) => b.box[0])),
      top = Math.min(...members.map((b) => b.box[1]));
    const right = Math.max(...members.map((b) => b.box[0] + b.box[2])),
      bottom = Math.max(...members.map((b) => b.box[1] + b.box[3]));
    const merged: ImageBlock = {
      ...members[0],
      box: [left, top, right - left, bottom - top],
      source: members.map((b) => b.source).join("\n"),
      target: members
        .map((b) => b.target)
        .filter(Boolean)
        .join("\n"),
      lines: members.flatMap(
        (b) => b.lines || [{ text: b.source, box: b.box, angle: b.angle }],
      ),
      flags: [],
      style: newStyle(),
    };
    commit({
      ...doc,
      blocks: doc.blocks.flatMap((b) =>
        b.id === merged.id ? [merged] : group.includes(b.id) ? [] : [b],
      ),
    });
    setSelected(merged.id);
    setGroup([]);
  }
  function splitRegion() {
    if (!block || !asset) return;
    const lines = block.lines?.length
      ? block.lines
      : block.source.split("\n").map((text, index, all) => {
          const top =
            block.box[1] + Math.floor((block.box[3] * index) / all.length);
          return {
            text,
            box: [
              block.box[0],
              top,
              block.box[2],
              Math.max(
                1,
                Math.floor((block.box[3] * (index + 1)) / all.length) +
                  block.box[1] -
                  top,
              ),
            ] as PixelBox,
          };
        });
    if (lines.length < 2) return;
    const targets = block.target.split("\n");
    const parts = lines.map((line, i) => ({
      ...block,
      id: crypto.randomUUID().replaceAll("-", ""),
      source: line.text,
      target:
        targets.length === lines.length
          ? targets[i]
          : i === 0
            ? block.target
            : "",
      box: line.box,
      lines: [line],
      flags: [],
      style: newStyle(),
    }));
    commit({
      ...doc,
      blocks: doc.blocks.flatMap((b) => (b.id === block.id ? parts : [b])),
    });
    setSelected(parts[0].id);
  }
  function reorder(direction: number) {
    const index = doc.blocks.findIndex((b) => b.id === selected),
      other = index + direction;
    if (index < 0 || other < 0 || other >= doc.blocks.length) return;
    const values = [...doc.blocks];
    [values[index], values[other]] = [values[other], values[index]];
    commit({ ...doc, blocks: values });
  }
  async function render() {
    if (!asset) return;
    setBusy(true);
    try {
      await flush();
      const job = await api.imageRender({
        project_id: projectId,
        image_id: asset.id,
      });
      onStarted(job);
    } catch (error) {
      report(error);
    } finally {
      setBusy(false);
    }
  }
  async function reviewImage() {
    if (!asset?.link) return;
    setBusy(true);
    try {
      await flush();
      const current = assetRef.current!;
      const response = await api.imageReview({
        project_id: projectId,
        image_id: current.id,
        revision: current.revision,
        confirmed: !["confirmed", "translated", "rendered"].includes(
          current.status || "",
        ),
      });
      accept({ ...current, ...response });
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  async function approve() {
    if (!asset) return;
    setBusy(true);
    try {
      await flush();
      const response = await api.imageApprove({
        project_id: projectId,
        image_id: asset.id,
        revision: assetRef.current!.revision,
      });
      accept({ ...assetRef.current!, ...response });
    } catch (error) {
      report(error);
    } finally {
      setBusy(false);
    }
  }
  async function exportImage() {
    if (!asset) return;
    setBusy(true);
    try {
      const result = await api.imageExport({
        project_id: projectId,
        image_id: asset.id,
      });
      setExportPath(result.path);
    } catch (error) {
      report(error);
    } finally {
      setBusy(false);
    }
  }
  const tools: [Tool, string, typeof MousePointer2][] = [
    ["select", "Select", MousePointer2],
    ["region", "Add region", Plus],
    ["pan", "Pan", Hand],
    ["paint", "Paint", Paintbrush],
    ["erase-paint", "Erase paint", Eraser],
    ["cut", "Erase to transparency", Eraser],
  ];
  return (
    <fieldset className="image-editor-fieldset" disabled={active}>
      <div className="page-heading">
        <div>
          <span className="eyebrow">IMAGE WORKSPACE</span>
          <h1>Translate images.</h1>
          <p>
            Mark text, adjust its appearance, and review the rendered result.
          </p>
        </div>
        <button onClick={choose} disabled={busy}>
          <FolderOpen size={16} />
          Open image…
        </button>
      </div>
      <div className="image-workspace-toolbar">
        <label className="image-picker">
          Image
          <select
            aria-label="Current image"
            disabled={busy}
            value={asset?.id || ""}
            onChange={(e) => load(e.target.value)}
          >
            {!asset && <option value="">Choose an image</option>}
            {images.map((image) => (
              <option value={image.id} key={image.id}>
                {image.name}
              </option>
            ))}
          </select>
        </label>
        <span className="muted">
          {asset ? `${asset.width} × ${asset.height} pixels` : ""}
        </span>
        {asset?.link && (
          <>
            <span>{asset.status?.replaceAll("_", " ")}</span>
            <button disabled={busy || active} onClick={reviewImage}>
              {["confirmed", "translated", "rendered"].includes(
                asset.status || "",
              )
                ? "Mark this image for review"
                : "Confirm this image’s text"}
            </button>
          </>
        )}
        <span className="save-indicator" role="status">
          {asset
            ? saving
              ? "Saving…"
              : saved
                ? "Saved"
                : "Unsaved edits"
            : ""}
        </span>
      </div>
      <div className="image-editor-layout">
        <div className="image-stage">
          <div className="image-tools">
            {tools.map(([value, label, Icon]) => (
              <button
                key={value}
                aria-label={label}
                aria-pressed={tool === value}
                disabled={!asset}
                onClick={() => setTool(value)}
              >
                <Icon size={16} />
                <span>{label}</span>
              </button>
            ))}
            <button
              aria-label="Undo image edit"
              disabled={!undo.current.length}
              onClick={undoEdit}
            >
              <Undo2 size={16} />
            </button>
            <button
              aria-label="Redo image edit"
              disabled={!redo.current.length}
              onClick={redoEdit}
            >
              <Redo2 size={16} />
            </button>
          </div>
          <canvas
            ref={canvas}
            className={`pixel-canvas tool-${tool}`}
            tabIndex={0}
            aria-label="Image canvas. Use Add region to draw a box; arrow keys move the selected region."
            onPointerDown={down}
            onPointerMove={move}
            onPointerUp={up}
            onPointerCancel={cancel}
            onKeyDown={(event) => {
              if (active) return;
              if (event.key === "Escape") {
                cancel();
                setTool("select");
              } else if (
                (event.ctrlKey || event.metaKey) &&
                event.key.toLowerCase() === "z"
              ) {
                event.preventDefault();
                event.shiftKey ? redoEdit() : undoEdit();
              } else if (
                (event.ctrlKey || event.metaKey) &&
                event.key.toLowerCase() === "s"
              ) {
                event.preventDefault();
                flush().catch(report);
              } else if (event.key === "Delete" && selected) {
                event.preventDefault();
                remove();
              } else if (block && event.key.startsWith("Arrow")) {
                event.preventDefault();
                const step = event.shiftKey ? 10 : 1;
                const axis =
                  event.key === "ArrowLeft" || event.key === "ArrowRight"
                    ? 0
                    : 1;
                updateBox(
                  axis,
                  block.box[axis] +
                    (event.key === "ArrowLeft" || event.key === "ArrowUp"
                      ? -step
                      : step),
                );
              }
            }}
          />
          <div className="image-camera">
            <button
              disabled={!asset}
              onClick={() => {
                if (asset) {
                  fitMode.current = true;
                  setZoom(
                    fitZoom(
                      asset.width,
                      asset.height,
                      viewport.width,
                      viewport.height,
                    ),
                  );
                  setPan([0, 0]);
                }
              }}
            >
              Fit image
            </button>
            <label>
              <ZoomIn size={15} />
              <input
                aria-label="Image zoom"
                type="range"
                min={1}
                max={400}
                value={Math.min(400, zoom)}
                onChange={(e) => {
                  fitMode.current = false;
                  setZoom(Number(e.target.value));
                }}
              />
              {zoom}%
            </label>
            <button
              disabled={!asset}
              aria-pressed={view === "original"}
              onClick={() => setView("original")}
            >
              Original
            </button>
            <button
              disabled={!asset?.preview_url}
              aria-pressed={view === "preview"}
              onClick={() => setView("preview")}
            >
              Preview
            </button>
          </div>
          {(["paint", "erase-paint", "cut"] as string[]).includes(tool) && (
            <div className="brush-options">
              <label>
                Brush width
                <input
                  aria-label="Brush width"
                  type="range"
                  min={1}
                  max={100}
                  value={Math.min(100, brushSize)}
                  onChange={(e) => setBrushSize(Number(e.target.value))}
                />
                {brushSize}px
              </label>
              {tool === "paint" && (
                <label>
                  Paint color
                  <input
                    aria-label="Paint color"
                    type="color"
                    value={brushColor}
                    onChange={(e) => setBrushColor(e.target.value)}
                  />
                </label>
              )}
            </div>
          )}
          {!asset && (
            <p className="footnote">
              Open a local PNG, JPEG or WebP. Originals stay unchanged; edits
              are saved in this project.
            </p>
          )}
          {asset && (
            <div className="actions">
              <button
                className="primary"
                disabled={busy || active}
                onClick={render}
              >
                Render preview
              </button>
              <button
                disabled={
                  busy ||
                  active ||
                  !currentPreview ||
                  asset.notes.some((note) => !note.ok)
                }
                onClick={approve}
              >
                <Check size={15} />
                {approved
                  ? asset.link
                    ? "Written to editable image"
                    : "Preview approved"
                  : asset.link
                    ? "Approve and write editable image"
                    : "Approve preview"}
              </button>
              <button disabled={!approved || busy} onClick={exportImage}>
                Export PNG
              </button>
              {exportPath && (
                <button
                  onClick={() => api.openExport(exportPath).catch(report)}
                >
                  Open output folder
                </button>
              )}
            </div>
          )}
          {exportPath && (
            <p className="output-path image-output-path">{exportPath}</p>
          )}
          {asset && !currentPreview && asset.preview_url && (
            <p className="footnote">
              This preview predates the current edits. Render again before
              approval.
            </p>
          )}
          {asset?.notes.map((note) => (
            <p
              className={`image-note ${note.ok ? "" : "error"}`}
              key={note.block_id}
            >
              {note.ok ? "✓" : "!"}{" "}
              {doc.blocks.findIndex((item) => item.id === note.block_id) + 1}:{" "}
              {note.message}
            </p>
          ))}
        </div>
        <aside className="image-inspector">
          <div className="section-heading">
            <h2>Text regions</h2>
            <span className="muted">{doc.blocks.length}</span>
          </div>
          <div className="actions">
            <label className="check">
              <input
                type="checkbox"
                checked={showBoxes}
                onChange={(e) => setShowBoxes(e.target.checked)}
              />
              Show boxes
            </label>
            <button disabled={group.length < 2} onClick={mergeRegions}>
              Merge selected
            </button>
            <button
              disabled={
                !block ||
                !(
                  (block.lines && block.lines.length > 1) ||
                  block.source.includes("\n")
                )
              }
              onClick={splitRegion}
            >
              Split lines
            </button>
          </div>
          <div className="region-list">
            {doc.blocks.map((item, index) => (
              <div className="region-row" key={item.id}>
                <input
                  type="checkbox"
                  aria-label={`Group region ${index + 1}`}
                  checked={group.includes(item.id)}
                  onChange={(e) =>
                    setGroup(
                      e.target.checked
                        ? [...group, item.id]
                        : group.filter((id) => id !== item.id),
                    )
                  }
                />
                <button
                  aria-pressed={selected === item.id}
                  onClick={() => setSelected(item.id)}
                >
                  {index + 1}
                  <span>
                    {item.skip ? "Skipped · " : ""}
                    {item.target || item.source || "Untitled region"}
                  </span>
                </button>
              </div>
            ))}
          </div>
          {block ? (
            <>
              <div className="pixel-fields">
                {["X", "Y", "Width", "Height"].map((label, index) => (
                  <label key={label}>
                    {label}
                    <input
                      aria-label={`Region ${label.toLowerCase()}`}
                      type="number"
                      value={block.box[index]}
                      onChange={(e) => updateBox(index, Number(e.target.value))}
                    />
                  </label>
                ))}
              </div>
              <div className="actions">
                <button onClick={() => reorder(-1)}>Earlier</button>
                <button onClick={() => reorder(1)}>Later</button>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={!!block.skip}
                    onChange={(e) => updateBlock({ skip: e.target.checked })}
                  />
                  Skip region
                </label>
              </div>
              <label>
                Text rotation
                <select
                  aria-label="Text rotation"
                  value={block.angle || 0}
                  onChange={(e) =>
                    updateBlock({ angle: Number(e.target.value) })
                  }
                >
                  <option value={0}>Horizontal</option>
                  <option value={90}>Vertical</option>
                  <option value={-90}>Vertical, reverse</option>
                </select>
              </label>
              {!!block.flags?.length && (
                <p className="image-note">Review: {block.flags.join(", ")}</p>
              )}
              <label className="image-text-label">
                Original text
                <textarea
                  aria-label="Original image text"
                  value={block.source}
                  onChange={(e) => updateBlock({ source: e.target.value })}
                />
              </label>
              <label className="image-text-label">
                Translated text
                <textarea
                  aria-label="Translated image text"
                  value={block.target}
                  onChange={(e) => updateBlock({ target: e.target.value })}
                />
              </label>
              <label className="image-style-label">
                Appearance
                <select
                  aria-label="Image background treatment"
                  value={block.style.background}
                  onChange={(e) =>
                    updateBlock({
                      style: { ...block.style, background: e.target.value },
                    })
                  }
                >
                  <option value="auto">Match original automatically</option>
                  <option value="keep">Keep background</option>
                  <option value="solid">Solid background</option>
                  <option value="transparent">Transparent background</option>
                  <option value="vgradient">Vertical gradient</option>
                  <option value="hgradient">Horizontal gradient</option>
                  <option value="patch">Clone a donor region</option>
                  <option value="inpaint">Reconstruct artwork</option>
                </select>
              </label>
              {block.style.background !== "auto" && (
                <>
                  <div className="pixel-fields">
                    <label>
                      Text color
                      <input
                        aria-label="Image text color"
                        type="color"
                        value={block.style.text_color}
                        onChange={(e) =>
                          updateBlock({
                            style: {
                              ...block.style,
                              text_color: e.target.value,
                            },
                          })
                        }
                      />
                    </label>
                    <label>
                      Fill color
                      <input
                        aria-label="Image fill color"
                        type="color"
                        value={block.style.fill}
                        onChange={(e) =>
                          updateBlock({
                            style: { ...block.style, fill: e.target.value },
                          })
                        }
                      />
                    </label>
                    <label>
                      Text size
                      <input
                        aria-label="Image text size"
                        type="number"
                        min={5}
                        max={400}
                        value={block.style.cap_height}
                        onChange={(e) =>
                          updateBlock({
                            style: {
                              ...block.style,
                              cap_height: clamp(Number(e.target.value), 5, 400),
                            },
                          })
                        }
                      />
                    </label>
                    <label>
                      Alignment
                      <select
                        aria-label="Image text alignment"
                        value={block.style.align}
                        onChange={(e) =>
                          updateBlock({
                            style: { ...block.style, align: e.target.value },
                          })
                        }
                      >
                        <option value="left">Left</option>
                        <option value="center">Center</option>
                        <option value="right">Right</option>
                      </select>
                    </label>
                  </div>
                  <div className="actions">
                    <label className="check compact">
                      <input
                        type="checkbox"
                        checked={block.style.bold}
                        onChange={(e) =>
                          updateBlock({
                            style: { ...block.style, bold: e.target.checked },
                          })
                        }
                      />
                      Bold
                    </label>
                    <label className="check compact">
                      <input
                        type="checkbox"
                        checked={block.style.italic}
                        onChange={(e) =>
                          updateBlock({
                            style: { ...block.style, italic: e.target.checked },
                          })
                        }
                      />
                      Italic
                    </label>
                  </div>
                </>
              )}
              {block.style.background !== "auto" && (
                <details className="image-type-controls">
                  <summary>Typography and reconstruction</summary>
                  <label>
                    Font family or file
                    <input
                      aria-label="Image font"
                      list={`image-fonts-${projectId}`}
                      value={block.style.font || ""}
                      onChange={(e) =>
                        updateBlock({
                          style: { ...block.style, font: e.target.value },
                        })
                      }
                      placeholder="Automatic bundled font"
                    />
                    <datalist id={`image-fonts-${projectId}`}>
                      {fonts.map((f) => (
                        <option key={f.path} value={f.path}>
                          {f.name}
                        </option>
                      ))}
                    </datalist>
                  </label>
                  <div className="pixel-fields">
                    {(
                      [
                        ["scale_x", "Width %", 100, 10, 400],
                        ["scale_y", "Height %", 100, 10, 400],
                        ["tracking", "Tracking", 0, -200, 1000],
                        ["outline_width", "Outline width", 0, 0, 5],
                        ["text_color_alpha", "Text opacity", 255, 0, 255],
                        ["fill_alpha", "Fill opacity", 255, 0, 255],
                        ["outline_color_alpha", "Outline opacity", 255, 0, 255],
                      ] as const
                    ).map(([key, label, fallback, min, max]) => (
                      <label key={key}>
                        {label}
                        <input
                          type="number"
                          aria-label={label}
                          min={min}
                          max={max}
                          value={block.style[key] ?? fallback}
                          onChange={(e) =>
                            updateBlock({
                              style: {
                                ...block.style,
                                [key]: clamp(Number(e.target.value), min, max),
                              },
                            })
                          }
                        />
                      </label>
                    ))}
                  </div>
                  <label>
                    Outline color
                    <input
                      type="color"
                      value={block.style.outline_color || "#000000"}
                      onChange={(e) =>
                        updateBlock({
                          style: {
                            ...block.style,
                            outline_color: e.target.value,
                          },
                        })
                      }
                    />
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={!!block.style.overflow}
                      onChange={(e) =>
                        updateBlock({
                          style: { ...block.style, overflow: e.target.checked },
                        })
                      }
                    />
                    Allow text overflow
                  </label>
                  <label>
                    Reconstruction
                    <select
                      value={block.style.inpaint_method || ""}
                      onChange={(e) =>
                        updateBlock({
                          style: {
                            ...block.style,
                            inpaint_method: e.target.value,
                          },
                        })
                      }
                    >
                      <option value="">Built-in automatic</option>
                      <option value="telea">Telea</option>
                      <option value="ns">Navier–Stokes</option>
                      <option value="patchmatch">PatchMatch</option>
                      <option value="lama">LaMa</option>
                      <option value="lama_manga">LaMa manga</option>
                      <option value="aot">AOT</option>
                    </select>
                  </label>
                  {block.style.background === "patch" && (
                    <div className="pixel-fields">
                      {[
                        "Donor X",
                        "Donor Y",
                        "Donor width",
                        "Donor height",
                      ].map((label, i) => (
                        <label key={label}>
                          {label}
                          <input
                            type="number"
                            value={block.style.donor?.[i] ?? block.box[i]}
                            onChange={(e) => {
                              const donor = [
                                ...(block.style.donor || block.box),
                              ] as PixelBox;
                              donor[i] = Number(e.target.value);
                              updateBlock({ style: { ...block.style, donor } });
                            }}
                          />
                        </label>
                      ))}
                    </div>
                  )}
                  <p className="muted">
                    Measured confidence:{" "}
                    {Math.round((block.style.confidence || 0) * 100)}%.{" "}
                    {block.style.notes?.join(" ")}
                  </p>
                  <button onClick={() => updateBlock({ style: newStyle() })}>
                    Measure appearance again
                  </button>
                </details>
              )}
              <button className="quiet" onClick={remove}>
                <Trash2 size={15} />
                Remove region
              </button>
              <p className="footnote">
                Coordinates and brush widths use original image pixels. Zooming
                and resizing do not move your work.
              </p>
            </>
          ) : (
            <p className="muted">
              Choose Add region and drag over the image, or select a saved
              region.
            </p>
          )}
        </aside>
      </div>
    </fieldset>
  );
}
