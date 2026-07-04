import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";

export function CandidateDetailModal({ candidate, onClose, onEdit }) {
  if (!candidate) return null;

  return (
    <Modal title="Candidate Details" onClose={onClose}>
      <div className="max-h-[66vh] space-y-4 overflow-y-auto pr-1 text-sm">
        <div>
          <h4 className="text-xl font-semibold">{candidate.name}</h4>
          <p className="text-slate-500">{candidate.role}</p>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <Info label="Candidate Code" value={candidate.candidateCode} />
          <Info label="Email" value={candidate.email} />
          <Info label="Location" value={candidate.location} />
          <Info label="Source" value={candidate.source} />
          <Info label="Status" value={candidate.status} />
          <Info label="Score" value={candidate.score} />
          <Info label="Experience" value={candidate.yearsExperience} />
          <Info label="Last Updated" value={candidate.lastUpdated} />
          <Info label="Added By" value={candidate.createdByName} />
          <Info label="Updated By" value={candidate.updatedByName} />
          <Info label="First Contacted By" value={candidate.firstContactedByName} />
          <Info label="First Contacted At" value={candidate.firstContactedAt} />
        </div>

        {candidate.ranking && (
          <div>
            <p className="mb-2 font-medium text-slate-700">Explainable Score</p>
            <div className="space-y-3 rounded-2xl bg-slate-50 p-3">
              <div className="grid gap-3 md:grid-cols-3">
                <Info label="Manual Score" value={candidate.ranking.manual_score} />
                <Info label="Rank" value={candidate.ranking.rank} />
                <Info label="Category" value={candidate.ranking.category} />
              </div>

              <div>
                <p className="mb-2 text-xs uppercase tracking-wide text-slate-500">
                  Feature Contributions
                </p>

                <div className="grid gap-2">
                  {Object.entries(candidate.ranking.feature_contributions || {}).map(
                    ([featureName, points]) => (
                      <div
                        key={featureName}
                        className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2"
                      >
                        <span className="text-xs font-medium text-slate-700">
                          {featureName}
                        </span>
                        <span className="text-sm font-semibold text-slate-900">
                          {points}
                        </span>
                      </div>
                    )
                  )}

                  {Object.keys(candidate.ranking.feature_contributions || {}).length === 0 && (
                    <p className="text-sm text-slate-500">
                      No feature contribution data available.
                    </p>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        <div>
          <p className="mb-2 font-medium text-slate-700">LinkedIn / Profile</p>
          {candidate.profileUrl ? (
            <a
              href={candidate.profileUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-orange-600 underline"
            >
              {candidate.profileUrl}
            </a>
          ) : (
            <p className="text-slate-500">No profile URL available.</p>
          )}
        </div>

        <div>
          <p className="mb-2 font-medium text-slate-700">Skills</p>
          <div className="flex flex-wrap gap-2">
            {(candidate.skills || []).map((skill) => (
              <Badge key={skill} tone="orange">
                {skill}
              </Badge>
            ))}
          </div>
        </div>

        <div>
          <p className="mb-2 font-medium text-slate-700">Notes</p>
          <p className="rounded-2xl bg-slate-50 p-3 text-slate-700">
            {candidate.notes || "No notes."}
          </p>
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onEdit(candidate)}>
            Edit Manually
          </Button>

          {candidate.profileUrl && (
            <a
              href={candidate.profileUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Button>Open LinkedIn/Profile</Button>
            </a>
          )}
        </div>
      </div>
    </Modal>
  );
}

function Info({ label, value }) {
  return (
    <div className="rounded-2xl bg-slate-50 p-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="font-medium text-slate-900">{value || "-"}</p>
    </div>
  );
}