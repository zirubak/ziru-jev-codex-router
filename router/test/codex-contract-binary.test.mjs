import assert from "node:assert/strict";
import test from "node:test";
import { contractBinaryPaths } from "./codex-contract-binary.mjs";

test("an explicit versioned contract does not enumerate ambient Codex installations", () => {
  assert.deepEqual(contractBinaryPaths({
    explicit: "/fixture/pinned-codex",
    expectedVersion: "codex-cli 0.159.2",
    discovered: ["/fixture/old-codex", "/fixture/desktop-codex"],
  }), ["/fixture/pinned-codex"]);
});

test("ordinary contract discovery retains all installed candidates", () => {
  assert.deepEqual(contractBinaryPaths({
    discovered: ["/fixture/preferred", "/fixture/desktop"],
  }), ["/fixture/preferred", "/fixture/desktop"]);
});


test("an explicit unversioned contract does not execute ambient installations", () => {
  assert.deepEqual(contractBinaryPaths({
    explicit: "/fixture/pinned-codex",
    discovered: ["/fixture/old-codex", "/fixture/desktop-codex"],
  }), ["/fixture/pinned-codex"]);
});
