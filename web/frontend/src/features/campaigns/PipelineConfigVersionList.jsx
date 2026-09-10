import { Card } from "../../components/ui/Card";
import { Badge } from "../../components/ui/Badge";

export function PipelineConfigVersionList({ versions = [], loading }) {
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
          Every config change starts a new version once the previous one has results. The pipeline
          always runs against and displays the current (latest) version.
        </p>
      </div>

      <div className="space-y-2">
        {versions.map((version) => (
          <div
            key={version.id}
            className="rounded-lg border border-slate-200 px-4 py-3 text-sm"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="font-medium text-slate-800">v{version.versionNumber}</span>
                {version.isCurrent && <Badge tone="brand">Current</Badge>}
                <span className="text-slate-500">{version.pipelineName}</span>
              </div>
              <span className="text-xs text-slate-500">Created {version.createdAt}</span>
            </div>

            <div className="mt-2 flex flex-wrap gap-2 text-xs">
              <Badge tone={version.hasResults ? "green" : "gray"}>
                {version.hasResults ? "Has results" : "Not run yet"}
              </Badge>
              {typeof version.acceptedCandidates === "number" && (
                <Badge tone="amber">{version.acceptedCandidates} accepted</Badge>
              )}
              {typeof version.rankedCandidates === "number" && (
                <Badge tone="amber">{version.rankedCandidates} ranked</Badge>
              )}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
