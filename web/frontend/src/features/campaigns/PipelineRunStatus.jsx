import { Check, LoaderCircle } from "lucide-react";
import { Badge } from "../../components/ui/Badge";
import { buildPipelineProgressView } from "./pipelineProgress";

export function PipelineRunStatus({ run }) {
  const progress = buildPipelineProgressView(run);
  if (!progress) {
    return null;
  }

  return (
    <div
      className="mt-4 overflow-hidden rounded-xl border border-indigo-200 bg-indigo-50/70"
      role="status"
      aria-live="polite"
    >
      <div className="flex flex-col gap-4 px-4 py-4 sm:px-5">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-100 text-indigo-700">
            <LoaderCircle className="h-5 w-5 animate-spin" />
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-semibold text-slate-900">{progress.title}</p>
              {progress.stepLabel && <Badge tone="brand">{progress.stepLabel}</Badge>}
            </div>
            <p className="mt-1 text-sm text-slate-600">{progress.countLabel}</p>
            {progress.detail && (
              <p className="mt-1 text-xs text-slate-500">{progress.detail}</p>
            )}
            {progress.foundLabel && (
              <p className="mt-1 text-xs font-medium text-indigo-700">
                {progress.foundLabel}
              </p>
            )}
          </div>

          {progress.percentage !== null && (
            <span className="shrink-0 text-sm font-semibold tabular-nums text-indigo-700">
              {progress.percentage}%
            </span>
          )}
        </div>

        <div
          className="h-2 overflow-hidden rounded-full bg-indigo-100"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress.percentage ?? undefined}
          aria-label={progress.countLabel}
        >
          <div
            className={`h-full rounded-full bg-indigo-600 transition-all duration-500 ${
              progress.percentage === null ? "w-1/3 animate-pulse" : ""
            }`}
            style={
              progress.percentage === null
                ? undefined
                : { width: `${progress.percentage}%` }
            }
          />
        </div>

        {progress.phases.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {progress.phases.map((phase) => {
              const complete = phase.state === "complete";
              const active = phase.state === "active";

              return (
                <div
                  key={phase.key}
                  className={`flex min-w-[7rem] flex-1 items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${
                    active
                      ? "border-indigo-300 bg-white text-indigo-700 shadow-sm"
                      : complete
                        ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                        : "border-slate-200 bg-white/70 text-slate-400"
                  }`}
                >
                  <span
                    className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${
                      active
                        ? "bg-indigo-100 text-indigo-700"
                        : complete
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-slate-100 text-slate-400"
                    }`}
                  >
                    {complete ? (
                      <Check className="h-3.5 w-3.5" />
                    ) : active ? (
                      <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-600" />
                    ) : (
                      <span className="h-1.5 w-1.5 rounded-full bg-slate-300" />
                    )}
                  </span>
                  <span className="truncate">{phase.label}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
