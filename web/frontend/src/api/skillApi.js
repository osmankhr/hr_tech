import { httpClient } from "./httpClient";

export const skillApi = {
  getAll() {
    return httpClient.get("/skills");
  },
};