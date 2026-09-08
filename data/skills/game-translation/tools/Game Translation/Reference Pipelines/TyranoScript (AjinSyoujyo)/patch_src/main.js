// English patch loader for 亜人少女.
//
// Electron resolves the app directory in the order  resources/app,
// resources/app.asar, resources/default_app.asar  -- so a loose resources/app
// wins without touching the 745 MB archive. This shim therefore:
//
//   1. loads index.html from *inside* app.asar, so every relative path the game
//      uses still resolves into the original archive, and
//   2. intercepts file:// for the handful of paths listed in override/, serving
//      the translated file instead.
//
// The result is a ~2 MB drop-in patch. Deleting resources/app uninstalls it.

const electron = require('electron');
const { app, BrowserWindow, protocol, Menu } = electron;
const fs = require('fs');
const path = require('path');

const ASAR = path.join(process.resourcesPath, 'app.asar');
const OVERRIDE = path.join(__dirname, 'override');

// Relative paths we actually have a replacement for. Collected once so the
// interceptor is a Set lookup rather than a stat() on every image the game loads.
const overrides = new Map();

function indexOverrides(dir, prefix) {
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch (err) {
    return;
  }
  for (const entry of entries) {
    const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      indexOverrides(path.join(dir, entry.name), rel);
    } else {
      overrides.set(rel.toLowerCase(), path.join(dir, entry.name));
    }
  }
}

function urlToPath(rawUrl) {
  const url = new URL(rawUrl);
  let file = decodeURIComponent(url.pathname);
  if (process.platform === 'win32' && /^\/[A-Za-z]:/.test(file)) {
    file = file.slice(1);
  }
  return path.normalize(file);
}

app.on('ready', () => {
  indexOverrides(OVERRIDE, '');
  console.log(`[english] ${overrides.size} override files`);

  protocol.interceptFileProtocol('file', (request, callback) => {
    const target = urlToPath(request.url);
    if (target.startsWith(ASAR + path.sep)) {
      const rel = path.relative(ASAR, target).split(path.sep).join('/').toLowerCase();
      const replacement = overrides.get(rel);
      if (replacement) {
        callback({ path: replacement });
        return;
      }
    }
    callback({ path: target });
  });

  const map_package = JSON.parse(fs.readFileSync(path.join(__dirname, 'package.json')));
  const map_window = map_package['window'];
  const width = parseInt(map_window['width']);
  let height = parseInt(map_window['height']);
  const resize = map_window['resize'];
  if (process.platform === 'win32' && resize === false) {
    height = height + 20;
  }

  const mainWindow = new BrowserWindow({
    width: width,
    height: height,
    resizable: resize,
    useContentSize: true,
    show: false,
    webPreferences: { nodeIntegration: true },
  });

  // TyranoScript keys $.isElectron() off this suffix; without it the save-key
  // check and the audio unlock take the browser path.
  mainWindow.webContents.setUserAgent(mainWindow.webContents.getUserAgent() + ' TyranoErectron');
  mainWindow.loadURL('file://' + path.join(ASAR, 'index.html').split(path.sep).join('/'));

  if (map_window['devtools'] === true) {
    mainWindow.webContents.openDevTools();
  }

  mainWindow.on('ready-to-show', () => {
    if (process.platform === 'win32') {
      mainWindow.removeMenu();
      mainWindow.minimize();
      mainWindow.restore();
    } else {
      Menu.setApplicationMenu(Menu.buildFromTemplate([
        { label: 'File', submenu: [{ label: 'Quit', role: 'close' }] },
      ]));
    }
    mainWindow.show();
  });

  mainWindow.on('closed', () => {
    // window is garbage collected with the app
  });
});

app.on('window-all-closed', () => {
  app.quit();
});
