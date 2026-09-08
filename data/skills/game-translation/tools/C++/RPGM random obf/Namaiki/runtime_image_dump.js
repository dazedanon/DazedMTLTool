(function() {
    "use strict";

    const fs = require("fs");
    const path = require("path");

    const rootDir = process.cwd();
    const outputDir = path.join(rootDir, "runtime_dump_assets");
    const summaryPath = path.join(outputDir, "_runtime_dump_summary.txt");
    const logPath = path.join(outputDir, "_runtime_dump_log.json");
    const timeoutMs = 30000;
    const concurrency = 3;
    const scriptUrls = [
        "js/libs/pixi.js",
        "js/libs/pako.min.js",
        "js/libs/localforage.min.js",
        "js/libs/effekseer.min.js",
        "js/libs/vorbisdecoder.js",
        "js/rmmz_core.bin",
        "js/rmmz_managers.bin",
        "js/rmmz_objects.js",
        "js/rmmz_scenes.js",
        "js/rmmz_sprites.js",
        "js/rmmz_windows.js",
        "js/plugins.js"
    ];

    const state = {
        total: 0,
        done: 0,
        ok: [],
        failed: [],
        blankish: []
    };
    const logLines = [];

    function status(text) {
        const element = document.getElementById("status");
        if (element) element.textContent = text;
        console.log(text);
    }

    function log(text) {
        const line = `[${new Date().toLocaleTimeString()}] ${text}`;
        logLines.push(line);
        if (logLines.length > 250) logLines.shift();
        const element = document.getElementById("log");
        if (element) element.textContent = logLines.join("\n");
        console.log(line);
    }

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    function walkFiles(dir) {
        const files = [];
        if (!fs.existsSync(dir)) return files;
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
            const fullPath = path.join(dir, entry.name);
            if (entry.isDirectory()) {
                files.push(...walkFiles(fullPath));
            } else if (entry.isFile()) {
                files.push(fullPath);
            }
        }
        return files;
    }

    function toGamePath(filePath) {
        return path.relative(rootDir, filePath).split(path.sep).join("/");
    }

    function outputPathFor(gamePath) {
        const cleanPath = gamePath.endsWith("_") ? gamePath.slice(0, -1) : gamePath;
        return path.join(outputDir, ...cleanPath.split("/"));
    }

    function encodeGameUrl(gamePath) {
        return gamePath.split("/").map(part => encodeURIComponent(part)).join("/");
    }

    function loadScript(url) {
        return new Promise((resolve, reject) => {
            if (url.endsWith(".bin")) {
                try {
                    nw.Window.get().evalNWBin(null, url);
                    resolve();
                } catch (error) {
                    reject(new Error(`Failed to load ${url}: ${error.message}`));
                }
                return;
            }

            const script = document.createElement("script");
            script.type = "text/javascript";
            script.src = url;
            script.async = false;
            script.defer = true;
            script.onload = resolve;
            script.onerror = () => reject(new Error(`Failed to load ${url}`));
            document.body.appendChild(script);
        });
    }

    async function loadGameScripts() {
        for (let i = 0; i < scriptUrls.length; i++) {
            const url = scriptUrls[i];
            status(`Loading scripts ${i + 1}/${scriptUrls.length}: ${url}`);
            await loadScript(url);
        }
        if (typeof PluginManager !== "undefined" && typeof PluginManager.setup === "function" && typeof $plugins !== "undefined") {
            PluginManager.setup($plugins);
        }
    }

    function readFallbackSystem() {
        const systemPath = path.join(rootDir, "decrypted_data", "System.json");
        if (!fs.existsSync(systemPath)) {
            throw new Error("Could not read decrypted_data/System.json for encryption settings");
        }
        return JSON.parse(fs.readFileSync(systemPath, "utf8"));
    }

    async function loadDatabaseSettings() {
        let system = null;
        if (typeof DataManager !== "undefined" && typeof DataManager.loadDatabase === "function") {
            try {
                DataManager.loadDatabase();
                const started = Date.now();
                while (Date.now() - started < 60000) {
                    if (DataManager.isDatabaseLoaded()) {
                        system = window.$dataSystem;
                        break;
                    }
                    await sleep(50);
                }
            } catch (error) {
                log(`Database load fell back to decrypted_data: ${error.message}`);
            }
        }

        if (!system) {
            system = readFallbackSystem();
        }

        Utils.setEncryptionInfo(
            !!system.hasEncryptedImages,
            !!system.hasEncryptedAudio,
            system.encryptionKey || ""
        );
        log(`Encryption key loaded: ${system.encryptionKey || "(empty)"}`);
    }

    function imageFiles() {
        return walkFiles(path.join(rootDir, "img"))
            .map(toGamePath)
            .filter(file => /\.(png_|png|jpg_|jpg|jpeg_|jpeg|webp_|webp)$/i.test(file))
            .sort((a, b) => a.localeCompare(b));
    }

    function waitForBitmap(bitmap, gamePath) {
        return new Promise((resolve, reject) => {
            let settled = false;
            const started = Date.now();

            const finish = () => {
                if (settled) return;
                settled = true;
                resolve(bitmap);
            };

            const fail = error => {
                if (settled) return;
                settled = true;
                reject(error);
            };

            if (bitmap.addLoadListener) {
                bitmap.addLoadListener(finish);
            }

            const tick = () => {
                if (settled) return;
                try {
                    if (bitmap.isReady && bitmap.isReady()) {
                        finish();
                        return;
                    }
                    if (bitmap.isError && bitmap.isError()) {
                        fail(new Error("runtime image decode failed"));
                        return;
                    }
                    if (bitmap.checkError) {
                        bitmap.checkError();
                    }
                } catch (error) {
                    fail(error);
                    return;
                }
                if (Date.now() - started > timeoutMs) {
                    fail(new Error(`timeout waiting for ${gamePath}`));
                    return;
                }
                setTimeout(tick, 50);
            };
            tick();
        });
    }

    function loadPlainImage(url, gamePath) {
        return new Promise((resolve, reject) => {
            const image = new Image();
            const timer = setTimeout(() => reject(new Error(`timeout waiting for ${gamePath}`)), timeoutMs);
            image.onload = () => {
                clearTimeout(timer);
                resolve(image);
            };
            image.onerror = () => {
                clearTimeout(timer);
                reject(new Error("plain image decode failed"));
            };
            image.src = url;
        });
    }

    function drawSourceToCanvas(source, width, height) {
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext("2d");
        context.clearRect(0, 0, width, height);
        context.drawImage(source, 0, 0);
        return canvas;
    }

    function pixelStats(canvas) {
        const context = canvas.getContext("2d");
        const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
        const pixels = canvas.width * canvas.height;
        let visible = 0;
        let black = 0;
        for (let i = 0; i < data.length; i += 4) {
            if (data[i + 3] === 0) continue;
            visible++;
            if (data[i] < 4 && data[i + 1] < 4 && data[i + 2] < 4) black++;
        }
        return {
            visibleRatio: pixels ? visible / pixels : 0,
            blackishRatio: visible ? black / visible : 0
        };
    }

    async function canvasForFile(gamePath) {
        const encrypted = gamePath.endsWith("_");
        const cleanPath = encrypted ? gamePath.slice(0, -1) : gamePath;

        if (encrypted) {
            const slash = cleanPath.lastIndexOf("/");
            const folder = cleanPath.slice(0, slash + 1);
            const basename = cleanPath.slice(slash + 1).replace(/\.[^.]+$/, "");
            const bitmap = ImageManager.loadBitmap(folder, basename);
            await waitForBitmap(bitmap, gamePath);
            const source = bitmap._image || bitmap.canvas;
            if (!bitmap.width || !bitmap.height || !source) {
                throw new Error("runtime bitmap had no drawable image");
            }
            const canvas = drawSourceToCanvas(source, bitmap.width, bitmap.height);
            if (bitmap.destroy) bitmap.destroy();
            return canvas;
        }

        const image = await loadPlainImage(encodeGameUrl(gamePath), gamePath);
        return drawSourceToCanvas(image, image.naturalWidth || image.width, image.naturalHeight || image.height);
    }

    async function processOne(gamePath) {
        const outputPath = outputPathFor(gamePath);
        try {
            const canvas = await canvasForFile(gamePath);
            const stats = pixelStats(canvas);
            const png = canvas.toDataURL("image/png");
            if (!png.startsWith("data:image/png;base64,")) {
                throw new Error("canvas did not produce PNG data");
            }
            fs.mkdirSync(path.dirname(outputPath), { recursive: true });
            fs.writeFileSync(outputPath, Buffer.from(png.slice("data:image/png;base64,".length), "base64"));
            state.ok.push({ file: gamePath, output: path.relative(rootDir, outputPath), ...stats });
            if (stats.visibleRatio < 0.001 || stats.blackishRatio > 0.995) {
                state.blankish.push(gamePath);
            }
        } catch (error) {
            state.failed.push({ file: gamePath, error: error.message });
            log(`FAILED ${gamePath}: ${error.message}`);
        } finally {
            state.done++;
            if (state.done % 10 === 0 || state.done === state.total) {
                status(`Dumped ${state.done}/${state.total} images, ok ${state.ok.length}, failed ${state.failed.length}`);
            }
        }
    }

    async function runQueue(files) {
        let next = 0;
        async function worker() {
            while (next < files.length) {
                const index = next++;
                await processOne(files[index]);
            }
        }
        await Promise.all(Array.from({ length: Math.min(concurrency, files.length) }, worker));
    }

    function writeSummary() {
        fs.mkdirSync(outputDir, { recursive: true });
        fs.writeFileSync(logPath, JSON.stringify(state, null, 2));
        const lines = [
            `Runtime image dump`,
            `Root: ${rootDir}`,
            `Output: ${outputDir}`,
            `Total: ${state.total}`,
            `OK: ${state.ok.length}`,
            `Failed: ${state.failed.length}`,
            `Blank or almost all black: ${state.blankish.length}`,
            ""
        ];
        if (state.failed.length) {
            lines.push("Failed files:");
            for (const item of state.failed) {
                lines.push(`${item.file} :: ${item.error}`);
            }
            lines.push("");
        }
        if (state.blankish.length) {
            lines.push("Blank or almost all black files:");
            lines.push(...state.blankish);
            lines.push("");
        }
        fs.writeFileSync(summaryPath, lines.join("\n"), "utf8");
    }

    async function main() {
        window.onerror = (_message, _source, _line, _column, error) => {
            log(`Window error: ${error ? error.stack || error.message : _message}`);
        };

        fs.mkdirSync(outputDir, { recursive: true });
        await loadGameScripts();
        await loadDatabaseSettings();

        const files = imageFiles();
        state.total = files.length;
        log(`Found ${files.length} image files under img/`);
        await runQueue(files);
        writeSummary();
        status(`Finished. OK ${state.ok.length}/${state.total}, failed ${state.failed.length}.`);
        log(`Wrote ${summaryPath}`);
        setTimeout(() => nw.App.quit(), 1500);
    }

    main().catch(error => {
        state.failed.push({ file: "(startup)", error: error.stack || error.message });
        writeSummary();
        status("Runtime dump failed during startup");
        log(error.stack || error.message);
    });
})();
