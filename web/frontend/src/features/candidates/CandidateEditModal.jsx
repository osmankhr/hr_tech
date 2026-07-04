import { useState } from "react";
import { Button } from "../../components/ui/Button";
import { InputField } from "../../components/ui/InputField";
import { Modal } from "../../components/ui/Modal";

export function CandidateEditModal({ candidate, onClose, onSave }) {
  // Guard clause placed first to prevent initializing state with null
  if (!candidate) return null;

  // Initializing state only when candidate safely exists
  const [form, setForm] = useState(candidate);

  const updateField = (field, value) => {
    setForm((previousForm) => ({
      ...previousForm,
      [field]: value,
    }));
  };

  // Fixed the syntax typo here
  const updateSkillsText = (value) => {
    updateField(
      "skills",
      value
        .split(",")
        .map((skill) => skill.trim())
        .filter(Boolean)
    );
  };

  return (
    <Modal title="Edit Candidate Manually" onClose={onClose} size="max-w-4xl">
      <div className="grid gap-4 md:grid-cols-2">
        <InputField
          label="Full name"
          value={form.name || ""}
          onChange={(value) => updateField("name", value)}
        />

        <InputField
          label="Email"
          value={form.email || ""}
          onChange={(value) => updateField("email", value)}
        />

        <InputField
          label="Current title"
          value={form.role || ""}
          onChange={(value) => updateField("role", value)}
        />

        <InputField
          label="Location"
          value={form.location || ""}
          onChange={(value) => updateField("location", value)}
        />

        <InputField
          label="LinkedIn/Profile URL"
          value={form.profileUrl || ""}
          onChange={(value) => updateField("profileUrl", value)}
        />

        <InputField
          type="number"
          label="Score"
          value={form.score || 0}
          onChange={(value) => updateField("score", value)}
        />

        <InputField
          type="number"
          label="Years experience"
          value={form.yearsExperience || 0}
          onChange={(value) => updateField("yearsExperience", value)}
        />

        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-700">
            Status
          </span>
          <select
            className="w-full rounded-2xl border border-slate-300 px-4 py-3 text-sm outline-none focus:border-orange-500"
            value={form.status || "New"}
            onChange={(event) => updateField("status", event.target.value)}
          >
            <option value="New">New</option>
            <option value="Reviewed">Reviewed</option>
            <option value="Contacted">Contacted</option>
            <option value="Shortlisted">Shortlisted</option>
            <option value="Rejected">Rejected</option>
          </select>
        </label>

        <label className="block md:col-span-2">
          <span className="mb-1 block text-sm font-medium text-slate-700">
            Skills, comma separated
          </span>
          <input
            className="w-full rounded-2xl border border-slate-300 px-4 py-3 text-sm outline-none focus:border-orange-500"
            value={(form.skills || []).join(", ")}
            onChange={(event) => updateSkillsText(event.target.value)}
          />
        </label>

        <label className="block md:col-span-2">
          <span className="mb-1 block text-sm font-medium text-slate-700">
            Notes
          </span>
          <textarea
            className="min-h-28 w-full rounded-2xl border border-slate-300 px-4 py-3 text-sm outline-none focus:border-orange-500"
            value={form.notes || ""}
            onChange={(event) => updateField("notes", event.target.value)}
          />
        </label>
      </div>

      <div className="mt-5 flex justify-end gap-2">
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>

        <Button variant="dark" onClick={() => onSave(form)}>
          Update Candidate
        </Button>
      </div>
    </Modal>
  );
}
