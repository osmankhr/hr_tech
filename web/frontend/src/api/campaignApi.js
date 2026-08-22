import { httpClient } from "./httpClient";
import { API_BASE_URL } from "../config/api";

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

  importRankedResults(id, rankedResultsPath = "") {
    const formData = new FormData();
    formData.append("ranked_results_path", rankedResultsPath);
    return httpClient.post(`/campaigns/${id}/pipeline/import-ranked`, formData);
  },

  getPipelineRuns(id) {
    return httpClient.get(`/campaigns/${id}/pipeline/runs`);
  },

  getSearchResultsStatus(id) {
    return httpClient.get(`/campaigns/${id}/pipeline/search-results-status`);
  },

  getRankedResultsStatus(id) {
    return httpClient.get(`/campaigns/${id}/pipeline/ranked-results-status`);
  },

  getRankings(id) {
    return httpClient.get(`/campaigns/${id}/rankings`);
  },

  runPipeline(id, runType = "full", maxCandidates = null) {
    const formData = new FormData();
    formData.append("run_type", runType);
    if (maxCandidates !== null && maxCandidates !== undefined) {
      formData.append("max_candidates", String(maxCandidates));
    }
    return httpClient.post(`/campaigns/${id}/pipeline/run`, formData);
  },

  getCandidatesByCampaign(id, page = 1, pageSize = 10) {
    return httpClient.get(
      `/campaigns/${id}/candidates?page=${page}&page_size=${pageSize}`
    );
  },

  async exportRankedCsv(id) {
    const token = localStorage.getItem("hr_auth_token") || "";

    const response = await fetch(
      `${API_BASE_URL}/campaigns/${id}/pipeline/export-ranked-csv`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    );

    if (!response.ok) {
      let message = "CSV export failed";
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
    anchor.download = `campaign_${id}_ranked_results.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(objectUrl);
  },

  async exportSearchCsv(id) {
    const token = localStorage.getItem("hr_auth_token") || "";

    const response = await fetch(
      `${API_BASE_URL}/campaigns/${id}/pipeline/export-search-csv`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    );

    if (!response.ok) {
      let message = "CSV export failed";
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
    anchor.download = `campaign_${id}_search_results.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(objectUrl);
  },
};