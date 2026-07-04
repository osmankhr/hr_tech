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
};