import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";

export function CampaignDeleteModal({
  campaign,
  deleting = false,
  error = "",
  onCancel,
  onConfirm,
}) {
  if (!campaign) return null;

  return (
    <Modal title="Delete Campaign" onClose={onCancel} size="max-w-2xl">
      <div className="space-y-4 text-sm">
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-red-800">
          <p className="font-semibold">This action cannot be undone.</p>
          <p className="mt-1 text-red-700">
            Deleting this campaign will remove linked candidates from the database and delete
            campaign files under candidate_pool/campaigns.
          </p>
        </div>

        <div className="rounded-2xl bg-slate-50 p-4">
          <p className="text-xs uppercase tracking-wide text-slate-500">Campaign</p>
          <p className="mt-1 text-base font-semibold text-slate-900">
            {campaign.campaignName || "Unnamed Campaign"}
          </p>
          <p className="mt-1 text-sm text-slate-500">
            {campaign.campaignCode || campaign.id}
          </p>
        </div>

        {error && (
          <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onCancel} disabled={deleting}>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={deleting}>
            {deleting ? "Deleting..." : "Delete Campaign"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
