import { useEffect, useMemo, useState } from "react";
import { EmptyState } from "../../components/ui/EmptyState";
import { Icons } from "../../components/ui/Icon";
import { getSourcePlatformInfo } from "../../utils/sourceBadge";
import { CandidateCard } from "./CandidateCard";

const CANDIDATE_SORT_OPTIONS = [
  { value: "score_desc", label: "Score: High → Low (Yüksek → Düşük)" },
  { value: "score_asc", label: "Score: Low → High (Düşük → Yüksek)" },
  { value: "name_asc", label: "Name: A → Z" },
  { value: "name_desc", label: "Name: Z → A" },
  { value: "exp_desc", label: "Experience: High → Low" },
  { value: "source_asc", label: "Platform: A → Z" },
  { value: "recent", label: "Recently Updated" },
];

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
  pageSize = 10,
  headerAction = null,
  headerExtra = null,
}) {
  const [sourceFilter, setSourceFilter] = useState("all");
  const [sortBy, setSortBy] = useState("score_desc");
  const [internalPage, setInternalPage] = useState(1);

  useEffect(() => {
    setInternalPage(1);
  }, [sourceFilter, sortBy, candidates]);

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

  const filteredAndSortedCandidates = useMemo(() => {
    const list =
      sourceFilter === "all"
        ? [...(candidates || [])]
        : (candidates || []).filter(
            (cand) =>
              getSourcePlatformInfo(cand.source, cand.profileUrl).key === sourceFilter
          );

    const getEffectiveScore = (c) => {
      const manual = c?.ranking?.manual_score;
      if (manual !== null && manual !== undefined && Number.isFinite(Number(manual))) {
        return Number(manual);
      }
      return Number(c?.score || 0);
    };

    list.sort((a, b) => {
      if (sortBy === "score_desc") {
        const diff = getEffectiveScore(b) - getEffectiveScore(a);
        if (diff !== 0) return diff;
        return String(a.name || "").localeCompare(String(b.name || ""));
      }
      if (sortBy === "score_asc") {
        const diff = getEffectiveScore(a) - getEffectiveScore(b);
        if (diff !== 0) return diff;
        return String(a.name || "").localeCompare(String(b.name || ""));
      }
      if (sortBy === "name_asc") {
        return String(a.name || "").localeCompare(String(b.name || ""), undefined, {
          sensitivity: "base",
        });
      }
      if (sortBy === "name_desc") {
        return String(b.name || "").localeCompare(String(a.name || ""), undefined, {
          sensitivity: "base",
        });
      }
      if (sortBy === "exp_desc") {
        const expA = Number.isFinite(Number(a.yearsExperience)) ? Number(a.yearsExperience) : -1;
        const expB = Number.isFinite(Number(b.yearsExperience)) ? Number(b.yearsExperience) : -1;
        if (expB !== expA) return expB - expA;
        return getEffectiveScore(b) - getEffectiveScore(a);
      }
      if (sortBy === "source_asc") {
        const pA = getSourcePlatformInfo(a.source, a.profileUrl).label;
        const pB = getSourcePlatformInfo(b.source, b.profileUrl).label;
        const cmp = pA.localeCompare(pB);
        if (cmp !== 0) return cmp;
        return getEffectiveScore(b) - getEffectiveScore(a);
      }
      if (sortBy === "recent") {
        return String(b.lastUpdated || "").localeCompare(String(a.lastUpdated || ""));
      }
      return 0;
    });

    return list;
  }, [candidates, sourceFilter, sortBy]);

  const useClientPagination = !onPageChange || (candidates || []).length > pageSize;
  const effectivePage = useClientPagination ? internalPage : page || 1;
  const effectiveTotalPages = useClientPagination
    ? Math.max(1, Math.ceil(filteredAndSortedCandidates.length / pageSize))
    : totalPages || 1;
  const handlePageChange = useClientPagination ? setInternalPage : onPageChange;

  const visibleCandidates = useMemo(() => {
    if (!useClientPagination) {
      return filteredAndSortedCandidates;
    }
    const start = (effectivePage - 1) * pageSize;
    return filteredAndSortedCandidates.slice(start, start + pageSize);
  }, [filteredAndSortedCandidates, useClientPagination, effectivePage, pageSize]);

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

      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {sourceSummary.length > 0 && (
            <>
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
            </>
          )}
        </div>

        <div className="flex items-center gap-2">
          <label className="text-xs font-medium text-slate-500" htmlFor="candidate-sort-select">
            Sort:
          </label>
          <select
            id="candidate-sort-select"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 outline-none focus:border-indigo-600"
          >
            {CANDIDATE_SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

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

      {!!handlePageChange && effectiveTotalPages > 1 && (
        <div className="mt-4 flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
          <button
            type="button"
            onClick={() => handlePageChange(Math.max(1, effectivePage - 1))}
            disabled={effectivePage <= 1}
            className="rounded-xl border border-slate-300 px-3 py-1.5 disabled:opacity-50"
          >
            Previous
          </button>

          <span className="text-slate-600">
            Page {effectivePage} / {effectiveTotalPages} ({filteredAndSortedCandidates.length} candidates)
          </span>

          <button
            type="button"
            onClick={() => handlePageChange(Math.min(effectiveTotalPages, effectivePage + 1))}
            disabled={effectivePage >= effectiveTotalPages}
            className="rounded-xl border border-slate-300 px-3 py-1.5 disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}