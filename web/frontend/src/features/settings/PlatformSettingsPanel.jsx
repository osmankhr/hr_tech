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

  const [contactedStatus, setContactedStatus] = useState(null);
  const [contactedLoading, setContactedLoading] = useState(true);
  const [contactedUploading, setContactedUploading] = useState(false);
  const [contactedError, setContactedError] = useState("");
  const [contactedMessage, setContactedMessage] = useState("");

  const [form, setForm] = useState({
    KAGGLE_API_TOKEN: "",
    KAGGLE_USERNAME: "",
    KAGGLE_KEY: "",
    GITHUB_TOKEN: "",
    HF_TOKEN: "",
    EXA_API_KEY: "",
  });

  const loadContactedStatus = useCallback(async () => {
    setContactedLoading(true);
    try {
      const data = await campaignApi.getContactedCandidatesStatus();
      setContactedStatus(data);
    } catch (err) {
      setContactedError(err.message || "Could not load contacted candidates status.");
    } finally {
      setContactedLoading(false);
    }
  }, []);

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
    loadContactedStatus();
  }, [loadSettings, loadContactedStatus]);

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
        KAGGLE_API_TOKEN: "",
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
          ? ["KAGGLE_API_TOKEN", "KAGGLE_USERNAME", "KAGGLE_KEY"]
          : [keyToClear];
      const updated = await campaignApi.updateIntegrationSettings({
        credentials: {},
        clear_keys: keysToClear,
      });
      setStatus(updated);
      if (keysToClear.includes("KAGGLE_USERNAME") || keysToClear.includes("KAGGLE_API_TOKEN")) {
        setForm((prev) => ({
          ...prev,
          KAGGLE_API_TOKEN: "",
          KAGGLE_USERNAME: "",
          KAGGLE_KEY: "",
        }));
      }
      setMessage(`Cleared ${keysToClear.join(", ")}.`);
    } catch (err) {
      setError(err.message || "Could not clear key.");
    } finally {
      setSaving(false);
    }
  };

  const handleContactedUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setContactedUploading(true);
    setContactedError("");
    setContactedMessage("");
    try {
      const res = await campaignApi.uploadContactedCandidates(file);
      setContactedStatus(res);
      setContactedMessage(
        `Successfully uploaded "${file.name}". Indexed ${res.total_names} candidate names and ${res.total_urls} profile URLs across all campaigns.`
      );
    } catch (err) {
      setContactedError(err.message || "Failed to upload contacted candidates file.");
    } finally {
      setContactedUploading(false);
      event.target.value = "";
    }
  };

  const handleContactedDelete = async () => {
    if (!window.confirm("Are you sure you want to remove the company-wide contacted candidates list?")) {
      return;
    }
    setContactedUploading(true);
    setContactedError("");
    setContactedMessage("");
    try {
      const res = await campaignApi.deleteContactedCandidates();
      setContactedStatus(res);
      setContactedMessage("Company contacted candidates list removed.");
    } catch (err) {
      setContactedError(err.message || "Could not remove contacted candidates list.");
    } finally {
      setContactedUploading(false);
    }
  };

  const handleContactedDownload = async () => {
    try {
      await campaignApi.downloadContactedCandidates();
    } catch (err) {
      setContactedError(err.message || "Could not download file.");
    }
  };

  const handleComparisonDownload = async () => {
    try {
      await campaignApi.downloadComparisonReport();
    } catch (err) {
      setContactedError(err.message || "Could not download comparison report.");
    }
  };

  const keys = status?.keys || {};
  const platforms = status?.platforms || {};

  return (
    <section className="space-y-6">
      {/* Company Contacted Candidates Card */}
      <Card className="p-5">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-semibold text-slate-900">
                Company Contacted Candidates
              </h3>
              <Badge tone={contactedStatus?.configured ? "green" : "amber"}>
                {contactedStatus?.configured ? "Active Across All Campaigns" : "No List Uploaded"}
              </Badge>
            </div>
            <p className="mt-1 text-sm text-slate-500">
              Upload your company-wide Excel (<code>.xlsx</code>, <code>.xls</code>) or <code>.csv</code> list of contacted candidates.
              The search pipeline automatically eliminates these candidates across all campaigns, replenishes the pool with fresh profiles,
              and evaluates them independently so HR can compare system reviews against recruiter decisions.
            </p>
          </div>
        </div>

        {contactedError && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {contactedError}
          </div>
        )}

        {contactedMessage && (
          <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            {contactedMessage}
          </div>
        )}

        {contactedLoading ? (
          <p className="text-sm text-slate-500">Loading contacted candidates status...</p>
        ) : (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5">
                <span className="text-xs font-semibold text-slate-800">Status</span>
                <p className="mt-1 text-sm font-medium text-slate-900">
                  {contactedStatus?.configured ? "Active (Deduplicating)" : "Inactive"}
                </p>
                <p className="mt-0.5 text-xs text-slate-500">
                  {contactedStatus?.configured
                    ? `File: ${contactedStatus.filename}`
                    : "No spreadsheet active"}
                </p>
              </div>

              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5">
                <span className="text-xs font-semibold text-slate-800">Indexed Candidates</span>
                <p className="mt-1 text-sm font-medium text-slate-900">
                  {contactedStatus?.total_names || 0} names
                </p>
                <p className="mt-0.5 text-xs text-slate-500">
                  {contactedStatus?.total_urls || 0} profile URLs
                </p>
              </div>

              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5">
                <span className="text-xs font-semibold text-slate-800">Last Updated</span>
                <p className="mt-1 text-sm font-medium text-slate-900">
                  {contactedStatus?.updated_at
                    ? new Date(contactedStatus.updated_at).toLocaleDateString()
                    : "—"}
                </p>
                <p className="mt-0.5 text-xs text-slate-500">
                  {contactedStatus?.file_size_bytes
                    ? `${(contactedStatus.file_size_bytes / 1024).toFixed(1)} KB`
                    : "—"}
                </p>
              </div>

              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5">
                <span className="text-xs font-semibold text-slate-800">HR vs AI Benchmark</span>
                <p className="mt-1 text-sm font-medium text-slate-900">
                  {contactedStatus?.comparison_report_available ? "Ready" : "Pending runs"}
                </p>
                <p className="mt-0.5 text-xs text-slate-500">
                  {contactedStatus?.comparison_report_available
                    ? "Comparison spreadsheet available"
                    : "Evaluates on next campaign run"}
                </p>
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 p-4">
              <h4 className="text-sm font-medium text-slate-800">
                Upload or Replace Contacted Candidates List
              </h4>
              <p className="mt-0.5 text-xs text-slate-500">
                Supported: <code>.xlsx</code>, <code>.xls</code>, <code>.csv</code> (up to 25 MB).
                Matches on columns: <i>Candidate Name</i> (Turkish/English normalized), <i>Status</i>, <i>Notes/Feedback</i>, <i>Recruiter</i>, and <i>Profile URL</i>.
              </p>

              <div className="mt-3 flex flex-wrap items-center gap-3">
                <label className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-slate-900 bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-50">
                  <span>{contactedUploading ? "Processing File..." : "Choose Excel / CSV File"}</span>
                  <input
                    type="file"
                    accept=".xlsx,.xls,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,text/csv"
                    className="hidden"
                    disabled={contactedUploading}
                    onChange={handleContactedUpload}
                  />
                </label>

                {contactedStatus?.configured && (
                  <>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleContactedDownload}
                    >
                      Download Active List
                    </Button>

                    <Button
                      type="button"
                      variant="outline"
                      className="text-red-700 hover:bg-red-50"
                      onClick={handleContactedDelete}
                    >
                      Remove List
                    </Button>
                  </>
                )}

                {contactedStatus?.comparison_report_available && (
                  <Button
                    type="button"
                    variant="primary"
                    onClick={handleComparisonDownload}
                  >
                    Download HR vs AI Benchmark (.xlsx)
                  </Button>
                )}
              </div>
            </div>
          </div>
        )}
      </Card>

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
                  ? keys.KAGGLE_API_TOKEN?.configured
                    ? `Token: ${keys.KAGGLE_API_TOKEN?.masked}`
                    : `Connected as ${keys.KAGGLE_USERNAME?.masked || "user"}`
                  : "Add KAGGLE_API_TOKEN (or Username & Key) for live kernel/competition activity checks."}
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
                  Supports Kaggle API v2 Bearer tokens (<code>KAGGLE_API_TOKEN=KGAT_...</code>) or legacy{" "}
                  <code>kaggle.json</code> (<code>KAGGLE_USERNAME</code> + <code>KAGGLE_KEY</code>).
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
                {(keys.KAGGLE_API_TOKEN?.configured ||
                  keys.KAGGLE_USERNAME?.configured ||
                  keys.KAGGLE_KEY?.configured) && (
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

            <div className="mb-4">
              <label className="block text-sm">
                <div className="mb-1 flex items-center justify-between">
                  <span className="font-medium text-slate-700">
                    Kaggle API Token (<code>KAGGLE_API_TOKEN</code> — Recommended, e.g.{" "}
                    <code>KGAT_...</code>)
                  </span>
                  {keys.KAGGLE_API_TOKEN?.configured && (
                    <span className="text-xs text-emerald-700">
                      Current: {keys.KAGGLE_API_TOKEN.masked}
                    </span>
                  )}
                </div>
                <div className="flex gap-2">
                  <input
                    type="password"
                    value={form.KAGGLE_API_TOKEN}
                    onChange={(e) => updateField("KAGGLE_API_TOKEN", e.target.value)}
                    placeholder={
                      keys.KAGGLE_API_TOKEN?.configured
                        ? "Leave blank to keep existing token, or enter new KGAT_... token"
                        : "KGAT_..."
                    }
                    className="w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm outline-none focus:border-indigo-600"
                  />
                  {keys.KAGGLE_API_TOKEN?.configured && (
                    <button
                      type="button"
                      onClick={() => handleClearKey("KAGGLE_API_TOKEN")}
                      disabled={saving}
                      className="rounded-lg border border-slate-300 px-3 py-2 text-xs text-slate-600 hover:bg-slate-100"
                    >
                      Clear
                    </button>
                  )}
                </div>
              </label>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block text-sm">
                <span className="mb-1 block font-medium text-slate-700">
                  Legacy Kaggle Username (<code>KAGGLE_USERNAME</code> — Optional)
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
                    Legacy Kaggle Key (<code>KAGGLE_KEY</code> — Optional)
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
              <div className="mt-2 rounded-lg border border-indigo-200 bg-indigo-50/80 px-3.5 py-2.5 text-xs text-indigo-900">
                <p className="font-medium">
                  ℹ️ Bilgi: GitHub ve Hugging Face aramaları token girmeden de (Public API ile) doğrudan çalışır; ancak yüksek hacimli aramalarda rate-limit&apos;e takılmamak için opsiyonel olarak token ekleyebilirsiniz.
                </p>
                <p className="mt-0.5 text-indigo-700">
                  (Works without a token via Public API; you can optionally add tokens to avoid rate limits in high-volume searches.)
                </p>
              </div>
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
