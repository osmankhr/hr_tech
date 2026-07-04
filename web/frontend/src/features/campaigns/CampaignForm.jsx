import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { InputField } from "../../components/ui/InputField";
import { SkillSelector } from "../../components/ui/SkillSelector";

export function CampaignForm({
  form,
  updateForm,
  skillInput,
  setSkillInput,
  selectedSkills,
  availableSkillSuggestions,
  addSkill,
  removeSkill,
  handleSkillKeyDown,
  handleCvUpload,
  sampleCvRef,
  formError,
  onClose,
  onSave,
  submitLabel = "Save Campaign",
}) {
  return (
    <Card className="mb-6 p-5">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold">Campaign Form</h3>
          <p className="mt-1 text-sm text-slate-500">
            Add or update campaign search criteria.
          </p>
        </div>

        <Button variant="outline" onClick={onClose}>
          Close
        </Button>
      </div>

      {formError && (
        <div className="mb-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {formError}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <InputField
          label="Campaign name *"
          placeholder="e.g. Data Team Hiring Q3"
          value={form.campaignName}
          onChange={(value) => updateForm("campaignName", value)}
        />

        <InputField
          label="Location *"
          placeholder="e.g. Istanbul, Remote, Hybrid"
          value={form.location}
          onChange={(value) => updateForm("location", value)}
        />

        <InputField
          label="Position name *"
          placeholder="e.g. Senior Data Scientist"
          value={form.positionName}
          onChange={(value) => updateForm("positionName", value)}
        />

        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-700">
            Experience *
          </span>
          <select
            className="w-full rounded-2xl border border-slate-300 px-4 py-3 text-sm outline-none focus:border-orange-500"
            value={form.experience}
            onChange={(event) => updateForm("experience", event.target.value)}
          >
            <option value="0-1">0-1 years</option>
            <option value="1+">1+ years</option>
            <option value="2+">2+ years</option>
            <option value="3-5">3-5 years</option>
            <option value="5+">5+ years</option>
            <option value="8+">8+ years</option>
            <option value="10+">10+ years</option>
          </select>
        </label>

        <InputField
          type="number"
          label="Target profiles"
          min="1"
          value={form.targetProfiles}
          onChange={(value) => updateForm("targetProfiles", value)}
        />

        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-700">
            Status
          </span>
          <select
            className="w-full rounded-2xl border border-slate-300 px-4 py-3 text-sm outline-none focus:border-orange-500"
            value={form.status}
            onChange={(event) => updateForm("status", event.target.value)}
          >
            <option value="Active">Active</option>
            <option value="Past">Past</option>
            <option value="Draft">Draft</option>
            <option value="Paused">Paused</option>
          </select>
        </label>

        <label className="block md:col-span-2">
          <span className="mb-1 block text-sm font-medium text-slate-700">
            Sample CV input, PDF only - optional
          </span>
          <input
            ref={sampleCvRef}
            type="file"
            accept="application/pdf,.pdf"
            className="w-full rounded-2xl border border-slate-300 bg-white px-4 py-2.5 text-sm file:mr-4 file:rounded-xl file:border-0 file:bg-slate-900 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-slate-800"
            onChange={handleCvUpload}
          />

          {form.sampleCvFile && (
            <span className="mt-1 block text-xs text-emerald-700">
              Selected: {form.sampleCvFile.name}
            </span>
          )}
        </label>
      </div>

      <SkillSelector
        skillInput={skillInput}
        setSkillInput={setSkillInput}
        selectedSkills={selectedSkills}
        availableSkillSuggestions={availableSkillSuggestions}
        addSkill={addSkill}
        removeSkill={removeSkill}
        handleSkillKeyDown={handleSkillKeyDown}
      />

      <div className="mt-5 flex flex-wrap gap-2">
        <Button onClick={onSave} variant="dark">
          {submitLabel}
        </Button>

        <Button onClick={onClose} variant="outline">
          Cancel
        </Button>
      </div>
    </Card>
  );
}