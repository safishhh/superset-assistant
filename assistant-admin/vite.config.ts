import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const R = (p: string) => new URL(p, import.meta.url).pathname;

export default defineConfig({
  base: "/admin/",
  plugins: [react()],
  resolve: {
    // 审计页复用 assistant-ext 的渲染组件，必须固定到后台自己的 React，
    // 否则扩展目录下的 node_modules 会引入第二份 React（hooks 报 null）
    alias: {
      react: R("./node_modules/react"),
      "react-dom": R("./node_modules/react-dom"),
    },
    dedupe: ["react", "react-dom"],
  },
  server: {
    port: 5173,
    proxy: {
      "/admin/api": "http://localhost:28088",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
