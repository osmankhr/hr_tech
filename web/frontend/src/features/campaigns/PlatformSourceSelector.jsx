const PLATFORM_OPTIONS = [
  {
    id: "github",
    label: "GitHub",
    badge: "Open Source & Code",
    description:
      "Fetches developers with recent repository pushes, stars, followers, and programming languages.",
  },
  {
    id: "huggingface",
    label: "Hugging Face",
    badge: "ML Models & Datasets",
    description:
      "Fetches individual model and dataset authors with recent Hub updates, likes, and downloads.",
  },
  {
    id: "kaggle",
    label: "Kaggle",
    badge: "Kernels & Competitions",
    description:
      "Fetches active Kaggle notebook authors and competitors via Kaggle Official API + Exa discovery.",
  },
];

/**
 * Reusable campaign-level selector for toggling active candidate discovery
 * from GitHub, Hugging Face, and Kaggle alongside the primary Exa.ai search.
 */
export function PlatformSourceSelector({
  platforms = [],
  activityDays = 180,
  onPlatformsChange,
  onActivityDaysChange,
  onOpenSettings,
}) {
  const selectedSet = new Set(Array.isArray(platforms) ? platforms : []);

  const togglePlatform = (platformId) => {
    const next = new Set(selectedSet);
    if (next.has(platformId)) {
      next.delete(platformId);
    } else {
      next.add(platformId);
    }
    const ordered = PLATFORM_OPTIONS.map((p) => p.id).filter((id) => next.has(id));
    onPlatformsChange(ordered);
  };

  const selectAll = () => {
    onPlatformsChange(PLATFORM_OPTIONS.map((p) => p.id));
  };

  const clearAll = () => {
    onPlatformsChange([]);
  };

  return (
    <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50/70 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold text-slate-900">
              Candidate Discovery Platforms (Per-Campaign)
            </h4>
            <span className="rounded-full bg-indigo-100 px-2.5 py-0.5 text-xs font-medium text-indigo-800">
              Exa.ai Primary Search: Always Active
            </span>
          </div>
          <p className="mt-1 text-xs text-slate-600">
            Activate community platforms below to automatically fetch candidates who are{" "}
            <strong>actively contributing</strong> within the recency window alongside Exa.ai search.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={selectAll}
            className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
          >
            Enable All
          </button>
          <button
            type="button"
            onClick={clearAll}
            className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
          >
            Exa Only
          </button>
          {onOpenSettings && (
            <button
              type="button"
              onClick={onOpenSettings}
              className="rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-700 hover:bg-indigo-100"
            >
              API &amp; Kaggle Keys
            </button>
          )}
        </div>
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-3">
        {PLATFORM_OPTIONS.map((platform) => {
          const active = selectedSet.has(platform.id);
          return (
            <button
              key={platform.id}
              type="button"
              onClick={() => togglePlatform(platform.id)}
              className={`flex flex-col justify-between rounded-xl border p-3.5 text-left transition ${
                active
                  ? "border-indigo-600 bg-white shadow-sm ring-2 ring-indigo-600/15"
                  : "border-slate-200 bg-white/70 opacity-80 hover:border-slate-300 hover:opacity-100"
              }`}
            >
              <div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-slate-900">{platform.label}</span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                      active
                        ? "bg-emerald-100 text-emerald-800"
                        : "bg-slate-100 text-slate-600"
                    }`}
                  >
                    {active ? "Active" : "Off"}
                  </span>
                </div>
                <p className="mt-0.5 text-[11px] font-medium text-indigo-700">{platform.badge}</p>
                <p className="mt-1.5 text-xs leading-relaxed text-slate-600">
                  {platform.description}
                </p>
              </div>
            </button>
          );
        })}
      </div>

      <div className="mt-3 flex flex-col gap-2 border-t border-slate-200 pt-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-xs text-slate-600">
          <span className="font-medium text-slate-800">Active Contribution Window:</span> Only include
          GitHub / Hugging Face / Kaggle users with verified activity in the last{" "}
          <strong>{activityDays || 180}</strong> days.
        </div>

        <div className="flex items-center gap-2">
          <label className="text-xs font-medium text-slate-700" htmlFor="activity-days-input">
            Activity Days:
          </label>
          <input
            id="activity-days-input"
            type="number"
            min={1}
            max={3650}
            value={activityDays}
            onChange={(event) => {
              const raw = Number.parseInt(event.target.value, 10);
              onActivityDaysChange(Number.isFinite(raw) && raw > 0 ? raw : 180);
            }}
            className="w-24 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-900 outline-none focus:border-indigo-600"
          />
        </div>
      </div>

      <div className="mt-3 rounded-lg border border-indigo-200 bg-indigo-50/70 px-3 py-2 text-xs text-indigo-900">
        <strong>ℹ️ Bilgi:</strong> GitHub ve Hugging Face aramaları token girmeden de (Public API ile) çalışır; ancak yüksek hacimli aramalarda rate-limit&apos;e takılmamak için <strong>Platform &amp; API Settings</strong> ekranından opsiyonel olarak token ekleyebilirsiniz.
      </div>
    </div>
  );
}
