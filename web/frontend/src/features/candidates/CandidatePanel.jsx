import { useMemo, useState } from "react";
import { EmptyState } from "../../components/ui/EmptyState";
import { Icons } from "../../components/ui/Icon";
import { getSourcePlatformInfo } from "../../utils/sourceBadge";
import { CandidateCard } from "./CandidateCard";

export function CandidatePanel({
  candidates,
  full = false,
  onOpenCandidate,
  onEditCandidate,
  title = "Recent Candidates",
  subtitle = "Latest profiles from SQLite database",
  page,
  totalPages,
  onPageChange,
  headerAction = null,
  headerExtra = null,
}) {
  const [sourceFilter, setSourceFilter] = useState("all");

  const sourceSummary = useMemo(() => {
    const counts = new Map();
    (candidates || []).forEach((cand) => {
      const info = getSourcePlatformInfo(cand.source, cand.profileUrl);
      const existing = counts.get(info.key) || { ...info, count: 0 };
      existing.count += 1;
      counts.set(info.key, existing);
    });
    return Array.from(counts.values());
  }, [candidates]);

  const visibleCandidates = useMemo(() => {
    if (sourceFilter === "all") {
      return candidates;
    }
    return (candidates || []).filter(
      (cand) => getSourcePlatformInfo(cand.source, cand.profileUrl).key === sourceFilter
    );
  }, [candidates, sourceFilter]);

  return (
    <div
      className={
        full
          ? ""
          : "rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200"
      }
    >
      {!full && (
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-base font-semibold text-slate-900">{title}</h3>
            <p className="text-sm text-slate-500">{subtitle}</p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {headerExtra}
            {headerAction}
            <Icons.Users className="h-5 w-5 text-slate-400" />
          </div>
        </div>
      )}

      {sourceSummary.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setSourceFilter("all")}
            className={`rounded-full px-2.5 py-1 text-xs font-medium transition ${
              sourceFilter === "all"
                ? "bg-slate-900 text-white"
                : "bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
          >
            All Sources ({candidates.length})
          </button>
          {sourceSummary.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() =>
                setSourceFilter((prev) => (prev === item.key ? "all" : item.key))
              }
              className={`rounded-full px-2.5 py-1 text-xs font-semibold transition ${
                sourceFilter === item.key
                  ? "ring-2 ring-indigo-600 " + item.pillClass
                  : item.pillClass + " opacity-85 hover:opacity-100"
              }`}
            >
              {item.display} ({item.count})
            </button>
          ))}
        </div>
      )}

      <div className="grid gap-3">
        {visibleCandidates.map((candidate) => (
          <CandidateCard
            key={candidate.id}
            candidate={candidate}
            onOpen={onOpenCandidate}
            onEdit={onEditCandidate}
          />
        ))}

        {visibleCandidates.length === 0 && (
          <EmptyState message="No candidates found." />
        )}
      </div>

      {!!onPageChange && !!totalPages && totalPages > 1 && (
        <div className="mt-4 flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
          <button
            type="button"
            onClick={() => onPageChange(Math.max(1, (page || 1) - 1))}
            disabled={(page || 1) <= 1}
            className="rounded-xl border border-slate-300 px-3 py-1.5 disabled:opacity-50"
          >
            Previous
          </button>

          <span className="text-slate-600">
            Page {page || 1} / {totalPages}
          </span>

          <button
            type="button"
            onClick={() => onPageChange(Math.min(totalPages, (page || 1) + 1))}
            disabled={(page || 1) >= totalPages}
            className="rounded-xl border border-slate-300 px-3 py-1.5 disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}