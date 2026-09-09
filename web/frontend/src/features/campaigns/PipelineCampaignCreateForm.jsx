import { useState } from "react";
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
  templates = [],
  onUseTemplate,
}) {
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [appliedTemplateName, setAppliedTemplateName] = useState("");

  const applyTemplate = (rawId) => {
    if (!rawId || !onUseTemplate) {
      return;
    }
    const template = templates.find((item) => String(item.id) === String(rawId));
    onUseTemplate(Number(rawId));
    setAppliedTemplateName(template?.templateName || "");
  };

  const handleSelectTemplate = (event) => {
    const rawId = event.target.value;
    setSelectedTemplateId(rawId);
    // Apply immediately on selection so the recruiter sees the fields fill in
    // without a second click.
    applyTemplate(rawId);
  };

  const handleUseTemplate = () => applyTemplate(selectedTemplateId);

  return (
    <Card className="mb-6 p-5">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold text-slate-900">Create Pipeline Campaign</h3>
          <p className="mt-1 text-sm text-slate-500">
            Single input area for campaign name, description, locations, job description, and filter criteria.
          </p>
        </div>

        <Button variant="outline" onClick={onClose}>
          Close
        </Button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="mb-5 rounded-lg border border-slate-200 bg-slate-50 p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="block flex-1 text-sm">
            <span className="mb-1 block font-medium text-slate-700">Load From Saved Config</span>
            <select
              value={selectedTemplateId}
              onChange={handleSelectTemplate}
              className="w-full rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm outline-none focus:border-indigo-600"
            >
              <option value="">
                {templates.length === 0 ? "No saved configs yet" : "Select a saved config…"}
              </option>
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.templateName}
                  {template.sourceCampaignName
                    ? ` — used for ${template.sourceCampaignName}`
                    : " — not yet run"}
                </option>
              ))}
            </select>
          </label>

          <Button
            type="button"
            variant="outline"
            disabled={!selectedTemplateId}
            onClick={handleUseTemplate}
          >
            Re-apply Config
          </Button>
        </div>
        {appliedTemplateName ? (
          <p className="mt-2 text-xs font-medium text-emerald-700">
            ✓ Loaded “{appliedTemplateName}” into the fields below — review and edit before saving.
          </p>
        ) : (
          <p className="mt-2 text-xs text-slate-500">
            Selecting a config copies its campaign name, locations, job description, and filter
            criteria into the fields below — every campaign you create here is saved as a reusable
            config.
          </p>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Campaign Name *</span>
          <input
            value={form.name}
            onChange={(event) => onChange("name", event.target.value)}
            placeholder="Example Campaign - Senior ML Engineer"
            className="w-full rounded-lg border border-slate-300 px-4 py-3 outline-none focus:border-indigo-600"
          />
        </label>

        <label className="block text-sm md:col-span-2">
          <span className="mb-1 block font-medium text-slate-700">Campaign Description *</span>
          <textarea
            value={form.description}
            onChange={(event) => onChange("description", event.target.value)}
            rows={3}
            className="w-full rounded-lg border border-slate-300 px-4 py-3 outline-none focus:border-indigo-600"
          />
        </label>
      </div>

      <div className="mt-4">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-sm font-medium text-slate-700">Locations *</p>
          <button
            type="button"
            className="text-sm font-medium text-indigo-700"
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
                className="rounded-lg border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-600"
              />
              <input
                value={location.hint}
                onChange={(event) => onLocationChange(index, "hint", event.target.value)}
                placeholder="hint (example: Focus on Turkey-based professionals)"
                className="rounded-lg border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-600"
              />
              <button
                type="button"
                onClick={() => onRemoveLocation(index)}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
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
            className="w-full rounded-lg border border-slate-300 px-3 py-2.5 font-mono text-xs outline-none focus:border-indigo-600"
          />
        </label>

        <label className="text-sm">
          <span className="mb-1 block font-medium text-slate-700">Filter Criteria (Markdown) *</span>
          <textarea
            value={form.filterCriteria}
            onChange={(event) => onChange("filterCriteria", event.target.value)}
            rows={14}
            className="w-full rounded-lg border border-slate-300 px-3 py-2.5 font-mono text-xs outline-none focus:border-indigo-600"
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
