// Execute the installed bundle's controllers with tiny reactive/DOM adapters.
// No game, browser, local settings, or network is needed for these regressions.
const assert = require("node:assert/strict");
const vm = require("node:vm");
const outputs = JSON.parse(require("node:fs").readFileSync(0, "utf8"));
const scales = [0.75, 1, 1.5, 2, 3, 1.45]; // auto at 816px with DPR 2
const near = (actual, expected) =>
  assert.ok(Math.abs(actual - expected) < 1e-7, `${actual} != ${expected}`);

function environment(source, saved) {
  const listeners = new Map();
  const values = new Map();
  const host = {style: {}};
  const mounts = [];
  const context = vm.createContext({
    innerWidth: 816, innerHeight: 624, devicePixelRatio: 2,
    Graphics: {width: 816},
    location: {protocol: "https:", pathname: "/game/index.html"},
    document: {
      getElementById: () => host,
      documentElement: {clientWidth: 816},
    },
    localStorage: {
      get length() { return values.size; },
      key: index => [...values.keys()][index],
      getItem: key => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      removeItem: key => values.delete(key),
    },
    MutationObserver: class { observe() {} },
    Event: class { constructor(type) { this.type = type; } },
    setInterval() {},
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type).add(fn);
    },
    removeEventListener(type, fn) { listeners.get(type)?.delete(fn); },
    dispatchEvent(event) {
      for (const fn of listeners.get(event.type) || []) fn(event);
    },
    P: value => ({value}), V: state => state.value,
    F: (state, value) => { state.value = value; },
    Js: fn => mounts.push(fn),
    ml: {}, Q: {activeTab: "map"},
    Bl: {load() {}}, Z: {install() {}}, Nl: {install() {}},
    nu: {install() {}}, $: {init() {}}, ru: [],
    zl: {rememberPosition: true},
    Ol: {getItem: key => saved[key], setItem: (key, value) => { saved[key] = value; }},
  });
  context.window = context;
  const marker = "/*</DazedMTLTool-Forge-bootstrap>*/";
  vm.runInContext(source.slice(0, source.indexOf(marker) + marker.length), context);
  const start = source.indexOf("let n=[{id:ml.General,label:");
  const end = source.indexOf(";var ne=hp()", start);
  assert.ok(start > 0 && end > start, "Forge panel controller must be available");
  context.panel = vm.runInContext(`(() => {
    ${source.slice(start, end)};
    return {
      bounds: () => ({x: V(r), y: V(i), w: V(a), h: V(o)}),
      startResize: C, resize: ee, endResize: te,
      startDrag: y, drag: _, endDrag: v,
    };
  })()`, context);
  mounts.forEach(fn => fn());
  return {context, panel: context.panel, host};
}

const mouse = (clientX, clientY) => ({
  clientX, clientY, button: 0, deltaY: -1,
  preventDefault() {}, stopPropagation() {},
  target: {closest() { return null; }},
});

