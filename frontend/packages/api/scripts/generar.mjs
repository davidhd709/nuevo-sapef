// Regenera el contrato y los tipos del cliente desde el backend:
//   1. el backend escribe openapi.json (sin levantar el servidor)
//   2. openapi-typescript genera src/esquema.ts
// Ejecutar cada vez que cambie la API:  pnpm api
import { execFileSync, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const aqui = dirname(fileURLToPath(import.meta.url));
const paquete = resolve(aqui, "..");
const backend = resolve(paquete, "../../../backend");
const contrato = resolve(paquete, "openapi.json");
const argsOpenapi = ["-m", "app.exportar_openapi", contrato];

function exportarOpenApi() {
  if (process.platform === "win32") {
    const venvPython = resolve(backend, ".venv/Scripts/python.exe");
    if (existsSync(venvPython)) {
      execFileSync(venvPython, argsOpenapi, { cwd: backend, stdio: "inherit" });
      return;
    }
    const candidatos = [
      ["uv", ["run", "--no-sync", "python", ...argsOpenapi]],
      ["py", ["-m", "uv", "run", "--no-sync", "python", ...argsOpenapi]],
      ["python", ["-m", "uv", "run", "--no-sync", "python", ...argsOpenapi]],
    ];
    for (const [cmd, args] of candidatos) {
      const probe = spawnSync(cmd, ["--version"], { cwd: backend, stdio: "ignore" });
      if (!probe.error && probe.status === 0) {
        execFileSync(cmd, args, { cwd: backend, stdio: "inherit" });
        return;
      }
    }
    throw new Error("No se encontró .venv/Scripts/python.exe ni uv/py/python en PATH.");
  }

  const venvPython = resolve(backend, ".venv/bin/python");
  const probeUv = spawnSync("uv", ["--version"], { cwd: backend, stdio: "ignore" });
  if (!probeUv.error && probeUv.status === 0) {
    execFileSync("uv", ["run", "--no-sync", "python", ...argsOpenapi], {
      cwd: backend,
      stdio: "inherit",
    });
    return;
  }
  if (existsSync(venvPython)) {
    execFileSync(venvPython, argsOpenapi, { cwd: backend, stdio: "inherit" });
    return;
  }
  execFileSync("python3", argsOpenapi, { cwd: backend, stdio: "inherit" });
}

exportarOpenApi();
execFileSync(
  "pnpm",
  ["exec", "openapi-typescript", contrato, "-o", resolve(paquete, "src/esquema.ts")],
  {
    cwd: paquete,
    stdio: "inherit",
    shell: process.platform === "win32",
  },
);
