import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api → memory-platform（默认 8000，可用 RME_API_TARGET 覆盖）。
// 代理只在 dev server 生效；生产部署由反向代理承担同样职责。
const apiTarget = process.env.RME_API_TARGET || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    include: ["three", "three/examples/jsm/controls/OrbitControls.js"],
  },
  server: {
    host: "0.0.0.0",
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
