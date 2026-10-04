import { writeFileSync } from "node:fs";
import { runDuringOwnerSignalCleanup, runProcessTree, withOwnerSignalExitBarrier } from "file:///home/runner/work/ziru-jev-codex-router/ziru-jev-codex-router/router/src/process-tree.mjs";
const [readyPath, completedPath, mode, rollbackText, barrierText, depthText = '0'] = process.argv.slice(2);
const rollbackMs = Number.parseInt(rollbackText, 10);
const barrierMs = Number.parseInt(barrierText, 10);
const depth = Number.parseInt(depthText, 10);
if (depth > 0) {
  await runProcessTree(process.execPath, [process.argv[1], readyPath, completedPath, mode, rollbackText, barrierText, String(depth - 1)], {
    childMayOwnProcessTrees: true,
    deadline: Date.now() + 10_000,
    env: { ...process.env, CODEX_ROUTER_OPERATION_CHILD: '1' },
  });
} else await withOwnerSignalExitBarrier(async (ownerSignal) => {
  writeFileSync(readyPath, String(process.pid));
  await new Promise((resolve) => {
    const hold = setInterval(() => {}, 1000);
    const finish = () => { clearInterval(hold); resolve(); };
    ownerSignal.addEventListener("abort", finish, { once: true });
    if (ownerSignal.aborted) finish();
  });
  await runDuringOwnerSignalCleanup(async () => {
    if (mode === "stuck") await new Promise(() => {});
    await new Promise((resolve) => setTimeout(resolve, rollbackMs));
    writeFileSync(completedPath, "restored");
  });
}, { timeoutMs: barrierMs });
