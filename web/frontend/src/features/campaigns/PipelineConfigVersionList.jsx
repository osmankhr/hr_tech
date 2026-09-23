import { Card } from "../../components/ui/Card";
import { Badge } from "../../components/ui/Badge";

export function PipelineConfigVersionList({
  versions = [],
  loading,
  selectedVersionId,
  onSelectVersion,
}) {
  if (loading) {
    return <p className="text-sm text-slate-500">Loading config versions...</p>;
  }

  if (versions.length === 0) {
    return null;
  }

  return (
    <Card className="p-5">
      <div className="mb-3">
        <h3 className="text-base font-semibold text-slate-900">Config Version History</h3>
        <p className="text-sm text-slate-500">
          Every config change starts a new version once the previous one has results. Each version
          keeps its own candidate list — select one to view the candidates that config produced.
        </p>
      </div>

      <div className="space-y-2">
        {versions.map((version) => {
          const isSelected = String(version.id) === String(selectedVersionId);

          return (
            <button
              key={version.id}
              type="button"
              onClick={() => onSelectVersion?.(version.id)}
              className={`w-full rounded-lg border px-4 py-3 text-left text-sm transition ${
                isSelected
                  ? "border-indigo-500 bg-indigo-50 ring-1 ring-indigo-200"
                  : "border-slate-200 hover:bg-slate-50"
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-slate-800">v{version.versionNumber}</span>
                  {version.isCurrent && <Badge tone="brand">Current</Badge>}
                  {isSelected && <Badge tone="gray">Viewing</Badge>}
                  <span className="text-slate-500">{version.pipelineName}</span>
                </div>
                <span className="text-xs text-slate-500">Created {version.createdAt}</span>
              </div>

              <div className="mt-2 flex flex-wrap gap-2 text-xs">
                <Badge tone={version.hasResults ? "green" : "gray"}>
                  {version.hasResults ? "Has results" : "Not run yet"}
                </Badge>
                <Badge tone="gray">{version.importedCandidates} candidates</Badge>
                {typeof version.acceptedCandidates === "number" && (
                  <Badge tone="amber">{version.acceptedCandidates} accepted</Badge>
                )}
                {typeof version.rankedCandidates === "number" && (
                  <Badge tone="amber">{version.rankedCandidates} ranked</Badge>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </Card>
  );
}
