//=============================================================================
// TLInspector.js
// Idea by Sakura · Plugin by Kao_SSS
//=============================================================================
/*:
 * @plugindesc Translation Source Inspector - shows which source file/line every
 * on-screen line of text and image comes from, and jumps to it in VSCode.
 * @author Kao_SSS
 *
 * @help
 * ----------------------------------------------------------------------------
 * TLInspector  (RPGMaker MV / MZ, NW.js)
 * Credits: Idea by Sakura · Plugin by Kao_SSS
 * ----------------------------------------------------------------------------
 * A drop-in proofreading aid for translators. While the game runs, it tracks
 * every message / choice / scrolling-text line and every on-screen image, and
 * maps each one back to its EXACT source file and line number:
 *
 *   - Dialogue / choices / scroll text  -> www/data/MapXXX.json,
 *     CommonEvents.json, Troops.json  (by identity-matching the running event
 *     list, so duplicate strings are never confused).
 *   - Scenario-plugin dialogue          -> scenario/Scenario.json and similar
 *     (plugin scenario engines such as Nore/"Tes" that keep command-lists in one
 *     big JSON dictionary keyed by scene name, loaded into $dataScenario). Both
 *     in-game location and "Locate in Files" cover these.
 *   - Pictures and other images        -> img/... path + the event command
 *     (or JS call stack) that loaded them.
 *   - Plugin / menu UI text (Bitmap.drawText / drawTextEx) -> where the VALUE
 *     itself lives whenever it can be resolved: a TextManager vocab assignment
 *     in a plugin .js, a System.json term, a database name/description, a
 *     notetag <tag:value>, or a plugins.js parameter. Strings built with
 *     String.prototype.format ("%1 remaining") are traced back to their
 *     template. The draw call site is kept as secondary info.
 *
 * Press the hotkey (default F10) to open the inspector overlay. Each row has an
 * "Open in VSCode" button (runs `code -g file:line`) and an **edit** button to
 * change the text and save it back to the source file without leaving the game.
 *
 * Live refresh (NW.js playtest only):
 *   In-game overlay "save to file" reloads that JSON into memory immediately.
 *   VSCode / external saves: we watch data/*.json; once the file mtime is stable
 *   (save finished), reload instantly. The game cannot hook Ctrl+S in VSCode itself.
 *
 * Limitations:
 *   - NW.js desktop playtest only (not browser)
 *   - Text already shown by a running event won't update until re-triggered
 *     (in-game overlay edit still updates the current message box)
 *   - Plugin .js / plugins.js changes still need F5
 *
 * ----------------------------------------------------------------------------
 * Install:  drop this file in www/js/plugins/ and add one line to plugins.js:
 *   { "name": "TLInspector", "status": true, "description": "TL source inspector", "parameters": {} }
 * Place it LAST in the list. Remove that line to fully disable for a release.
 *
 * Config: edit the CFG object a few lines below.
 * ----------------------------------------------------------------------------
 */

