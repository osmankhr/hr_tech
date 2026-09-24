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
  let message = `Request failed (${response.status})`;

  try {
    const errorBody = await response.json();

    if (Array.isArray(errorBody.detail)) {
      message = errorBody.detail
        .map((error) => {
          const field = error.loc?.slice(1).join(".") || "request";
          return `${field}: ${error.msg}`;
        })
        .join("\n");
    } else {
      message =
        errorBody.detail ||
        errorBody.message ||
        message;
    }

    console.error("API request failed:", {
      status: response.status,
      path,
      response: errorBody,
    });
  } catch {
    message = response.statusText || message;
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