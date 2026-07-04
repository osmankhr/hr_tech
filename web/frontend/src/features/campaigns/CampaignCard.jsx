import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";

function MetricBox({ label, value }) {
  return (
    <div className="rounded-2xl bg-slate-50 p-3">
      <p className="font-semibold">{value || 0}</p>
      <p className="text-xs text-slate-500">{label}</p>
    </div>
  );
}

export function CampaignCard({ campaign, full, onOpen, onEdit, onDelete }) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(campaign)}
      className="cursor-pointer rounded-2xl border border-slate-200 p-4 transition hover:border-orange-200 hover:bg-orange-50/30"
    >
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="font-semibold text-slate-900">
              {campaign.campaignName}
            </h4>

            <Badge tone={campaign.status === "Active" ? "green" : "gray"}>
              {campaign.status}
            </Badge>
          </div>

          <p className="mt-1 text-sm font-medium text-slate-700">
            {campaign.positionName}
          </p>

          <div className="mt-2 flex flex-wrap gap-3 text-sm text-slate-500">
            <span>📍 {campaign.location}</span>
            <span>📅 {campaign.createdAt || "-"}</span>
            <span>🧭 Exp: {campaign.experience}</span>
            <span>{campaign.campaignCode || campaign.id}</span>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {(campaign.desiredSkills || []).map((skill) => (
              <Badge key={skill} tone="orange">
                {skill}
              </Badge>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-3 gap-2 text-center text-sm">
          <MetricBox label="Target" value={campaign.targetProfiles} />
          <MetricBox label="Found" value={campaign.candidates} />
          <MetricBox label="Shortlist" value={campaign.shortlisted} />
        </div>
      </div>

      {full && (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            variant="outline"
            onClick={(event) => {
              event.stopPropagation();
              onOpen(campaign);
            }}
          >
            View Details
          </Button>

          <Button
            variant="outline"
            onClick={(event) => {
              event.stopPropagation();
              onEdit(campaign);
            }}
          >
            Edit Manually
          </Button>

          <Button
            variant="outline"
            onClick={(event) => event.stopPropagation()}
          >
            Run Search
          </Button>

          {onDelete && (
            <Button
              variant="danger"
              onClick={(event) => {
                event.stopPropagation();
                onDelete(campaign);
              }}
            >
              Delete
            </Button>
          )}
        </div>
      )}
    </div>
  );
}