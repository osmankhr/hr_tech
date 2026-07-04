import { httpClient } from "./httpClient";

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

  getRankings(id) {
    return httpClient.get(`/campaigns/${id}/rankings`);
  },

  runPipeline(id, runType = "full") {
    const formData = new FormData();
    formData.append("run_type", runType);
    return httpClient.post(`/campaigns/${id}/pipeline/run`, formData);
  },

  getCandidatesByCampaign(id, page = 1, pageSize = 10) {
    return httpClient.get(
      `/campaigns/${id}/candidates?page=${page}&page_size=${pageSize}`
    );
  },
};