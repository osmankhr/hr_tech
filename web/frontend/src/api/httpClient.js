import { API_BASE_URL } from "../config/api";

function getToken() {
  return localStorage.getItem("hr_auth_token");
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getToken();

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let message = "Request failed";

    if (response.status === 413) {
      message = "File exceeds the maximum upload size limit allowed by the server.";
    } else if (response.status === 401) {
      message = "Session expired or not authenticated. Please log in again.";
    } else {
      try {
        const errorBody = await response.json();
        if (typeof errorBody.detail === "string" && errorBody.detail) {
          message = errorBody.detail;
        } else if (Array.isArray(errorBody.detail) && errorBody.detail.length > 0) {
          message = errorBody.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
        } else if (errorBody.message) {
          message = errorBody.message;
        } else if (response.statusText) {
          message = response.statusText;
        }
      } catch {
        message = response.statusText || `Request failed with status ${response.status}`;
      }
    }

    throw new Error(message);
  }

  return response.json();
}

export const httpClient = {
  get(path) {
    return request(path);
  },

  delete(path) {
    return request(path, {
      method: "DELETE",
    });
  },

  post(path, body) {
    return request(path, {
      method: "POST",
      body,
    });
  },

  put(path, body) {
    return request(path, {
      method: "PUT",
      body,
    });
  },
};