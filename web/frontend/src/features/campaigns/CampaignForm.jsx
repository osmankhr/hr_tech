import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { InputField } from "../../components/ui/InputField";
import { SkillSelector } from "../../components/ui/SkillSelector";
import { PlatformSourceSelector } from "./PlatformSourceSelector";

export function CampaignForm({
  form,
  updateForm,
  pipelineConfig,
  onPipelineConfigChange,
  onLocationChange,
  onAddLocation,
  onRemoveLocation,
  pipelineConfigLoading = false,
  saving = false,
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
  isModal = false,
}) {
  const Container = isModal ? "div" : Card;
  const containerProps = isModal ? { className: "space-y-4" } : { className: "mb-6 p-5" };

  return (
    <Container {...containerProps}>
      {!isModal && (
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h3 className="text-base font-semibold text-slate-900">Edit Campaign &amp; Pipeline Configuration</h3>
            <p className="mt-1 text-sm text-slate-500">
              Update campaign details, locations, platform sources, job description, and filter criteria.
            </p>
          </div>

          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </div>
      )}

      {isModal && (
        <p className="mb-2 text-sm text-slate-500">
          Update campaign details, locations, platform sources, job description, and filter criteria.
        </p>
      )}

      {formError && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {formError}
        </div>
      )}

      {pipelineConfigLoading && (
        <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          Loading campaign pipeline configuration...
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
          label="Position name *"
          placeholder="e.g. Senior Data Scientist"
          value={form.positionName}
          onChange={(value) => updateForm("positionName", value)}
        />

        {pipelineConfig && onPipelineConfigChange && (
          <label className="block text-sm md:col-span-2">
            <span className="mb-1 block font-medium text-slate-700">
              Campaign Description *
            </span>
            <textarea
              value={pipelineConfig.pipelineDescription || ""}
              onChange={(event) =>
                onPipelineConfigChange("pipelineDescription", event.target.value)
              }
              rows={3}
              placeholder="Short summary of the hiring campaign and target profile"
              className="w-full rounded-lg border border-slate-300 px-4 py-3 text-sm outline-none focus:border-indigo-600"
            />
          </label>
        )}

        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-700">
            Experience *
          </span>
          <select
            className="w-full rounded-lg border border-slate-300 px-4 py-3 text-sm outline-none focus:border-indigo-600"
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
            className="w-full rounded-lg border border-slate-300 px-4 py-3 text-sm outline-none focus:border-indigo-600"
            value={form.status}
            onChange={(event) => updateForm("status", event.target.value)}
          >
            <option value="Active">Active</option>
            <option value="Past">Past</option>
            <option value="Draft">Draft</option>
            <option value="Paused">Paused</option>
          </select>
        </label>

        {!pipelineConfig && (
          <InputField
            label="Location *"
            placeholder="e.g. Istanbul, Remote, Hybrid"
            value={form.location}
            onChange={(value) => updateForm("location", value)}
          />
        )}

        <label className="block md:col-span-2">
          <span className="mb-1 block text-sm font-medium text-slate-700">
            Sample CV input, PDF only - optional
          </span>
          <input
            ref={sampleCvRef}
            type="file"
            accept="application/pdf,.pdf"
            className="w-full rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm file:mr-4 file:rounded-xl file:border-0 file:bg-slate-900 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-slate-800"
            onChange={handleCvUpload}
          />

          {form.sampleCvFile && (
            <span className="mt-1 block text-xs text-emerald-700">
              Selected: {form.sampleCvFile.name}
            </span>
          )}
        </label>
      </div>

      {pipelineConfig && (
        <>
          <div className="mt-5">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm font-medium text-slate-700">Locations *</p>
              {onAddLocation && (
                <button
                  type="button"
                  className="text-sm font-medium text-indigo-700"
                  onClick={onAddLocation}
                >
                  + Add Location
                </button>
              )}
            </div>

            <div className="space-y-2">
              {(pipelineConfig.locations || []).map((location, index) => (
                <div key={index} className="grid gap-2 md:grid-cols-[1fr_2fr_auto]">
                  <input
                    value={location.name || ""}
                    onChange={(event) =>
                      onLocationChange && onLocationChange(index, "name", event.target.value)
                    }
                    placeholder="name (example: turkey)"
                    className="rounded-lg border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-indigo-600"
                  />
                  <input
                    value={location.hint || ""}
                    onChange={(event) =>
                      onLocationChange && onLocationChange(index, "hint", event.target.value)
                    }
                    placeholder="hint (example: Focus on Turkey-based professionals)"
                    className="rounded-lg border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-indigo-600"
                  />
                  {onRemoveLocation && (
                    <button
                      type="button"
                      onClick={() => onRemoveLocation(index)}
                      className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
                    >
                      Remove
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>

          <PlatformSourceSelector
            platforms={pipelineConfig.platforms || []}
            activityDays={pipelineConfig.activityDays ?? 180}
            onPlatformsChange={(nextPlatforms) =>
              onPipelineConfigChange && onPipelineConfigChange("platforms", nextPlatforms)
            }
            onActivityDaysChange={(nextDays) =>
              onPipelineConfigChange && onPipelineConfigChange("activityDays", nextDays)
            }
          />

          <div className="mt-4 grid gap-4 xl:grid-cols-2">
            <label className="text-sm">
              <span className="mb-1 block font-medium text-slate-700">
                Job Description (Markdown) *
              </span>
              <textarea
                value={pipelineConfig.jobDescription || ""}
                onChange={(event) =>
                  onPipelineConfigChange &&
                  onPipelineConfigChange("jobDescription", event.target.value)
                }
                rows={12}
                className="w-full rounded-lg border border-slate-300 px-3 py-2.5 font-mono text-xs outline-none focus:border-indigo-600"
              />
            </label>

            <label className="text-sm">
              <span className="mb-1 block font-medium text-slate-700">
                Filter Criteria (Markdown) *
              </span>
              <textarea
                value={pipelineConfig.filterCriteria || ""}
                onChange={(event) =>
                  onPipelineConfigChange &&
                  onPipelineConfigChange("filterCriteria", event.target.value)
                }
                rows={12}
                className="w-full rounded-lg border border-slate-300 px-3 py-2.5 font-mono text-xs outline-none focus:border-indigo-600"
              />
            </label>
          </div>
        </>
      )}

      <SkillSelector
        skillInput={skillInput}
        setSkillInput={setSkillInput}
        selectedSkills={selectedSkills}
        availableSkillSuggestions={availableSkillSuggestions}
        addSkill={addSkill}
        removeSkill={removeSkill}
        handleSkillKeyDown={handleSkillKeyDown}
      />

      <div className="mt-6 flex flex-wrap items-center justify-end gap-3 border-t border-slate-200 pt-4">
        <Button onClick={onClose} variant="outline" disabled={saving}>
          Cancel
        </Button>

        <Button onClick={onSave} variant="dark" disabled={saving || pipelineConfigLoading}>
          {saving ? "Saving..." : submitLabel}
        </Button>
      </div>
    </Container>
  );
}