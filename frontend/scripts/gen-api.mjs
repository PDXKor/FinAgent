// Regenerate src/api/generated/*.d.ts from the backends' source; no servers needed.
// Python per backend: $DATA_PYTHON / $AGENTS_PYTHON, else that package's .venv.
import { execFileSync, execSync } from "node:child_process";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const venvPython = (pkg) =>
  [join(root, pkg, ".venv", "bin", "python"), join(root, pkg, ".venv", "Scripts", "python.exe")].find(
    existsSync,
  );

const apps = {
  data: [
    "DATA_PYTHON",
    "from finagent.api.app import create_app; from finagent.api.config import ApiSettings; " +
      "app = create_app(ApiSettings(_env_file=None))",
  ],
  agents: [
    "AGENTS_PYTHON",
    "from finagent_agents.server import create_app; from finagent_agents.config import AgentSettings; " +
      "app = create_app(AgentSettings(_env_file=None))",
  ],
};

const tmp = mkdtempSync(join(tmpdir(), "finagent-api-"));
try {
  for (const [name, [envVar, setup]] of Object.entries(apps)) {
    const python = process.env[envVar] || venvPython(name);
    if (!python) throw new Error(`no Python for ${name}: set ${envVar} or create ${name}/.venv`);
    const spec = execFileSync(python, ["-c", `import json; ${setup}; print(json.dumps(app.openapi()))`], {
      encoding: "utf8",
    });
    const file = join(tmp, `${name}.json`);
    writeFileSync(file, spec);
    execSync(`npx openapi-typescript "${file}" -o src/api/generated/${name}.d.ts`, { stdio: "inherit" });
  }
} finally {
  rmSync(tmp, { recursive: true, force: true });
}
