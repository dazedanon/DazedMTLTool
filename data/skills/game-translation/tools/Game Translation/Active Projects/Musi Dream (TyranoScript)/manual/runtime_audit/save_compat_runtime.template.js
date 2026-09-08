;
// Musi Dream English: refresh only cached display text in legacy save snapshots.
(function () {
    "use strict";
    var menu = tyrano.plugin.kag.menu;
    if (menu.__musiDreamEnglishCache) return;
    var display = __MUSI_SAVE_DISPLAY_DATA__;
    var own = function (object, key) { return Object.prototype.hasOwnProperty.call(object, key); };
    var clone = function (value) { return JSON.parse(JSON.stringify(value)); };
    var hasClass = function (node, name) { return (" " + (node.class || "") + " ").indexOf(" " + name + " ") >= 0; };
    var escapeText = function (text) { return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); };
    function scenarioKey(storage) {
        var name = String(storage || "").replace(/\\/g, "/").replace(/^\.\//, "");
        if (name.indexOf("data/") !== 0) name = "data/scenario/" + name;
        var parts = [];
        name.split("/").forEach(function (part) { if (part === "..") parts.pop(); else if (part && part !== ".") parts.push(part); });
        return parts.join("/");
    }
    function resolver(data) {
        var stat = data.stat || {}, scenario = display.scenarios[scenarioKey(stat.current_scenario)];
        var index = data.current_order_index, rows = [];
        if (scenario && Number.isInteger(index)) {
            var start = -1;
            scenario.breaks.forEach(function (value) { if (value < index && value > start) start = value; });
            rows = scenario.rows.filter(function (row) { return row[0] > start && row[0] <= index + 1; });
        }
        return function (text) {
            if (typeof text !== "string") return null;
            var matches = rows.filter(function (row) { return row[1] === text; });
            if (matches.length && matches.every(function (row) { return row[2] === matches[0][2]; })) return matches[0][2];
            return own(display.unique, text) ? display.unique[text] : null;
        };
    }
    function textLeaf(text) { return { text: escapeText(text), attr: {}, children: [] }; }
    function refreshCaptions(data, translate) {
        if (!data || typeof data !== "object") return;
        if (typeof data.title === "string" && own(display.captions, data.title)) data.title = display.captions[data.title];
        if (!data.stat) return;
        function caption(text) {
            if (typeof text !== "string") return text;
            var direct = translate(text); if (direct !== null) return direct;
            var result = text;
            Object.keys(display.names).some(function (name) {
                if (text.indexOf(name + "：") !== 0) return false;
                var remainder = text.slice(name.length + 1), body = translate(remainder);
                result = display.names[name] + ": " + (body !== null ? body : remainder);
                return true;
            });
            // Engine-generated backlog markup only; keep opening tags/classes intact.
            return result.replace(/(<(b|span) class="backlog_(chara_name|text)[^"]*">)([^<>]*)(<\/\2>)/g,
                function (all, open, tag, kind, content, close) {
                    var english = kind === "chara_name" && own(display.names, content) ? display.names[content] : kind === "text" ? translate(content) : null;
                    return english === null ? all : open + escapeText(english) + close;
                });
        }
        data.title = caption(data.title);
        data.stat.current_save_str = caption(data.stat.current_save_str);
    }
    function allPlainChildren(node) {
        return Array.isArray(node.children) && node.children.every(function (child) {
            return !child.tag && typeof child.text === "string" && (!child.children || child.children.length === 0);
        });
    }
    function setPlain(node, text) {
        node.text = text;
        node.children = [textLeaf(text)];
    }
    function migrateMessage(node, translate) {
        if (!node || typeof node !== "object" || !Array.isArray(node.children)) return;
        // A renderer-created text run: its children are only simple .char spans.
        // Retain the wrapper/current_span styles and each cloned character style.
        if (node.children.length && node.children.every(function (child) {
            return child.tag === "SPAN" && hasClass(child, "char") && allPlainChildren(child) &&
                (!child.attr || Object.keys(child.attr).length === 0);
        })) {
            var english = translate(node.text);
            if (english !== null) {
                var sample = node.children[0];
                node.children = Array.from(english).map(function (char) {
                    var child = clone(sample); child.text = char; child.children = [textLeaf(char)]; return child;
                });
                node.text = english;
                return;
            }
        }
        node.children.forEach(function (child) { migrateMessage(child, translate); });
        // Parent text fields are cached aggregates; rendering uses the children.
        var aggregate = translate(node.text);
        if (aggregate !== null) node.text = aggregate;
    }
    function visit(node, callback) {
        if (!node || typeof node !== "object") return;
        if (callback(node) === false) return;
        if (Array.isArray(node.children)) node.children.forEach(function (child) { visit(child, callback); });
    }
    function refresh(data) {
        if (!data || !data.stat || !data.layer) return;
        var translate = resolver(data), layer = data.layer;
        ["current_message_str"].forEach(function (key) {
            var english = translate(data.stat[key]); if (english !== null) data.stat[key] = english;
        });
        var speaker = data.stat.current_speaker;
        if (typeof speaker === "string" && own(display.names, speaker) &&
            !own(data.stat.charas || {}, speaker) && !own(data.stat.jcharas || {}, speaker)) {
            data.stat.current_speaker = display.names[speaker];
        }
        refreshCaptions(data, translate);
        [layer.map_layer_fore, layer.map_layer_back].forEach(function (layers) {
            if (!layers || typeof layers !== "object") return;
            Object.keys(layers).filter(function (key) { return /^message\d+$/.test(key); }).forEach(function (key) {
                visit(layers[key], function (node) {
                    if (hasClass(node, "chara_name_area") && allPlainChildren(node) && own(display.names, node.text)) {
                        setPlain(node, display.names[node.text]); return false;
                    }
                    if (hasClass(node, "message_inner")) { migrateMessage(node, translate); return false; }
                });
            });
        });
        visit(layer.layer_free, function (node) {
            if (node.attr && node.attr["data-event-tag"] === "glink" && allPlainChildren(node) && own(display.choices, node.text)) {
                // Keep the serialized event parameters verbatim: they include keys.
                setPlain(node, display.choices[node.text]); return false;
            }
        });
    }
    var originalLoad = menu.loadGameData;
    menu.loadGameData = function (data, options) { refresh(data); return originalLoad.call(this, data, options); };
    var originalGetSaveData = menu.getSaveData;
    if (typeof originalGetSaveData === "function") menu.getSaveData = function () {
        var result = originalGetSaveData.apply(this, arguments);
        if (result && Array.isArray(result.data)) result.data.forEach(function (slot) { refreshCaptions(slot, resolver(slot || {})); });
        return result;
    };
    Object.defineProperty(menu, "__musiDreamEnglishCache", { value: true });
}());
