import fs from "node:fs";
import path from "node:path";

const rootDir = process.cwd();
const sourceDir = path.join(rootDir, "apps", "web", ".next");
const targetDir = path.join(rootDir, ".next");

if (!fs.existsSync(sourceDir)) {
  console.error(`[sync-next-output] source directory not found: ${sourceDir}`);
  process.exit(1);
}

fs.rmSync(targetDir, { recursive: true, force: true });
fs.cpSync(sourceDir, targetDir, { recursive: true });
console.log(`[sync-next-output] copied ${sourceDir} -> ${targetDir}`);
