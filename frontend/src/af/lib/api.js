import axios from "axios";

export const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const api = axios.create({ baseURL: `${BACKEND_URL}/api/af` });
export const TOKEN_KEY = "af_token";

api.interceptors.request.use((cfg) => {
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

api.interceptors.response.use((r) => r, (err) => {
  if (err?.response?.status === 401 && !err.config.url.startsWith("/auth/")) {
    localStorage.removeItem(TOKEN_KEY);
    if (window.location.pathname !== "/login") window.location.href = "/login";
  }
  return Promise.reject(err);
});

export const errMsg = (e) => {
  const d = e?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join(" ");
  return e?.message || "Something went wrong";
};
