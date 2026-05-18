import axios from "axios";

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || "",
  timeout: 120000,
});

http.interceptors.request.use((config) => {
  const t = localStorage.getItem("ekb_token");
  if (t) {
    config.headers.Authorization = `Bearer ${t}`;
  }
  return config;
});

export default http;
