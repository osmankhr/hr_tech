import test from "node:test";
import assert from "node:assert/strict";

import { buildPipelineProgressView } from "./pipelineProgress.js";


test("builds filtering progress with candidate count and percentage", () => {
  const view = buildPipelineProgressView({
    status: "Running",
    run_type: "full",
    progress: {
      phase: "filter",
      label: "AI reviewing candidates",
      phases: ["queries", "search", "filter", "ranking", "report"],
      current: 24,
      total: 100,
      detail: "Reviewing profiles",
    },
  });

  assert.equal(view.title, "AI reviewing candidates");
  assert.equal(view.stepLabel, "Step 3 of 5");
  assert.equal(view.countLabel, "24 of 100 candidates reviewed");
  assert.equal(view.percentage, 24);
  assert.equal(view.detail, "Reviewing profiles");
  assert.deepEqual(view.phases.map((phase) => phase.state), [
    "complete",
    "complete",
    "active",
    "upcoming",
    "upcoming",
  ]);
});


test("builds search progress with query and discovered candidate counts", () => {
  const view = buildPipelineProgressView({
    status: "Running",
    progress: {
      phase: "search",
      phases: ["queries", "search", "filter"],
      current: 3,
      total: 8,
      found: 42,
    },
  });

  assert.equal(view.countLabel, "3 of 8 searches completed");
  assert.equal(view.foundLabel, "42 candidates found so far");
  assert.equal(view.percentage, 38);
});


test("falls back gracefully before the first status file update", () => {
  const view = buildPipelineProgressView({ status: "Running", run_type: "rank" });

  assert.equal(view.title, "Pipeline is running");
  assert.equal(view.countLabel, "Preparing live progress...");
  assert.equal(view.percentage, null);
  assert.deepEqual(view.phases, []);
});


test("returns null for a non-running run", () => {
  assert.equal(buildPipelineProgressView({ status: "Completed" }), null);
});
