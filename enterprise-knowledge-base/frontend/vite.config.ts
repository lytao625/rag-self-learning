import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const proxyTarget = env.API_PROXY_TARGET || "http://127.0.0.1:8000";
  return {
    plugins: [vue()],
    server: {
      port: 5173,
      host: true,
      proxy: {
        "/api": { target: proxyTarget, changeOrigin: true },
        "/health": { target: proxyTarget, changeOrigin: true },
        "/ready": { target: proxyTarget, changeOrigin: true },
      },
    },
  };
});
