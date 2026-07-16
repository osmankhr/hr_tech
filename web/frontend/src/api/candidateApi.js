import { httpClient } from "./httpClient";

export const candidateApi = {
  getAll() {
    return httpClient.get("/candidates");
  },

  getById(id) {
    return httpClient.get(`/candidates/${id}`);
  },

  update(id, formData) {
    return httpClient.put(`/candidates/${id}`, formData);
  },

  refresh() {
    return httpClient.post("/candidates/refresh");
  },

  getActivities(id) {
    return httpClient.get(`/candidates/${id}/activities`);
  },

  getComments(id) {
    return httpClient.get(`/candidates/${id}/comments`);
  },

  addComment(id, data) {
    const formData = new FormData();
    formData.append("content", data.content);
    if (data.parent_id) {
      formData.append("parent_id", data.parent_id);
    }
    return httpClient.post(`/candidates/${id}/comments`, formData);
  },
};