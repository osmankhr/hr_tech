import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";

export function PipelineCampaignCreateForm({
  form,
  onChange,
  onLocationChange,
  onAddLocation,
  onRemoveLocation,
  onSave,
  onClose,
  error,
  saving,
}) {
  return (
    <Card className="mb-6 p-5">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold">Create Pipeline Campaign</h3>
          <p className="mt-1 text-sm text-slate-500">
            Single input area for campaign name, description, locations, job description, and filter criteria.
          </p>
        </div>

        <Button variant="outline" onClick={onClose}>
          Close
        </Button>
      </div>

      {error && (
        <div className="mb-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Campaign Name *</span>
          <input
            value={form.name}
            onChange={(event) => onChange("name", event.target.value)}
            placeholder="Example Campaign - Senior ML Engineer"
            className="w-full rounded-2xl border border-slate-300 px-4 py-3 outline-none focus:border-orange-500"
          />
        </label>

        <label className="block text-sm md:col-span-2">
          <span className="mb-1 block font-medium text-slate-700">Campaign Description *</span>
          <textarea
            value={form.description}
            onChange={(event) => onChange("description", event.target.value)}
            rows={3}
            className="w-full rounded-2xl border border-slate-300 px-4 py-3 outline-none focus:border-orange-500"
          />
        </label>
      </div>

      <div className="mt-4">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-sm font-medium text-slate-700">Locations *</p>
          <button
            type="button"
            className="text-sm font-medium text-orange-600"
            onClick={onAddLocation}
          >
            + Add Location
          </button>
        </div>

        <div className="space-y-2">
          {(form.locations || []).map((location, index) => (
            <div key={index} className="grid gap-2 md:grid-cols-[1fr_2fr_auto]">
              <input
                value={location.name}
                onChange={(event) => onLocationChange(index, "name", event.target.value)}
                placeholder="name (example: turkey)"
                className="rounded-2xl border border-slate-300 px-3 py-2.5 outline-none focus:border-orange-500"
              />
              <input
                value={location.hint}
                onChange={(event) => onLocationChange(index, "hint", event.target.value)}
                placeholder="hint (example: Focus on Turkey-based professionals)"
                className="rounded-2xl border border-slate-300 px-3 py-2.5 outline-none focus:border-orange-500"
              />
              <button
                type="button"
                onClick={() => onRemoveLocation(index)}
                className="rounded-2xl border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <label className="text-sm">
          <span className="mb-1 block font-medium text-slate-700">Job Description (Markdown) *</span>
          <textarea
            value={form.jobDescription}
            onChange={(event) => onChange("jobDescription", event.target.value)}
            rows={14}
            className="w-full rounded-2xl border border-slate-300 px-3 py-2.5 font-mono text-xs outline-none focus:border-orange-500"
          />
        </label>

        <label className="text-sm">
          <span className="mb-1 block font-medium text-slate-700">Filter Criteria (Markdown) *</span>
          <textarea
            value={form.filterCriteria}
            onChange={(event) => onChange("filterCriteria", event.target.value)}
            rows={14}
            className="w-full rounded-2xl border border-slate-300 px-3 py-2.5 font-mono text-xs outline-none focus:border-orange-500"
          />
        </label>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        <Button onClick={onSave} variant="dark" disabled={saving}>
          {saving ? "Saving..." : "Save Campaign Config"}
        </Button>

        <Button onClick={onClose} variant="outline" disabled={saving}>
          Cancel
        </Button>
      </div>
    </Card>
  );
}
