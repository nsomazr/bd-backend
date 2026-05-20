// PM2 ecosystem config for the Maisha Chat backend.
// Single worker is intentional: each worker would load its own LLM into memory.
// Multiple threads (handled inside gunicorn) serve concurrent SSE streams.
//
// The gunicorn binary is resolved from the project-local virtualenv. By
// default we look at ./.env (the venv living inside bd-backend), but the
// deploy script may set $VENV_PATH to override.
const path = require("node:path");
const fs = require("node:fs");

const BACKEND_DIR = __dirname;

function resolveGunicorn() {
  const candidates = [
    process.env.VENV_PATH,
    path.join(BACKEND_DIR, ".env"),
    path.join(BACKEND_DIR, "venv"),
    path.join(BACKEND_DIR, ".venv"),
    "/home/happiness/blood_donation_ai/llm_env",
  ].filter(Boolean);
  for (const venv of candidates) {
    const bin = path.join(venv, "bin", "gunicorn");
    if (fs.existsSync(bin)) return bin;
  }
  return path.join(BACKEND_DIR, ".env", "bin", "gunicorn");
}

module.exports = {
  apps: [
    {
      name: "bd-backend",
      cwd: BACKEND_DIR,
      script: resolveGunicorn(),
      args: [
        "bd_backend.wsgi:application",
        "-b", "127.0.0.1:8090",
        "-w", "1",
        "--threads", "4",
        "--timeout", "600",
        "--graceful-timeout", "30",
        "--access-logfile", "-",
        "--error-logfile", "-",
      ].join(" "),
      interpreter: "none",
      autorestart: true,
      max_restarts: 10,
      kill_timeout: 30000,
      env: {
        DJANGO_SETTINGS_MODULE: "bd_backend.settings",
        PYTHONUNBUFFERED: "1",
      },
    },
  ],
};
