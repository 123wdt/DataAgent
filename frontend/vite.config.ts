import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "fs";
import path from "path";

// 后端 FastAPI 服务在 8002，前端 dev 用 5173，跨域代理到后端。
// 鉴权密钥从项目根 .env 读取（仅在 vite dev server 的 Node 端注入，不会进前端 bundle）。
function readSecret(): string {
  try {
    const lines = fs.readFileSync(path.resolve(process.cwd(), "../.env"), "utf-8").split("\n");
    for (const l of lines) {
      const line = l.trim();
      if (line.startsWith("AUTH_SECRET=")) return line.split("=").slice(1).join("=");
    }
  } catch {
    /* 无 .env 则无鉴权 */
  }
  return "";
}

export default defineConfig(() => {
  const backend = process.env.VITE_API_BASE || "http://127.0.0.1:8002";
  const authSecret = readSecret();

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: backend,
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/api/, ""),
          configure: (proxy) => {
            if (!authSecret) return;
            proxy.on("proxyReq", (proxyReq) => {
              proxyReq.setHeader("Authorization", `Bearer ${authSecret}`);
            });
          },
        },
      },
    },
  };
});
