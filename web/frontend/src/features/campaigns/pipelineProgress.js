const PHASE_LABELS = {
  queries: "Generating search queries",
  search: "Searching for candidate profiles",
  filter: "AI reviewing candidates",
  ranking: "Scoring and ranking candidates",
  report: "Building shortlist report",
};

const PHASE_SHORT_LABELS = {
  queries: "Queries",
  search: "Search",
  filter: "Review",
  ranking: "Ranking",
  report: "Report",
};

function asProgressNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function buildCountLabel(phase, current, total) {
  if (current === null || total === null) {
    return "Processing...";
  }

  if (phase === "filter") {
    return `${current} of ${total} candidates reviewed`;
  }
  if (phase === "ranking") {
    return `${current} of ${total} candidates ranked`;
  }
  if (phase === "search") {
    return `${current} of ${total} searches completed`;
  }
  if (phase === "queries") {
    return `${current} of ${total} locations prepared`;
  }

  return `${current} of ${total} completed`;
}

export function buildPipelineProgressView(run) {
  if (!run || run.status !== "Running") {
    return null;
  }

  const progress = run.progress;
  if (!progress || !progress.phase) {
    return {
      title: "Pipeline is running",
      detail: "The first live status update will appear shortly.",
      stepLabel: null,
      countLabel: "Preparing live progress...",
      foundLabel: null,
      percentage: null,
      phases: [],
    };
  }

  const phase = progress.phase;
  const phaseKeys = Array.isArray(progress.phases)
    ? progress.phases.filter((item) => typeof item === "string" && item)
    : [];
  const activeIndex = phaseKeys.indexOf(phase);
  const current = asProgressNumber(progress.current);
  const total = asProgressNumber(progress.total);
  const found = asProgressNumber(progress.found);
  const percentage =
    current !== null && total !== null && total > 0
      ? Math.min(100, Math.max(0, Math.round((current / total) * 100)))
      : null;

  return {
    title: progress.label || PHASE_LABELS[phase] || "Pipeline is running",
    detail: progress.detail || null,
    stepLabel:
      activeIndex >= 0 && phaseKeys.length > 0
        ? `Step ${activeIndex + 1} of ${phaseKeys.length}`
        : null,
    countLabel: buildCountLabel(phase, current, total),
    foundLabel:
      phase === "search" && found !== null
        ? `${found} candidates found so far`
        : null,
    percentage,
    phases: phaseKeys.map((phaseKey, index) => ({
      key: phaseKey,
      label: PHASE_SHORT_LABELS[phaseKey] || phaseKey,
      state:
        activeIndex === -1 || index > activeIndex
          ? "upcoming"
          : index === activeIndex
            ? "active"
            : "complete",
    })),
  };
}
