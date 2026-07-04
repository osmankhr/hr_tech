import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { CampaignCard } from "./CampaignCard";

export function CampaignPanel({
  title,
  campaigns,
  full = false,
  onOpenCampaign,
  onEditCampaign,
  onDeleteCampaign,
}) {
  return (
    <Card className="p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold">{title}</h3>
          <p className="text-sm text-slate-500">
            {campaigns.length} campaign(s)
          </p>
        </div>

        <span className="text-xl text-slate-400">💼</span>
      </div>

      <div className="space-y-3">
        {campaigns.map((campaign) => (
          <CampaignCard
            key={campaign.id}
            campaign={campaign}
            full={full}
            onOpen={onOpenCampaign}
            onEdit={onEditCampaign}
            onDelete={onDeleteCampaign}
          />
        ))}

        {campaigns.length === 0 && (
          <EmptyState message="No campaigns found." />
        )}
      </div>
    </Card>
  );
}