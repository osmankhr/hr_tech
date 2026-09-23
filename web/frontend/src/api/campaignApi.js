import { httpClient } from "./httpClient";
import { API_BASE_URL } from "../config/api";

// Most pipeline reads are scoped to a config version so an older config's candidate list stays
// viewable after an edit. Omitting it means "the current version".
function versionQuery(configVersionId, separator = "?") {
  if (configVersionId === null || configVersionId === undefined || configVersionId === "") {
    return "";
  }
  return `${separator}config_version_id=${encodeURIComponent(configVersionId)}`;
}

async function downloadFile(path, filename) {
  const token = localStorage.getItem("hr_auth_token") || "";

  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) {
    let message = "Export failed";
    try {
      const errorBody = await response.json();
      message = errorBody.detail || errorBody.message || message;
    } catch {
      message = response.statusText || message;
    }
    throw new Error(message);
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

export const campaignApi = {
  getAll() {
    return httpClient.get("/campaigns");
  },

  remove(id) {
    return httpClient.delete(`/campaigns/${id}`);
  },

  getById(id) {
    return httpClient.get(`/campaigns/${id}`);
  },

  create(formData) {
    return httpClient.post("/campaigns", formData);
  },

  update(id, formData) {
    return httpClient.put(`/campaigns/${id}`, formData);
  },

  setupPipeline(id, payload) {
    const formData = new FormData();
    formData.append("pipeline_name", payload.pipelineName || "");
    formData.append("pipeline_description", payload.pipelineDescription || "");
    formData.append("locations_json", JSON.stringify(payload.locations || []));
    formData.append("job_description", payload.jobDescription || "");
    formData.append("filter_criteria", payload.filterCriteria || "");

    return httpClient.post(`/campaigns/${id}/pipeline/setup`, formData);
  },

  importRankedResults(id, rankedResultsPath = "", configVersionId = null) {
    const formData = new FormData();
    formData.append("ranked_results_path", rankedResultsPath);
    // Attribute the import to the version the run belonged to, not just whatever is current.
    if (configVersionId !== null && configVersionId !== undefined) {
      formData.append("config_version_id", String(configVersionId));
    }
    return httpClient.post(`/campaigns/${id}/pipeline/import-ranked`, formData);
  },

  getTemplates() {
    return httpClient.get("/campaign-templates");
  },

  saveTemplate(payload) {
    const formData = new FormData();
    formData.append("template_name", payload.templateName || "");
    formData.append("pipeline_description", payload.pipelineDescription || "");
    formData.append("locations_json", JSON.stringify(payload.locations || []));
    formData.append("job_description", payload.jobDescription || "");
    formData.append("filter_criteria", payload.filterCriteria || "");
    if (payload.sourceCampaignId !== null && payload.sourceCampaignId !== undefined) {
      formData.append("source_campaign_id", String(payload.sourceCampaignId));
    }
    return httpClient.post("/campaign-templates", formData);
  },

  getPipelineRuns(id) {
    return httpClient.get(`/campaigns/${id}/pipeline/runs`);
  },

  getSearchResultsStatus(id, configVersionId = null) {
    return httpClient.get(
      `/campaigns/${id}/pipeline/search-results-status${versionQuery(configVersionId)}`
    );
  },

  getRankedResultsStatus(id, configVersionId = null) {
    return httpClient.get(
      `/campaigns/${id}/pipeline/ranked-results-status${versionQuery(configVersionId)}`
    );
  },

  getRankings(id, configVersionId = null) {
    return httpClient.get(`/campaigns/${id}/rankings${versionQuery(configVersionId)}`);
  },

  getConfigVersions(id) {
    return httpClient.get(`/campaigns/${id}/pipeline/config-versions`);
  },

  updateConfig(id, payload) {
    const formData = new FormData();
    formData.append("pipeline_name", payload.pipelineName || "");
    formData.append("pipeline_description", payload.pipelineDescription || "");
    formData.append("locations_json", JSON.stringify(payload.locations || []));
    formData.append("job_description", payload.jobDescription || "");
    formData.append("filter_criteria", payload.filterCriteria || "");
    return httpClient.put(`/campaigns/${id}/pipeline/config`, formData);
  },

  getScoringExplainer(id, configVersionId = null) {
    return httpClient.get(
      `/campaigns/${id}/pipeline/scoring-explainer${versionQuery(configVersionId)}`
    );
  },

  getUsageSummary(id, configVersionId = null) {
    return httpClient.get(
      `/campaigns/${id}/pipeline/usage-summary${versionQuery(configVersionId)}`
    );
  },

  runPipeline(id, runType = "full", maxCandidates = null) {
    const formData = new FormData();
    formData.append("run_type", runType);
    if (maxCandidates !== null && maxCandidates !== undefined) {
      formData.append("max_candidates", String(maxCandidates));
    }
    return httpClient.post(`/campaigns/${id}/pipeline/run`, formData);
  },

  getCandidatesByCampaign(id, page = 1, pageSize = 10, configVersionId = null) {
    return httpClient.get(
      `/campaigns/${id}/candidates?page=${page}&page_size=${pageSize}` +
        versionQuery(configVersionId, "&")
    );
  },

  exportRankedCsv(id, configVersionId = null) {
    return downloadFile(
      `/campaigns/${id}/pipeline/export-ranked-csv${versionQuery(configVersionId)}`,
      `campaign_${id}_ranked_results.csv`
    );
  },

  exportSearchCsv(id, configVersionId = null) {
    return downloadFile(
      `/campaigns/${id}/pipeline/export-search-csv${versionQuery(configVersionId)}`,
      `campaign_${id}_search_results.csv`
    );
  },
};