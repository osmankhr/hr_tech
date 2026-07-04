import { EmptyState } from "../../components/ui/EmptyState";
import { Icons } from "../../components/ui/Icon";
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
}) {
  return (
    <div
      className={
        full
          ? ""
          : "rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-200"
      }
    >
      {!full && (
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold">{title}</h3>
            <p className="text-sm text-slate-500">{subtitle}</p>
          </div>

          <Icons.Users className="h-5 w-5 text-slate-400" />
        </div>
      )}

      <div className="grid gap-3">
        {candidates.map((candidate) => (
          <CandidateCard
            key={candidate.id}
            candidate={candidate}
            onOpen={onOpenCandidate}
            onEdit={onEditCandidate}
          />
        ))}

        {candidates.length === 0 && (
          <EmptyState message="No candidates found." />
        )}
      </div>

      {!!onPageChange && !!totalPages && totalPages > 1 && (
        <div className="mt-4 flex items-center justify-between rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
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