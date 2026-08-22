import { Mail, MapPin, Star } from "lucide-react";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";

function getCandidateStatusTone(status) {
  if (status === "Shortlisted") return "green";
  if (status === "Contacted") return "brand";
  if (status === "Reviewed") return "gray";
  if (status === "Rejected") return "red";
  return "amber";
}

export function CandidateCard({ candidate, onOpen, onEdit }) {
  return (
    <div className="rounded-lg border border-slate-200 p-4 transition hover:border-indigo-200 hover:bg-indigo-50/30">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div
          role="button"
          tabIndex={0}
          onClick={() => onOpen(candidate)}
          className="min-w-0 flex-1 cursor-pointer"
        >
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="font-semibold text-slate-900">{candidate.name}</h4>

            <Badge tone={getCandidateStatusTone(candidate.status)}>
              {candidate.status}
            </Badge>

            <Badge>{candidate.source}</Badge>
          </div>

          <p className="mt-1 text-sm font-medium text-slate-700">
            {candidate.role}
          </p>

          <div className="mt-2 flex flex-wrap gap-3 text-sm text-slate-500">
            <span className="inline-flex items-center gap-1">
              <MapPin className="h-3.5 w-3.5" /> {candidate.location}
            </span>
            <span className="inline-flex items-center gap-1">
              <Mail className="h-3.5 w-3.5" /> {candidate.email}
            </span>
            <span>Experience: {candidate.yearsExperience || "-"} years</span>
            {candidate.ranking?.rank && (
              <span>
                Rank: #{candidate.ranking.rank} ({candidate.ranking.category || "-"})
              </span>
            )}
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {(candidate.skills || []).map((skill) => (
              <Badge key={skill} tone="brand">
                {skill}
              </Badge>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-3 lg:flex-col lg:items-end">
          <div className="flex items-center gap-1 rounded-lg bg-amber-50 px-3 py-2 text-amber-700">
            <Star className="h-4 w-4" />
            <span className="font-semibold">
              {candidate.ranking?.manual_score ?? candidate.score}
            </span>
          </div>

          <Button variant="outline" onClick={() => onOpen(candidate)}>
            Open
          </Button>

          <Button variant="outline" onClick={() => onEdit(candidate)}>
            Edit
          </Button>
        </div>
      </div>
    </div>
  );
}