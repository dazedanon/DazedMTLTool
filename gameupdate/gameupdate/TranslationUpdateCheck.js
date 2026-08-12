/*:
 * @target MV MZ
 * @plugindesc Warns when a newer DazedTL translation patch is available.
 * @author DazedTranslations
 *
 * @help TranslationUpdateCheck.js
 *
 * This plugin reads gameupdate/patch-config.txt and
 * gameupdate/previous_patch_sha.txt, then compares the installed patch with
 * the configured repository branch. If a newer commit exists, it shows a
 * warning telling the player to run GameUpdate.
 *
 * The check is deliberately fail-open. Missing files, unsupported configs,
 * network failures, malformed responses, and all other errors are ignored so
 * they can never prevent the game from starting.
 */

(function() {
    "use strict";

    var REQUEST_TIMEOUT_MS = 5000;
    var MAX_RESPONSE_BYTES = 1024 * 1024;

    function nodeRequire(name) {
        if (typeof require === "function") {
            return require(name);
        }
        if (typeof window !== "undefined" && typeof window.require === "function") {
            return window.require(name);
        }
        return null;
    }

    function uniquePush(items, value, path) {
        if (!value) return;
        var normalized;
        try {
            normalized = path.resolve(value);
        } catch (_error) {
            return;
        }
        if (items.indexOf(normalized) < 0) items.push(normalized);
        if (path.basename(normalized).toLowerCase() === "www") {
            var parent = path.dirname(normalized);
            if (items.indexOf(parent) < 0) items.push(parent);
        }
    }

    function findGameRoot(fs, path) {
        var candidates = [];
        try {
            if (typeof process !== "undefined" && process.cwd) {
                uniquePush(candidates, process.cwd(), path);
            }
        } catch (_cwdError) {
            // A failed root candidate is not a startup failure.
        }
        try {
            if (typeof location !== "undefined" && location.pathname) {
                var locationPath = decodeURIComponent(location.pathname);
                if (/^\/[A-Za-z]:\//.test(locationPath)) locationPath = locationPath.slice(1);
                uniquePush(candidates, path.dirname(locationPath), path);
            }
        } catch (_locationError) {
            // Continue with the other candidates.
        }
        try {
            if (typeof process !== "undefined" && process.execPath) {
                uniquePush(candidates, path.dirname(process.execPath), path);
            }
        } catch (_execError) {
            // Continue with the other candidates.
        }

        for (var i = 0; i < candidates.length; i++) {
            var configPath = path.join(candidates[i], "gameupdate", "patch-config.txt");
            try {
                if (fs.statSync(configPath).isFile()) return candidates[i];
            } catch (_statError) {
                // Try the next possible game root.
            }
        }
        return null;
    }

    function parseConfig(text) {
        var config = {
            forge: "gitlab",
            host: "",
            username: "",
            repo: "",
            branch: ""
        };
        String(text || "").split(/\r?\n/).forEach(function(rawLine) {
            var line = rawLine.trim();
            if (!line || line.charAt(0) === "#") return;
            var equals = line.indexOf("=");
            if (equals < 1) return;
            var key = line.slice(0, equals).trim().toLowerCase();
            var value = line.slice(equals + 1).trim();
            if (key === "provider") key = "forge";
            if (key === "owner" || key === "org") key = "username";
            if (Object.prototype.hasOwnProperty.call(config, key)) config[key] = value;
        });
        return config;
    }

    function resolveRemote(config) {
        var rawForge = String(config.forge || "gitlab").toLowerCase().replace(/\s/g, "");
        var forge;
        if (/^(gitlab|gl|gitgud)$/.test(rawForge)) forge = "gitlab";
        else if (/^(github|gh)$/.test(rawForge)) forge = "github";
        else if (/^(forgejo|gitea|fj|codeberg)$/.test(rawForge)) forge = "forgejo";
        else return null;

        if (!config.username || !config.repo || !config.branch) return null;
        if (/^YOUR_/i.test(config.username) || /^YOUR_/i.test(config.repo)) return null;

        var host = String(config.host || "").trim()
            .replace(/^https?:\/\//i, "").replace(/\/.*$/, "").replace(/\s/g, "");
        if (!host) {
            host = forge === "github" ? "github.com" :
                forge === "forgejo" ? "codeberg.org" : "gitgud.io";
        }
        if (!/^[A-Za-z0-9.-]+(?::[0-9]+)?$/.test(host)) return null;

        var webHost = host;
        var webOwner = String(config.username).split("/").map(encodeURIComponent).join("/");
        var repoUrl = "https://" + webHost + "/" + webOwner + "/" + encodeURIComponent(config.repo);
        var hostParts = host.split(":");
        var hostname = hostParts[0];
        var port = hostParts.length === 2 ? Number(hostParts[1]) : 443;
        var owner = encodeURIComponent(config.username);
        var repo = encodeURIComponent(config.repo);
        var branch = encodeURIComponent(config.branch);
        var apiPath;
        if (forge === "gitlab") {
            var project = encodeURIComponent(config.username + "/" + config.repo);
            apiPath = "/api/v4/projects/" + project + "/repository/branches/" + branch;
        } else if (forge === "github") {
            hostname = hostname === "github.com" ? "api.github.com" : hostname;
            apiPath = (hostname === "api.github.com" ? "" : "/api/v3") +
                "/repos/" + owner + "/" + repo + "/commits/" + branch;
        } else {
            apiPath = "/api/v1/repos/" + owner + "/" + repo + "/branches/" + branch;
        }
        return {
            forge: forge,
            hostname: hostname,
            port: port,
            path: apiPath,
            repoUrl: repoUrl
        };
    }

    function latestShaFromResponse(forge, payload) {
        if (!payload || typeof payload !== "object") return "";
        if (forge === "github") return String(payload.sha || "").trim();
        return String(payload.commit && payload.commit.id || "").trim();
    }

    function requestLatestSha(https, remote, callback) {
        var finished = false;
        function finish(value) {
            if (finished) return;
            finished = true;
            callback(value || "");
        }
        var request;
        try {
            request = https.get({
                protocol: "https:",
                hostname: remote.hostname,
                port: remote.port,
                path: remote.path,
                headers: {
                    "User-Agent": "DazedTL-TranslationUpdateCheck/1.0",
                    "Accept": "application/json"
                }
            }, function(response) {
                try {
                    if (response.statusCode !== 200) {
                        if (response.resume) response.resume();
                        finish("");
                        return;
                    }
                    var body = "";
                    response.setEncoding("utf8");
                    response.on("data", function(chunk) {
                        body += chunk;
                        if (body.length > MAX_RESPONSE_BYTES) {
                            if (request && request.destroy) request.destroy();
                            finish("");
                        }
                    });
                    response.on("end", function() {
                        try {
                            finish(latestShaFromResponse(remote.forge, JSON.parse(body)));
                        } catch (_jsonError) {
                            finish("");
                        }
                    });
                    response.on("error", function() { finish(""); });
                } catch (_responseError) {
                    finish("");
                }
            });
            request.on("error", function() { finish(""); });
            request.setTimeout(REQUEST_TIMEOUT_MS, function() {
                try { request.destroy(); } catch (_destroyError) { /* fail open */ }
                finish("");
            });
        } catch (_requestError) {
            finish("");
        }
    }

    function sameCommit(installed, latest) {
        installed = String(installed || "").trim().toLowerCase();
        latest = String(latest || "").trim().toLowerCase();
        if (!/^[0-9a-f]{7,64}$/.test(installed) || !/^[0-9a-f]{7,64}$/.test(latest)) {
            return true;
        }
        return installed === latest || installed.indexOf(latest) === 0 || latest.indexOf(installed) === 0;
    }

    function openExternal(url) {
        try {
            if (typeof nw !== "undefined" && nw.Shell && nw.Shell.openExternal) {
                nw.Shell.openExternal(url);
                return;
            }
        } catch (_nwError) {
            // Try legacy NW.js or a normal browser window below.
        }
        try {
            var gui = nodeRequire("nw.gui");
            if (gui && gui.Shell && gui.Shell.openExternal) {
                gui.Shell.openExternal(url);
                return;
            }
        } catch (_legacyNwError) {
            // Try the browser fallback below.
        }
        try {
            if (typeof window !== "undefined" && typeof window.open === "function") {
                window.open(url, "_blank");
            }
        } catch (_windowError) {
            // A link failure must never affect the game.
        }
    }

    function showClickableWarning(repoUrl, latestSha, statePath, fs) {
        if (typeof document === "undefined" || !document.body || !document.createElement) {
            return false;
        }

        var backdrop = document.createElement("div");
        backdrop.style.position = "fixed";
        backdrop.style.left = "0";
        backdrop.style.top = "0";
        backdrop.style.right = "0";
        backdrop.style.bottom = "0";
        backdrop.style.zIndex = "2147483647";
        backdrop.style.display = "flex";
        backdrop.style.alignItems = "center";
        backdrop.style.justifyContent = "center";
        backdrop.style.background = "rgba(0, 0, 0, 0.72)";
        backdrop.style.fontFamily = "sans-serif";

        var panel = document.createElement("div");
        panel.style.maxWidth = "560px";
        panel.style.margin = "24px";
        panel.style.padding = "24px";
        panel.style.border = "2px solid #d8a84e";
        panel.style.borderRadius = "8px";
        panel.style.background = "#20232a";
        panel.style.color = "#f4f4f4";
        panel.style.boxShadow = "0 12px 36px rgba(0, 0, 0, 0.55)";

        var title = document.createElement("div");
        title.textContent = "Translation update available";
        title.style.fontSize = "22px";
        title.style.fontWeight = "bold";
        title.style.marginBottom = "12px";
        panel.appendChild(title);

        var detail = document.createElement("div");
        detail.textContent = "A newer version of this translation is available. Close the game and run GameUpdate, or patch it manually from the repository:";
        detail.style.fontSize = "16px";
        detail.style.lineHeight = "1.5";
        detail.style.marginBottom = "14px";
        panel.appendChild(detail);

        var link = document.createElement("a");
        link.href = repoUrl;
        link.textContent = "Open translation repository (manual patch)";
        link.style.display = "inline-block";
        link.style.color = "#72b7ff";
        link.style.fontSize = "16px";
        link.style.marginBottom = "18px";
        link.style.textDecoration = "underline";
        link.addEventListener("click", function(event) {
            try { event.preventDefault(); } catch (_eventError) { /* keep opening */ }
            openExternal(repoUrl);
        });
        panel.appendChild(link);

        var actions = document.createElement("div");
        actions.style.textAlign = "right";

        var installed = document.createElement("button");
        installed.type = "button";
        installed.textContent = "I installed this update manually";
        installed.style.padding = "8px 12px";
        installed.style.marginRight = "10px";
        installed.style.fontSize = "14px";
        installed.style.cursor = "pointer";
        installed.addEventListener("click", function() {
            try {
                var confirmed = typeof window === "undefined" ||
                    typeof window.confirm !== "function" ||
                    window.confirm(
                        "Only confirm after closing the game and copying the latest " +
                        "translation files into this game. Mark this update as installed?"
                    );
                if (!confirmed) return;
                fs.writeFileSync(statePath, latestSha + "\n", "ascii");
                if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
            } catch (_stateError) {
                try {
                    if (typeof window !== "undefined" && typeof window.alert === "function") {
                        window.alert(
                            "The translation version could not be saved. The game can " +
                            "continue, but this warning may appear again."
                        );
                    }
                } catch (_stateWarningError) {
                    // Failure to save or explain updater state never affects the game.
                }
            }
        });
        actions.appendChild(installed);

        var close = document.createElement("button");
        close.type = "button";
        close.textContent = "Continue";
        close.style.padding = "8px 18px";
        close.style.fontSize = "16px";
        close.style.cursor = "pointer";
        close.addEventListener("click", function() {
            try {
                if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
            } catch (_closeError) {
                // The game continues even if the warning cannot remove itself.
            }
        });
        actions.appendChild(close);
        panel.appendChild(actions);
        backdrop.appendChild(panel);
        document.body.appendChild(backdrop);
        return true;
    }

    function warnPlayer(repoUrl, latestSha, statePath, fs) {
        try {
            var message = "A newer version of this translation is available.\n\n" +
                "Close the game and run GameUpdate.bat (Windows) or " +
                "GameUpdate_linux.sh (Linux) from the game folder.\n\n" + repoUrl;
            if (showClickableWarning(repoUrl, latestSha, statePath, fs)) return;
            if (typeof window !== "undefined" && typeof window.alert === "function") {
                window.alert(message);
            }
        } catch (_warningError) {
            // Even a failed warning must not affect the game.
        }
    }

    function checkForUpdate() {
        try {
            var fs = nodeRequire("fs");
            var path = nodeRequire("path");
            var https = nodeRequire("https");
            if (!fs || !path || !https) return;

            var gameRoot = findGameRoot(fs, path);
            if (!gameRoot) return;
            var updaterRoot = path.join(gameRoot, "gameupdate");
            var config = parseConfig(fs.readFileSync(path.join(updaterRoot, "patch-config.txt"), "utf8"));
            var remote = resolveRemote(config);
            if (!remote) return;

            var installed = fs.readFileSync(path.join(updaterRoot, "previous_patch_sha.txt"), "utf8").trim();
            if (!/^[0-9a-f]{7,64}$/i.test(installed)) return;
            var statePath = path.join(updaterRoot, "previous_patch_sha.txt");
            requestLatestSha(https, remote, function(latest) {
                try {
                    if (!sameCommit(installed, latest)) {
                        warnPlayer(remote.repoUrl, latest, statePath, fs);
                    }
                } catch (_compareError) {
                    // The game always continues.
                }
            });
        } catch (_checkError) {
            // Missing state/config, filesystem errors, and runtime differences are expected.
        }
    }

    try {
        setTimeout(checkForUpdate, 0);
    } catch (_startupError) {
        // Loading this plugin must never prevent RPG Maker from booting.
    }
})();
