import { useMemo, useState } from "react";
import { Briefcase } from "lucide-react";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { CampaignCard } from "./CampaignCard";

const CAMPAIGN_SORT_OPTIONS = [
  { value: "newest", label: "Newest First (En Yeni)" },
  { value: "name_asc", label: "Name: A → Z" },
  { value: "name_desc", label: "Name: Z → A" },
  { value: "found_desc", label: "Found Candidates: High → Low" },
  { value: "shortlisted_desc", label: "Shortlisted: High → Low" },
];

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
  const [sortBy, setSortBy] = useState("newest");

  const sortedCampaigns = useMemo(() => {
    const list = [...(campaigns || [])];
    list.sort((a, b) => {
      if (sortBy === "name_asc") {
        return String(a.campaignName || "").localeCompare(
          String(b.campaignName || ""),
          undefined,
          { sensitivity: "base" }
        );
      }
      if (sortBy === "name_desc") {
        return String(b.campaignName || "").localeCompare(
          String(a.campaignName || ""),
          undefined,
          { sensitivity: "base" }
        );
      }
      if (sortBy === "found_desc") {
        return Number(b.found || 0) - Number(a.found || 0);
      }
      if (sortBy === "shortlisted_desc") {
        return Number(b.shortlisted || 0) - Number(a.shortlisted || 0);
      }
      // newest
      return Number(b.id || 0) - Number(a.id || 0);
    });
    return list;
  }, [campaigns, sortBy]);

  return (
    <Card className="p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-base font-semibold text-slate-900">{title}</h3>
          <p className="text-sm text-slate-500">
            {campaigns.length} campaign(s)
          </p>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-xs font-medium text-slate-500" htmlFor={`campaign-sort-${title}`}>
            Sort:
          </label>
          <select
            id={`campaign-sort-${title}`}
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 outline-none focus:border-indigo-600"
          >
            {CAMPAIGN_SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <Briefcase className="h-5 w-5 text-slate-400" />
        </div>
      </div>

      <div className="space-y-3">
        {sortedCampaigns.map((campaign) => (
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

        {sortedCampaigns.length === 0 && (
          <EmptyState message="No campaigns found." />
        )}
      </div>
    </Card>
  );
}