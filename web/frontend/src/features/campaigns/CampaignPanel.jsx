import { Briefcase } from "lucide-react";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { CampaignCard } from "./CampaignCard";

export function CampaignPanel({
  title,
  campaigns,
  full = false,
  onOpenCampaign,
  onViewDetails,
  onEditCampaign,
  onDeleteCampaign,
  renderExtraActions,
}) {
  return (
    <Card className="p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-slate-900">{title}</h3>
          <p className="text-sm text-slate-500">
            {campaigns.length} campaign(s)
          </p>
        </div>

        <Briefcase className="h-5 w-5 text-slate-400" />
      </div>

      <div className="space-y-3">
        {campaigns.map((campaign) => (
          <CampaignCard
            key={campaign.id}
            campaign={campaign}
            full={full}
            onOpen={onOpenCampaign}
            onViewDetails={onViewDetails}
            onEdit={onEditCampaign}
            onDelete={onDeleteCampaign}
            extraActions={renderExtraActions ? renderExtraActions(campaign) : null}
          />
        ))}

        {campaigns.length === 0 && (
          <EmptyState message="No campaigns found." />
        )}
      </div>
    </Card>
  );
}