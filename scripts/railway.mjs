// Runs the Railway CLI pinned in package.json, to preview and apply .railway/railway.ts:
//
//   npm run iac:plan     shows what would change on Railway, and changes nothing
//   npm run iac:apply    makes those changes
//
// The IaC SDK checks the CLI's version by running the program named in the `_` environment
// variable, which some shells (Git Bash on Windows, for one) set to a path it can't run. This
// points `_` at the pinned CLI, so the check passes in every shell.
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const binary = process.platform === "win32" ? "railway.exe" : "railway";
const cli = join(root, "node_modules", "@railway", "cli", "bin", binary);

if (!existsSync(cli)) {
  console.error("The Railway CLI isn't installed. Run `npm install` in the repository root.");
  process.exit(1);
}

const run = spawnSync(cli, process.argv.slice(2), {
  stdio: "inherit",
  env: { ...process.env, _: cli },
});
if (run.error) {
  console.error(run.error.message);
  process.exit(1);
}
process.exit(run.status ?? 1);