(function () {
    'use strict';

    //=========================================================================
    // Config
    //=========================================================================
    var CFG = {
        enabled: true,
        hotkey: 'F9',          // key (event.key) that toggles the overlay
        editorCmd: 'auto',      // 'auto' = auto-detect installed editors (VS Code, Cursor,
                                // VSCodium, Insiders, Windsurf). Or set an absolute path to
                                // force a specific editor exe.
        editor: 'auto',         // which editor click-to-source opens files in:
                                //   'auto'    = VSCode if it's installed, else the built-in
                                //               in-game editor (also the fallback if a
                                //               VSCode launch fails).
                                //   'builtin' = always the built-in in-game editor (view &
                                //               edit the source file right inside the game).
                                //   'vscode'  = always VSCode (uses editorCmd above).
        workspaceFolder: 'auto',// 'auto' = open files inside the game ROOT folder as the
                                // VSCode workspace (so they don't land in whatever window
                                // happened to be open last). Or set an absolute folder.
        editorReuseWindow: true,// pass -r so VSCode reuses its current window
        historySize: 80,        // how many past text lines to keep
        captureUiText: true,    // capture plugin / menu / UI text drawn via Bitmap.drawText
                                // (so e.g. status-window strings from plugins.js are locatable)
        dataDirOverride: null,  // set an absolute path to force the data dir
        uiScale: 'auto'         // overlay scale: 'auto' from game width, or a number (1.5, 2, …)
    };

    if (!CFG.enabled) { return; }

    function resolveUiScale(v) {
        if (v !== 'auto' && v != null && String(v).trim() !== '') {
            var n = parseFloat(v);
            if (!isNaN(n) && n > 0) { return Math.max(0.75, Math.min(3, n)); }
        }
        var base = 816;
        var viewW = window.innerWidth || document.documentElement.clientWidth || base;
        // The overlay lives in WINDOW pixels, so scale from the window size only.
        // Using the game's internal resolution made a 1920px-wide game in a ~1366px
        // window zoom 2.35x, with the 460px panel swallowing >80% of the screen.
        var scale = viewW / base;
        var dpr = window.devicePixelRatio || 1;
        if (dpr > 1.15) { scale *= Math.min(2, 0.75 + dpr * 0.35); }
        // Whatever the math says, keep the panel under ~45% of the window
        // (the >=1 floor below still wins for small windows).
        scale = Math.min(scale, (viewW * 0.45) / 460);
        return Math.max(1, Math.min(2.75, scale));
    }

    function currentUiScale() {
        return resolveUiScale(CFG.uiScale);
    }

    function applyOverlayScale() {
        var s = currentUiScale();
        var z = (s === 1) ? '' : String(s);
        if (ui.root) {
            ui.root.style.zoom = z;
            ui.root.style.transformOrigin = (ui.side === 'left') ? 'top left' : 'top right';
        }
        if (editor.root) {
            editor.root.style.zoom = z;
            editor.root.style.transformOrigin = 'top center';
        }
        if (ui.pickLabel) { ui.pickLabel.style.zoom = z; }
    }

    //=========================================================================
    // Node / environment bootstrap (NW.js exposes require)
    //=========================================================================
    var nodeOk = false, fs = null, path = null, cp = null;
    try {
        if (typeof require === 'function') {
            fs = require('fs');
            path = require('path');
            cp = require('child_process');
            nodeOk = true;
        }
    } catch (e) { nodeOk = false; }

    var ENGINE = (typeof Utils !== 'undefined' && Utils.RPGMAKER_NAME) || 'MV';

    // Resolve the www root (where index.html lives) -> data dir.
    // Primary method = exactly how the engine itself resolves paths
    // (StorageManager.localFileDirectoryPath uses process.mainModule.filename),
    // which is reliable regardless of the page URL scheme NW.js uses.
    function resolveWwwRoot() {
        try {
            if (nodeOk && process.mainModule && process.mainModule.filename) {
                return path.dirname(process.mainModule.filename);
            }
        } catch (e) { /* fall through */ }
        try {
            var href = window.location.href;             // file:///C:/.../www/index.html
            var p = decodeURIComponent(new URL(href).pathname);
            if (/^\/[A-Za-z]:\//.test(p)) { p = p.slice(1); } // strip leading slash on Windows
            return path ? path.dirname(p) : p.replace(/\/[^\/]*$/, '');
        } catch (e2) {
            return nodeOk ? process.cwd() : '';
        }
    }
    var WWW_ROOT = resolveWwwRoot();
    var DATA_DIR = CFG.dataDirOverride || (path ? path.join(WWW_ROOT, 'data') : WWW_ROOT + '/data');

    // The game root = folder holding the .exe. On MV that's the PARENT of www/; on MZ
    // there is no www/, so it IS the resolved root. Used as the VSCode workspace folder
    // so opened files land in the game's own project window, not the last-used one.
    var GAME_ROOT = (function () {
        try {
            if (path && WWW_ROOT && path.basename(WWW_ROOT).toLowerCase() === 'www') {
                return path.dirname(WWW_ROOT);
            }
        } catch (e) { /* ignore */ }
        return WWW_ROOT;
    })();

    function mapFile(mapId) {
        var n = ('000' + mapId).slice(-3);
        return path ? path.join(DATA_DIR, 'Map' + n + '.json') : DATA_DIR + '/Map' + n + '.json';
    }
    function dataFile(name) {
        return path ? path.join(DATA_DIR, name) : DATA_DIR + '/' + name;
    }

    // Scenario systems (e.g. the Nore / "Tes" engine) keep event command-lists OUTSIDE
    // Map/CommonEvents/Troops: one big JSON dictionary under scenario/, keyed by scene
    // name, loaded into a global ($dataScenario) and run via Game_Interpreter.setupChild.
    // Each value is a plain MZ command list, so once we know the file + key it resolves
    // to a line just like any other data file.
    var SCENARIO_DIR = 'scenario';
    var SCENARIO_SETS = [
        { global: '$dataScenario', file: 'Scenario.json' },
        { global: '$dataScenario_en', file: 'Scenario_en.json' }
    ];
    function scenarioPath(fileName) {
        return path ? path.join(WWW_ROOT, SCENARIO_DIR, fileName)
                    : WWW_ROOT + '/' + SCENARIO_DIR + '/' + fileName;
    }
    // Every *.json actually present in the scenario/ folder (empty for normal games).
    function scenarioFiles() {
        var out = [];
        if (!nodeOk) { return out; }
        try {
            fs.readdirSync(scenarioPath('')).forEach(function (f) {
                if (/\.json$/i.test(f)) { out.push(scenarioPath(f)); }
            });
        } catch (e) { /* no scenario/ folder -> normal for most games */ }
        return out;
    }
    // If a scenario file's dictionary is already parsed into a known global, return the
    // global name so callers can reuse it instead of re-parsing a (often huge) file.
    function scenarioGlobalForFile(file) {
        var base = baseName(file).toLowerCase();
        for (var i = 0; i < SCENARIO_SETS.length; i++) {
            if (SCENARIO_SETS[i].file.toLowerCase() === base) { return SCENARIO_SETS[i].global; }
        }
        return null;
    }

    function log() {
        if (window.console) { console.log.apply(console, ['[TLInspector]'].concat([].slice.call(arguments))); }
    }
    log('init', { engine: ENGINE, node: nodeOk, dataDir: DATA_DIR, credits: 'Idea by Sakura · Plugin by Kao_SSS' });

    //=========================================================================
    // File cache + JSON value locator (path -> char offset -> line:col)
    //=========================================================================
    var fileCache = {}; // path -> { mtime, text, lineStarts }

    function readFileCached(file) {
        if (!nodeOk) { return null; }
        try {
            var st = fs.statSync(file);
            var mt = st.mtimeMs;
            var c = fileCache[file];
            if (c && c.mtime === mt) { return c; }
            var text = fs.readFileSync(file, 'utf8');
            var lineStarts = [0];
            for (var i = 0; i < text.length; i++) {
                if (text.charCodeAt(i) === 10) { lineStarts.push(i + 1); }
            }
            c = { mtime: mt, text: text, lineStarts: lineStarts };
            fileCache[file] = c;
            return c;
        } catch (e) { return null; }
    }

    function offsetToLineCol(c, off) {
        var ls = c.lineStarts, lo = 0, hi = ls.length - 1, mid;
        while (lo < hi) {
            mid = (lo + hi + 1) >> 1;
            if (ls[mid] <= off) { lo = mid; } else { hi = mid - 1; }
        }
        return { line: lo + 1, col: off - ls[lo] + 1 };
    }

    // --- minimal structural JSON scanner ------------------------------------
    function skipWs(t, i) {
        while (i < t.length) {
            var ch = t.charCodeAt(i);
            if (ch === 32 || ch === 9 || ch === 10 || ch === 13) { i++; } else { break; }
        }
        return i;
    }
    function scanString(t, i) { // i at opening quote -> returns index after closing quote
        i++; // past "
        while (i < t.length) {
            var ch = t[i];
            if (ch === '\\') { i += 2; continue; }
            if (ch === '"') { return i + 1; }
            i++;
        }
        return i;
    }
    function readKey(t, i) { // i at opening quote -> { end, value }
        var start = i + 1, j = i + 1, out = '';
        while (j < t.length) {
            var ch = t[j];
            if (ch === '\\') { out += t[j + 1]; j += 2; continue; }
            if (ch === '"') { return { end: j + 1, value: out }; }
            out += ch; j++;
        }
        return { end: j, value: out };
    }
    function skipValue(t, i) {
        i = skipWs(t, i);
        var ch = t[i];
        if (ch === '"') { return scanString(t, i); }
        if (ch === '{' || ch === '[') {
            var open = ch, close = ch === '{' ? '}' : ']', depth = 0;
            for (; i < t.length; i++) {
                var c = t[i];
                if (c === '"') { i = scanString(t, i) - 1; continue; }
                if (c === open) { depth++; }
                else if (c === close) { depth--; if (depth === 0) { return i + 1; } }
            }
            return i;
        }
        // number / true / false / null
        while (i < t.length && ',}] \t\r\n'.indexOf(t[i]) === -1) { i++; }
        return i;
    }

    // Walk `path` (array of string keys / number indices) -> start offset of value, or -1.
    function locateOffset(t, pathArr) {
        var i = skipWs(t, 0);
        for (var s = 0; s < pathArr.length; s++) {
            var step = pathArr[s];
            i = skipWs(t, i);
            if (typeof step === 'number') {
                if (t[i] !== '[') { return -1; }
                i = skipWs(t, i + 1);
                if (t[i] === ']') { return -1; }
                for (var k = 0; k < step; k++) {
                    i = skipValue(t, i);
                    i = skipWs(t, i);
                    if (t[i] !== ',') { return -1; }
                    i = skipWs(t, i + 1);
                }
                // i now at target element value start
            } else {
                if (t[i] !== '{') { return -1; }
                i = skipWs(t, i + 1);
                var found = false;
                while (i < t.length && t[i] !== '}') {
                    if (t[i] !== '"') { return -1; }
                    var key = readKey(t, i);
                    i = skipWs(t, key.end);
                    if (t[i] !== ':') { return -1; }
                    i = skipWs(t, i + 1);
                    if (key.value === step) { found = true; break; }
                    i = skipValue(t, i);
                    i = skipWs(t, i);
                    if (t[i] === ',') { i = skipWs(t, i + 1); }
                }
                if (!found) { return -1; }
            }
        }
        return skipWs(t, i);
    }

    // File drifted under a structural path (e.g. the scenario JSON was re-exported while
    // the game held an older parse, shifting command indices): find the exact quoted
    // value instead, preferring the occurrence nearest the path's top-level container so
    // duplicate lines in other scenes/events don't win.
    function reanchorByText(c, pathArr, quoted) {
        var hits = [], p = c.text.indexOf(quoted), CAP = 5000;
        while (p >= 0 && hits.length < CAP) { hits.push(p); p = c.text.indexOf(quoted, p + quoted.length); }
        if (!hits.length) { return null; }
        if (hits.length === 1) { return offsetToLineCol(c, hits[0]); }
        var anchor = locateOffset(c.text, pathArr.slice(0, 1)); // start of the scene / list
        var best = hits[0];
        if (anchor >= 0) {
            var bd = Math.abs(hits[0] - anchor);
            for (var k = 1; k < hits.length; k++) { var dd = Math.abs(hits[k] - anchor); if (dd < bd) { bd = dd; best = hits[k]; } }
        }
        return offsetToLineCol(c, best);
    }

    var lineCache = {}; // file::pathKey::mtime -> {line,col}
    function locateLine(file, pathArr, expectedText) {
        if (!file || !pathArr || !nodeOk) { return null; }
        var c = readFileCached(file);
        if (!c) { return null; }
        var key = file + '::' + pathArr.join('/') + '::' + c.mtime;
        if (lineCache.hasOwnProperty(key)) { return lineCache[key]; }
        var off = locateOffset(c.text, pathArr);
        var quoted = (expectedText != null && expectedText !== '') ? JSON.stringify(String(expectedText)) : null;
        var res;
        if (off >= 0 && (!quoted || c.text.substr(off, quoted.length) === quoted)) {
            res = offsetToLineCol(c, off);            // path still valid (verified against the text)
        } else if (quoted) {
            // Path drifted (or the text isn't where the path points) -> re-anchor by exact
            // text; if that finds nothing, still fall back to the structural offset.
            res = reanchorByText(c, pathArr, quoted) || (off >= 0 ? offsetToLineCol(c, off) : null);
        } else {
            res = off >= 0 ? offsetToLineCol(c, off) : null;
        }
        lineCache[key] = res;
        return res;
    }

    //=========================================================================
    // Provenance: map a running event command-list to its source file + path
    //=========================================================================
    function resolveList(list) {
        try {
            if (typeof $dataMap !== 'undefined' && $dataMap && $dataMap.events &&
                typeof $gameMap !== 'undefined' && $gameMap) {
                var evs = $dataMap.events;
                for (var e = 0; e < evs.length; e++) {
                    var ev = evs[e];
                    if (!ev || !ev.pages) { continue; }
                    for (var p = 0; p < ev.pages.length; p++) {
                        if (ev.pages[p].list === list) {
                            return { file: mapFile($gameMap.mapId()),
                                     prefix: ['events', e, 'pages', p, 'list'],
                                     label: 'Map' + ('000' + $gameMap.mapId()).slice(-3) + ' ev' + e };
                        }
                    }
                }
            }
            if (typeof $dataCommonEvents !== 'undefined' && $dataCommonEvents) {
                for (var c = 0; c < $dataCommonEvents.length; c++) {
                    var ce = $dataCommonEvents[c];
                    if (ce && ce.list === list) {
                        return { file: dataFile('CommonEvents.json'),
                                 prefix: [c, 'list'], label: 'CommonEvent ' + c };
                    }
                }
            }
            if (typeof $gameTroop !== 'undefined' && $gameTroop && $gameTroop._troopId &&
                typeof $dataTroops !== 'undefined' && $dataTroops) {
                var tr = $dataTroops[$gameTroop._troopId];
                if (tr && tr.pages) {
                    for (var tp = 0; tp < tr.pages.length; tp++) {
                        if (tr.pages[tp].list === list) {
                            return { file: dataFile('Troops.json'),
                                     prefix: [$gameTroop._troopId, 'pages', tp, 'list'],
                                     label: 'Troop ' + $gameTroop._troopId };
                        }
                    }
                }
            }
            // Scenario dictionaries: the running list is a value of $dataScenario keyed
            // by scene name (setupChild runs the list by reference, so identity holds).
            for (var si = 0; si < SCENARIO_SETS.length; si++) {
                var sg = SCENARIO_SETS[si], dict = window[sg.global];
                if (!dict || typeof dict !== 'object') { continue; }
                for (var sk in dict) {
                    if (dict.hasOwnProperty(sk) && dict[sk] === list) {
                        return { file: scenarioPath(sg.file), prefix: [sk],
                                 label: sg.file.replace(/\.json$/i, '') + ':' + sk };
                    }
                }
            }
        } catch (e) { log('resolveList error', e); }
        return null;
    }

    function pathToString(arr) {
        var s = '';
        for (var i = 0; i < arr.length; i++) {
            s += typeof arr[i] === 'number' ? '[' + arr[i] + ']' : (i ? '.' : '') + arr[i];
        }
        return s;
    }

    //=========================================================================
    // Record store
    //=========================================================================
    var groupSeq = 0;
    var currentGroup = -1;
    var textRecords = [];   // {kind,text,file,prefix,tail,group,ts,_key}
    var imageTriggers = {}; // picture filename -> {file,prefix,tail,label}
    var BUMP_GUARD_MS = 1000;

    function findByKey(key) {
        for (var i = 0; i < textRecords.length; i++) { if (textRecords[i]._key === key) { return i; } }
        return -1;
    }
    // Text seen again -> move it to the top (newest) so it never feels "undetected"
    // when it was buried in history. Guard against churn from per-frame UI redraws.
    function seenExisting(i, group) {
        var r = textRecords[i], now = Date.now();
        if (now - r.ts < BUMP_GUARD_MS) {
            r.ts = now; if (group != null && group !== -1) { r.group = group; }
            return; // recently seen: keep its position
        }
        textRecords.splice(i, 1);
        r.ts = now; if (group != null && group !== -1) { r.group = group; }
        textRecords.push(r);
        scheduleRefresh();
    }

    function pushText(kind, prov, tail, text, group, srcIndex, srcEventId) {
        if (text == null || text === '') { return; }
        var file = prov ? prov.file : null;
        var key = 't\u0000' + kind + '\u0000' + text + '\u0000' + (file || '') + '\u0000' + (tail ? JSON.stringify(tail) : '');
        var i = findByKey(key);
        if (i >= 0) { seenExisting(i, group); return; }
        textRecords.push({
            kind: kind, text: text, file: file,
            prefix: prov ? prov.prefix : null,
            tail: tail, label: prov ? prov.label : '(unresolved)',
            group: group, ts: Date.now(),
            srcIndex: (srcIndex == null ? null : srcIndex),
            srcEventId: (srcEventId == null ? 0 : srcEventId),
            _key: key
        });
        while (textRecords.length > CFG.historySize) { textRecords.shift(); }
        scheduleRefresh();
    }

    function captureFromList(list, startIdx, textCode, eventId) {
        var prov = resolveList(list);
        var group = ++groupSeq;
        currentGroup = group;
        var i = startIdx + 1;
        while (i < list.length && list[i] && list[i].code === textCode) {
            pushText('text', prov, prov ? prov.prefix.concat([i, 'parameters', 0]) : null,
                list[i].parameters[0], group, i, eventId);
            i++;
        }
        // inline "Show Choices" immediately following the text block
        if (list[i] && list[i].code === 102) {
            captureChoices(list, i, prov, group, eventId);
        }
    }

    function captureChoices(list, idx, prov, group, eventId) {
        if (prov === undefined) { prov = resolveList(list); }
        if (group === undefined) { group = ++groupSeq; currentGroup = group; }
        var choices = list[idx] && list[idx].parameters && list[idx].parameters[0];
        if (!Array.isArray(choices)) { return; }
        for (var n = 0; n < choices.length; n++) {
            pushText('choice', prov,
                prov ? prov.prefix.concat([idx, 'parameters', 0, n]) : null,
                choices[n], group, idx, eventId);
        }
    }

    //=========================================================================
    // Hooks: text
    //=========================================================================
    if (typeof Game_Interpreter !== 'undefined') {
        var GI = Game_Interpreter.prototype;

        var _c101 = GI.command101;
        GI.command101 = function () {
            var list = this._list, start = this._index;
            var r = _c101.apply(this, arguments);
            try { if (this._index !== start) { captureFromList(list, start, 401, this._eventId); } }
            catch (e) { log('c101', e); }
            return r;
        };

        var _c105 = GI.command105;
        GI.command105 = function () {
            var list = this._list, start = this._index;
            var r = _c105.apply(this, arguments);
            try { if (this._index !== start) { captureFromList(list, start, 405, this._eventId); } }
            catch (e) { log('c105', e); }
            return r;
        };

        var _c102 = GI.command102;
        GI.command102 = function () {
            // A STANDALONE "Show Choices" (not following a message — those are consumed
            // inside command101) doesn't advance this._index within the method: MV bumps
            // it later in executeCommand, MZ takes params as an arg. So gating on an index
            // change missed standalone choice menus entirely. Instead capture exactly when
            // the choices get set up: this call, while the message box wasn't already busy.
            var list = this._list, idx = this._index;
            var wasBusy = (typeof $gameMessage !== 'undefined') && $gameMessage &&
                          $gameMessage.isBusy && $gameMessage.isBusy();
            var r = _c102.apply(this, arguments);
            try {
                if (!wasBusy && list && list[idx] && list[idx].code === 102) {
                    captureChoices(list, idx, undefined, undefined, this._eventId);
                }
            } catch (e) { log('c102', e); }
            return r;
        };

        // Show Picture -> remember which command triggered each picture file
        var _c231 = GI.command231;
        GI.command231 = function () {
            try {
                var list = this._list, idx = this._index;
                var name = this._params && this._params[1];
                if (name) {
                    var prov = resolveList(list);
                    imageTriggers['img/pictures/' + name + '.png'] = {
                        file: prov ? prov.file : null,
                        path: prov ? prov.prefix.concat([idx, 'parameters', 1]) : null,
                        label: prov ? prov.label : '(unresolved)'
                    };
                }
            } catch (e) { log('c231', e); }
            return _c231.apply(this, arguments);
        };
    }

    // Clear "live" marker when the message box closes
    if (typeof Game_Message !== 'undefined') {
        var _clear = Game_Message.prototype.clear;
        Game_Message.prototype.clear = function () {
            currentGroup = -1;
            scheduleRefresh();
            return _clear.apply(this, arguments);
        };
    }

    // Capture plugin / menu / UI text. The true chokepoint is Bitmap.drawText:
    // Window_Base.drawText/drawTextEx AND direct `this.contents.drawText(...)` calls
    // inside plugins all funnel through it. We skip while a message box is showing
    // (that text is captured precisely via the interpreter hooks) and de-duplicate by
    // a digit-normalized key so a ticking value ("Money: 12"/"Money: 13") logs once.
    if (CFG.captureUiText && typeof Bitmap !== 'undefined' && Bitmap.prototype.drawText) {
        // Direct draws (Window_Base.drawText, plugin `this.contents.drawText(...)`).
        // drawTextEx renders one character per call here, so single chars are dropped.
        var _bmDrawText = Bitmap.prototype.drawText;
        Bitmap.prototype.drawText = function (text) {
            try { maybeCaptureUiText(text); } catch (e) { /* ignore */ }
            return _bmDrawText.apply(this, arguments);
        };
    }
    if (CFG.captureUiText && typeof Window_Base !== 'undefined' && Window_Base.prototype.drawTextEx) {
        // Escape-processed text (item descriptions, help text, names) arrives here as a
        // whole string before being drawn character-by-character.
        var _drawTextEx = Window_Base.prototype.drawTextEx;
        Window_Base.prototype.drawTextEx = function (text) {
            try { maybeCaptureUiText(text); } catch (e) { /* ignore */ }
            return _drawTextEx.apply(this, arguments);
        };
    }
    function maybeCaptureUiText(text) {
        if (typeof text !== 'string') { return; }
        if (text.replace(/\s/g, '').length < 2) { return; }       // drop single chars (per-char draws)
        if (!/[^\s\d.,:%/+\-()]/.test(text)) { return; }          // require a real letter
        if (typeof $gameMessage !== 'undefined' && $gameMessage && $gameMessage.isBusy && $gameMessage.isBusy()) { return; }
        var key = 'ui ' + text.replace(/\d+/g, '#');              // digit-normalized: "Money: 12/13" -> one entry
        var i = findByKey(key);
        if (i >= 0) { seenExisting(i, -1); return; }
        var site = firstUserFrame(new Error().stack);
        var rec = { kind: 'ui', text: text, file: site.file, prefix: null,
            tail: null, label: site.label, uiLine: site.line, uiCol: null,
            group: -1, ts: Date.now(), _key: key };
        // Prefer the VALUE's own home (vocab assignment / term / notetag / parameter)
        // over the draw call site; keep the site as secondary info.
        try {
            var src = resolveUiSource(text);
            if (src) {
                rec.srcKind = src.kind; rec.label = src.label; rec.expText = src.expText;
                if (src.file) {
                    rec.file = src.file; rec.uiLine = src.line || null; rec.uiCol = src.col || null;
                    rec.tail = src.tail || null;
                    rec.siteFile = site.file; rec.siteLine = site.line; rec.siteLabel = site.label;
                }
            }
        } catch (e) { log('uiSource', e); }
        textRecords.push(rec);
        while (textRecords.length > CFG.historySize) { textRecords.shift(); }
        scheduleRefresh();
    }

    function firstUserFrame(stack) {
        var lines = (stack || '').split('\n');
        for (var i = 1; i < lines.length; i++) {
            var m = lines[i].match(/(js\/plugins\/[^):]+|js\/[^):]+):(\d+):(\d+)/);
            if (m && m[1].indexOf('TLInspector') === -1) {
                var f = m[1];
                return { file: path ? path.join(WWW_ROOT, f) : WWW_ROOT + '/' + f,
                         line: parseInt(m[2], 10), label: f + ':' + m[2] };
            }
        }
        return { file: null, line: null, label: '(unknown)' };
    }

    //=========================================================================
    // UI text provenance: map a drawn string back to the VALUE's own home
    // (TextManager vocab assignment, System.json term, database field, notetag
    // meta value, or plugins.js parameter) instead of just the draw call site.
    // Index is built lazily from live game state; invalidated on F9 reload.
    //=========================================================================
    var uiValueIndex = null, uiIndexBuiltAt = 0;

    function uiIndexAdd(map, value, cand) {
        if (typeof value !== 'string') { return; }
        if (value.replace(/\s/g, '').length < 2) { return; } // same floor as capture
        (map[value] || (map[value] = [])).push(cand);
    }

    function buildUiValueIndex() {
        // null prototype: game text can legitimately be 'constructor'/'toString'…
        var map = Object.create(null);
        // TextManager vocab: plugin-assigned own DATA properties. (The engine's own
        // terms are accessor properties reading $dataSystem.terms -> indexed below.)
        try {
            if (typeof TextManager !== 'undefined') {
                Object.getOwnPropertyNames(TextManager).forEach(function (p) {
                    var d = Object.getOwnPropertyDescriptor(TextManager, p);
                    if (d && !d.get && typeof d.value === 'string') {
                        uiIndexAdd(map, d.value, { t: 'tm', prop: p });
                    }
                });
            }
        } catch (e) { log('uiIndex tm', e); }
        // System.json: terms, type-name lists, and a few top-level strings.
        try {
            if (typeof $dataSystem !== 'undefined' && $dataSystem) {
                var sysFile = dataFile('System.json');
                var terms = $dataSystem.terms || {};
                ['basic', 'commands', 'params'].forEach(function (g) {
                    (terms[g] || []).forEach(function (v, i) {
                        uiIndexAdd(map, v, { t: 'json', file: sysFile, path: ['terms', g, i],
                                             label: 'System terms.' + g + '[' + i + ']' });
                    });
                });
                var msgs = terms.messages || {};
                Object.keys(msgs).forEach(function (k) {
                    uiIndexAdd(map, msgs[k], { t: 'json', file: sysFile, path: ['terms', 'messages', k],
                                               label: 'System terms.messages.' + k });
                });
                ['elements', 'skillTypes', 'weaponTypes', 'armorTypes', 'equipTypes'].forEach(function (g) {
                    ($dataSystem[g] || []).forEach(function (v, i) {
                        uiIndexAdd(map, v, { t: 'json', file: sysFile, path: [g, i],
                                             label: 'System ' + g + '[' + i + ']' });
                    });
                });
                uiIndexAdd(map, $dataSystem.gameTitle, { t: 'json', file: sysFile, path: ['gameTitle'], label: 'System gameTitle' });
                uiIndexAdd(map, $dataSystem.currencyUnit, { t: 'json', file: sysFile, path: ['currencyUnit'], label: 'System currencyUnit' });
            }
        } catch (e) { log('uiIndex system', e); }
        // Database display fields + notetag meta values. A meta value resolves to the
        // object's "note" line; locateMetaValue narrows to the value inside the tag.
        [
            ['$dataActors', 'Actors.json', ['name', 'nickname', 'profile']],
            ['$dataClasses', 'Classes.json', ['name']],
            ['$dataSkills', 'Skills.json', ['name', 'description', 'message1', 'message2']],
            ['$dataItems', 'Items.json', ['name', 'description']],
            ['$dataWeapons', 'Weapons.json', ['name', 'description']],
            ['$dataArmors', 'Armors.json', ['name', 'description']],
            ['$dataEnemies', 'Enemies.json', ['name']],
            ['$dataStates', 'States.json', ['name', 'message1', 'message2', 'message3', 'message4']]
        ].forEach(function (spec) {
            try {
                var arr = window[spec[0]];
                if (!Array.isArray(arr)) { return; }
                var file = dataFile(spec[1]), short = spec[1].replace(/\.json$/i, '');
                for (var id = 1; id < arr.length; id++) {
                    var o = arr[id];
                    if (!o) { continue; }
                    spec[2].forEach(function (f) {
                        uiIndexAdd(map, o[f], { t: 'json', file: file, path: [id, f],
                                                label: short + '[' + id + '].' + f });
                    });
                    if (o.meta) {
                        Object.keys(o.meta).forEach(function (mk) {
                            if (typeof o.meta[mk] === 'string') {
                                uiIndexAdd(map, o.meta[mk], { t: 'meta', file: file, path: [id, 'note'],
                                                              label: short + '[' + id + '] note <' + mk + ':…>' });
                            }
                        });
                    }
                }
            } catch (e) { log('uiIndex ' + spec[0], e); }
        });
        // Plugin parameters (plugins.js).
        try {
            if (window.$plugins) {
                window.$plugins.forEach(function (pl) {
                    if (!pl || pl.status === false || !pl.parameters) { return; }
                    Object.keys(pl.parameters).forEach(function (pk) {
                        uiIndexAdd(map, pl.parameters[pk], { t: 'param', plugin: pl.name, param: pk });
                    });
                });
            }
        } catch (e) { log('uiIndex params', e); }
        return map;
    }

    function uiValueCandidates(text) {
        if (!uiValueIndex) { uiValueIndex = buildUiValueIndex(); uiIndexBuiltAt = Date.now(); }
        if (!jsLitIndex) { jsLitIndex = buildJsLitIndex(); }
        var c = uiValueIndex[text] || null;
        var lits = jsLitIndex[text] || null;
        if (!c && !lits && Date.now() - uiIndexBuiltAt > 5000) {
            // Vocab tables can be rewritten at runtime (language toggles): on a miss,
            // rebuild against current state, at most once every 5s.
            uiValueIndex = buildUiValueIndex(); uiIndexBuiltAt = Date.now();
            c = uiValueIndex[text] || null;
        }
        if (lits) { c = (c || []).concat(lits); }
        return c;
    }

    // Parse a JS string literal starting at t[i] (the quote) -> {value, end} or null.
    function parseJsString(t, i) {
        var q = t[i];
        if (q !== '"' && q !== "'" && q !== '`') { return null; }
        var out = '', j = i + 1;
        while (j < t.length) {
            var ch = t[j];
            if (ch === '\\') {
                var n = t[j + 1];
                if (n === 'n') { out += '\n'; }
                else if (n === 't') { out += '\t'; }
                else if (n === 'r') { out += '\r'; }
                else if (n === 'u') { out += String.fromCharCode(parseInt(t.substr(j + 2, 4), 16) || 0); j += 4; }
                else if (n === 'x') { out += String.fromCharCode(parseInt(t.substr(j + 2, 2), 16) || 0); j += 2; }
                else { out += n; }
                j += 2; continue;
            }
            if (ch === q) { return { value: out, end: j + 1 }; }
            if (ch === '\n' && q !== '`') { return null; } // unterminated
            out += ch; j++;
        }
        return null;
    }

    // Plugin .js files in LOAD order (later plugins overwrite earlier assignments, so
    // "last literal match" below = the assignment that actually won at runtime).
    function pluginFilesInLoadOrder() {
        var out = [];
        if (!nodeOk) { return out; }
        var pdir = path.join(WWW_ROOT, 'js', 'plugins');
        try {
            if (window.$plugins) {
                window.$plugins.forEach(function (pl) {
                    if (pl && pl.status !== false && pl.name && pl.name !== 'TLInspector') {
                        out.push(path.join(pdir, pl.name + '.js'));
                    }
                });
            }
        } catch (e) { /* ignore */ }
        if (!out.length) {
            try {
                fs.readdirSync(pdir).forEach(function (f) {
                    if (/\.js$/.test(f) && f !== 'TLInspector.js') { out.push(path.join(pdir, f)); }
                });
            } catch (e) { /* ignore */ }
        }
        return out;
    }

    // Find the plugin-file assignment `TextManager.<prop> = '<literal>'` whose literal
    // equals the property's CURRENT runtime value — this is what distinguishes an
    // English vocab file from the Japanese one when both assign the same property.
    // Falls back to the last assignment site in load order (value built at runtime).
    var tmAssignCache = {}; // prop \0 value -> {file,line,col,exact} | null
    function locateTextManagerAssignment(prop, value) {
        var key = prop + '\u0000' + value;
        if (tmAssignCache.hasOwnProperty(key)) { return tmAssignCache[key]; }
        var safe = String(prop).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        var re = new RegExp('TextManager\\s*(?:\\.\\s*' + safe +
                            '|\\[\\s*[\'"]' + safe + '[\'"]\\s*\\])\\s*=(?![=>])', 'g');
        var literalHit = null, lastSite = null;
        pluginFilesInLoadOrder().forEach(function (file) {
            var c = readFileCached(file);
            if (!c) { return; }
            re.lastIndex = 0;
            var m;
            while ((m = re.exec(c.text))) {
                if (inComment(c, m.index)) { continue; }
                var vi = skipWs(c.text, m.index + m[0].length);
                var site = { file: file, off: vi };
                lastSite = site;
                var lit = parseJsString(c.text, vi);
                if (lit && lit.value === value) { literalHit = site; }
            }
        });
        var hit = literalHit || lastSite, res = null;
        if (hit) {
            var lc = offsetToLineCol(readFileCached(hit.file), hit.off);
            res = { file: hit.file, line: lc.line, col: lc.col, off: hit.off, exact: !!literalHit };
        }
        tmAssignCache[key] = res;
        return res;
    }

    // Locate a plugin parameter value inside plugins.js (bounded to that plugin's entry).
    function locatePluginParam(plugin, param, value) {
        if (!nodeOk) { return null; }
        var file = path.join(WWW_ROOT, 'js', 'plugins.js');
        var c = readFileCached(file);
        if (!c) { return null; }
        var anchor = c.text.indexOf('"name":"' + plugin + '"');
        if (anchor < 0) {
            anchor = c.text.search(new RegExp('"name"\\s*:\\s*"' +
                String(plugin).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '"'));
        }
        if (anchor < 0) { return null; }
        var next = c.text.indexOf('"name":', anchor + 7); // start of the NEXT plugin entry
        var p = c.text.indexOf(JSON.stringify(String(value)), anchor);
        var lc = offsetToLineCol(c, (p >= 0 && (next < 0 || p < next)) ? p : anchor);
        return { file: file, line: lc.line, col: lc.col };
    }

    // Line/col of a notetag VALUE inside an object's "note" string. The JSON path
    // points at the whole note; narrow to the meta value's escaped text within it.
    function locateMetaValue(file, pathArr, value) {
        if (!file || !pathArr || !nodeOk) { return null; }
        var c = readFileCached(file);
        if (!c) { return null; }
        var key = file + '::meta:' + pathArr.join('/') + '::' + value + '::' + c.mtime;
        if (lineCache.hasOwnProperty(key)) { return lineCache[key]; }
        var res = null;
        var off = locateOffset(c.text, pathArr);
        if (off >= 0 && c.text[off] === '"') {
            var end = scanString(c.text, off);
            var esc = JSON.stringify(String(value)).slice(1, -1);
            var p = esc ? c.text.indexOf(esc, off) : -1;
            res = offsetToLineCol(c, (p >= 0 && p < end) ? p : off);
        } else if (off >= 0) {
            res = offsetToLineCol(c, off);
        }
        lineCache[key] = res;
        return res;
    }

    // String literals hardcoded in plugin .js code — e.g. a medal/skill table defined
    // as arrays right in a plugin ("Great Sage" in Nore_MedalParam.js). Lowest-priority
    // source: a drawn string can coincidentally equal an unrelated code literal, so
    // vocab/data/notetag/param sources always win over this. Built once, lazily
    // (plugin files can't change without F5); dropped on F9 in case one was edited
    // through the built-in editor.
    var jsLitIndex = null;
    var JSLIT_MAX_PER_VALUE = 8;
    function buildJsLitIndex() {
        // null prototype: plugin code is full of literals like 'constructor'/'toString'
        var map = Object.create(null);
        pluginFilesInLoadOrder().forEach(function (file) {
            var c = readFileCached(file);
            if (!c) { return; }
            var t = c.text, i = 0, n = t.length;
            while (i < n) {
                var ch = t[i], nx = t[i + 1];
                if (ch === '/' && nx === '/') { var e1 = t.indexOf('\n', i); i = e1 < 0 ? n : e1 + 1; continue; }
                if (ch === '/' && nx === '*') { var e2 = t.indexOf('*/', i + 2); i = e2 < 0 ? n : e2 + 2; continue; }
                if (ch === '"' || ch === "'" || ch === '`') {
                    var lit = parseJsString(t, i);
                    if (lit) {
                        var v = lit.value;
                        // same floors as maybeCaptureUiText: >=2 non-space chars + a real letter
                        if (v.replace(/\s/g, '').length >= 2 && /[^\s\d.,:%/+\-()]/.test(v)) {
                            var arr = map[v] || (map[v] = []);
                            if (arr.length < JSLIT_MAX_PER_VALUE) { arr.push({ t: 'jslit', file: file, off: i }); }
                        }
                        i = lit.end; continue;
                    }
                }
                i++;
            }
        });
        return map;
    }

    // Recent String.prototype.format calls (template -> output), so a drawn string
    // like "2 turn(s) remaining" resolves to its '%1 turn(s) remaining' template even
    // though the drawn form never exists in any file.
    var FORMAT_LOG = [], FORMAT_LOG_MAX = 40;
    if (CFG.captureUiText && String.prototype.format) {
        var _strFormat = String.prototype.format;
        String.prototype.format = function () {
            var out = _strFormat.apply(this, arguments);
            try {
                if (arguments.length && typeof out === 'string' && out.length >= 2) {
                    var tpl = String(this);
                    if (tpl !== out) {
                        var last = FORMAT_LOG[FORMAT_LOG.length - 1];
                        if (!last || last.out !== out || last.tpl !== tpl) {
                            FORMAT_LOG.push({ tpl: tpl, out: out });
                            if (FORMAT_LOG.length > FORMAT_LOG_MAX) { FORMAT_LOG.shift(); }
                        }
                    }
                }
            } catch (e) { /* ignore */ }
            return out;
        };
    }

    // Drawn string -> best value-source descriptor, or null if unknown.
    function resolveUiSource(text) {
        var val = text, via = '', cands = uiValueCandidates(text);
        if (!cands) {
            for (var i = FORMAT_LOG.length - 1; i >= 0; i--) {
                if (FORMAT_LOG[i].out === text) {
                    cands = uiValueCandidates(FORMAT_LOG[i].tpl);
                    if (cands) { val = FORMAT_LOG[i].tpl; via = ' ← format()'; }
                    break;
                }
            }
        }
        if (!cands || !cands.length) { return null; }
        var ORDER = { tm: 0, json: 1, meta: 2, param: 3, jslit: 4 };
        var best = cands[0];
        for (var k = 1; k < cands.length; k++) {
            if (ORDER[cands[k].t] < ORDER[best.t]) { best = cands[k]; }
        }
        var loc = null;
        if (best.t === 'tm') {
            loc = locateTextManagerAssignment(best.prop, val);
            // The assignment's own RHS literal is also in the jslit index — that's the
            // SAME location, not an "other match": drop it before counting extras.
            if (loc) {
                cands = cands.filter(function (x) {
                    return !(x.t === 'jslit' && x.file === loc.file && x.off === loc.off);
                });
            }
        }
        var extra = cands.length - 1;
        var suffix = via + (extra > 0 ? ' (+' + extra + ' other match' + (extra > 1 ? 'es' : '') + ')' : '');
        if (best.t === 'tm') {
            if (loc) {
                return { kind: 'tm', file: loc.file, line: loc.line, col: loc.col,
                         label: 'TextManager.' + best.prop + suffix, expText: val };
            }
            return { kind: 'tm', file: null, expText: val,
                     label: 'TextManager.' + best.prop + ' (assignment not in plugin files)' + suffix };
        }
        if (best.t === 'param') {
            var pp = locatePluginParam(best.plugin, best.param, val);
            return { kind: 'param', file: pp && pp.file, line: pp && pp.line, col: pp && pp.col,
                     label: 'plugins.js ' + best.plugin + ' → ' + best.param + suffix, expText: val };
        }
        if (best.t === 'jslit') {
            var cf = readFileCached(best.file);
            if (!cf) { return null; }
            var ll = offsetToLineCol(cf, best.off);
            return { kind: 'jslit', file: best.file, line: ll.line, col: ll.col,
                     label: baseName(best.file) + ' string literal' + suffix, expText: val };
        }
        return { kind: best.t, file: best.file, tail: best.path, label: best.label + suffix, expText: val };
    }

    //=========================================================================
    // Hooks: images (load log with call-site)
    //=========================================================================
    var imageLog = []; // {url, label, ts, bitmap}
    if (typeof ImageManager !== 'undefined') {
        var _loadBitmap = ImageManager.loadBitmap;
        ImageManager.loadBitmap = function (folder, filename) {
            var bm = _loadBitmap.apply(this, arguments);
            try {
                if (filename) {
                    var url = folder + filename + '.png';
                    var last = imageLog[imageLog.length - 1];
                    if (!last || last.url !== url) {
                        var site = firstUserFrame(new Error().stack);
                        imageLog.push({ url: url, label: site.label, ts: Date.now(), bitmap: bm });
                        while (imageLog.length > CFG.historySize) { imageLog.shift(); }
                    } else if (last && !last.bitmap) { last.bitmap = bm; }
                }
            } catch (e) { /* ignore */ }
            return bm;
        };
    }

    //=========================================================================
    // Live on-screen image collection (walk the sprite tree)
    //=========================================================================
    function collectOnScreenImages() {
        var out = [], seen = {};
        var scene = (typeof SceneManager !== 'undefined') && SceneManager._scene;
        if (!scene) { return out; }
        var canvas = getGameCanvas();
        var rect = canvas ? canvas.getBoundingClientRect() : null;
        var scale = rect && typeof Graphics !== 'undefined' && Graphics.width ?
            rect.width / Graphics.width : 1;

        (function walk(obj) {
            if (!obj) { return; }
            if (obj.visible === false) { return; }
            var bmp = obj.bitmap;
            if (bmp && bmp._url) {
                var vis = ('worldVisible' in obj) ? obj.worldVisible : true;
                if (vis) {
                    var b = null;
                    try { b = obj.getBounds && obj.getBounds(); } catch (e) { b = null; }
                    if (b && b.width > 0 && b.height > 0) {
                        if (!seen[bmp._url]) { seen[bmp._url] = true; }
                        out.push({
                            url: decodeUrl(bmp._url),
                            bitmap: bmp,
                            screen: rect ? {
                                x: rect.left + b.x * scale, y: rect.top + b.y * scale,
                                w: b.width * scale, h: b.height * scale
                            } : null
                        });
                    }
                }
            }
            var kids = obj.children;
            if (kids) { for (var i = 0; i < kids.length; i++) { walk(kids[i]); } }
        })(scene);
        return out;
    }

    function getGameCanvas() {
        if (typeof Graphics !== 'undefined') {
            if (Graphics._canvas) { return Graphics._canvas; }
            if (Graphics._renderer && Graphics._renderer.view) { return Graphics._renderer.view; }
        }
        return document.querySelector('canvas');
    }

    // Bitmap URLs are percent-encoded (ImageManager uses encodeURIComponent on the
    // filename), e.g. "img/pictures/%E3%83%90%E3%82%B9.png" for "バス". Decode so the
    // path matches the real file on disk.
    function decodeUrl(u) {
        if (!u) { return u; }
        try { return decodeURIComponent(u); } catch (e) { return u; }
    }

    function urlToAbsPath(url) {
        if (!url) { return null; }
        var rel = decodeUrl(url).replace(/^\.?\//, '');
        return path ? path.join(WWW_ROOT, rel) : WWW_ROOT + '/' + rel;
    }

    //=========================================================================
    // External actions (VSCode / file explorer)
    //=========================================================================
    // Auto-locate installed editors so the user never has to touch the system PATH.
    // We support the whole VS Code family (VS Code, Insiders, Cursor, VSCodium,
    // Windsurf): they share an identical CLI ("<folder> -g file:line:col"), so the
    // same launch path works for all of them. The user picks which one to use from a
    // dropdown in the panel (see the editor <select>); the choice is remembered.
    //
    // Each candidate is [id, display name, absolute exe path]. The first existing
    // path for a given id wins; ids are de-duplicated so each editor lists once.
    function editorCandidates() {
        var defs = [];
        if (!nodeOk) { return defs; }
        var env = process.env, plat = process.platform;
        function J() { return path.join.apply(path, arguments); }
        if (plat === 'win32') {
            [env.LOCALAPPDATA, env.ProgramFiles, env['ProgramFiles(x86)']].forEach(function (b) {
                if (!b) { return; }
                defs.push(['vscode', 'VS Code', J(b, 'Programs', 'Microsoft VS Code', 'Code.exe')]);
                defs.push(['vscode', 'VS Code', J(b, 'Microsoft VS Code', 'Code.exe')]);
                defs.push(['insiders', 'VS Code Insiders', J(b, 'Programs', 'Microsoft VS Code Insiders', 'Code - Insiders.exe')]);
                defs.push(['cursor', 'Cursor', J(b, 'Programs', 'cursor', 'Cursor.exe')]);
                defs.push(['cursor', 'Cursor', J(b, 'cursor', 'Cursor.exe')]);
                defs.push(['vscodium', 'VSCodium', J(b, 'Programs', 'VSCodium', 'VSCodium.exe')]);
                defs.push(['vscodium', 'VSCodium', J(b, 'VSCodium', 'VSCodium.exe')]);
                defs.push(['windsurf', 'Windsurf', J(b, 'Programs', 'Windsurf', 'Windsurf.exe')]);
            });
        } else if (plat === 'darwin') {
            defs.push(['vscode', 'VS Code', '/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code']);
            defs.push(['insiders', 'VS Code Insiders', '/Applications/Visual Studio Code - Insiders.app/Contents/Resources/app/bin/code']);
            defs.push(['cursor', 'Cursor', '/Applications/Cursor.app/Contents/Resources/app/bin/cursor']);
            defs.push(['vscodium', 'VSCodium', '/Applications/VSCodium.app/Contents/Resources/app/bin/codium']);
            defs.push(['windsurf', 'Windsurf', '/Applications/Windsurf.app/Contents/Resources/app/bin/windsurf']);
        } else {
            defs.push(['vscode', 'VS Code', '/usr/bin/code']);
            defs.push(['vscode', 'VS Code', '/usr/share/code/bin/code']);
            defs.push(['vscode', 'VS Code', '/snap/bin/code']);
            defs.push(['cursor', 'Cursor', '/usr/bin/cursor']);
            defs.push(['vscodium', 'VSCodium', '/usr/bin/codium']);
            defs.push(['windsurf', 'Windsurf', '/usr/bin/windsurf']);
        }
        return defs;
    }

    var _editorList = null;
    function detectEditors() {
        if (_editorList) { return _editorList; }
        _editorList = [];
        var seen = {};
        // An explicit CFG.editorCmd path always wins and heads the list.
        if (CFG.editorCmd && CFG.editorCmd !== 'auto') {
            _editorList.push({ id: 'custom', name: 'Custom (config)', cmd: CFG.editorCmd });
            seen.custom = true;
        }
        editorCandidates().forEach(function (d) {
            var id = d[0];
            if (seen[id]) { return; }
            try {
                if (fs.existsSync(d[2])) {
                    seen[id] = true;
                    _editorList.push({ id: id, name: d[1], cmd: d[2] });
                    log('editor found', d[1], d[2]);
                }
            } catch (e) { /* ignore */ }
        });
        // Always offer a PATH-based VS Code fallback so there's at least one option even
        // when nothing was found on disk (the user may have `code` on PATH).
        if (!seen.vscode && !seen.custom) {
            _editorList.push({ id: 'vscode', name: 'VS Code (PATH)', cmd: 'code' });
        }
        return _editorList;
    }

    // The editor currently selected in the dropdown (or the first available one).
    function currentEditor() {
        var list = detectEditors();
        if (!list.length) { return { id: 'vscode', name: 'VS Code (PATH)', cmd: 'code' }; }
        for (var i = 0; i < list.length; i++) {
            if (list[i].id === ui.editorId) { return list[i]; }
        }
        return list[0];
    }

    // True when at least one real external editor exe was located on disk (not just the
    // bare 'code' PATH fallback). 'auto' mode uses this to pick external vs built-in.
    function vscodeAvailable() {
        var list = detectEditors();
        for (var i = 0; i < list.length; i++) {
            if (list[i].cmd !== 'code') { return true; }
        }
        return false;
    }

    // The header checkbox (ui.useBuiltin) is the live switch; CFG.editor is just the
    // initial default it's seeded from at startup.
    function shouldUseBuiltin() {
        if (ui && ui.useBuiltin != null) { return ui.useBuiltin; }
        return CFG.editor === 'builtin' || (CFG.editor !== 'vscode' && !vscodeAvailable());
    }

    function openInEditor(file, line, col) {
        if (!nodeOk || !file) { toast('No file resolved for this entry'); return; }
        // Route to the built-in in-game editor when the header switch (or config) selects
        // it, so users without VSCode - or who prefer editing in-game - still get it.
        if (shouldUseBuiltin()) {
            openBuiltInEditor(file, line, col);
            return;
        }
        var loc = file + (line ? ':' + line + (col ? ':' + col : '') : '');
        var ed = currentEditor();
        var cmd = ed.cmd;
        // Pass the game folder so VSCode opens (or reuses) THAT workspace and reveals the
        // file in it, instead of dropping the file into whatever window was last focused.
        // Passing a folder makes VSCode route to the matching window itself, so we drop the
        // -r "reuse last window" flag (which is what caused the wrong-workspace behavior).
        var ws = (CFG.workspaceFolder && CFG.workspaceFolder !== 'auto') ? CFG.workspaceFolder : GAME_ROOT;
        var done = function (err) {
            if (err) {
                log('editor', err);
                toast(ed.name + ' launch failed - opening the built-in editor');
                openBuiltInEditor(file, line, col);
            }
        };
        try {
            if (cmd === 'code') {
                // PATH fallback (code.cmd) needs a shell. The command line does NOT
                // start with a quote (program name has no spaces) and each path IS
                // quoted, so spaces in the paths are preserved instead of being split
                // into separate arguments.
                var folder = ws ? '"' + ws + '" ' : '';
                cp.exec(cmd + ' ' + folder + '-g "' + loc + '"', { cwd: WWW_ROOT }, done);
            } else {
                // Resolved absolute editor exe: run with no shell. Node quotes each
                // argument, so a path with spaces stays a single argument.
                var args = [];
                if (ws) { args.push(ws); }
                args.push('-g', loc);
                cp.execFile(cmd, args, { cwd: WWW_ROOT }, done);
            }
        } catch (e) { toast('Editor launch failed'); log(e); }
    }

    function revealInExplorer(absPath) {
        if (!nodeOk || !absPath) { return; }
        try {
            if (process.platform === 'win32') {
                cp.execFile('explorer.exe', ['/select,', absPath]);
            } else if (process.platform === 'darwin') {
                cp.execFile('open', ['-R', absPath]);
            } else {
                cp.execFile('xdg-open', [path.dirname(absPath)]);
            }
        } catch (e) { log('reveal', e); }
    }

    //=========================================================================
    // Image decryption (RPGMaker MV .rpgmvp / MZ .png_) + encryption-aware reveal
    //=========================================================================
    var ENC = {
        on: function () {
            try { return typeof $dataSystem !== 'undefined' && $dataSystem && !!$dataSystem.hasEncryptedImages; }
            catch (e) { return false; }
        },
        keyBytes: function () {
            try { return ($dataSystem.encryptionKey || '').match(/.{2}/g) || []; }
            catch (e) { return []; }
        },
        // Candidate on-disk encrypted siblings for a plain .png path. MV renames the
        // extension (image.png -> image.rpgmvp); MZ keeps the name and appends "_"
        // (image.png -> image.png_). The XOR algorithm is identical for both.
        encPaths: function (absPng) {
            return [absPng.replace(/\.png$/i, '.rpgmvp'),   // MV
                    absPng + '_'];                          // MZ  (image.png -> image.png_)
        }
    };

    // Returns {path, created} for a real .png on disk, decrypting the encrypted
    // sibling (.rpgmvp on MV, .png_ on MZ) if the plain .png does not exist.
    // Replicates the engine Decrypter (16-byte fake header + XOR of the next 16
    // bytes with the encryption key).
    function decryptToSibling(absPng) {
        try {
            if (fs.existsSync(absPng)) { return { path: absPng, created: false }; }
            var cands = ENC.encPaths(absPng), enc = null;
            for (var c = 0; c < cands.length; c++) {
                if (fs.existsSync(cands[c])) { enc = cands[c]; break; }
            }
            if (!enc) { return null; }
            var buf = fs.readFileSync(enc);
            var body = buf.slice(16);                 // drop the fake PNG header
            var key = ENC.keyBytes();
            for (var i = 0; i < 16 && i < key.length; i++) {
                body[i] = body[i] ^ parseInt(key[i], 16);
            }
            fs.writeFileSync(absPng, body);
            return { path: absPng, created: true };
        } catch (e) { log('decrypt', e); return null; }
    }

    function revealImage(absPng) {
        if (!nodeOk || !absPng) { return; }
        var r = decryptToSibling(absPng);
        if (!r) { toast('Not found on disk (.png / .rpgmvp / .png_)'); return; }
        toast(r.created ? 'Decrypted -> revealing .png' : 'Revealing');
        revealInExplorer(r.path);
    }

    //=========================================================================
    // Thumbnails (from the already-decoded in-memory Bitmap, so encrypted
    // images preview fine without touching disk) + a shared image-row builder.
    //=========================================================================
    var thumbCache = {}; // url -> dataURL
    function bitmapThumb(bmp, url) {
        if (url && thumbCache[url]) { return thumbCache[url]; }
        try {
            if (!bmp || (bmp.isReady && !bmp.isReady())) { return null; }
            var src = (bmp._image && bmp._image.width) ? bmp._image
                    : (bmp.canvas || bmp._canvas || bmp.__canvas);
            var sw = bmp.width, sh = bmp.height;
            if (!src || !sw || !sh) { return null; }
            var max = 60, scale = Math.min(max / sw, max / sh, 1);
            var w = Math.max(1, Math.round(sw * scale)), h = Math.max(1, Math.round(sh * scale));
            var c = document.createElement('canvas');
            c.width = w; c.height = h;
            c.getContext('2d').drawImage(src, 0, 0, sw, sh, 0, 0, w, h);
            var data = c.toDataURL('image/png');
            if (url) { thumbCache[url] = data; }
            return data;
        } catch (e) { return null; }
    }

    function buildImgRow(url, bitmap, opts) {
        opts = opts || {};
        var abs = urlToAbsPath(url);
        var row = document.createElement('div');
        row.className = 'tl-row';
        var thumb = bitmapThumb(bitmap, url);
        row.innerHTML =
            '<div class="tl-imgwrap">' +
                (thumb ? '<img class="tl-thumb" src="' + thumb + '">'
                       : '<div class="tl-thumb tl-noimg">?</div>') +
                '<div class="tl-imginfo">' +
                    '<div class="tl-txt" style="color:#cfe">' + esc(url) + '</div>' +
                    '<div class="tl-meta">' +
                        '<span class="tl-mini" data-act="reveal">Reveal' + (ENC.on() ? ' (decrypt)' : '') + '</span>' +
                        (opts.trigger ? '<span class="tl-loc" data-act="trig">trigger: ' + esc(opts.trigger.label) + '</span>' : '') +
                        (opts.fromLabel ? '<span class="tl-loc" style="cursor:default">from ' + esc(opts.fromLabel) + '</span>' : '') +
                    '</div>' +
                '</div>' +
            '</div>';
        row.querySelector('[data-act="reveal"]').addEventListener('click', function () { revealImage(abs); });
        if (opts.screen) {
            row.addEventListener('mouseenter', function () { showHighlight(opts.screen); });
            row.addEventListener('mouseleave', function () { hideHighlight(); });
        }
        if (opts.trigger && opts.trigger.file) {
            var te = row.querySelector('[data-act="trig"]');
            te.style.cursor = 'pointer';
            te.addEventListener('click', function () {
                var l = locateLine(opts.trigger.file, opts.trigger.path);
                openInEditor(opts.trigger.file, l && l.line, l && l.col);
            });
        }
        return row;
    }

    //=========================================================================
    // Duplicate-line search: index every message/choice string across all data
    // files so a translator can find identical lines and avoid mismatched edits.
    //=========================================================================
    var dupIndex = null; // [{file, path, text}]

    // Emit every message / choice string in an MZ command list, tagged with its JSON path.
    function walkCommandList(list, prefix, emit) {
        if (!Array.isArray(list)) { return; }
        for (var i = 0; i < list.length; i++) {
            var cmd = list[i];
            if (!cmd) { continue; }
            if (cmd.code === 401 || cmd.code === 405) {
                if (cmd.parameters && typeof cmd.parameters[0] === 'string') {
                    emit(prefix.concat([i, 'parameters', 0]), cmd.parameters[0]);
                }
            } else if (cmd.code === 102 && cmd.parameters && Array.isArray(cmd.parameters[0])) {
                cmd.parameters[0].forEach(function (ch, n) {
                    if (typeof ch === 'string') { emit(prefix.concat([i, 'parameters', 0, n]), ch); }
                });
            }
        }
    }

    function collectMessages(absFile, fname, obj, emit) {
        if (/^Map\d+/.test(fname) && obj && obj.events) {
            obj.events.forEach(function (ev, e) {
                if (!ev || !ev.pages) { return; }
                ev.pages.forEach(function (pg, p) { walkCommandList(pg.list, ['events', e, 'pages', p, 'list'], emit); });
            });
        } else if (fname === 'CommonEvents.json' && Array.isArray(obj)) {
            obj.forEach(function (ce, c) { if (ce && ce.list) { walkCommandList(ce.list, [c, 'list'], emit); } });
        } else if (fname === 'Troops.json' && Array.isArray(obj)) {
            obj.forEach(function (tr, t) {
                if (tr && tr.pages) { tr.pages.forEach(function (pg, p) { walkCommandList(pg.list, [t, 'pages', p, 'list'], emit); }); }
            });
        }
    }

    // Scenario dictionary { "scene name": [ ...command list... ], ... } -> each value is
    // a command list whose JSON path is [sceneName, index, 'parameters', 0].
    function collectScenarioMessages(dict, emit) {
        if (!dict || typeof dict !== 'object') { return; }
        Object.keys(dict).forEach(function (key) {
            if (Array.isArray(dict[key])) { walkCommandList(dict[key], [key], emit); }
        });
    }

    function buildDupIndex() {
        if (dupIndex) { return dupIndex; }
        dupIndex = [];
        if (!nodeOk) { return dupIndex; }
        try {
            var files = fs.readdirSync(DATA_DIR).filter(function (f) {
                return /^Map\d+\.json$/.test(f) || f === 'CommonEvents.json' || f === 'Troops.json';
            });
            files.forEach(function (fname) {
                var abs = dataFile(fname);
                var c = readFileCached(abs);
                if (!c) { return; }
                var obj;
                try { obj = JSON.parse(c.text); } catch (e) { return; }
                collectMessages(abs, fname, obj, function (pathArr, text) {
                    dupIndex.push({ file: abs, path: pathArr, text: text });
                });
            });
            // Scenario dictionaries: reuse the already-parsed global (Scenario.json can be
            // tens of MB) and only fall back to parsing the file if the global is absent.
            scenarioFiles().forEach(function (abs) {
                var gname = scenarioGlobalForFile(abs);
                var dict = gname ? window[gname] : null;
                if (!dict) {
                    var sc = readFileCached(abs);
                    if (!sc) { return; }
                    try { dict = JSON.parse(sc.text); } catch (e) { return; }
                }
                collectScenarioMessages(dict, function (pathArr, text) {
                    dupIndex.push({ file: abs, path: pathArr, text: text });
                });
            });
            log('dup index built', dupIndex.length, 'messages');
        } catch (e) { log('dup index', e); }
        return dupIndex;
    }

    function normText(s, ignoreNl) {
        return ignoreNl ? s.replace(/\n/g, ' ').replace(/\s+/g, ' ').trim() : s;
    }

    function findOccurrences(text, ignoreNl) {
        var idx = buildDupIndex();
        var key = normText(text, ignoreNl);
        var out = [];
        for (var i = 0; i < idx.length; i++) {
            if (normText(idx[i].text, ignoreNl) === key) { out.push(idx[i]); }
        }
        return out;
    }

    // Structural match: the running interpreter told us the event id + command index,
    // so even if the list was a deep copy (reference match failed), we can find the
    // ON-DISK command at that index whose text matches. With the event id this is
    // almost always unique = confident, exact location.
    function structuralCandidates(r) {
        var out = [];
        if (r.srcIndex == null) { return out; }
        var idx = r.srcIndex, want = r.text;
        function check(list, file, prefix) {
            if (!Array.isArray(list) || idx < 0 || idx >= list.length) { return; }
            var cmd = list[idx];
            if (!cmd || !cmd.parameters) { return; }
            if ((cmd.code === 401 || cmd.code === 405) && cmd.parameters[0] === want) {
                out.push({ file: file, path: prefix.concat([idx, 'parameters', 0]) });
            } else if (cmd.code === 102 && Array.isArray(cmd.parameters[0])) {
                var n = cmd.parameters[0].indexOf(want);
                if (n >= 0) { out.push({ file: file, path: prefix.concat([idx, 'parameters', 0, n]) }); }
            }
        }
        try {
            if (typeof $dataMap !== 'undefined' && $dataMap && $dataMap.events &&
                typeof $gameMap !== 'undefined' && $gameMap) {
                var mf = mapFile($gameMap.mapId());
                if (r.srcEventId > 0 && $dataMap.events[r.srcEventId] && $dataMap.events[r.srcEventId].pages) {
                    $dataMap.events[r.srcEventId].pages.forEach(function (pg, p) {
                        check(pg.list, mf, ['events', r.srcEventId, 'pages', p, 'list']);
                    });
                } else {
                    $dataMap.events.forEach(function (ev, e) {
                        if (ev && ev.pages) { ev.pages.forEach(function (pg, p) { check(pg.list, mf, ['events', e, 'pages', p, 'list']); }); }
                    });
                }
            }
            if (!out.length && typeof $dataCommonEvents !== 'undefined' && $dataCommonEvents) {
                $dataCommonEvents.forEach(function (ce, c) { if (ce && ce.list) { check(ce.list, dataFile('CommonEvents.json'), [c, 'list']); } });
            }
            if (!out.length && typeof $dataTroops !== 'undefined' && $dataTroops &&
                typeof $gameTroop !== 'undefined' && $gameTroop && $gameTroop._troopId) {
                var tr = $dataTroops[$gameTroop._troopId];
                if (tr && tr.pages) { tr.pages.forEach(function (pg, p) { check(pg.list, dataFile('Troops.json'), [$gameTroop._troopId, 'pages', p, 'list']); }); }
            }
        } catch (e) { log('structural', e); }
        var uniq = [], seen = {};
        out.forEach(function (o) { var k = o.file + JSON.stringify(o.path); if (!seen[k]) { seen[k] = 1; uniq.push(o); } });
        return uniq;
    }

    // Resolve an unresolved record: structural match (confident) first, then a global
    // text-index search as a last resort.
    function resolveRecord(r) {
        if (r.file || r._tried || !nodeOk) { return; }
        r._tried = true;
        var cands = structuralCandidates(r);
        if (cands.length === 1) {
            r.file = cands[0].file; r.tail = cands[0].path;
            r.label = '(located: event ' + (r.srcEventId || '?') + ')';
            return;
        }
        if (cands.length > 1) { r._candidates = cands; r._ambig = cands.length; return; }
        var occ = findOccurrences(r.text, false);
        if (occ.length === 0) { occ = findOccurrences(r.text, true); } // tolerate \n/wordwrap diffs
        if (occ.length === 1) {
            r.file = occ[0].file; r.tail = occ[0].path; r.label = '(located by text)';
        } else if (occ.length > 1) {
            r._candidates = occ.map(function (o) { return { file: o.file, path: o.path }; });
            r._ambig = occ.length;
        }
    }

    //=========================================================================
    // Literal search across data + plugin / system files (for UI text like
    // "First kiss: None" that lives in plugins.js parameters, or event text that a
    // plugin re-renders as UI — e.g. "Passed the preliminaries" inside a Map JSON).
    //=========================================================================
    var _scanFiles = null;
    function pluginAndSystemFiles() {
        if (_scanFiles) { return _scanFiles; }
        _scanFiles = [];
        if (!nodeOk) { return _scanFiles; }
        try {
            // Most reliable sources for UI labels first: database files (item/skill
            // names + descriptions, terms), then the event data (Maps), then plugin
            // parameters (plugins.js), then plugin code last (where a literal is most
            // likely a false positive).
            ['System', 'Items', 'Weapons', 'Armors', 'Skills', 'States', 'Actors',
             'Classes', 'Enemies', 'Troops', 'CommonEvents', 'MapInfos', 'Animations', 'Tilesets']
                .forEach(function (n) { _scanFiles.push(dataFile(n + '.json')); });
            // Map JSONs hold event message text that plugins may draw as UI (battle/
            // arena results, custom windows). Numeric-sorted so results read naturally.
            try {
                fs.readdirSync(DATA_DIR)
                    .filter(function (f) { return /^Map\d+\.json$/.test(f); })
                    .sort(function (a, b) {
                        return parseInt(a.match(/\d+/)[0], 10) - parseInt(b.match(/\d+/)[0], 10);
                    })
                    .forEach(function (f) { _scanFiles.push(dataFile(f)); });
            } catch (e) { /* ignore */ }
            // Scenario dictionaries (plugin scenario systems) hold the bulk of dialogue in
            // some games; without these "Locate in Files" can't find scenario-only text.
            scenarioFiles().forEach(function (f) { _scanFiles.push(f); });
            var jsDir = path.join(WWW_ROOT, 'js');
            _scanFiles.push(path.join(jsDir, 'plugins.js'));
            var pdir = path.join(jsDir, 'plugins');
            fs.readdirSync(pdir).forEach(function (f) {
                if (/\.js$/.test(f) && f !== 'TLInspector.js') { _scanFiles.push(path.join(pdir, f)); }
            });
        } catch (e) { log('scanFiles', e); }
        return _scanFiles;
    }

    function isWordChar(ch) { return !!ch && /[A-Za-z0-9_]/.test(ch); }

    // Build (and cache on the file entry) the character ranges of JS comments, so we
    // can drop matches that live in comments (which never render). A small lexer that
    // also tracks string literals so `//` inside a string isn't treated as a comment.
    function commentRangesFor(c) {
        if (c._comments) { return c._comments; }
        var t = c.text, ranges = [], i = 0, n = t.length, state = 0, start = 0;
        while (i < n) {
            var ch = t[i], nx = t[i + 1];
            if (state === 0) {
                if (ch === '/' && nx === '/') { state = 1; start = i; i += 2; continue; }
                if (ch === '/' && nx === '*') { state = 2; start = i; i += 2; continue; }
                if (ch === "'") { state = 3; } else if (ch === '"') { state = 4; } else if (ch === '`') { state = 5; }
                i++; continue;
            }
            if (state === 1) { if (ch === '\n') { ranges.push([start, i]); state = 0; } i++; continue; }
            if (state === 2) { if (ch === '*' && nx === '/') { ranges.push([start, i + 2]); state = 0; i += 2; continue; } i++; continue; }
            if (ch === '\\') { i += 2; continue; } // escape inside a string
            if ((state === 3 && ch === "'") || (state === 4 && ch === '"') || (state === 5 && ch === '`')) { state = 0; }
            i++;
        }
        if (state === 1 || state === 2) { ranges.push([start, n]); }
        c._comments = ranges;
        return ranges;
    }
    function inComment(c, pos) {
        var r = commentRangesFor(c), lo = 0, hi = r.length - 1;
        while (lo <= hi) {
            var mid = (lo + hi) >> 1;
            if (pos < r[mid][0]) { hi = mid - 1; }
            else if (pos >= r[mid][1]) { lo = mid + 1; }
            else { return true; }
        }
        return false;
    }

    function searchFiles(text) {
        var results = [], seen = {};
        if (!nodeOk || !text) { return results; }
        var escaped = JSON.stringify(text).slice(1, -1);          // JSON-escaped form (\n etc.)
        var variants = escaped === text ? [text] : [text, escaped]; // raw form + escaped, deduped
        // As the text appears inside a single-quoted JS literal ('Let\'s go home').
        var jsq = escaped.replace(/\\"/g, '"').replace(/'/g, "\\'");
        if (variants.indexOf(jsq) < 0) { variants.push(jsq); }
        pluginAndSystemFiles().forEach(function (file) {
            var c = readFileCached(file);
            if (!c) { return; }
            var isJs = /\.js$/i.test(file);
            variants.forEach(function (v) {
                if (!v) { return; }
                var checkL = isWordChar(v[0]), checkR = isWordChar(v[v.length - 1]);
                var pos = c.text.indexOf(v);
                while (pos >= 0) {
                    // Skip matches embedded inside a larger word/identifier, e.g. "Tools"
                    // inside "isDevToolsOpen", and matches inside JS comments (never render).
                    var embedded = (checkL && isWordChar(c.text[pos - 1])) ||
                                   (checkR && isWordChar(c.text[pos + v.length]));
                    if (!embedded && !(isJs && inComment(c, pos))) {
                        var lc = offsetToLineCol(c, pos);
                        var k = file + ':' + lc.line;
                        // A complete string value ("text" in JSON; '…' / "…" / `…` in
                        // JS) is a high-confidence match vs. text buried in a longer one.
                        var qb = c.text[pos - 1], qa = c.text[pos + v.length];
                        var quoted = (qb === '"' && qa === '"') ||
                                     (isJs && qb === qa && (qb === "'" || qb === '`'));
                        if (!seen[k]) { seen[k] = 1; results.push({ file: file, line: lc.line, col: lc.col, quoted: quoted }); }
                    }
                    pos = c.text.indexOf(v, pos + v.length);
                }
            });
        });
        // Stable sort: exact quoted-value matches first, original (data-first) order otherwise.
        results.forEach(function (r, i) { r._i = i; });
        results.sort(function (a, b) { return (b.quoted - a.quoted) || (a._i - b._i); });
        return results;
    }

    // Exact literal first; if nothing, trim trailing words (handles "Label: <dynamic>"
    // where the value isn't in the file) until something matches.
    function searchFilesSmart(text) {
        var r = searchFiles(text);
        if (r.length) { return { results: r, query: text, partial: false }; }
        // Numbers may be runtime-substituted into a %1/%2 template: "2 turn(s) left"
        // never exists on disk while '%1 turn(s) left' does.
        var n = 0;
        var tpl = text.replace(/\d+(?:\.\d+)?/g, function () { return '%' + (++n); });
        if (n > 0 && tpl !== text) {
            var rt = searchFiles(tpl);
            if (rt.length) { return { results: rt, query: tpl, partial: true }; }
        }
        var words = text.replace(/\n/g, ' ').split(/\s+/).filter(Boolean);
        for (var n = words.length - 1; n >= 1; n--) {
            var sub = words.slice(0, n).join(' ');
            if (sub.length < 3) { break; }
            var rr = searchFiles(sub);
            if (rr.length) { return { results: rr, query: sub, partial: true }; }
        }
        return { results: [], query: text, partial: false };
    }

    //=========================================================================
    // Built-in editor (in-game): a small multi-tab code editor that views & edits
    // the source files directly, jumping to the same line click-to-source would.
    // Routed to from openInEditor() when CFG.editor / the header switch selects it,
    // when VSCode isn't installed, or as the fallback when a VSCode launch fails.
    // "Open all" stacks every result as a tab. Includes a find/replace widget with
    // regex, match-case and whole-word, next/prev, and replace / replace-all.
    //=========================================================================
    var EDLH = 18; // editor line-height in px (kept in sync with the CSS below)
    var editor = {
        root: null, area: null, gutter: null, tabsEl: null, findEl: null,
        fq: null, frin: null, fcount: null, statusEl: null,
        docs: [], active: -1, _lines: -1,
        find: { open: false, q: '', r: '', re: false, cs: false, ww: false,
                matches: [], idx: -1, invalid: false }
    };

    function baseName(f) { return f ? String(f).replace(/^.*[\\\/]/, '') : ''; }
    function activeDoc() { return editor.active >= 0 ? editor.docs[editor.active] : null; }

    // After a save, drop the cached text + located line numbers for the file so the
    // panel (and the JSON locator) recompute against the new content.
    function invalidateFile(file) {
        delete fileCache[file];
        var pre = file + '::';
        for (var k in lineCache) {
            if (lineCache.hasOwnProperty(k) && k.indexOf(pre) === 0) { delete lineCache[k]; }
        }
        dupIndex = null; // message text may have changed
    }

    function buildEditor() {
        if (editor.root) { return; }
        var root = document.createElement('div');
        root.id = 'tl-editor';
        root.style.cssText = [
            'position:fixed', 'top:3%', 'left:50%', 'transform:translateX(-50%)',
            'width:80%', 'max-width:1100px', 'height:92%', 'z-index:2147483646',
            'background:#15171d', 'color:#e6e6e6', 'border:1px solid #344',
            'border-radius:8px', 'box-shadow:0 8px 40px rgba(0,0,0,0.7)',
            'display:none', 'flex-direction:column', 'font:12px Consolas,Menlo,monospace'
        ].join(';');

        var head = document.createElement('div');
        head.style.cssText = 'padding:8px 12px;background:#11131a;border-bottom:1px solid #333;display:flex;align-items:center;gap:10px;flex:0 0 auto;border-radius:8px 8px 0 0';
        head.innerHTML =
            '<b style="color:#6cf">Edit</b>' +
            '<span style="flex:1"></span>' +
            '<span class="tl-ed-btn" data-act="find" title="Find / Replace (Ctrl+F / Ctrl+H)">Find</span>' +
            '<span class="tl-ed-btn" data-act="save" title="Save active file (Ctrl+S)">Save</span>' +
            '<span class="tl-ed-btn" data-act="close" title="Close editor (Esc)">&#x2715;</span>';
        root.appendChild(head);

        // tab strip (one tab per open file)
        var tabs = document.createElement('div');
        tabs.className = 'tl-ed-tabs';
        root.appendChild(tabs);

        // find / replace widget (hidden until opened)
        var find = document.createElement('div');
        find.className = 'tl-ed-find';
        find.style.display = 'none';
        find.innerHTML =
            '<div class="tl-fr">' +
                '<input class="tl-fq" type="text" placeholder="Find" spellcheck="false">' +
                '<span class="tl-fopt" data-opt="cs" title="Match case">Aa</span>' +
                '<span class="tl-fopt" data-opt="ww" title="Whole word">W</span>' +
                '<span class="tl-fopt" data-opt="re" title="Use regular expression">.*</span>' +
                '<span class="tl-fcount"></span>' +
                '<span class="tl-fbtn" data-fa="prev" title="Previous match (Shift+Enter)">&#x2191;</span>' +
                '<span class="tl-fbtn" data-fa="next" title="Next match (Enter)">&#x2193;</span>' +
                '<span class="tl-fbtn" data-fa="close" title="Close (Esc)">&#x2715;</span>' +
            '</div>' +
            '<div class="tl-fr">' +
                '<input class="tl-fr-in" type="text" placeholder="Replace" spellcheck="false">' +
                '<span class="tl-fbtn" data-fa="rep" title="Replace (Enter)">Replace</span>' +
                '<span class="tl-fbtn" data-fa="repall" title="Replace all matches">Replace All</span>' +
            '</div>';
        root.appendChild(find);

        var main = document.createElement('div');
        main.style.cssText = 'flex:1 1 auto;display:flex;overflow:hidden;background:#1b1e26';

        var gutter = document.createElement('div');
        gutter.className = 'tl-ed-gutter';
        gutter.style.cssText = 'flex:0 0 auto;min-width:42px;overflow:hidden;text-align:right;' +
            'padding:8px 6px 8px 10px;color:#566;background:#161922;white-space:pre;' +
            'user-select:none;-webkit-user-select:none;font:12px/18px Consolas,Menlo,monospace';

        var area = document.createElement('textarea');
        area.className = 'tl-ed-area';
        area.setAttribute('wrap', 'off');          // one logical line == one visual row
        area.setAttribute('spellcheck', 'false');
        area.style.cssText = 'flex:1 1 auto;resize:none;border:0;outline:0;padding:8px 10px;' +
            'color:#e6e6e6;background:#1b1e26;white-space:pre;overflow:auto;' +
            'font:12px/18px Consolas,Menlo,monospace;tab-size:4;-moz-tab-size:4';

        main.appendChild(gutter);
        main.appendChild(area);
        root.appendChild(main);

        var foot = document.createElement('div');
        foot.style.cssText = 'padding:5px 12px;background:#11131a;border-top:1px solid #333;color:#8aa;flex:0 0 auto;display:flex;gap:14px;border-radius:0 0 8px 8px';
        foot.innerHTML = '<span>Ctrl+S save &middot; Ctrl+F find &middot; Ctrl+H replace &middot; Esc close &middot; Tab indent</span>' +
            '<span class="tl-ed-status" style="flex:1;text-align:right;color:#7a7"></span>';
        root.appendChild(foot);

        var st = document.createElement('style');
        st.textContent =
            '#tl-editor .tl-ed-btn{cursor:pointer;padding:3px 9px;border-radius:4px;background:#333;color:#ddd}' +
            '#tl-editor .tl-ed-btn:hover{filter:brightness(1.35)}' +
            '#tl-editor .tl-ed-tabs{display:flex;overflow-x:auto;background:#0e1016;border-bottom:1px solid #333;flex:0 0 auto}' +
            '#tl-editor .tl-ed-tab{display:flex;align-items:center;gap:6px;padding:5px 8px;border-right:1px solid #222;color:#9ab;cursor:pointer;white-space:nowrap;max-width:220px;flex:0 0 auto}' +
            '#tl-editor .tl-ed-tab.on{background:#1b1e26;color:#fff}' +
            '#tl-editor .tl-ed-tab .nm{overflow:hidden;text-overflow:ellipsis}' +
            '#tl-editor .tl-ed-tab .dot{color:#fd6}' +
            '#tl-editor .tl-ed-tab .x{color:#889;border-radius:3px;padding:0 4px}' +
            '#tl-editor .tl-ed-tab .x:hover{background:#555;color:#fff}' +
            '#tl-editor .tl-ed-find{background:#12141b;border-bottom:1px solid #333;padding:5px 8px;flex:0 0 auto}' +
            '#tl-editor .tl-fr{display:flex;align-items:center;gap:6px;margin:2px 0}' +
            '#tl-editor .tl-fq,#tl-editor .tl-fr-in{flex:0 0 240px;width:240px;min-width:0;background:#1b1e26;border:1px solid #344;color:#eee;padding:3px 6px;font:12px Consolas,Menlo,monospace;outline:none}' +
            '#tl-editor .tl-fopt{cursor:pointer;padding:2px 6px;border-radius:3px;background:#222;color:#9ab;font:11px monospace}' +
            '#tl-editor .tl-fopt.on{background:#2a5db0;color:#fff}' +
            '#tl-editor .tl-fcount{color:#9ab;min-width:62px;text-align:center;font-size:11px}' +
            '#tl-editor .tl-fcount.err{color:#f88}' +
            '#tl-editor .tl-fbtn{cursor:pointer;padding:2px 8px;border-radius:3px;background:#333;color:#ddd;white-space:nowrap}' +
            '#tl-editor .tl-fbtn:hover{filter:brightness(1.3)}';
        root.appendChild(st);

        head.addEventListener('click', function (e) {
            var a = e.target.getAttribute('data-act');
            if (a === 'save') { saveEditor(); }
            else if (a === 'close') { closeEditor(); }
            else if (a === 'find') { openFind(false); }
        });

        // tab strip: click selects, click the x closes
        tabs.addEventListener('click', function (e) {
            var t = e.target;
            while (t && t !== tabs && !t.hasAttribute('data-ti')) { t = t.parentNode; }
            if (!t || t === tabs) { return; }
            var i = parseInt(t.getAttribute('data-ti'), 10);
            if (e.target.classList.contains('x')) { closeTab(i); } else { selectTab(i); }
        });

        // find widget wiring
        editor.fq = find.querySelector('.tl-fq');
        editor.frin = find.querySelector('.tl-fr-in');
        editor.fcount = find.querySelector('.tl-fcount');
        editor.fq.addEventListener('input', function () {
            editor.find.q = this.value; recomputeMatches();
            showMatch(editor.find.idx < 0 ? 0 : editor.find.idx);
        });
        editor.fq.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); showMatch(editor.find.idx + (e.shiftKey ? -1 : 1)); }
            else if (e.key === 'Escape') { e.preventDefault(); closeFind(); }
        });
        editor.frin.addEventListener('input', function () { editor.find.r = this.value; });
        editor.frin.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); replaceCurrent(); }
            else if (e.key === 'Escape') { e.preventDefault(); closeFind(); }
        });
        find.addEventListener('click', function (e) {
            var opt = e.target.getAttribute('data-opt');
            var fa = e.target.getAttribute('data-fa');
            if (opt) {
                var f = editor.find; f[opt] = !f[opt];
                e.target.classList.toggle('on', f[opt]);
                recomputeMatches(); showMatch(f.idx < 0 ? 0 : f.idx);
            } else if (fa === 'next') { showMatch(editor.find.idx + 1); }
            else if (fa === 'prev') { showMatch(editor.find.idx - 1); }
            else if (fa === 'close') { closeFind(); }
            else if (fa === 'rep') { replaceCurrent(); }
            else if (fa === 'repall') { replaceAll(); }
        });

        area.addEventListener('input', function () {
            markDirty(); refreshGutter();
            if (editor.find.open) { recomputeMatches(); updateFindCount(); }
        });
        area.addEventListener('scroll', syncGutter);
        area.addEventListener('keydown', onEditorKey, false);

        // Keep the game from reacting to clicks/keys aimed at the editor (mirrors the
        // inspector panel's isolation). With "freeze" off this is what protects typing.
        ['mousedown', 'mouseup', 'click', 'dblclick', 'wheel', 'contextmenu',
         'touchstart', 'touchend', 'touchmove', 'pointerdown', 'pointerup',
         'keydown', 'keyup', 'keypress'].forEach(function (t) {
            root.addEventListener(t, function (ev) { ev.stopPropagation(); }, false);
        });

        document.body.appendChild(root);
        editor.root = root;
        editor.area = area;
        editor.gutter = gutter;
        editor.tabsEl = tabs;
        editor.findEl = find;
        editor.statusEl = foot.querySelector('.tl-ed-status');
        applyOverlayScale();
    }

    //--- documents / tabs ----------------------------------------------------
    function docIndexByFile(file) {
        for (var i = 0; i < editor.docs.length; i++) { if (editor.docs[i].file === file) { return i; } }
        return -1;
    }

    // Files above this size are NOT loaded whole into the <textarea>: a 68MB scenario
    // file would push ~3M lines into the DOM and build a gutter string with millions of
    // numbers, freezing then crashing the game. Instead we load a WINDOW of lines around
    // the target and splice edits back into the full text on save (see saveEditor).
    var BIG_FILE_BYTES = 3 * 1024 * 1024;
    var WINDOW_BEFORE = 300, WINDOW_AFTER = 300;

    // Slice a window of [WINDOW_BEFORE+WINDOW_AFTER] lines centred on targetLine out of the
    // full text; fills winStart/winEnd/baseLine/text on the doc.
    function windowDoc(doc, targetLine) {
        var full = doc.fullText, tgt = (targetLine && targetLine > 0) ? targetLine : 1;
        var startLine = Math.max(1, tgt - WINDOW_BEFORE);
        var winStart = lineStartOffset(full, startLine);
        var winEnd = winStart, n = 0, cap = WINDOW_BEFORE + WINDOW_AFTER;
        while (n < cap) { var p = full.indexOf('\n', winEnd); if (p < 0) { winEnd = full.length; break; } winEnd = p + 1; n++; }
        doc.baseLine = startLine; doc.winStart = winStart; doc.winEnd = winEnd;
        doc.text = full.slice(winStart, winEnd);
    }
    function winLineCount(d) {
        var c = 1, t = d.text; for (var i = 0; i < t.length; i++) { if (t.charCodeAt(i) === 10) { c++; } }
        return c;
    }
    function lineInWindow(d, line) {
        return d.windowed && line >= d.baseLine && line <= d.baseLine + winLineCount(d) - 1;
    }

    function createDoc(file, targetLine) {
        var raw;
        try { raw = fs.readFileSync(file, 'utf8'); }
        catch (e) { toast('Could not read file'); log('read', e); return null; }
        var bom = raw.charCodeAt(0) === 0xFEFF;
        if (bom) { raw = raw.slice(1); }
        var nl = /\r\n/.test(raw) ? '\r\n' : '\n';      // preserve the file's line endings
        var full = raw.replace(/\r\n/g, '\n');
        var doc = { file: file, name: baseName(file), nl: nl, bom: bom, dirty: false,
                    line: 0, scrollTop: 0, selStart: 0, selEnd: 0, windowed: false, baseLine: 1 };
        if (full.length > BIG_FILE_BYTES) {
            doc.windowed = true;
            doc.fullText = full;
            windowDoc(doc, targetLine);
        } else {
            doc.text = full;
        }
        return doc;
    }

    function stashActive() {
        var d = activeDoc(); if (!d) { return; }
        d.text = editor.area.value;
        d.scrollTop = editor.area.scrollTop;
        d.selStart = editor.area.selectionStart;
        d.selEnd = editor.area.selectionEnd;
    }

    function loadActive() {
        var d = activeDoc();
        editor._lines = -1;
        if (!d) { editor.area.value = ''; refreshGutter(); updateEditorTitle(); return; }
        editor.area.value = d.text;
        refreshGutter();
        editor.area.scrollTop = d.scrollTop || 0;
        try { editor.area.setSelectionRange(d.selStart || 0, d.selEnd || 0); } catch (e) { /* ignore */ }
        syncGutter();
        updateEditorTitle();
        if (editor.find.open) { recomputeMatches(); updateFindCount(); }
    }

    function selectTab(i, line) {
        if (i < 0 || i >= editor.docs.length) { return; }
        if (i !== editor.active) { stashActive(); editor.active = i; loadActive(); }
        renderTabs();
        if (line) { jumpToLine(line); }
        editor.area.focus();
    }

    function closeTab(i) {
        var d = editor.docs[i]; if (!d) { return; }
        if (d.dirty && !window.confirm('Discard unsaved changes to ' + d.name + '?')) { return; }
        if (i === editor.active) {
            editor.docs.splice(i, 1);
            if (!editor.docs.length) { editor.active = -1; renderTabs(); editor.root.style.display = 'none'; return; }
            editor.active = Math.min(i, editor.docs.length - 1);
            loadActive();
        } else {
            if (i < editor.active) { editor.active--; }
            editor.docs.splice(i, 1);
        }
        renderTabs();
    }

    function renderTabs() {
        var el = editor.tabsEl; if (!el) { return; }
        el.innerHTML = '';
        editor.docs.forEach(function (d, i) {
            var t = document.createElement('div');
            t.className = 'tl-ed-tab' + (i === editor.active ? ' on' : '');
            t.setAttribute('data-ti', i);
            t.title = d.file;
            t.innerHTML = (d.dirty ? '<span class="dot">&#9679;</span>' : '') +
                '<span class="nm">' + esc(d.name) + '</span>' +
                '<span class="x">&#x2715;</span>';
            el.appendChild(t);
        });
    }

    function markDirty() {
        var d = activeDoc(); if (!d) { return; }
        if (!d.dirty) { d.dirty = true; renderTabs(); }
        updateEditorTitle();
    }

    //--- view helpers --------------------------------------------------------
    function insertAtCursor(area, str) {
        var s = area.selectionStart, e = area.selectionEnd, v = area.value;
        area.value = v.slice(0, s) + str + v.slice(e);
        area.selectionStart = area.selectionEnd = s + str.length;
    }

    function onEditorKey(e) {
        if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) { e.preventDefault(); saveEditor(); return; }
        if ((e.ctrlKey || e.metaKey) && (e.key === 'f' || e.key === 'F')) { e.preventDefault(); openFind(false); return; }
        if ((e.ctrlKey || e.metaKey) && (e.key === 'h' || e.key === 'H')) { e.preventDefault(); openFind(true); return; }
        if (e.key === 'Escape') { e.preventDefault(); if (editor.find.open) { closeFind(); } else { closeEditor(); } return; }
        if (e.key === 'Tab') { e.preventDefault(); insertAtCursor(editor.area, '\t'); markDirty(); }
    }

    function syncGutter() {
        if (editor.gutter && editor.area) { editor.gutter.scrollTop = editor.area.scrollTop; }
    }

    function refreshGutter() {
        var v = editor.area.value, count = 1;
        for (var i = 0; i < v.length; i++) { if (v.charCodeAt(i) === 10) { count++; } }
        var d = activeDoc(), base = (d && d.windowed) ? d.baseLine : 1;
        if (count === editor._lines && base === editor._gutterBase) { return; }
        editor._lines = count; editor._gutterBase = base;
        var s = '';
        for (var k = 0; k < count; k++) { s += (base + k) + '\n'; }
        editor.gutter.textContent = s;
        syncGutter();
    }

    function updateEditorTitle(line) {
        var d = activeDoc();
        if (!d) { setEditorStatus(''); return; }
        if (line != null) { d.line = line; }
        setEditorStatus(d.name + (d.line ? ':' + d.line : '') + (d.dirty ? '  (unsaved)' : ''));
    }

    function setEditorStatus(msg) {
        if (editor.statusEl) { editor.statusEl.textContent = msg || ''; }
    }

    function lineStartOffset(text, line) {
        var off = 0, cur = 1;
        while (cur < line) {
            var nl = text.indexOf('\n', off);
            if (nl < 0) { break; }
            off = nl + 1; cur++;
        }
        return off;
    }

    // Actual rendered line height of the textarea. Under a CSS zoom the browser
    // rounds every rendered line box to whole device pixels, so the nominal 18px is
    // off by up to ~1% — across a 70k-line file that puts the viewport hundreds of
    // lines away from the (correctly placed) cursor. Measure instead of trusting EDLH.
    function editorLineHeight() {
        var area = editor.area;
        if (!area) { return EDLH; }
        var v = area.value, lines = 1;
        for (var i = 0; i < v.length; i++) { if (v.charCodeAt(i) === 10) { lines++; } }
        var h = (area.scrollHeight - 16) / lines; // 16 = 8px top + bottom padding (CSS above)
        return (h > EDLH / 2 && h < EDLH * 2) ? h : EDLH;
    }

    function jumpToLine(line) {
        var d = activeDoc();
        // In windowed mode `line` is a FILE line; translate to the textarea's local line.
        var local = (d && d.windowed) ? (line - d.baseLine + 1) : line;
        if (local < 1) { local = 1; }
        var area = editor.area, text = area.value;
        var so = lineStartOffset(text, local);
        var eo = text.indexOf('\n', so); if (eo < 0) { eo = text.length; }
        try { area.setSelectionRange(so, eo); } catch (e) { /* ignore */ }
        area.scrollTop = Math.max(0, (local - 4) * editorLineHeight());
        syncGutter();
        updateEditorTitle(line); // status shows the real FILE line
    }

    // Entry point from openInEditor(): open (or focus) a tab for `file` and jump to line.
    function openBuiltInEditor(file, line, col) {
        if (!nodeOk || !file) { toast('No file to open'); return; }
        buildEditor();
        editor.root.style.display = 'flex';
        var i = docIndexByFile(file);
        if (i < 0) {
            var d = createDoc(file, line); if (!d) { return; }
            stashActive();
            editor.docs.push(d);
            i = editor.docs.length - 1;
            editor.active = i;
            loadActive();
            renderTabs();
            jumpToLine(line || 1);
            editor.area.focus();
            if (d.windowed) {
                toast('Large file — showing lines ' + d.baseLine + '–' +
                      (d.baseLine + winLineCount(d) - 1) + ' of ' + d.name + ' (partial view)');
            }
        } else {
            var d2 = editor.docs[i];
            // Re-open of a windowed file whose target is outside the loaded window: recut
            // the window around the new line (unless there are unsaved edits to preserve).
            if (d2.windowed && line && !lineInWindow(d2, line) && !d2.dirty) {
                stashActive(); editor.active = i;
                windowDoc(d2, line);
                loadActive(); renderTabs(); jumpToLine(line); editor.area.focus();
            } else {
                selectTab(i, line || 1);
            }
        }
    }

    function saveEditor() {
        var d = activeDoc(); if (!d) { return; }
        d.text = editor.area.value;
        // Windowed docs hold only a slice in the textarea: splice it back into the full
        // text (and re-anchor the window to the edited slice's new extent) before writing.
        var full;
        if (d.windowed) {
            full = d.fullText.slice(0, d.winStart) + d.text + d.fullText.slice(d.winEnd);
            d.fullText = full;
            d.winEnd = d.winStart + d.text.length;
        } else {
            full = d.text;
        }
        var out = (d.nl === '\r\n') ? full.replace(/\n/g, '\r\n') : full;
        if (d.bom) { out = String.fromCharCode(0xFEFF) + out; }
        try {
            fs.writeFileSync(d.file, out, 'utf8');
            d.dirty = false;
            renderTabs(); updateEditorTitle();
            invalidateFile(d.file);
            // Push the just-saved edit straight onto the live game: reload data files,
            // re-fetch on-screen images and redraw the scene so the change is visible
            // immediately without leaving the editor or restarting.
            refreshGameElements();
            toast('Saved ' + d.name + (d.windowed ? ' (partial view)' : '') + ' — reloaded in-game');
        } catch (e) { setEditorStatus('save failed'); toast('Save failed: ' + e.message); log('save', e); }
    }

    // Closes the editor window but KEEPS the open tabs in memory (like minimizing),
    // so unsaved edits aren't lost; reopening any result shows them again.
    function closeEditor() {
        if (!editor.root) { return; }
        editor.root.style.display = 'none';
    }

    //--- find / replace ------------------------------------------------------
    function openFind(replaceFocus) {
        buildEditor();
        var f = editor.find; f.open = true;
        editor.findEl.style.display = 'block';
        // seed the query from a short single-line selection (VSCode behaviour)
        var sel = editor.area.value.slice(editor.area.selectionStart, editor.area.selectionEnd);
        if (sel && sel.indexOf('\n') < 0 && sel.length <= 200) { f.q = sel; editor.fq.value = sel; }
        recomputeMatches();
        var inp = replaceFocus ? editor.frin : editor.fq;
        inp.focus(); inp.select();
        showMatch(f.idx < 0 ? 0 : f.idx);
    }

    function closeFind() {
        editor.find.open = false;
        if (editor.findEl) { editor.findEl.style.display = 'none'; }
        editor.area.focus();
    }

    function buildFindRegex(global) {
        var f = editor.find;
        if (!f.q) { return null; }
        var src = f.re ? f.q : f.q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        if (f.ww) { src = '\\b' + src + '\\b'; }
        try { return new RegExp(src, (global ? 'g' : '') + (f.cs ? '' : 'i') + 'm'); }
        catch (e) { return null; }
    }

    function recomputeMatches(caret) {
        var f = editor.find, text = editor.area.value;
        f.matches = []; f.invalid = false;
        if (!f.q) { f.idx = -1; updateFindCount(); return; }
        var re = buildFindRegex(true);
        if (!re) { f.invalid = !!f.re; f.idx = -1; updateFindCount(); return; }
        var m, guard = 0;
        while ((m = re.exec(text)) !== null) {
            f.matches.push({ start: m.index, end: m.index + m[0].length });
            if (m[0].length === 0) { re.lastIndex++; }   // never loop on empty match
            if (++guard > 200000) { break; }
        }
        var c = (caret == null) ? (editor.area.selectionStart || 0) : caret;
        f.idx = -1;
        for (var i = 0; i < f.matches.length; i++) { if (f.matches[i].start >= c) { f.idx = i; break; } }
        if (f.idx === -1 && f.matches.length) { f.idx = 0; }
        updateFindCount();
    }

    // Select + scroll to match i (wraps). Does NOT move focus, so the user keeps
    // typing in the find box while matches highlight live in the textarea.
    function showMatch(i) {
        var f = editor.find;
        if (!f.matches.length) { updateFindCount(); return; }
        f.idx = ((i % f.matches.length) + f.matches.length) % f.matches.length;
        var mt = f.matches[f.idx], area = editor.area;
        try { area.setSelectionRange(mt.start, mt.end); } catch (e) { /* ignore */ }
        var line = area.value.slice(0, mt.start).split('\n').length;
        area.scrollTop = Math.max(0, (line - 4) * editorLineHeight());
        syncGutter(); updateFindCount();
    }

    function updateFindCount() {
        var f = editor.find, el = editor.fcount;
        if (!el) { return; }
        if (f.invalid) { el.textContent = 'bad regex'; el.className = 'tl-fcount err'; return; }
        el.className = 'tl-fcount';
        if (!f.q) { el.textContent = ''; }
        else if (!f.matches.length) { el.textContent = 'No results'; }
        else { el.textContent = (f.idx + 1) + ' of ' + f.matches.length; }
    }

    function computeReplacement(matched) {
        var f = editor.find;
        if (!f.re) { return f.r; }                       // literal: insert as-is
        var re = buildFindRegex(false);
        try { return matched.replace(re, f.r); }         // regex: honour $1, $& etc.
        catch (e) { return matched; }
    }

    function replaceCurrent() {
        var f = editor.find;
        if (!f.matches.length) { return; }
        if (f.idx < 0) { f.idx = 0; }
        var mt = f.matches[f.idx], area = editor.area, val = area.value;
        var rep = computeReplacement(val.slice(mt.start, mt.end));
        area.value = val.slice(0, mt.start) + rep + val.slice(mt.end);
        markDirty(); refreshGutter();
        recomputeMatches(mt.start + rep.length);         // positions shifted; reanchor
        showMatch(f.idx);
    }

    function replaceAll() {
        var f = editor.find, area = editor.area;
        var reg = buildFindRegex(true);
        if (!reg) { return; }
        var arr = area.value.match(reg);
        var count = arr ? arr.length : 0;
        if (!count) { toast('No matches'); return; }
        // literal mode: function replacer so $ in the replacement stays literal.
        area.value = f.re ? area.value.replace(reg, f.r)
                          : area.value.replace(reg, function () { return f.r; });
        markDirty(); refreshGutter();
        recomputeMatches(); showMatch(0);
        toast('Replaced ' + count + ' occurrence' + (count === 1 ? '' : 's'));
    }

    //=========================================================================
    // Live refresh: reload the data files + images a translator just edited and
    // redraw the current scene, so saved changes show up in-game without a restart.
    // Bound to the panel's "Reload" button.
    //=========================================================================
    var DATA_GLOBALS = {
        'System': '$dataSystem', 'Actors': '$dataActors', 'Classes': '$dataClasses',
        'Skills': '$dataSkills', 'Items': '$dataItems', 'Weapons': '$dataWeapons',
        'Armors': '$dataArmors', 'Enemies': '$dataEnemies', 'Troops': '$dataTroops',
        'States': '$dataStates', 'Animations': '$dataAnimations', 'Tilesets': '$dataTilesets',
        'CommonEvents': '$dataCommonEvents', 'MapInfos': '$dataMapInfos'
    };

    // Run the engine's post-load step on a freshly parsed data object. This is what
    // rebuilds each entry's `.meta`/notetag fields (via DataManager.extractMetadata)
    // AND re-fires any plugin that aliased DataManager.onLoad to process notetags.
    // Skipping it is what crashed plugins like character-lighting (event.meta was
    // undefined -> "Cannot read property 'CharLight' of undefined").
    function runOnLoad(obj) {
        try {
            if (typeof DataManager !== 'undefined' && typeof DataManager.onLoad === 'function') {
                DataManager.onLoad(obj);
            }
        } catch (e) { /* a plugin's onLoad hook may itself throw; don't abort the reload */ }
    }

    // Reload scenario dictionaries only when the file actually changed on disk. These can
    // be tens of MB, so re-parsing on every reload (when nothing scenario-side changed)
    // would stall F9. On first sight we adopt the current mtime WITHOUT re-parsing an
    // already-loaded global, so an unchanged scenario never costs a big parse.
    var _scenarioMtime = {};
    function scenarioMtime(file) {
        try { var st = fs.statSync(file); return st.mtimeMs || (st.mtime && st.mtime.getTime()) || 0; }
        catch (e) { return -1; }
    }
    function reloadScenarioData() {
        var n = 0;
        SCENARIO_SETS.forEach(function (sg) {
            if (typeof window[sg.global] === 'undefined') { return; } // game doesn't use it
            var file = scenarioPath(sg.file), m = scenarioMtime(file);
            if (m < 0) { return; }
            var known = _scenarioMtime.hasOwnProperty(file);
            if (!known) { _scenarioMtime[file] = m; if (window[sg.global]) { return; } }
            if (known && _scenarioMtime[file] === m && window[sg.global]) { return; } // unchanged
            try { window[sg.global] = JSON.parse(fs.readFileSync(file, 'utf8')); _scenarioMtime[file] = m; n++; }
            catch (e) { /* mid-write or gone; keep the in-memory copy */ }
        });
        return n;
    }

    function reloadDataFiles() {
        var n = 0;
        for (var name in DATA_GLOBALS) {
            if (!DATA_GLOBALS.hasOwnProperty(name)) { continue; }
            var gname = DATA_GLOBALS[name];
            if (typeof window[gname] === 'undefined') { continue; }
            try {
                window[gname] = JSON.parse(fs.readFileSync(dataFile(name + '.json'), 'utf8'));
                runOnLoad(window[gname]);
                n++;
            } catch (e) { /* file may be absent for this game; skip */ }
        }
        n += reloadScenarioData();
        try {
            if (typeof $gameMap !== 'undefined' && $gameMap && $gameMap.mapId()) {
                // $dataMap must be assigned BEFORE onLoad: it keys off (object === $dataMap)
                // to know it should extract event metadata.
                window.$dataMap = JSON.parse(fs.readFileSync(mapFile($gameMap.mapId()), 'utf8'));
                runOnLoad(window.$dataMap);
                n++;
            }
        } catch (e) { /* ignore */ }
        return n;
    }

    // Redraw every window in the current scene (item names, descriptions, terms,
    // status text, etc. are re-read from the freshly reloaded data).
    function refreshSceneWindows() {
        var scene = (typeof SceneManager !== 'undefined') && SceneManager._scene;
        if (!scene || typeof Window_Base === 'undefined') { return 0; }
        var n = 0;
        (function walk(obj) {
            if (!obj) { return; }
            if (obj instanceof Window_Base && typeof obj.refresh === 'function') {
                try { obj.refresh(); n++; } catch (e) { /* some windows refresh only with state */ }
            }
            var kids = obj.children;
            if (kids) { for (var i = 0; i < kids.length; i++) { walk(kids[i]); } }
        })(scene);
        return n;
    }

    function clearImageCaches() {
        try {
            if (typeof ImageManager !== 'undefined') {
                if (typeof ImageManager.clear === 'function') { ImageManager.clear(); }
                if (ImageManager._cache) { ImageManager._cache = {}; }
                if (ImageManager._system) { ImageManager._system = {}; }
                if (typeof ImageCache !== 'undefined' && ImageManager._imageCache) { ImageManager._imageCache = new ImageCache(); }
            }
        } catch (e) { /* ignore */ }
        thumbCache = {};
    }

    // Force on-screen sprites to re-fetch their bitmap from disk. Routing through
    // ImageManager.loadBitmap (cache already cleared) keeps decryption working.
    function reloadOnScreenImages() {
        var scene = (typeof SceneManager !== 'undefined') && SceneManager._scene;
        if (!scene || typeof ImageManager === 'undefined') { return 0; }
        var n = 0;
        (function walk(obj) {
            if (!obj) { return; }
            var bmp = obj.bitmap;
            if (bmp && bmp._url) {
                var url = decodeUrl(bmp._url);
                var slash = url.lastIndexOf('/');
                var folder = url.slice(0, slash + 1);
                var fname = url.slice(slash + 1).replace(/\.png$/i, '');
                try { obj.bitmap = ImageManager.loadBitmap(folder, fname); n++; }
                catch (e) { /* ignore */ }
            }
            var kids = obj.children;
            if (kids) { for (var i = 0; i < kids.length; i++) { walk(kids[i]); } }
        })(scene);
        return n;
    }

    function refreshGameElements() {
        if (!nodeOk) { toast('Reload needs Node (NW.js)'); return; }
        // Drop our own caches so the panel relocates against the new file contents.
        fileCache = {}; lineCache = {}; dupIndex = null; _scanFiles = null;
        uiValueIndex = null; tmAssignCache = {}; jsLitIndex = null; // notetags / vocab / plugin edits

        var parts = [];
        var d = reloadDataFiles();        if (d) { parts.push(d + ' data file' + (d === 1 ? '' : 's')); }
        clearImageCaches();
        var im = reloadOnScreenImages();  if (im) { parts.push(im + ' image' + (im === 1 ? '' : 's')); }
        var w = refreshSceneWindows();    if (w) { parts.push(w + ' window' + (w === 1 ? '' : 's')); }

        // Nudge the map to rebuild event sprites/state if we're on it.
        try { if (typeof $gameMap !== 'undefined' && $gameMap && $gameMap.requestRefresh) { $gameMap.requestRefresh(); } } catch (e) { /* ignore */ }

        render(); // refresh our own panel too
        toast(parts.length ? ('Reloaded ' + parts.join(', ')) : 'Nothing on screen to reload');
    }

    //=========================================================================
    // Overlay UI
    //=========================================================================
    var ui = { root: null, body: null, tab: 'text', highlight: null, hlLayer: null,
               open: false, refreshTimer: 0, side: 'right', pick: false, catcher: null,
               pickLabel: null, _pickHits: null, selection: null, ignoreNl: false, freeze: false };
    try { ui.side = window.localStorage.getItem('tlins.side') || 'right'; } catch (e) { /* ignore */ }
    try { ui.ignoreNl = window.localStorage.getItem('tlins.ignl') === '1'; } catch (e) { /* ignore */ }
    try { ui.freeze = window.localStorage.getItem('tlins.freeze') === '1'; } catch (e) { /* ignore */ }
    // Editor switch: remembered choice if set, else seeded from CFG.editor (with 'auto'
    // resolving to built-in only when VSCode isn't actually installed).
    try {
        var _sb = window.localStorage.getItem('tlins.builtin');
        ui.useBuiltin = _sb === '1' ? true : _sb === '0' ? false :
            (CFG.editor === 'builtin' || (CFG.editor !== 'vscode' && !vscodeAvailable()));
    } catch (e) { ui.useBuiltin = (CFG.editor === 'builtin'); }
    // Which external editor the dropdown opens results in (null => first detected).
    try { ui.editorId = window.localStorage.getItem('tlins.editor') || null; } catch (e) { ui.editorId = null; }

    function applySide() {
        if (!ui.root) { return; }
        var left = ui.side === 'left';
        ui.root.style.left = left ? '0' : 'auto';
        ui.root.style.right = left ? 'auto' : '0';
        ui.root.style.boxShadow = (left ? '2px' : '-2px') + ' 0 12px rgba(0,0,0,0.6)';
        applyOverlayScale();
    }

    function flipSide() {
        ui.side = ui.side === 'left' ? 'right' : 'left';
        try { window.localStorage.setItem('tlins.side', ui.side); } catch (e) { /* ignore */ }
        applySide();
    }

    function buildUI() {
        if (ui.root) { return; }
        var root = document.createElement('div');
        root.id = 'tl-inspector';
        root.style.cssText = [
            'position:fixed', 'top:0', 'right:0', 'width:460px', 'height:100%',
            'background:rgba(20,22,28,0.96)', 'color:#e6e6e6', 'z-index:2147483646',
            'font:12px/1.45 Consolas,Menlo,monospace', 'box-shadow:-2px 0 12px rgba(0,0,0,0.6)',
            'display:none', 'flex-direction:column'
        ].join(';');

        var head = document.createElement('div');
        head.style.cssText = 'background:#11131a;border-bottom:1px solid #333;flex:0 0 auto';
        head.innerHTML =
            '<div class="tl-hrow" style="padding:7px 10px 4px">' +
                '<b style="color:#6cf">TL Inspector</b>' +
                '<span style="flex:1"></span>' +
                '<span data-tab="text" class="tl-tab">Text</span>' +
                '<span data-tab="images" class="tl-tab">Images</span>' +
                '<span style="flex:1"></span>' +
                '<span data-act="flip" class="tl-btn tl-ic" title="Move panel to the other side">&#x21c4;</span>' +
                '<span data-act="close" class="tl-btn tl-ic" title="Close panel (F10)">&#x2715;</span>' +
            '</div>' +
            '<div class="tl-hrow" style="padding:0 10px 7px">' +
                '<span data-act="pick" class="tl-btn tl-inspect" title="Hover the game to highlight an object, then click to reveal it">&#x2316; Inspect</span>' +
                '<label class="tl-btn tl-frz" title="Open clicked file:line results in the built-in in-game editor instead of an external editor">' +
                    '<input type="checkbox" data-act="builtin"' + (ui.useBuiltin ? ' checked' : '') + '> Built-in Editor</label>' +
                '<select class="tl-edsel" data-act="edsel" title="Which installed editor opens clicked file:line results"></select>' +
                '<label class="tl-btn tl-frz" title="Block mouse/keyboard from reaching the game while the panel is open">' +
                    '<input type="checkbox" data-act="freeze"' + (ui.freeze ? ' checked' : '') + '> Freeze</label>' +
                '<span data-act="refresh" class="tl-btn" title="Reload on-screen text &amp; images from disk (auto-reloads on save too)">&#x21bb; Reload</span>' +
            '</div>';
        root.appendChild(head);

        var body = document.createElement('div');
        body.style.cssText = 'flex:1 1 auto;overflow:auto;padding:6px 8px';
        root.appendChild(body);

        var style = document.createElement('style');
        style.textContent =
            '#tl-inspector .tl-hrow{display:flex;align-items:center;gap:6px;flex-wrap:wrap}' +
            '#tl-inspector .tl-tab{cursor:pointer;padding:3px 11px;border-radius:4px;background:#222;color:#bbb;display:inline-flex;align-items:center;line-height:1.3}' +
            '#tl-inspector .tl-tab.on{background:#2a5db0;color:#fff}' +
            '#tl-inspector .tl-btn{cursor:pointer;padding:3px 10px;border-radius:4px;background:#333;color:#ddd;display:inline-flex;align-items:center;gap:5px;line-height:1.3}' +
            '#tl-inspector .tl-btn.on{background:#3a7;color:#022}' +
            '#tl-inspector .tl-ic{min-width:30px;justify-content:center;padding:3px 6px}' +
            '#tl-inspector .tl-edsel{background:#333;color:#ddd;border:1px solid #475;border-radius:4px;padding:3px 4px;font:inherit;cursor:pointer;max-width:140px;line-height:1.3}' +
            '#tl-inspector .tl-frz input{margin:0 1px 0 0}' +
            '#tl-inspector .tl-btn:hover,#tl-inspector .tl-tab:hover{filter:brightness(1.3)}' +
            '#tl-inspector .tl-row{border:1px solid #2b2f3a;border-radius:6px;padding:6px 8px;margin:0 0 6px;background:#1b1e26}' +
            '#tl-inspector .tl-row.live{border-color:#3a7;background:#1b2620}' +
            '#tl-inspector .tl-txt{color:#fff;white-space:pre-wrap;word-break:break-word;margin-bottom:4px;' +
                '-webkit-user-select:text;user-select:text;cursor:text}' +
            '#tl-inspector .tl-meta{color:#8aa;font-size:11px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}' +
            '#tl-inspector .tl-loc{color:#9cd;cursor:pointer;text-decoration:underline}' +
            '#tl-inspector .tl-badge{font-size:10px;padding:0 5px;border-radius:8px;background:#345}' +
            '#tl-inspector .tl-badge.choice{background:#534}' +
            '#tl-inspector .tl-badge.ui{background:#553}' +
            '#tl-inspector .tl-badge.live{background:#3a7;color:#022}' +
            '#tl-inspector .tl-mini{cursor:pointer;color:#cda;background:#2a2f3a;padding:1px 7px;border-radius:4px;white-space:nowrap}' +
            '#tl-inspector .tl-mini:hover{background:#363c4a;color:#eda}' +
            '#tl-inspector .tl-imgwrap{display:flex;gap:8px;align-items:flex-start}' +
            '#tl-inspector .tl-thumb{width:60px;height:60px;object-fit:contain;border:1px solid #333;border-radius:4px;flex:0 0 auto;' +
                'background-image:linear-gradient(45deg,#2a2a2a 25%,transparent 25%),linear-gradient(-45deg,#2a2a2a 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#2a2a2a 75%),linear-gradient(-45deg,transparent 75%,#2a2a2a 75%);background-size:12px 12px;background-position:0 0,0 6px,6px -6px,-6px 0;background-color:#15171d;image-rendering:pixelated}' +
            '#tl-inspector .tl-noimg{display:flex;align-items:center;justify-content:center;color:#556;font-size:18px}' +
            '#tl-inspector .tl-imginfo{flex:1;min-width:0}' +
            '#tl-inspector .tl-dups{margin-top:6px;padding:4px 0 2px 8px;border-left:2px solid #46506a}' +
            '#tl-inspector .tl-dup{color:#9cd;cursor:pointer;text-decoration:underline;display:block;margin:2px 0}' +
            '#tl-inspector .tl-bar{margin:0 0 8px;color:#9ab}' +
            '#tl-inspector .tl-bar input{vertical-align:middle}' +
            '#tl-inspector .tl-empty{color:#778;padding:20px;text-align:center}';
        root.appendChild(style);

        document.body.appendChild(root);
        ui.root = root; ui.body = body;
        applySide();

        // Stop panel mouse/wheel/touch events from reaching the game's document-level
        // input handlers. Fixes: clicking the scrollbar/buttons driving the character,
        // and the mouse wheel not scrolling (the game preventDefault()s wheel events).
        ['mousedown', 'mouseup', 'click', 'dblclick', 'wheel', 'contextmenu',
         'touchstart', 'touchend', 'touchmove', 'pointerdown', 'pointerup'].forEach(function (t) {
            root.addEventListener(t, function (ev) { ev.stopPropagation(); }, false);
        });

        var frz = root.querySelector('[data-act="freeze"]');
        if (frz) {
            frz.addEventListener('change', function () {
                ui.freeze = this.checked;
                try { window.localStorage.setItem('tlins.freeze', ui.freeze ? '1' : ''); } catch (e) { /* ignore */ }
                toast(ui.freeze ? 'Game controls frozen while editor is open' : 'Game controls unfrozen');
            });
        }

        // Editor dropdown: list every detected external editor; only shown when the
        // built-in editor is NOT selected (since then clicks open externally).
        var edsel = root.querySelector('[data-act="edsel"]');
        function syncEdsel() {
            if (!edsel) { return; }
            edsel.style.display = ui.useBuiltin ? 'none' : '';
        }
        if (edsel) {
            var list = detectEditors();
            list.forEach(function (e) {
                var o = document.createElement('option');
                o.value = e.id; o.textContent = e.name;
                edsel.appendChild(o);
            });
            edsel.value = currentEditor().id;
            syncEdsel();
            edsel.addEventListener('change', function () {
                ui.editorId = this.value;
                try { window.localStorage.setItem('tlins.editor', ui.editorId); } catch (e) { /* ignore */ }
                toast('Results open in ' + currentEditor().name);
            });
        }

        var bld = root.querySelector('[data-act="builtin"]');
        if (bld) {
            bld.addEventListener('change', function () {
                ui.useBuiltin = this.checked;
                try { window.localStorage.setItem('tlins.builtin', ui.useBuiltin ? '1' : '0'); } catch (e) { /* ignore */ }
                syncEdsel();
                toast(ui.useBuiltin ? 'Results open in the built-in editor'
                                    : 'Results open in ' + currentEditor().name);
            });
        }

        head.addEventListener('click', function (ev) {
            var t = ev.target.getAttribute('data-tab');
            var a = ev.target.getAttribute('data-act');
            if (t) { ui.tab = t; if (t !== 'images' && ui.pick) { setPick(false); } render(); }
            else if (a === 'refresh') { refreshGameElements(); }
            else if (a === 'pick') { setPick(!ui.pick); }
            else if (a === 'flip') { flipSide(); }
            else if (a === 'close') { toggle(false); }
        });

        var hl = document.createElement('div');
        hl.style.cssText = 'position:fixed;border:2px solid #ff5;background:rgba(255,255,0,0.12);z-index:2147483645;pointer-events:none;display:none';
        document.body.appendChild(hl);
        ui.highlight = hl;

        var pl = document.createElement('div');
        pl.style.cssText = 'position:fixed;background:#000d;color:#9f9;padding:3px 7px;border-radius:4px;font:11px monospace;z-index:2147483647;pointer-events:none;display:none;max-width:60vw;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
        document.body.appendChild(pl);
        ui.pickLabel = pl;

        var hlz = document.createElement('div'); // container for multiple pick rects
        hlz.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483645;pointer-events:none;display:none';
        document.body.appendChild(hlz);
        ui.hlLayer = hlz;
        applyOverlayScale();
    }

    function setTabStyles() {
        var tabs = ui.root.querySelectorAll('.tl-tab');
        for (var i = 0; i < tabs.length; i++) {
            tabs[i].classList.toggle('on', tabs[i].getAttribute('data-tab') === ui.tab);
        }
        // Inspect only works on images, so only surface it on the Images tab.
        var insp = ui.root.querySelector('.tl-inspect');
        if (insp) { insp.style.display = (ui.tab === 'images') ? '' : 'none'; }
    }

    function esc(s) {
        return String(s).replace(/[&<>]/g, function (c) {
            return c === '&' ? '&amp;' : c === '<' ? '&lt;' : '&gt;';
        });
    }

    function render() {
        if (!ui.root || !ui.open) { return; }
        setTabStyles();
        var st = ui.body.scrollTop;               // preserve scroll across rebuilds
        ui.body.innerHTML = '';
        if (ui.tab === 'text') { renderText(); } else { renderImages(); }
        ui.body.scrollTop = st;
    }

    // Signature of what's currently on screen + how many thumbs are ready, so the
    // auto-refresh only rebuilds the Images tab when something actually changed
    // (otherwise the scrollbar would keep snapping back to the top).
    function onScreenSignature() {
        var urls = collectOnScreenImages().map(function (i) { return i.url; });
        var ready = urls.filter(function (u) { return thumbCache[u]; }).length;
        return urls.join('|') + '#' + ready + '#' + (ui.selection ? ui.selection.length : 0);
    }

    function renderText() {
        var bar = htmlEl('<div class="tl-bar" style="display:flex;align-items:center;gap:10px">' +
            '<label style="cursor:pointer"><input type="checkbox"' + (ui.ignoreNl ? ' checked' : '') +
            '> ignore line breaks (\\n) when matching</label>' +
            '<span style="flex:1"></span>' +
            '<span class="tl-mini" data-act="clearhist">Clear History (' + textRecords.length + ')</span></div>');
        bar.querySelector('input').addEventListener('change', function () {
            ui.ignoreNl = this.checked;
            try { window.localStorage.setItem('tlins.ignl', ui.ignoreNl ? '1' : ''); } catch (e) { /* ignore */ }
        });
        bar.querySelector('[data-act="clearhist"]').addEventListener('click', function () {
            textRecords.length = 0;
            currentGroup = -1;
            render();
        });
        ui.body.appendChild(bar);

        if (!textRecords.length) {
            ui.body.appendChild(htmlEl('<div class="tl-empty">No text captured yet.<br>Trigger a message in-game.</div>'));
            return;
        }
        var msgBusy = (typeof $gameMessage !== 'undefined') && $gameMessage && $gameMessage.isBusy && $gameMessage.isBusy();
        for (var i = textRecords.length - 1; i >= 0; i--) {
            var r = textRecords[i];
            if (!r.file) { resolveRecord(r); } // text-search fallback for identity misses
            var expText = (r.expText != null) ? r.expText : r.text; // format(): locate the template, not the output
            var loc = null;
            if (r.file && r.tail) {
                loc = (r.srcKind === 'meta') ? locateMetaValue(r.file, r.tail, expText)
                                             : locateLine(r.file, r.tail, expText);
            }
            var line = loc ? loc.line : (r.uiLine || null);
            var col = loc ? loc.col : (r.uiCol || null);
            var live = msgBusy && r.group === currentGroup && currentGroup !== -1;

            var row = document.createElement('div');
            row.className = 'tl-row' + (live ? ' live' : '');

            var fileShort = r.file ? r.file.replace(/^.*[\\\/]/, '') : null;
            var locText = fileShort ? (fileShort + (line ? ':' + line : ''))
                        : (r._ambig ? r._ambig + ' candidates — click "locate"' : r.label);

            row.innerHTML =
                '<div class="tl-txt">' + esc(r.text) + '</div>' +
                '<div class="tl-meta">' +
                    '<span class="tl-badge ' + r.kind + '">' + r.kind + '</span>' +
                    (live ? '<span class="tl-badge live">LIVE</span>' : '') +
                    '<span class="tl-loc">' + esc(locText) + '</span>' +
                    (r.srcKind && r.file ? '<span style="color:#8a9">' + esc(r.label) + '</span>' : '') +
                    (r.siteFile ? '<span class="tl-mini" data-act="site">drawn at ' +
                        esc((r.siteLabel || '').replace(/^.*\//, '')) + '</span>' : '') +
                    '<span class="tl-mini" data-act="dups">' +
                        (r.kind === 'ui' ? 'Locate In Files' : (r.file ? 'Find Duplicates' : 'Locate In Files')) + '</span>' +
                '</div>' +
                '<div class="tl-dups" style="display:none"></div>';

            (function (rec, ln, cl, rowEl) {
                var locEl = rowEl.querySelector('.tl-loc');
                if (locEl) {
                    locEl.addEventListener('click', function () {
                        if (rec.file) { openInEditor(rec.file, ln, cl); }
                        else { toast('Unresolved: ' + rec.label); }
                    });
                }
                var siteBtn = rowEl.querySelector('[data-act="site"]');
                if (siteBtn) {
                    siteBtn.addEventListener('click', function () {
                        openInEditor(rec.siteFile, rec.siteLine, null);
                    });
                }
                var dupBtn = rowEl.querySelector('[data-act="dups"]');
                var dupsEl = rowEl.querySelector('.tl-dups');
                if (dupBtn) {
                    dupBtn.addEventListener('click', function () {
                        if (dupsEl.style.display === 'none') {
                            dupsEl.style.display = 'block';
                            dupsEl.innerHTML = '<span style="color:#778">searching…</span>';
                            setTimeout(function () { populateDups(dupsEl, rec); }, 0);
                        } else { dupsEl.style.display = 'none'; }
                    });
                }
            })(r, line, col, row);

            ui.body.appendChild(row);
        }
    }

    function populateDups(container, rec) {
        container.innerHTML = '';
        var MAXSHOW = 150;
        var note = '', total = 0, shown = [];

        if (rec.kind === 'ui') {
            // UI/plugin text: literal search across data + plugin files.
            var s = searchFilesSmart(rec.text);
            total = s.results.length;
            note = total + ' match' + (total === 1 ? '' : 'es') +
                (s.partial ? ' for "' + s.query + '" (value part omitted)' : '');
            shown = s.results.slice(0, MAXSHOW).map(function (o) { return { file: o.file, line: o.line, col: o.col, quoted: o.quoted }; });
        } else {
            // Dialogue/choice text: list every identical line in the data files.
            // IMPORTANT: slice BEFORE resolving line numbers — a frequent speaker name
            // ("Yui") has thousands of hits and locating every one would freeze the game.
            var occ = findOccurrences(rec.text, ui.ignoreNl);
            total = occ.length;
            note = total + ' occurrence' + (total === 1 ? '' : 's') + (ui.ignoreNl ? ' (ignoring \\n)' : '');
            shown = occ.slice(0, MAXSHOW).map(function (o) {
                var l = locateLine(o.file, o.path, o.text);
                return { file: o.file, line: l && l.line, col: l && l.col,
                         isSelf: rec.file === o.file && JSON.stringify(rec.tail) === JSON.stringify(o.path) };
            });
        }

        if (!total) {
            container.innerHTML = '<span style="color:#778">no matches found' +
                (rec.kind === 'ui' ? ' (text may be built at runtime)' : '') + '</span>';
            return;
        }
        var head = htmlEl('<div style="color:#9ab;margin-bottom:3px">' + note +
            (total > MAXSHOW ? ' &mdash; showing first ' + MAXSHOW : '') +
            ' &nbsp;<span class="tl-mini" data-act="openall">Open All (' + shown.length + ')</span></div>');
        container.appendChild(head);
        shown.forEach(function (x) {
            var fn = x.file.replace(/^.*[\\\/]/, '');
            // For UI/file searches, flag whether the match is the WHOLE string value
            // ("exact") or just contained inside a longer one ("within longer text").
            var tag = (x.quoted === true) ? ' <span style="color:#7d7">exact</span>'
                    : (x.quoted === false) ? ' <span style="color:#c99">within longer text</span>' : '';
            var el = htmlEl('<span class="tl-dup">' + esc(fn) + (x.line ? ':' + x.line : '') + tag +
                (x.isSelf ? '  <span style="color:#7a7">(this line)</span>' : '') + '</span>');
            el.addEventListener('click', function () { openInEditor(x.file, x.line, x.col); });
            container.appendChild(el);
        });
        head.querySelector('[data-act="openall"]').addEventListener('click', function () {
            if (shown.length > 8 && !window.confirm('Open ' + shown.length + ' files in the editor?')) { return; }
            shown.forEach(function (x) { openInEditor(x.file, x.line, x.col); });
        });
    }

    function renderImages() {
        // Objects captured from an Inspect click (the full stack under the cursor)
        if (ui.selection && ui.selection.length) {
            var selHead = htmlEl('<div style="color:#fd6;margin:2px 0 6px;display:flex;align-items:center;gap:8px">' +
                '<b>Under cursor (' + ui.selection.length + ')</b>' +
                '<span class="tl-mini" data-act="clearsel">Clear</span></div>');
            selHead.querySelector('[data-act="clearsel"]').addEventListener('click', function () { ui.selection = null; render(); });
            ui.body.appendChild(selHead);
            ui.selection.forEach(function (sel) {
                ui.body.appendChild(buildImgRow(sel.url, sel.bitmap, { screen: sel.screen }));
            });
            ui.body.appendChild(htmlEl('<hr style="border:none;border-top:1px solid #333;margin:10px 0">'));
        }

        var live = collectOnScreenImages();
        ui.body.appendChild(htmlEl('<div style="color:#9cd;margin:2px 0 6px">On screen now (' + live.length + ')</div>'));
        if (!live.length) {
            ui.body.appendChild(htmlEl('<div class="tl-empty">No image sprites on screen.</div>'));
        }
        live.forEach(function (img) {
            ui.body.appendChild(buildImgRow(img.url, img.bitmap, { screen: img.screen, trigger: imageTriggers[img.url] }));
        });

        // recent loads (history)
        ui.body.appendChild(htmlEl('<div style="color:#9cd;margin:12px 0 6px">Recently loaded</div>'));
        for (var i = imageLog.length - 1; i >= 0 && i > imageLog.length - 25; i--) {
            var it = imageLog[i];
            ui.body.appendChild(buildImgRow(it.url, it.bitmap, { fromLabel: it.label }));
        }
    }

    function htmlEl(html) {
        var d = document.createElement('div');
        d.innerHTML = html;
        return d.firstChild;
    }

    function showHighlight(s) {
        if (!s || !ui.highlight) { return; }
        var h = ui.highlight;
        h.style.left = s.x + 'px'; h.style.top = s.y + 'px';
        h.style.width = s.w + 'px'; h.style.height = s.h + 'px';
        h.style.display = 'block';
    }
    function hideHighlight() { if (ui.highlight) { ui.highlight.style.display = 'none'; } }

    //=========================================================================
    // Inspect / pick mode: hover the game canvas to highlight the image object
    // under the cursor (topmost), click to reveal its source file.
    //=========================================================================
    function canvasScale(rect) {
        return (rect && typeof Graphics !== 'undefined' && Graphics.width) ? rect.width / Graphics.width : 1;
    }

    function boundsToScreen(b, rect, scale) {
        return { x: rect.left + b.x * scale, y: rect.top + b.y * scale,
                 w: b.width * scale, h: b.height * scale };
    }

    // ALL bitmap objects whose bounds contain the point, bottom-to-top draw order.
    function hitTestAll(stageX, stageY) {
        var scene = (typeof SceneManager !== 'undefined') && SceneManager._scene;
        var hits = [];
        if (!scene) { return hits; }
        (function walk(obj) {
            if (!obj || obj.visible === false) { return; }
            var bmp = obj.bitmap;
            if (bmp && bmp._url) {
                var vis = ('worldVisible' in obj) ? obj.worldVisible : true;
                if (vis) {
                    var b = null;
                    try { b = obj.getBounds && obj.getBounds(); } catch (e) { b = null; }
                    if (b && b.width > 0 && b.height > 0 &&
                        stageX >= b.x && stageX <= b.x + b.width &&
                        stageY >= b.y && stageY <= b.y + b.height) {
                        hits.push({ url: decodeUrl(bmp._url), bounds: b, bitmap: bmp });
                    }
                }
            }
            var kids = obj.children;
            if (kids) { for (var i = 0; i < kids.length; i++) { walk(kids[i]); } }
        })(scene);
        return hits; // index 0 = bottom-most, last = top-most
    }

    function showHighlights(rects) { // multiple rects; last (top-most) is brighter
        var layer = ui.hlLayer;
        if (!layer) { return; }
        layer.innerHTML = '';
        rects.forEach(function (r, i) {
            var top = i === rects.length - 1;
            var d = document.createElement('div');
            d.style.cssText = 'position:fixed;pointer-events:none;left:' + r.x + 'px;top:' + r.y +
                'px;width:' + r.w + 'px;height:' + r.h + 'px;border:2px ' +
                (top ? 'solid #ff5' : 'dashed #6cf') + ';background:' +
                (top ? 'rgba(255,255,0,0.12)' : 'rgba(80,170,255,0.06)');
            layer.appendChild(d);
        });
        layer.style.display = 'block';
    }
    function hideHighlights() { if (ui.hlLayer) { ui.hlLayer.innerHTML = ''; ui.hlLayer.style.display = 'none'; } }

    function onPickMove(ev) {
        var canvas = getGameCanvas();
        if (!canvas) { return; }
        var rect = canvas.getBoundingClientRect();
        var scale = canvasScale(rect);
        var sx = (ev.clientX - rect.left) / scale, sy = (ev.clientY - rect.top) / scale;
        var hits = hitTestAll(sx, sy);
        if (hits.length) {
            showHighlights(hits.map(function (h) { return boundsToScreen(h.bounds, rect, scale); }));
            var topName = hits[hits.length - 1].url.replace(/^.*\//, '');
            ui.pickLabel.innerHTML =
                (hits.length > 1 ? '<b>' + hits.length + ' objects here</b> &mdash; click to list<br>' : '') +
                'top: ' + esc(topName);
            ui.pickLabel.style.left = Math.min(ev.clientX + 12, window.innerWidth - 260) + 'px';
            ui.pickLabel.style.top = (ev.clientY + 14) + 'px';
            ui.pickLabel.style.display = 'block';
            ui._pickHits = hits.map(function (h) {
                return { url: h.url, bitmap: h.bitmap, screen: boundsToScreen(h.bounds, rect, scale) };
            });
        } else {
            hideHighlights();
            ui.pickLabel.style.display = 'none';
            ui._pickHits = null;
        }
    }

    // Click does NOT open anything: it lists every object under the cursor in the
    // panel, where the user can highlight/reveal each one deliberately.
    function onPickClick(ev) {
        ev.preventDefault(); ev.stopPropagation();
        var hits = ui._pickHits;
        setPick(false);
        if (hits && hits.length) {
            ui.selection = hits;
            ui.tab = 'images';
            render();
        }
    }

    function setPick(on) {
        buildUI();
        ui.pick = !!on;
        var btn = ui.root.querySelector('[data-act="pick"]');
        if (btn) { btn.classList.toggle('on', ui.pick); }
        if (ui.pick) {
            var canvas = getGameCanvas();
            var rect = canvas ? canvas.getBoundingClientRect() : { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight };
            if (!ui.catcher) {
                ui.catcher = document.createElement('div');
                ui.catcher.style.cssText = 'position:fixed;z-index:2147483644;cursor:crosshair;background:transparent';
                document.body.appendChild(ui.catcher);
                ui.catcher.addEventListener('mousemove', onPickMove);
                ui.catcher.addEventListener('click', onPickClick, true);
                // Swallow all pointer input over the canvas while inspecting, so the
                // game never reacts (this also keeps "freeze" effective during Inspect).
                ['mousedown', 'mouseup', 'dblclick', 'wheel', 'contextmenu', 'mousemove',
                 'touchstart', 'touchmove', 'touchend', 'pointerdown', 'pointerup', 'pointermove'].forEach(function (t) {
                    ui.catcher.addEventListener(t, function (e) { e.stopPropagation(); }, false);
                });
            }
            ui.catcher.style.left = rect.left + 'px';
            ui.catcher.style.top = rect.top + 'px';
            ui.catcher.style.width = rect.width + 'px';
            ui.catcher.style.height = rect.height + 'px';
            ui.catcher.style.display = 'block';
            toast('Inspect: hover an object, click to reveal. Esc/Inspect to exit.');
        } else {
            if (ui.catcher) { ui.catcher.style.display = 'none'; }
            hideHighlight();
            hideHighlights();
            if (ui.pickLabel) { ui.pickLabel.style.display = 'none'; }
        }
    }

    var refreshPending = false;
    function scheduleRefresh() {
        if (refreshPending || !ui.open) { return; }
        refreshPending = true;
        setTimeout(function () { refreshPending = false; render(); }, 60);
    }

    function toggle(force) {
        buildUI();
        ui.open = (typeof force === 'boolean') ? force : !ui.open;
        ui.root.style.display = ui.open ? 'flex' : 'none';
        if (!ui.open && ui.pick) { setPick(false); }
        hideHighlight();
        if (ui.open) {
            render();
            if (!ui.refreshTimer) {
                ui.refreshTimer = setInterval(function () {
                    if (ui.open && ui.tab === 'images') {
                        var sig = onScreenSignature();
                        if (sig !== ui._imgSig) { ui._imgSig = sig; render(); }
                    }
                }, 700);
            }
        }
    }

    //=========================================================================
    // Toast
    //=========================================================================
    var toastEl = null, toastTimer = 0;
    function toast(msg) {
        if (!toastEl) {
            toastEl = document.createElement('div');
            toastEl.style.cssText = 'position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:#222;color:#fff;padding:8px 14px;border-radius:6px;z-index:2147483647;font:12px monospace;box-shadow:0 2px 8px rgba(0,0,0,.5)';
            document.body.appendChild(toastEl);
        }
        toastEl.textContent = msg;
        toastEl.style.display = 'block';
        clearTimeout(toastTimer);
        toastTimer = setTimeout(function () { toastEl.style.display = 'none'; }, 2600);
    }

    //=========================================================================
    // Hotkey
    //=========================================================================
    document.addEventListener('keydown', function (e) {
        if (e.key === CFG.hotkey) {
            e.preventDefault();
            e.stopPropagation();
            toggle();
        } else if (e.key === 'Escape' && ui.pick) {
            e.preventDefault();
            e.stopPropagation();
            setPick(false);
        }
    }, true);

    // "Freeze game controls" guard: when enabled and the editor is open, block input
    // events from reaching the game's document/window listeners. Events targeting the
    // panel (or the Inspect catcher) and our own hotkeys are always allowed through.
    function inPanel(node) {
        return !!(node && (
            (ui.root && ui.root.contains(node)) ||
            (ui.catcher && ui.catcher === node) ||
            (editor.root && editor.root.contains(node))   // built-in editor needs raw input
        ));
    }
    function freezeGuard(e) {
        if (!ui.open || !ui.freeze) { return; }
        if (inPanel(e.target)) { return; } // our panel / built-in editor get input untouched
        var isKey = (e.type === 'keydown' || e.type === 'keyup' || e.type === 'keypress');
        if (isKey) {
            if (e.key === CFG.hotkey || e.key === 'Escape') { return; } // hotkeys always work
            // Always block the game from seeing the key (stopPropagation), but do NOT
            // cancel the browser default for copy/select shortcuts (Ctrl+C / Ctrl+A) so
            // the user can still copy selected text from the panel.
            e.stopPropagation();
            if (e.stopImmediatePropagation) { e.stopImmediatePropagation(); }
            if (e.cancelable && !(e.ctrlKey || e.metaKey)) { e.preventDefault(); }
            return;
        }
        if (inPanel(e.target)) { return; } // let the panel receive mouse/wheel/touch
        e.stopPropagation();
        if (e.stopImmediatePropagation) { e.stopImmediatePropagation(); }
        if (e.cancelable) { e.preventDefault(); }
    }
    ['mousedown', 'mouseup', 'click', 'dblclick', 'wheel', 'mousemove', 'contextmenu',
     'touchstart', 'touchmove', 'touchend', 'keydown', 'keyup', 'keypress',
     'pointerdown', 'pointerup', 'pointermove'].forEach(function (t) {
        window.addEventListener(t, freezeGuard, true); // capture: runs before game handlers
    });

    window.TLInspector = {
        open: function () { toggle(true); },
        close: function () { toggle(false); },
        records: textRecords,
        images: imageLog,
        // debug/testing helpers
        resolveUiSource: resolveUiSource,   // drawn string -> value-source descriptor
        locateMetaValue: locateMetaValue,
        searchFilesSmart: searchFilesSmart,
        cfg: CFG
    };

    log('ready - press ' + CFG.hotkey + ' to open');
})();
