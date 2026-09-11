import { useEffect, useState } from "react";
import { Modal } from "../../components/ui/Modal";
import { Button } from "../../components/ui/Button";

export function PipelineConfigEditModal({
  initialConfig,
  willCreateNewVersion,
  onClose,
  onSave,
  saving,
  error,
}) {
  const [form, setForm] = useState(null);

  // Re-seed local form state whenever the modal is (re)opened for a config.
  useEffect(() => {
    if (!initialConfig) {
      setForm(null);
      return;
    }
    setForm({
      pipelineName: initialConfig.pipelineName || "",
      pipelineDescription: initialConfig.pipelineDescription || "",
      locations:
        initialConfig.locations && initialConfig.locations.length > 0
          ? initialConfig.locations
          : [{ name: "", hint: "" }],
      jobDescription: initialConfig.jobDescription || "",
      filterCriteria: initialConfig.filterCriteria || "",
    });
  }, [initialConfig]);

  if (!initialConfig || !form) {
    return null;
  }

  const updateField = (field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const updateLocation = (index, key, value) => {
    setForm((prev) => ({
      ...prev,
      locations: prev.locations.map((item, idx) =>
        idx === index ? { ...item, [key]: value } : item
      ),
    }));
  };

  const addLocation = () => {
    setForm((prev) => ({
      ...prev,
      locations: [...prev.locations, { name: "", hint: "" }],
    }));
  };

  const removeLocation = (index) => {
    setForm((prev) => ({
      ...prev,
      locations: prev.locations.filter((_, idx) => idx !== index),
    }));
  };

  const handleSave = () => {
    const cleanedLocations = (form.locations || [])
      .map((item) => ({ name: (item.name || "").trim(), hint: (item.hint || "").trim() }))
      .filter((item) => item.name);

    onSave({
      pipelineName: form.pipelineName.trim(),
      pipelineDescription: form.pipelineDescription.trim(),
      locations: cleanedLocations,
      jobDescription: form.jobDescription,
      filterCriteria: form.filterCriteria,
    });
  };

  return (
    <Modal title="Edit Pipeline Config" onClose={onClose} size="max-w-4xl">
      {willCreateNewVersion ? (
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          This config already has results. Saving will start a <strong>new version</strong> —
          the current version's results stay saved and viewable, and the new version starts
          with no run history yet.
        </div>
      ) : (
        <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          This config hasn't produced results yet, so saving will update it in place.
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Campaign Name *</span>
          <input
            value={form.pipelineName}
            onChange={(event) => updateField("pipelineName", event.target.value)}
            className="w-full rounded-lg border border-slate-300 px-4 py-3 outline-none focus:border-indigo-600"
          />
        </label>

        <label className="block text-sm md:col-span-2">
          <span className="mb-1 block font-medium text-slate-700">Campaign Description</span>
          <textarea
            value={form.pipelineDescription}
            onChange={(event) => updateField("pipelineDescription", event.target.value)}
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
            onClick={addLocation}
          >
            + Add Location
          </button>
        </div>

        <div className="space-y-2">
          {(form.locations || []).map((location, index) => (
            <div key={index} className="grid gap-2 md:grid-cols-[1fr_2fr_auto]">
              <input
                value={location.name}
                onChange={(event) => updateLocation(index, "name", event.target.value)}
                placeholder="name (example: turkey)"
                className="rounded-lg border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-600"
              />
              <input
                value={location.hint}
                onChange={(event) => updateLocation(index, "hint", event.target.value)}
                placeholder="hint (example: Focus on Turkey-based professionals)"
                className="rounded-lg border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-600"
              />
              <button
                type="button"
                onClick={() => removeLocation(index)}
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
            onChange={(event) => updateField("jobDescription", event.target.value)}
            rows={14}
            className="w-full rounded-lg border border-slate-300 px-3 py-2.5 font-mono text-xs outline-none focus:border-indigo-600"
          />
        </label>

        <label className="text-sm">
          <span className="mb-1 block font-medium text-slate-700">Filter Criteria (Markdown) *</span>
          <textarea
            value={form.filterCriteria}
            onChange={(event) => updateField("filterCriteria", event.target.value)}
            rows={14}
            className="w-full rounded-lg border border-slate-300 px-3 py-2.5 font-mono text-xs outline-none focus:border-indigo-600"
          />
        </label>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        <Button onClick={handleSave} variant="dark" disabled={saving}>
          {saving ? "Saving..." : willCreateNewVersion ? "Save as New Version" : "Save Config"}
        </Button>
        <Button onClick={onClose} variant="outline" disabled={saving}>
          Cancel
        </Button>
      </div>
    </Modal>
  );
}
