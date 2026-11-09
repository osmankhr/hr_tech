import { useCallback, useEffect, useState } from "react";
import { campaignApi } from "../../api/campaignApi";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";

/**
 * Platform & API Settings panel for configuring Kaggle, GitHub, Hugging Face,
 * and Exa.ai credentials safely.
 *
 * Security design:
 * - Never displays raw secrets from the backend (only masked suffixes like ••••••••abcd).
 * - Supports importing a downloaded `kaggle.json` file directly in the browser to pre-fill
 *   KAGGLE_USERNAME and KAGGLE_KEY without manual copy-paste errors.
 */
export function PlatformSettingsPanel() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const [form, setForm] = useState({
    KAGGLE_USERNAME: "",
    KAGGLE_KEY: "",
    GITHUB_TOKEN: "",
    HF_TOKEN: "",
    EXA_API_KEY: "",
  });

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await campaignApi.getIntegrationSettings();
      setStatus(data);
      // Pre-fill non-secret KAGGLE_USERNAME if already configured
      const configuredUsername = data?.keys?.KAGGLE_USERNAME?.masked || "";
      setForm((prev) => ({
        ...prev,
        KAGGLE_USERNAME: prev.KAGGLE_USERNAME || configuredUsername,
      }));
    } catch (err) {
      setError(err.message || "Could not load platform integration settings.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const updateField = (key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setError("");
    setMessage("");
  };

  const handleKaggleJsonUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setError("");
    setMessage("");
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const username = (parsed.username || "").trim();
      const key = (parsed.key || "").trim();
      if (!username || !key) {
        setError("Invalid kaggle.json file: both 'username' and 'key' fields are required.");
        return;
      }
      setForm((prev) => ({
        ...prev,
        KAGGLE_USERNAME: username,
        KAGGLE_KEY: key,
      }));
      setMessage(
        `Loaded Kaggle credentials for "${username}" from kaggle.json. Click "Save API Settings" below to persist.`
      );
    } catch {
      setError("Could not parse kaggle.json. Please select a valid JSON file downloaded from Kaggle.");
    } finally {
      event.target.value = "";
    }
  };

  const handleSave = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");

    try {
      const credentials = {};
      Object.entries(form).forEach(([key, val]) => {
        const trimmed = (val || "").trim();
        if (trimmed) {
          credentials[key] = trimmed;
        }
      });

      const updated = await campaignApi.updateIntegrationSettings({
        credentials,
        clear_keys: [],
      });
      setStatus(updated);
      setForm((prev) => ({
        ...prev,
        KAGGLE_USERNAME: updated?.keys?.KAGGLE_USERNAME?.masked || "",
        KAGGLE_KEY: "",
        GITHUB_TOKEN: "",
        HF_TOKEN: "",
        EXA_API_KEY: "",
      }));
      setMessage("Platform API credentials saved securely.");
    } catch (err) {
      setError(err.message || "Could not save platform settings.");
    } finally {
      setSaving(false);
    }
  };

  const handleClearKey = async (keyToClear) => {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const keysToClear =
        keyToClear === "KAGGLE_BOTH"
          ? ["KAGGLE_USERNAME", "KAGGLE_KEY"]
          : [keyToClear];
      const updated = await campaignApi.updateIntegrationSettings({
        credentials: {},
        clear_keys: keysToClear,
      });
      setStatus(updated);
      if (keysToClear.includes("KAGGLE_USERNAME")) {
        setForm((prev) => ({ ...prev, KAGGLE_USERNAME: "", KAGGLE_KEY: "" }));
      }
      setMessage(`Cleared ${keysToClear.join(", ")}.`);
    } catch (err) {
      setError(err.message || "Could not clear key.");
    } finally {
      setSaving(false);
    }
  };

  const keys = status?.keys || {};
  const platforms = status?.platforms || {};

  return (
    <section className="space-y-6">
      <Card className="p-5">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h3 className="text-base font-semibold text-slate-900">
              Platform &amp; API Integration Settings
            </h3>
            <p className="mt-1 text-sm text-slate-500">
              Configure API credentials for Kaggle, GitHub, Hugging Face, and Exa.ai. Secrets are stored
              in the backend environment and are never exposed in plaintext after saving.
            </p>
          </div>
        </div>

        {loading && <p className="text-sm text-slate-500">Loading integration status...</p>}

        {error && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {message && (
          <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            {message}
          </div>
        )}

        {!loading && (
          <div className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-800">Kaggle Discovery</span>
                <Badge tone={platforms.kaggle?.official_api_configured ? "green" : "amber"}>
                  {platforms.kaggle?.official_api_configured
                    ? "Official API + Exa"
                    : platforms.kaggle?.exa_fallback_configured
                    ? "Exa Fallback Only"
                    : "Not Configured"}
                </Badge>
              </div>
              <p className="mt-1.5 text-xs text-slate-600">
                {platforms.kaggle?.official_api_configured
                  ? `Connected as ${keys.KAGGLE_USERNAME?.masked || "user"}`
                  : "Add Kaggle Username & Key for live kernel/competition activity checks."}
              </p>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-800">GitHub API</span>
                <Badge tone={platforms.github?.token_configured ? "green" : "brand"}>
                  {platforms.github?.token_configured ? "Authenticated (5000/hr)" : "Public (60/hr)"}
                </Badge>
              </div>
              <p className="mt-1.5 text-xs text-slate-600">
                {platforms.github?.token_configured
                  ? `Token: ${keys.GITHUB_TOKEN?.masked}`
                  : "Works without a token; add GITHUB_TOKEN for higher rate limits."}
              </p>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-800">Hugging Face Hub</span>
                <Badge tone={platforms.huggingface?.token_configured ? "green" : "brand"}>
                  {platforms.huggingface?.token_configured ? "Authenticated" : "Public API"}
                </Badge>
              </div>
              <p className="mt-1.5 text-xs text-slate-600">
                {platforms.huggingface?.token_configured
                  ? `Token: ${keys.HF_TOKEN?.masked}`
                  : "Works without a token; add HF_TOKEN for higher rate limits."}
              </p>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-800">Exa.ai Search</span>
                <Badge tone={platforms.exa?.ready ? "green" : "red"}>
                  {platforms.exa?.ready ? "Configured" : "Missing Key"}
                </Badge>
              </div>
              <p className="mt-1.5 text-xs text-slate-600">
                {platforms.exa?.ready
                  ? `Key: ${keys.EXA_API_KEY?.masked}`
                  : "Required for primary candidate search."}
              </p>
            </div>
          </div>
        )}

        <form onSubmit={handleSave} className="space-y-6">
          {/* Kaggle Section */}
          <div className="rounded-xl border border-slate-200 p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h4 className="text-sm font-semibold text-slate-900">
                  1. Kaggle API Credentials (Official REST API)
                </h4>
                <p className="text-xs text-slate-500">
                  From Kaggle &rarr; Settings &rarr; Account &rarr; API (&ldquo;Create New Token&rdquo;).
                  You can upload your downloaded <code>kaggle.json</code> or enter the fields below.
                </p>
              </div>

              <div className="flex items-center gap-2">
                <label className="cursor-pointer rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-medium text-indigo-700 hover:bg-indigo-100">
                  Import kaggle.json
                  <input
                    type="file"
                    accept=".json,application/json"
                    onChange={handleKaggleJsonUpload}
                    className="hidden"
                  />
                </label>
                {(keys.KAGGLE_USERNAME?.configured || keys.KAGGLE_KEY?.configured) && (
                  <button
                    type="button"
                    onClick={() => handleClearKey("KAGGLE_BOTH")}
                    disabled={saving}
                    className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-100"
                  >
                    Clear Kaggle Keys
                  </button>
                )}
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block text-sm">
                <span className="mb-1 block font-medium text-slate-700">
                  Kaggle Username (<code>KAGGLE_USERNAME</code>)
                </span>
                <input
                  type="text"
                  value={form.KAGGLE_USERNAME}
                  onChange={(e) => updateField("KAGGLE_USERNAME", e.target.value)}
                  placeholder="example: mustafakaggle"
                  className="w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm outline-none focus:border-indigo-600"
                />
              </label>

              <label className="block text-sm">
                <div className="mb-1 flex items-center justify-between">
                  <span className="font-medium text-slate-700">
                    Kaggle API Key / Token (<code>KAGGLE_KEY</code>)
                  </span>
                  {keys.KAGGLE_KEY?.configured && (
                    <span className="text-xs text-emerald-700">
                      Current: {keys.KAGGLE_KEY.masked}
                    </span>
                  )}
                </div>
                <input
                  type="password"
                  value={form.KAGGLE_KEY}
                  onChange={(e) => updateField("KAGGLE_KEY", e.target.value)}
                  placeholder={
                    keys.KAGGLE_KEY?.configured
                      ? "Leave blank to keep existing key, or enter new key"
                      : "Enter Kaggle API key from kaggle.json"
                  }
                  className="w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm outline-none focus:border-indigo-600"
                />
              </label>
            </div>
          </div>

          {/* GitHub & Hugging Face Section */}
          <div className="rounded-xl border border-slate-200 p-4">
            <div className="mb-3">
              <h4 className="text-sm font-semibold text-slate-900">
                2. GitHub &amp; Hugging Face Tokens (Optional — Rate Limit Boosters)
              </h4>
              <p className="text-xs text-slate-500">
                GitHub and Hugging Face searches work out-of-the-box without tokens. Adding tokens
                increases API rate limits for large campaigns.
              </p>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block text-sm">
                <div className="mb-1 flex items-center justify-between">
                  <span className="font-medium text-slate-700">
                    GitHub Personal Access Token (<code>GITHUB_TOKEN</code>)
                  </span>
                  {keys.GITHUB_TOKEN?.configured && (
                    <span className="text-xs text-emerald-700">
                      Current: {keys.GITHUB_TOKEN.masked}
                    </span>
                  )}
                </div>
                <div className="flex gap-2">
                  <input
                    type="password"
                    value={form.GITHUB_TOKEN}
                    onChange={(e) => updateField("GITHUB_TOKEN", e.target.value)}
                    placeholder={
                      keys.GITHUB_TOKEN?.configured
                        ? "Leave blank to keep existing token"
                        : "ghp_... or github_pat_... (optional)"
                    }
                    className="w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm outline-none focus:border-indigo-600"
                  />
                  {keys.GITHUB_TOKEN?.configured && (
                    <button
                      type="button"
                      onClick={() => handleClearKey("GITHUB_TOKEN")}
                      disabled={saving}
                      className="rounded-lg border border-slate-300 px-3 py-2 text-xs text-slate-600 hover:bg-slate-100"
                    >
                      Clear
                    </button>
                  )}
                </div>
              </label>

              <label className="block text-sm">
                <div className="mb-1 flex items-center justify-between">
                  <span className="font-medium text-slate-700">
                    Hugging Face Access Token (<code>HF_TOKEN</code>)
                  </span>
                  {keys.HF_TOKEN?.configured && (
                    <span className="text-xs text-emerald-700">
                      Current: {keys.HF_TOKEN.masked}
                    </span>
                  )}
                </div>
                <div className="flex gap-2">
                  <input
                    type="password"
                    value={form.HF_TOKEN}
                    onChange={(e) => updateField("HF_TOKEN", e.target.value)}
                    placeholder={
                      keys.HF_TOKEN?.configured
                        ? "Leave blank to keep existing token"
                        : "hf_... (optional)"
                    }
                    className="w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm outline-none focus:border-indigo-600"
                  />
                  {keys.HF_TOKEN?.configured && (
                    <button
                      type="button"
                      onClick={() => handleClearKey("HF_TOKEN")}
                      disabled={saving}
                      className="rounded-lg border border-slate-300 px-3 py-2 text-xs text-slate-600 hover:bg-slate-100"
                    >
                      Clear
                    </button>
                  )}
                </div>
              </label>
            </div>
          </div>

          {/* Exa API Section */}
          <div className="rounded-xl border border-slate-200 p-4">
            <div className="mb-3">
              <h4 className="text-sm font-semibold text-slate-900">
                3. Exa.ai Primary Search Key
              </h4>
              <p className="text-xs text-slate-500">
                Used for primary semantic people search and Kaggle profile discovery.
              </p>
            </div>

            <label className="block text-sm">
              <div className="mb-1 flex items-center justify-between">
                <span className="font-medium text-slate-700">
                  Exa API Key (<code>EXA_API_KEY</code>)
                </span>
                {keys.EXA_API_KEY?.configured && (
                  <span className="text-xs text-emerald-700">
                    Current: {keys.EXA_API_KEY.masked}
                  </span>
                )}
              </div>
              <input
                type="password"
                value={form.EXA_API_KEY}
                onChange={(e) => updateField("EXA_API_KEY", e.target.value)}
                placeholder={
                  keys.EXA_API_KEY?.configured
                    ? "Leave blank to keep existing Exa API key"
                    : "Enter EXA_API_KEY"
                }
                className="w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm outline-none focus:border-indigo-600"
              />
            </label>
          </div>

          <div className="flex items-center gap-3">
            <Button type="submit" variant="dark" disabled={saving}>
              {saving ? "Saving..." : "Save API Settings"}
            </Button>
          </div>
        </form>
      </Card>
    </section>
  );
}
