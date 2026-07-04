import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";

export function CampaignDetailModal({ campaign, onClose, onEdit }) {
  if (!campaign) return null;

  return (
    <Modal title="Campaign Details" onClose={onClose}>
      <div className="space-y-4 text-sm">
        <div>
          <h4 className="text-xl font-semibold">{campaign.campaignName}</h4>
          <p className="text-slate-500">{campaign.positionName}</p>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <Info label="Campaign Code" value={campaign.campaignCode} />
          <Info label="Created By" value={campaign.createdByName} />
          <Info label="Updated By" value={campaign.updatedByName} />
          <Info label="Location" value={campaign.location} />
          <Info label="Experience" value={campaign.experience} />
          <Info label="Status" value={campaign.status} />
          <Info label="Target Profiles" value={campaign.targetProfiles} />
          <Info label="Candidates Found" value={campaign.candidates} />
          <Info label="Shortlisted" value={campaign.shortlisted} />
          <Info label="Sample CV" value={campaign.sampleCvName || "-"} />
        </div>

        <div>
          <p className="mb-2 font-medium text-slate-700">Desired Skills</p>
          <div className="flex flex-wrap gap-2">
            {(campaign.desiredSkills || []).map((skill) => (
              <Badge key={skill} tone="orange">
                {skill}
              </Badge>
            ))}
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onEdit(campaign)}>
            Edit Manually
          </Button>
          <Button onClick={onClose}>Done</Button>
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