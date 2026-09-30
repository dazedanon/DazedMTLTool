const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

function bundledPath(root, relative) {
  if (
    typeof relative !== "string" ||
    path.isAbsolute(relative) ||
    relative.includes("\\") || relative.includes(":") ||
    relative.split("/").some((part) => !part || part === ".." || part === ".")
  )
    throw new Error("Invalid bundled runtime path.");
  return path.join(root, ...relative.split("/"));
}
function prepareRuntime({ packaged, resources, profile, onProcess }) {
  if (!packaged) {
    const root = path.resolve(__dirname, "../..");
    return Promise.resolve({
      root,
      python:
        process.env.DAZEDTL_PYTHON ||
        path.join(
          root,
          ".venv",
          process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
        ),
      workspace:
        process.env.DAZEDTL_DESKTOP_WORKSPACE ||
        path.join(root, ".tmp-ui/desktop-workspace"),
    });
  }
  const manifest = JSON.parse(
    fs.readFileSync(path.join(resources, "runtime.json"), "utf8"),
  );
  if (manifest.version !== 1) throw new Error("Unsupported bundled runtime version.");
  const python = bundledPath(resources, manifest.python);
  const source = path.join(resources, "backend");
  return new Promise((resolve, reject) => {
    const env = {
      ...process.env,
      PYTHONNOUSERSITE: "1",
      PYTHON_DOTENV_DISABLED: "1",
    };
    delete env.PYTHONPATH;
    delete env.PYTHONHOME;
    const child = spawn(
      python,
      [
        "-I",
        "-B",
        path.join(source, "desktop/backend/bundle.py"),
        "--source",
        source,
        "--profile",
        profile,
      ],
      { env, stdio: ["ignore", "pipe", "pipe"], windowsHide: true },
    );
    onProcess(child);
    let output = "",
      errors = "";
    child.stdout.on("data", (data) => {
      output += data;
    });
    child.stderr.on("data", (data) => {
      errors = (errors + data).slice(-4000);
    });
    child.on("error", () =>
      reject(
        new Error(
          "Could not start bundled Python. Re-extract the complete application package.",
        ),
      ),
    );
    child.on("exit", (code) => {
      onProcess(null);
      if (code !== 0)
        return reject(
          new Error(
            "Could not prepare the local runtime. Existing user data was retained. " +
              errors.slice(-1500),
          ),
        );
      try {
        const value = JSON.parse(output);
        resolve({
          ...value,
          workspace: process.env.DAZEDTL_DESKTOP_WORKSPACE || value.workspace,
        });
      } catch {
        reject(
          new Error("The bundled runtime returned an invalid setup result."),
        );
      }
    });
  });
}
module.exports = { prepareRuntime };
