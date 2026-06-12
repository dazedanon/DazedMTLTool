//=============================================================================
// TLInspector.js
// Idea by Sakura · Plugin by kaoss
//=============================================================================
/*:
 * @plugindesc Translation Source Inspector - shows which source file/line every
 * on-screen line of text and image comes from, and jumps to it in VSCode.
 * @author kaoss
 *
 * @help
 * ----------------------------------------------------------------------------
 * TLInspector  (RPGMaker MV / MZ, NW.js)
 * Credits: Idea by Sakura · Plugin by kaoss
 * ----------------------------------------------------------------------------
 * A drop-in proofreading aid for translators. While the game runs, it tracks
 * every message / choice / scrolling-text line and every on-screen image, and
 * maps each one back to its EXACT source file and line number:
 *
 *   - Dialogue / choices / scroll text  -> www/data/MapXXX.json,
 *     CommonEvents.json, Troops.json  (by identity-matching the running event
 *     list, so duplicate strings are never confused).
 *   - Pictures and other images        -> img/... path + the event command
 *     (or JS call stack) that loaded them.
 *
 * Press the hotkey (default F10) to open the inspector overlay. Each row has an
 * "Open in VSCode" button (runs `code -g file:line`) and an **edit** button to
 * change the text and save it back to the source file without leaving the game.
 *
 * Live refresh (NW.js playtest only):
 *   In-game overlay "save to file" reloads that JSON into memory immediately.
 *   VSCode / external saves: we watch data/*.json; once the file mtime is stable
 *   (save finished), reload instantly. The game cannot hook Ctrl+S in VSCode itself.
 *   F9 — manual reload of all database JSON + the current map
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
        hotkey: 'F10',          // key (event.key) that toggles the overlay
        editorCmd: 'auto',      // 'auto' = find VSCode automatically (no PATH setup
                                // needed). Or set an absolute path to any editor exe.
        workspaceFolder: 'auto',// 'auto' = open files inside the game ROOT folder as the
                                // VSCode workspace (so they don't land in whatever window
                                // happened to be open last). Or set an absolute folder.
        editorReuseWindow: true,// pass -r so VSCode reuses its current window
        historySize: 80,        // how many past text lines to keep
        captureUiText: true,    // capture plugin / menu / UI text drawn via Bitmap.drawText
                                // (so e.g. status-window strings from plugins.js are locatable)
        liveEdit: true,         // allow saving edited text back to the source file in-game
        liveRefresh: true,      // auto-reload data/*.json when files change on disk (NW.js)
        liveRefreshStableMs: 120,// VSCode save: reload once mtime unchanged this long
        liveRefreshPollMs: 400,  // how often we check data/*.json for external saves
        liveRefreshHotkey: 'F9',// manual reload: all DB JSON + current map
        dataDirOverride: null   // set an absolute path to force the data dir
    };

    if (!CFG.enabled) { return; }

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

    function log() {
        if (window.console) { console.log.apply(console, ['[TLInspector]'].concat([].slice.call(arguments))); }
    }
    log('init', { engine: ENGINE, node: nodeOk, dataDir: DATA_DIR, credits: 'Idea by Sakura · Plugin by kaoss' });

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
    function scanString(t, i) { // i at opening " -> returns index after closing "
        return scanQuotedString(t, i, '"');
    }
    function scanQuotedString(t, i, q) {
        if (!q) { q = t[i]; }
        if (q !== '"' && q !== "'") { return i; }
        i++; // past opening quote
        while (i < t.length) {
            var ch = t[i];
            if (ch === '\\') { i += 2; continue; }
            if (ch === q) { return i + 1; }
            i++;
        }
        return i;
    }
    function decodeStringLiteral(t, startOff) {
        var q = t[startOff];
        if (q !== '"' && q !== "'") { return null; }
        var j = startOff + 1, out = '';
        while (j < t.length) {
            var ch = t[j];
            if (ch === '\\') {
                j++;
                if (j >= t.length) { return null; }
                var e = t[j];
                if (e === 'n') { out += '\n'; }
                else if (e === 'r') { out += '\r'; }
                else if (e === 't') { out += '\t'; }
                else if (e === 'b') { out += '\b'; }
                else if (e === 'f') { out += '\f'; }
                else if (e === 'u') {
                    var hex = t.substr(j + 1, 4);
                    if (!/^[0-9a-fA-F]{4}$/.test(hex)) { return null; }
                    out += String.fromCharCode(parseInt(hex, 16));
                    j += 4;
                } else { out += e; }
                j++;
                continue;
            }
            if (ch === q) {
                return { start: startOff, end: j, quote: q, value: out };
            }
            out += ch;
            j++;
        }
        return null;
    }
    function encodeStringLiteral(text, quoteChar) {
        if (quoteChar === "'") {
            return "'" + String(text).replace(/\\/g, '\\\\').replace(/'/g, "\\'")
                .replace(/\r/g, '\\r').replace(/\n/g, '\\n').replace(/\t/g, '\\t') + "'";
        }
        return JSON.stringify(text);
    }
    // Scan a line for quoted literals whose decoded value exactly equals expectedText.
    function findExactStringLiteralOnLine(c, line, expectedText) {
        if (!c || !line || expectedText == null) { return null; }
        var lineStart = c.lineStarts[line - 1];
        if (lineStart == null) { return null; }
        var lineEnd = line < c.lineStarts.length ? c.lineStarts[line] : c.text.length;
        var i = lineStart, best = null;
        while (i < lineEnd) {
            var ch = c.text[i];
            if (ch === '"' || ch === "'") {
                var lit = decodeStringLiteral(c.text, i);
                if (lit) {
                    if (lit.value === expectedText) { best = lit; }
                    i = lit.end + 1;
                    continue;
                }
            }
            i++;
        }
        return best;
    }
    // Resolve a safe edit target: the whole string literal whose value matches expectedText.
    function resolveEditSite(file, line, col, expectedText) {
        var c = readFileCached(file);
        if (!c || !line || expectedText == null) { return null; }
        var lit = findExactStringLiteralOnLine(c, line, expectedText);
        if (lit) { return lit; }
        // Fallback: literal containing the column, but only if the WHOLE value matches.
        var pos = c.lineStarts[line - 1] + Math.max(0, (col || 1) - 1);
        var lineStart = c.lineStarts[line - 1];
        var lineEnd = line < c.lineStarts.length ? c.lineStarts[line] : c.text.length;
        var i = lineStart;
        while (i < lineEnd) {
            var ch = c.text[i];
            if (ch === '"' || ch === "'") {
                var candidate = decodeStringLiteral(c.text, i);
                if (candidate) {
                    if (pos > candidate.start && pos < candidate.end &&
                        candidate.value === expectedText) {
                        return candidate;
                    }
                    i = candidate.end + 1;
                    continue;
                }
            }
            i++;
        }
        return null;
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

    var lineCache = {}; // file::pathKey::mtime -> {line,col}
    function locateLine(file, pathArr) {
        if (!file || !pathArr || !nodeOk) { return null; }
        var c = readFileCached(file);
        if (!c) { return null; }
        var key = file + '::' + pathArr.join('/') + '::' + c.mtime;
        if (lineCache[key]) { return lineCache[key]; }
        var off = locateOffset(c.text, pathArr);
        var res = off >= 0 ? offsetToLineCol(c, off) : null;
        lineCache[key] = res;
        return res;
    }

    function invalidateFileCache(file) {
        delete fileCache[file];
        Object.keys(lineCache).forEach(function (k) {
            if (k.indexOf(file + '::') === 0) { delete lineCache[k]; }
        });
        dupIndex = null;
    }

    function writeStringAtOffset(file, startOff, newText, expectedOld, quoteChar) {
        var c = readFileCached(file);
        if (!c) { return { ok: false, err: 'read failed' }; }
        var t = c.text;
        var lit = decodeStringLiteral(t, startOff);
        if (!lit) { return { ok: false, err: 'not a complete string literal' }; }
        if (expectedOld != null && lit.value !== expectedOld) {
            return { ok: false, err: 'on-disk text differs from the captured line — use VSCode instead' };
        }
        var q = quoteChar || lit.quote;
        var repl = encodeStringLiteral(newText, q);
        var merged = t.slice(0, lit.start) + repl + t.slice(lit.end + 1);
        try {
            fs.writeFileSync(file, merged, 'utf8');
        } catch (e) { return { ok: false, err: String(e.message || e) }; }
        invalidateFileCache(file);
        markSelfWrite(file);
        return { ok: true };
    }

    function writeAtPath(file, pathArr, newText, expectedOld) {
        var c = readFileCached(file);
        if (!c) { return { ok: false, err: 'read failed' }; }
        var off = locateOffset(c.text, pathArr);
        if (off < 0) { return { ok: false, err: 'could not locate value' }; }
        if (c.text[off] !== '"') {
            return { ok: false, err: 'JSON value at path is not a string' };
        }
        return writeStringAtOffset(file, off, newText, expectedOld, '"');
    }

    function writeAtEditSite(file, site, newText, expectedOld) {
        if (!site) { return { ok: false, err: 'no edit target' }; }
        return writeStringAtOffset(file, site.start, newText, expectedOld, site.quote);
    }

    function memoryRootForFile(file) {
        if (!path) { return null; }
        var fname = path.basename(file);
        if (/^Map\d+\.json$/i.test(fname)) {
            if (typeof $dataMap === 'undefined' || !$dataMap) { return null; }
            if (typeof $gameMap !== 'undefined' && $gameMap && $gameMap.mapId) {
                var mapId = parseInt(fname.match(/\d+/)[0], 10);
                if ($gameMap.mapId() !== mapId) { return null; }
            }
            return $dataMap;
        }
        if (fname === 'CommonEvents.json') {
            return (typeof $dataCommonEvents !== 'undefined') ? $dataCommonEvents : null;
        }
        if (fname === 'Troops.json') {
            return (typeof $dataTroops !== 'undefined') ? $dataTroops : null;
        }
        return null;
    }

    function setAtPath(root, pathArr, val) {
        var o = root;
        for (var i = 0; i < pathArr.length - 1; i++) {
            o = o[pathArr[i]];
            if (o == null) { return false; }
        }
        o[pathArr[pathArr.length - 1]] = val;
        return true;
    }

    function applyLiveMessage(rec, newText) {
        if (typeof $gameMessage === 'undefined' || !$gameMessage) { return; }
        var busy = $gameMessage.isBusy && $gameMessage.isBusy();
        if (!busy || rec.group !== currentGroup || currentGroup === -1) { return; }
        try {
            if ($gameMessage._texts) {
                for (var i = 0; i < $gameMessage._texts.length; i++) {
                    if ($gameMessage._texts[i] === rec.text) { $gameMessage._texts[i] = newText; }
                }
            }
            if ($gameMessage._choices) {
                for (var j = 0; j < $gameMessage._choices.length; j++) {
                    if ($gameMessage._choices[j] === rec.text) { $gameMessage._choices[j] = newText; }
                }
            }
        } catch (e) { /* ignore */ }
    }

    function canEditRecord(rec) {
        if (!CFG.liveEdit || !nodeOk || rec._ambig) { return false; }
        if (rec.file && rec.tail) { return true; }
        if (rec.file && rec._editSite) { return true; }
        return false;
    }

    function bindEditSite(rec, file, line, col) {
        var site = resolveEditSite(file, line, col, rec.text);
        if (!site) {
            return false;
        }
        rec.file = file;
        rec._editSite = site;
        rec._editLine = line;
        rec._editCol = col || 1;
        delete rec._editQuoted;
        return true;
    }

    function isDataJsonFile(file) {
        if (!file || !path) { return false; }
        try {
            var ap = absPath(file);
            var dir = absPath(DATA_DIR);
            if (process.platform === 'win32') {
                return ap.toLowerCase().indexOf(dir.toLowerCase()) === 0 && /\.json$/i.test(ap);
            }
            return ap.indexOf(dir) === 0 && /\.json$/i.test(ap);
        } catch (e) { return false; }
    }

    function applyReloadAfterOverlaySave(file) {
        if (!CFG.liveRefresh || !isDataJsonFile(file)) { return false; }
        return reloadFile(file, { silent: true });
    }

    function saveRecordEdit(rec, newText) {
        if (!nodeOk) { toast('Live edit requires the desktop NW.js build'); return false; }
        if (newText === rec.text) { toast('No changes'); return false; }
        var expected = rec.text;
        var r;
        if (rec.file && rec.tail) {
            r = writeAtPath(rec.file, rec.tail, newText, expected);
        } else if (rec.file && rec._editSite) {
            r = writeAtEditSite(rec.file, rec._editSite, newText, expected);
        } else if (rec.file && (rec._editLine || rec.uiLine)) {
            var site = resolveEditSite(rec.file, rec._editLine || rec.uiLine,
                rec._editCol || 1, expected);
            if (!site) {
                toast('Cannot safely edit — pick an exact quoted string match first');
                return false;
            }
            rec._editSite = site;
            r = writeAtEditSite(rec.file, site, newText, expected);
        } else {
            toast('Cannot edit — source location unresolved');
            return false;
        }
        if (!r.ok) { toast('Save failed: ' + (r.err || '?')); log('save', r); return false; }
        rec.text = newText;
        rec._key = 't\u0000' + rec.kind + '\u0000' + newText + '\u0000' + (rec.file || '') +
            '\u0000' + (rec.tail ? JSON.stringify(rec.tail) : '');
        applyLiveMessage(rec, newText);
        var reloaded = applyReloadAfterOverlaySave(rec.file);
        if (!reloaded) { refreshSceneWindows(); }
        var note = rec.kind === 'ui' && !reloaded ? ' — UI may need scene change' : '';
        toast(reloaded ? 'Saved & reloaded' : ('Saved to file' + note));
        scheduleRefresh();
        return true;
    }

    function prepareUiEditTarget(rec, cb) {
        if (rec.tail) { cb(true); return; }
        var s = searchFilesSmart(rec.text);
        if (s.partial) {
            toast('Partial file match — live edit needs the full string; use VSCode');
            cb(false);
            return;
        }
        if (s.results.length === 1) {
            if (bindEditSite(rec, s.results[0].file, s.results[0].line, s.results[0].col)) {
                cb(true);
                return;
            }
            toast('Match is not a complete string value — use VSCode');
            cb(false);
            return;
        }
        if (s.results.length > 1) {
            toast(s.results.length + ' matches — use "locate in files" and pick an exact match');
            cb(false);
            return;
        }
        toast('No file match for this UI text');
        cb(false);
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
        textRecords.push({ kind: 'ui', text: text, file: site.file, prefix: null,
            tail: null, label: site.label, uiLine: site.line, group: -1, ts: Date.now(), _key: key });
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
    // Auto-locate VSCode so the user never has to touch the system PATH.
    var _editorPath = null;
    function detectEditor() {
        if (_editorPath !== null) { return _editorPath; }
        if (CFG.editorCmd && CFG.editorCmd !== 'auto') { _editorPath = CFG.editorCmd; return _editorPath; }
        if (nodeOk) {
            var env = process.env, plat = process.platform, cands = [];
            if (plat === 'win32') {
                [env.LOCALAPPDATA, env.ProgramFiles, env['ProgramFiles(x86)']].forEach(function (b) {
                    if (!b) { return; }
                    cands.push(path.join(b, 'Programs', 'Microsoft VS Code', 'Code.exe'));
                    cands.push(path.join(b, 'Microsoft VS Code', 'Code.exe'));
                    cands.push(path.join(b, 'Programs', 'Microsoft VS Code Insiders', 'Code - Insiders.exe'));
                });
            } else if (plat === 'darwin') {
                cands.push('/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code');
            } else {
                cands.push('/usr/bin/code', '/usr/share/code/bin/code', '/snap/bin/code');
            }
            for (var i = 0; i < cands.length; i++) {
                try { if (fs.existsSync(cands[i])) { _editorPath = cands[i]; log('editor found', _editorPath); return _editorPath; } }
                catch (e) { /* ignore */ }
            }
        }
        _editorPath = 'code'; // fall back to PATH lookup
        return _editorPath;
    }

    function openInEditor(file, line, col) {
        if (!nodeOk || !file) { toast('No file resolved for this entry'); return; }
        var loc = file + (line ? ':' + line + (col ? ':' + col : '') : '');
        var cmd = detectEditor();
        // Pass the game folder so VSCode opens (or reuses) THAT workspace and reveals the
        // file in it, instead of dropping the file into whatever window was last focused.
        // Passing a folder makes VSCode route to the matching window itself, so we drop the
        // -r "reuse last window" flag (which is what caused the wrong-workspace behavior).
        var ws = (CFG.workspaceFolder && CFG.workspaceFolder !== 'auto') ? CFG.workspaceFolder : GAME_ROOT;
        var done = function (err) {
            if (err) { toast('Editor launch failed; set CFG.editorCmd to your editor path.'); log('editor', err); }
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
                        '<span class="tl-mini" data-act="reveal">reveal' + (ENC.on() ? ' (decrypt)' : '') + '</span>' +
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

    function collectMessages(absFile, fname, obj, emit) {
        function walkList(list, prefix) {
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
        if (/^Map\d+/.test(fname) && obj && obj.events) {
            obj.events.forEach(function (ev, e) {
                if (!ev || !ev.pages) { return; }
                ev.pages.forEach(function (pg, p) { walkList(pg.list, ['events', e, 'pages', p, 'list']); });
            });
        } else if (fname === 'CommonEvents.json' && Array.isArray(obj)) {
            obj.forEach(function (ce, c) { if (ce && ce.list) { walkList(ce.list, [c, 'list']); } });
        } else if (fname === 'Troops.json' && Array.isArray(obj)) {
            obj.forEach(function (tr, t) {
                if (tr && tr.pages) { tr.pages.forEach(function (pg, p) { walkList(pg.list, [t, 'pages', p, 'list']); }); }
            });
        }
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
                        // A complete JSON string value ("text") is a high-confidence
                        // match (e.g. a menu term) vs. text buried in a longer string.
                        var quoted = c.text[pos - 1] === '"' && c.text[pos + v.length] === '"';
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
    // Overlay UI
    //=========================================================================
    var ui = { root: null, body: null, tab: 'text', highlight: null, hlLayer: null,
               open: false, refreshTimer: 0, side: 'right', pick: false, catcher: null,
               pickLabel: null, _pickHits: null, selection: null, ignoreNl: false, freeze: false };
    try { ui.side = window.localStorage.getItem('tlins.side') || 'right'; } catch (e) { /* ignore */ }
    try { ui.ignoreNl = window.localStorage.getItem('tlins.ignl') === '1'; } catch (e) { /* ignore */ }
    try { ui.freeze = window.localStorage.getItem('tlins.freeze') === '1'; } catch (e) { /* ignore */ }

    function applySide() {
        if (!ui.root) { return; }
        var left = ui.side === 'left';
        ui.root.style.left = left ? '0' : 'auto';
        ui.root.style.right = left ? 'auto' : '0';
        ui.root.style.boxShadow = (left ? '2px' : '-2px') + ' 0 12px rgba(0,0,0,0.6)';
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
        head.style.cssText = 'padding:8px 10px;background:#11131a;border-bottom:1px solid #333;display:flex;align-items:center;gap:8px;flex:0 0 auto';
        head.innerHTML =
            '<b style="color:#6cf" title="Idea by Sakura · Plugin by kaoss">TL Inspector</b>' +
            '<span data-tab="text" class="tl-tab">Text</span>' +
            '<span data-tab="images" class="tl-tab">Images</span>' +
            '<span data-act="pick" class="tl-btn" title="Hover the game to highlight an object, click to reveal it">&#x2316; Inspect</span>' +
            '<label class="tl-btn tl-frz" title="Block mouse/keyboard from reaching the game while the editor is open">' +
                '<input type="checkbox" data-act="freeze"' + (ui.freeze ? ' checked' : '') + '> freeze</label>' +
            '<span style="flex:1"></span>' +
            '<span data-act="flip" class="tl-btn" title="Move panel to the other side">&#x21c4;</span>' +
            '<span data-act="refresh" class="tl-btn">&#x21bb;</span>' +
            '<span data-act="close" class="tl-btn">&#x2715;</span>';
        root.appendChild(head);

        var body = document.createElement('div');
        body.style.cssText = 'flex:1 1 auto;overflow:auto;padding:6px 8px';
        root.appendChild(body);

        var style = document.createElement('style');
        style.textContent =
            '#tl-inspector .tl-tab{cursor:pointer;padding:2px 8px;border-radius:4px;background:#222;color:#bbb}' +
            '#tl-inspector .tl-tab.on{background:#2a5db0;color:#fff}' +
            '#tl-inspector .tl-btn{cursor:pointer;padding:2px 7px;border-radius:4px;background:#333}' +
            '#tl-inspector .tl-btn.on{background:#3a7;color:#022}' +
            '#tl-inspector .tl-btn:hover,#tl-inspector .tl-tab:hover{filter:brightness(1.3)}' +
            '#tl-inspector .tl-row{border:1px solid #2b2f3a;border-radius:6px;padding:6px 8px;margin:0 0 6px;background:#1b1e26}' +
            '#tl-inspector .tl-row.live{border-color:#3a7;background:#1b2620}' +
            '#tl-inspector .tl-txt{color:#fff;white-space:pre-wrap;word-break:break-word;margin-bottom:4px;' +
                '-webkit-user-select:text;user-select:text;cursor:text}' +
            '#tl-inspector .tl-meta{color:#8aa;font-size:11px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}' +
            '#tl-inspector .tl-loc{color:#9cd;cursor:pointer;text-decoration:underline}' +
            '#tl-inspector .tl-badge{font-size:10px;padding:0 5px;border-radius:8px;background:#345}' +
            '#tl-inspector .tl-badge.choice{background:#534}' +
            '#tl-inspector .tl-badge.ui{background:#553}' +
            '#tl-inspector .tl-badge.live{background:#3a7;color:#022}' +
            '#tl-inspector .tl-mini{cursor:pointer;color:#cda;text-decoration:underline}' +
            '#tl-inspector .tl-imgwrap{display:flex;gap:8px;align-items:flex-start}' +
            '#tl-inspector .tl-thumb{width:60px;height:60px;object-fit:contain;border:1px solid #333;border-radius:4px;flex:0 0 auto;' +
                'background-image:linear-gradient(45deg,#2a2a2a 25%,transparent 25%),linear-gradient(-45deg,#2a2a2a 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#2a2a2a 75%),linear-gradient(-45deg,transparent 75%,#2a2a2a 75%);background-size:12px 12px;background-position:0 0,0 6px,6px -6px,-6px 0;background-color:#15171d;image-rendering:pixelated}' +
            '#tl-inspector .tl-noimg{display:flex;align-items:center;justify-content:center;color:#556;font-size:18px}' +
            '#tl-inspector .tl-imginfo{flex:1;min-width:0}' +
            '#tl-inspector .tl-dups{margin-top:6px;padding:4px 0 2px 8px;border-left:2px solid #46506a}' +
            '#tl-inspector .tl-dup{color:#9cd;cursor:pointer;text-decoration:underline;display:block;margin:2px 0}' +
            '#tl-inspector .tl-edit{margin-top:6px;display:none}' +
            '#tl-inspector .tl-edit textarea{width:100%;min-height:64px;box-sizing:border-box;' +
                'background:#0f1118;color:#fff;border:1px solid #46506a;border-radius:4px;' +
                'padding:6px 8px;font:inherit;resize:vertical}' +
            '#tl-inspector .tl-edit-actions{display:flex;gap:10px;margin-top:4px}' +
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
        // Keyboard: stop bubble propagation so RPG Maker's Input (window keydown)
        // never sees Enter/Backspace/etc. while typing in the panel or edit box.
        ['mousedown', 'mouseup', 'click', 'dblclick', 'wheel', 'contextmenu',
         'touchstart', 'touchend', 'touchmove', 'pointerdown', 'pointerup'].forEach(function (t) {
            root.addEventListener(t, function (ev) { ev.stopPropagation(); }, false);
        });
        ['keydown', 'keyup', 'keypress'].forEach(function (t) {
            root.addEventListener(t, function (ev) {
                if (ev.key === CFG.hotkey ||
                    (CFG.liveRefresh && ev.key === CFG.liveRefreshHotkey)) { return; }
                ev.stopPropagation();
            }, false);
        });

        var frz = root.querySelector('[data-act="freeze"]');
        if (frz) {
            frz.addEventListener('change', function () {
                ui.freeze = this.checked;
                try { window.localStorage.setItem('tlins.freeze', ui.freeze ? '1' : ''); } catch (e) { /* ignore */ }
                toast(ui.freeze ? 'Game controls frozen while editor is open' : 'Game controls unfrozen');
            });
        }

        head.addEventListener('click', function (ev) {
            var t = ev.target.getAttribute('data-tab');
            var a = ev.target.getAttribute('data-act');
            if (t) { ui.tab = t; render(); }
            else if (a === 'refresh') { render(); }
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
    }

    function setTabStyles() {
        var tabs = ui.root.querySelectorAll('.tl-tab');
        for (var i = 0; i < tabs.length; i++) {
            tabs[i].classList.toggle('on', tabs[i].getAttribute('data-tab') === ui.tab);
        }
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
            '<span class="tl-mini" data-act="clearhist">clear history (' + textRecords.length + ')</span></div>');
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
            var loc = (r.file && r.tail) ? locateLine(r.file, r.tail) : null;
            var line = loc ? loc.line : (r.uiLine || null);
            var col = loc ? loc.col : null;
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
                    '<span class="tl-mini" data-act="dups">' +
                        (r.kind === 'ui' ? 'locate in files' : (r.file ? 'find duplicates' : 'locate in files')) + '</span>' +
                    (canEditRecord(r) ? '<span class="tl-mini" data-act="edit">edit</span>' : '') +
                '</div>' +
                '<div class="tl-dups" style="display:none"></div>' +
                '<div class="tl-edit" style="display:none">' +
                    '<textarea spellcheck="false"></textarea>' +
                    '<div class="tl-edit-actions">' +
                        '<span class="tl-mini" data-act="save">save to file</span>' +
                        '<span class="tl-mini" data-act="canceledit">cancel</span>' +
                    '</div>' +
                '</div>';

            (function (rec, ln, cl, rowEl) {
                var locEl = rowEl.querySelector('.tl-loc');
                if (locEl) {
                    locEl.addEventListener('click', function () {
                        if (rec.file) { openInEditor(rec.file, ln, cl); }
                        else { toast('Unresolved: ' + rec.label); }
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
                var editPanel = rowEl.querySelector('.tl-edit');
                var editBtn = rowEl.querySelector('[data-act="edit"]');
                if (editBtn && editPanel) {
                    var ta = editPanel.querySelector('textarea');
                    editBtn.addEventListener('click', function () {
                        function openEditor() {
                            ta.value = rec.text;
                            editPanel.style.display = 'block';
                            ta.focus();
                            try { ta.setSelectionRange(ta.value.length, ta.value.length); } catch (e) { /* ignore */ }
                        }
                        if (rec.kind === 'ui' && !rec.tail && !rec._editSite) {
                            prepareUiEditTarget(rec, function (ok) { if (ok) { openEditor(); } });
                        } else {
                            openEditor();
                        }
                    });
                    editPanel.querySelector('[data-act="save"]').addEventListener('click', function () {
                        if (saveRecordEdit(rec, ta.value)) { editPanel.style.display = 'none'; }
                    });
                    editPanel.querySelector('[data-act="canceledit"]').addEventListener('click', function () {
                        editPanel.style.display = 'none';
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
                var l = locateLine(o.file, o.path);
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
            ' &nbsp;<span class="tl-mini" data-act="openall">open all (' + shown.length + ')</span></div>');
        container.appendChild(head);
        shown.forEach(function (x) {
            var fn = x.file.replace(/^.*[\\\/]/, '');
            // For UI/file searches, flag whether the match is the WHOLE string value
            // ("exact") or just contained inside a longer one ("within longer text").
            var tag = (x.quoted === true) ? ' <span style="color:#7d7">exact</span>'
                    : (x.quoted === false) ? ' <span style="color:#c99">within longer text</span>' : '';
            var el = htmlEl('<span class="tl-dup">' + esc(fn) + (x.line ? ':' + x.line : '') + tag +
                (x.isSelf ? '  <span style="color:#7a7">(this line)</span>' : '') + '</span>');
            el.addEventListener('click', function () {
                if (rec.kind === 'ui' && x.line) {
                    if (x.quoted === false) {
                        toast('Match is inside a longer string — pick an exact match or use VSCode');
                        return;
                    }
                    if (bindEditSite(rec, x.file, x.line, x.col || 1)) {
                        scheduleRefresh();
                        toast('Exact match selected — click edit to change this string');
                    } else {
                        toast('Could not bind a safe edit target — use VSCode');
                    }
                    return;
                }
                openInEditor(x.file, x.line, x.col);
            });
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
                '<span class="tl-mini" data-act="clearsel">clear</span></div>');
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
    // Live refresh — hot-reload data/*.json from external editor saves (NW.js)
    //=========================================================================
    var _selfWrittenFiles = {};   // absPath -> timestamp (skip watcher echo from overlay saves)
    var _pendingStable = {};      // absPath -> { lastMt, stableSince, timer }
    var _watcherStarted = false;
    var _pollTimer = null;
    var _watchScanTimer = 0;
    var _knownMtimes = {};        // absPath -> mtimeMs (poll-based change detection)
    var DB_FILES = {};            // 'Items.json' -> { global: '$dataItems', meta: true }

    function absPath(file) {
        if (!file || !path) { return file; }
        try { return path.resolve(file); } catch (e) { return file; }
    }

    function syncMtimeCache(file) {
        if (!nodeOk || !file) { return; }
        try {
            _knownMtimes[absPath(file)] = fs.statSync(absPath(file)).mtimeMs;
        } catch (e) { /* ignore */ }
    }

    function markSelfWrite(file) {
        if (!CFG.liveRefresh || !file) { return; }
        _selfWrittenFiles[absPath(file)] = Date.now();
        syncMtimeCache(file);
    }

    function isSelfWrite(file) {
        if (!file) { return false; }
        var key = absPath(file);
        var t = _selfWrittenFiles[key];
        if (!t) { return false; }
        var windowMs = (CFG.liveRefreshStableMs || 120) + 600;
        if (Date.now() - t < windowMs) { return true; }
        delete _selfWrittenFiles[key];
        return false;
    }

    function buildDbFileMap() {
        DB_FILES = {};
        var entries = (typeof DataManager !== 'undefined' && DataManager._databaseFiles)
            ? DataManager._databaseFiles : null;
        if (entries && entries.length) {
            entries.forEach(function (entry) {
                DB_FILES[entry.src] = {
                    global: entry.name,
                    meta: entry.src !== 'System.json'
                };
            });
            return;
        }
        // Fallback before DataManager is ready (MV/MZ standard database list)
        [
            ['Actors.json', '$dataActors', true],
            ['Classes.json', '$dataClasses', true],
            ['Skills.json', '$dataSkills', true],
            ['Items.json', '$dataItems', true],
            ['Weapons.json', '$dataWeapons', true],
            ['Armors.json', '$dataArmors', true],
            ['Enemies.json', '$dataEnemies', true],
            ['Troops.json', '$dataTroops', true],
            ['States.json', '$dataStates', true],
            ['Animations.json', '$dataAnimations', true],
            ['Tilesets.json', '$dataTilesets', true],
            ['CommonEvents.json', '$dataCommonEvents', true],
            ['System.json', '$dataSystem', false],
            ['MapInfos.json', '$dataMapInfos', true]
        ].forEach(function (row) {
            DB_FILES[row[0]] = { global: row[1], meta: row[2] };
        });
    }

    function parseMapId(fname) {
        var m = /^Map(\d+)\.json$/i.exec(fname || '');
        return m ? parseInt(m[1], 10) : null;
    }

    function loadJsonFromDisk(file) {
        var ap = absPath(file);
        invalidateFileCache(ap);
        return JSON.parse(fs.readFileSync(ap, 'utf8'));
    }

    function applyDatabaseGlobal(globalName, data, useMeta) {
        window[globalName] = data;
        if (useMeta && typeof DataManager !== 'undefined' && DataManager.extractArrayMetadata) {
            DataManager.extractArrayMetadata(data);
        }
    }

    function refreshSceneWindows() {
        try {
            var scene = (typeof SceneManager !== 'undefined') && SceneManager._scene;
            if (!scene || !scene._windowLayer) { return; }
            var kids = scene._windowLayer.children;
            if (!kids) { return; }
            for (var i = 0; i < kids.length; i++) {
                var w = kids[i];
                if (w && typeof w.refresh === 'function') {
                    try { w.refresh(); } catch (e) { /* ignore */ }
                }
            }
        } catch (e) { log('refreshSceneWindows', e); }
    }

    function reloadFile(filePath, options) {
        options = options || {};
        if (!nodeOk || !fs || !path) {
            if (!options.silent) { toast('Live refresh requires NW.js playtest'); }
            return false;
        }
        var ap = absPath(filePath);
        if (!fs.existsSync(ap)) {
            if (!options.silent) { toast('File not found: ' + path.basename(ap)); }
            return false;
        }
        var fname = path.basename(ap);
        if (!/\.json$/i.test(fname)) { return false; }

        try {
            var mapId = parseMapId(fname);
            if (mapId != null) {
                var currentMap = (typeof $gameMap !== 'undefined' && $gameMap && $gameMap.mapId)
                    ? $gameMap.mapId() : 0;
                if (currentMap !== mapId) {
                    syncMtimeCache(ap);
                    if (!options.silent) { toast('Map file saved (switch maps to apply)'); }
                    return true;
                }
                if (typeof $dataMap !== 'undefined') {
                    $dataMap = loadJsonFromDisk(ap);
                }
                syncMtimeCache(ap);
                if (!options.silent) { toast('Reloaded ' + fname); }
                refreshSceneWindows();
                return true;
            }

            if (!Object.keys(DB_FILES).length) { buildDbFileMap(); }
            var spec = DB_FILES[fname];
            if (spec) {
                applyDatabaseGlobal(spec.global, loadJsonFromDisk(ap), spec.meta);
                syncMtimeCache(ap);
                if (!options.silent) { toast('Reloaded ' + fname); }
                refreshSceneWindows();
                return true;
            }

            log('reload skip (unknown data file)', fname);
            return false;
        } catch (e) {
            log('reload failed', fname, e);
            if (!options.silent) { toast('Reload failed: ' + fname); }
            return false;
        }
    }

    function reloadAllForPlaytest() {
        if (!nodeOk) { toast('Live refresh requires NW.js playtest'); return; }
        if (!Object.keys(DB_FILES).length) { buildDbFileMap(); }
        var count = 0;
        Object.keys(DB_FILES).forEach(function (fname) {
            if (reloadFile(dataFile(fname), { silent: true })) { count++; }
        });
        var mapId = (typeof $gameMap !== 'undefined' && $gameMap && $gameMap.mapId)
            ? $gameMap.mapId() : 0;
        if (mapId > 0 && reloadFile(mapFile(mapId), { silent: true })) { count++; }
        refreshSceneWindows();
        toast('Reloaded database + current map (' + count + ' files)');
    }

    // VSCode (etc.) saves land on disk; wait until mtime stops changing, then reload.
    function scheduleFileReload(filePath) {
        if (!CFG.liveRefresh || !nodeOk) { return; }
        waitForStableThenReload(absPath(filePath));
    }

    function waitForStableThenReload(ap) {
        if (isSelfWrite(ap)) { return; }
        var stableMs = CFG.liveRefreshStableMs || 120;
        var checkMs = 50;
        if (!_pendingStable[ap]) {
            _pendingStable[ap] = { lastMt: null, stableSince: 0, timer: 0 };
        }
        if (_pendingStable[ap].timer) { clearTimeout(_pendingStable[ap].timer); }

        function tick() {
            if (isSelfWrite(ap)) {
                delete _pendingStable[ap];
                return;
            }
            try {
                if (!fs.existsSync(ap)) {
                    _pendingStable[ap].timer = setTimeout(tick, checkMs);
                    return;
                }
                var mt = fs.statSync(ap).mtimeMs;
                var p = _pendingStable[ap];
                if (p.lastMt !== mt) {
                    p.lastMt = mt;
                    p.stableSince = Date.now();
                } else if (Date.now() - p.stableSince >= stableMs) {
                    delete _pendingStable[ap];
                    reloadFile(ap);
                    return;
                }
                p.timer = setTimeout(tick, checkMs);
            } catch (e) {
                delete _pendingStable[ap];
            }
        }

        _pendingStable[ap].timer = setTimeout(tick, checkMs);
    }

    function seedMtimes() {
        if (!nodeOk) { return; }
        try {
            fs.readdirSync(DATA_DIR).forEach(function (fname) {
                if (!/\.json$/i.test(fname)) { return; }
                syncMtimeCache(path.join(DATA_DIR, fname));
            });
        } catch (e) { log('seedMtimes', e); }
    }

    function pollDataDirForChanges() {
        if (!CFG.liveRefresh || !nodeOk) { return; }
        try {
            var names = fs.readdirSync(DATA_DIR);
            for (var i = 0; i < names.length; i++) {
                var fname = names[i];
                if (!/\.json$/i.test(fname)) { continue; }
                var ap = path.join(DATA_DIR, fname);
                try {
                    var mt = fs.statSync(ap).mtimeMs;
                    var prev = _knownMtimes[ap];
                    if (prev != null && mt !== prev && !isSelfWrite(ap)) {
                        scheduleFileReload(ap);
                    } else {
                        _knownMtimes[ap] = mt;
                    }
                } catch (e2) { /* ignore */ }
            }
        } catch (e) { /* ignore */ }
    }

    function startLiveRefreshPoll() {
        if (_pollTimer || !CFG.liveRefresh || !nodeOk) { return; }
        seedMtimes();
        var ms = CFG.liveRefreshPollMs || 400;
        _pollTimer = setInterval(pollDataDirForChanges, ms);
        log('live refresh polling every', ms + 'ms');
    }

    function scheduleDataDirScan() {
        if (!CFG.liveRefresh) { return; }
        clearTimeout(_watchScanTimer);
        _watchScanTimer = setTimeout(pollDataDirForChanges, 200);
    }

    function startLiveRefreshWatcher() {
        if (!CFG.liveRefresh || !nodeOk || _watcherStarted) { return; }
        _watcherStarted = true;
        buildDbFileMap();
        startLiveRefreshPoll();
        try {
            fs.watch(DATA_DIR, function (eventType, filename) {
                if (filename && /\.json$/i.test(filename)) {
                    scheduleFileReload(path.join(DATA_DIR, filename));
                } else {
                    // Windows fs.watch often fires with a null filename
                    scheduleDataDirScan();
                }
            });
            log('live refresh watching', DATA_DIR);
        } catch (e) {
            log('live refresh watch failed (poll-only)', e);
        }
    }

    if (CFG.liveRefresh && nodeOk) {
        if (typeof DataManager !== 'undefined') {
            startLiveRefreshWatcher();
        } else {
            var _waitDbTimer = setInterval(function () {
                if (typeof DataManager !== 'undefined') {
                    clearInterval(_waitDbTimer);
                    startLiveRefreshWatcher();
                }
            }, 100);
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
        } else if (CFG.liveRefresh && e.key === CFG.liveRefreshHotkey) {
            e.preventDefault();
            e.stopPropagation();
            reloadAllForPlaytest();
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
        return !!(node && ui.root && (ui.root.contains(node) || (ui.catcher && ui.catcher === node)));
    }
    function isEditableInPanel(node) {
        if (!node || !ui.root || !ui.root.contains(node)) { return false; }
        var tag = node.tagName;
        return tag === 'TEXTAREA' || tag === 'INPUT' || node.isContentEditable;
    }
    function freezeGuard(e) {
        if (!ui.open || !ui.freeze) { return; }
        var isKey = (e.type === 'keydown' || e.type === 'keyup' || e.type === 'keypress');
        if (isKey) {
            if (e.key === CFG.hotkey || e.key === 'Escape' ||
                (CFG.liveRefresh && e.key === CFG.liveRefreshHotkey)) { return; }
            // Typing in the panel / edit box must keep normal browser behaviour
            // (Backspace, Enter for newlines, etc.) — only block keys aimed at the game.
            if (inPanel(e.target) || isEditableInPanel(document.activeElement)) { return; }
            // Block the game from seeing this key.
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
        reload: function (file) { return reloadFile(file); },
        reloadAll: function () { reloadAllForPlaytest(); return true; },
        records: textRecords,
        images: imageLog,
        cfg: CFG
    };

    var _readyMsg = 'ready - ' + CFG.hotkey + ' inspector';
    if (CFG.liveRefresh && nodeOk) {
        _readyMsg += ', ' + CFG.liveRefreshHotkey + ' reload data (auto-watch on)';
    }
    log(_readyMsg);
})();