for (const [index, source] of outputs.entries()) {
  const scale = scales[index];
  // Previously saved windows larger than the game must recover on startup.
  const saved = {panel: {x: 1, y: 1, w: 4096, h: 4096}};
  const {context, panel, host} = environment(source, saved);
  const fits = () => {
    const b = panel.bounds();
    const fx = Number(host.style.zoom);
    assert.ok(b.x >= 0 && b.y >= 0);
    assert.ok((b.x + b.w) * fx <= context.innerWidth + 1e-7);
    assert.ok((b.y + b.h) * fx <= context.innerHeight + 1e-7);
  };
  near(Number(host.style.zoom), scale);
  fits();
  const before = panel.bounds();
  panel.startResize(mouse(816, 624));
  panel.resize(mouse(768, 576));
  panel.endResize();
  const smaller = panel.bounds();
  near((before.w - smaller.w) * scale, 48);
  near((before.h - smaller.h) * scale, 48);

  // The panel moves the same distance as the physical mouse and stays usable.
  panel.startDrag(mouse(0, 0));
  panel.drag(mouse(24, 24));
  panel.endDrag();
  near(panel.bounds().x * scale, 24);
  near(panel.bounds().y * scale, 24);
  fits();
  const restored = environment(source, saved).panel.bounds();
  for (const key of ["x", "y", "w", "h"]) near(restored[key], panel.bounds()[key]);

  // The old hard minimum could exceed the game after resizing the game itself.
  context.innerWidth = 480;
  context.innerHeight = 320;
  context.dispatchEvent({type: "resize"});
  fits();
  panel.startResize(mouse(480, 320));
  panel.resize(mouse(2000, 2000));
  panel.endResize();
  fits();
  panel.startResize(mouse(480, 320));
  panel.resize(mouse(456, 296));
  panel.endResize();
  assert.ok(panel.bounds().w < 480 / scale, "Small panels must still shrink");
  fits();

  // A DPI/auto-scale change must reclamp an already mounted panel too.
  if (index === outputs.length - 1) {
    context.devicePixelRatio = 3;
    context.dispatchEvent({type: "resize"});
    fits();
  }

  // Exercise Forge's actual map transforms and hover/click/wheel/pan handlers.
  const mapStart = source.indexOf("We=(e,t)=>");
  const mapEnd = source.indexOf(",tt=()=>", mapStart);
  assert.ok(mapStart > 0 && mapEnd > mapStart, "Forge map controller must be available");
  const actualScale = Number(host.style.zoom);
  context.canvas = {getBoundingClientRect: () => ({left: 83, top: 47})};
  for (const rotation of [0, 90, 180, 270]) {
    context.rotation = rotation;
    const map = vm.runInContext(`(() => {
      let h=P(504),g=P(360),_=P(.5),v=P(rotation),d=P(48),
          pe=P({clientWidth:400,clientHeight:300}),fe=P(canvas),
          i=P({width:100,height:100}),y=P(true),w=P(null),de=P(null),
          st=P([]),ce=P(null),he=false,ge=false,_e=0,ve=0,ye=0,be=0;
      const De=(value,min,max)=>Math.max(min,Math.min(max,value)),Oe=()=>{};
      let ${source.slice(mapStart, mapEnd)};
      return {
        hover: Ze, down: Je, move: Ye, up: Xe, wheel: qe,
        selected: () => V(w), hovered: () => V(ce), world: We,
        camera: () => ({x:V(h),y:V(g)}), zoom: () => V(_),
      };
    })()`, context);
    const angle = rotation * Math.PI / 180;
    const cos = Math.cos(angle), sin = Math.sin(angle);
    // Tile (12, 9) relative to a camera centred on tile (10, 7).
    const localX = 200 + (96 * cos - 96 * sin) * .5;
    const localY = 150 + (96 * sin + 96 * cos) * .5;
    const event = mouse(83 + localX * actualScale, 47 + localY * actualScale);
    map.hover(event);
    assert.equal(map.hovered().x, 12);
    assert.equal(map.hovered().y, 9);
    map.down(event); map.up(event);
    assert.equal(map.selected().x, 12);
    assert.equal(map.selected().y, 9);
    map.down(event); map.up(event);
    assert.equal(map.selected(), null, "Clicking the same tile deselects it");

    const anchor = map.world(localX, localY);
    map.wheel(event);
    near(map.world(localX, localY).x, anchor.x);
    near(map.world(localX, localY).y, anchor.y);
    const camera = map.camera();
    map.down(event);
    const moved = mouse(event.clientX + 24, event.clientY + 16);
    map.move(moved); map.up(moved);
    near(map.camera().x, camera.x - (24 * cos + 16 * sin) / actualScale / map.zoom());
    near(map.camera().y, camera.y - (-24 * sin + 16 * cos) / actualScale / map.zoom());
    assert.equal(map.selected(), null, "Panning must not select a tile");
  }
}
