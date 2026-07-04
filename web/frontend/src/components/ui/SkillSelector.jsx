export function SkillSelector({
  skillInput,
  setSkillInput,
  selectedSkills,
  availableSkillSuggestions,
  addSkill,
  removeSkill,
  handleSkillKeyDown,
}) {
  return (
    <div className="mt-4">
      <span className="mb-1 block text-sm font-medium text-slate-700">
        Desired skills *
      </span>

      <div className="rounded-2xl border border-slate-300 bg-white p-3 focus-within:border-orange-500">
        <div className="mb-2 flex flex-wrap gap-2">
          {selectedSkills.map((skill) => (
            <button
              key={skill}
              type="button"
              onClick={() => removeSkill(skill)}
              className="rounded-full border border-orange-200 bg-orange-50 px-3 py-1 text-xs font-medium text-orange-700 hover:bg-orange-100"
            >
              {skill} ×
            </button>
          ))}

          {selectedSkills.length === 0 && (
            <span className="text-xs text-slate-400">
              No skills added yet.
            </span>
          )}
        </div>

        <input
          className="w-full border-0 text-sm outline-none"
          placeholder="Type a skill and press Enter or comma"
          value={skillInput}
          onChange={(event) => setSkillInput(event.target.value)}
          onKeyDown={handleSkillKeyDown}
        />
      </div>

      <div className="mt-2 flex flex-wrap gap-2">
        {availableSkillSuggestions.map((skill) => (
          <button
            key={skill}
            type="button"
            onClick={() => addSkill(skill)}
            className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-700 hover:border-orange-200 hover:bg-orange-50 hover:text-orange-700"
          >
            + {skill}
          </button>
        ))}
      </div>
    </div>
  );
}