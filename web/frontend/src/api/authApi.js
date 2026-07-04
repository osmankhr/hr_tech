import { httpClient } from "./httpClient";

export const authApi = {
  signIn(email, password) {
    const formData = new FormData();
    formData.append("email", email);
    formData.append("password", password);

    return httpClient.post("/auth/signin", formData);
  },

  me() {
    return httpClient.get("/auth/me");
  },

  signOut() {
    return httpClient.post("/auth/signout");
  },
};