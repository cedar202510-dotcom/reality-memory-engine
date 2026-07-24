// memory-platform API 客户端（owner 直通：不带 Authorization 头）。
// dev 下走 Vite 代理 /api → 8000；部署时由反向代理保持同一前缀。
const BASE = "/api";

async function get(path, params) {
  const qs = params ? `?${new URLSearchParams(params)}` : "";
  const resp = await fetch(`${BASE}${path}${qs}`);
  if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`);
  return resp.json();
}

/** 找物查询。deep=true 走通道 2（混合召回 + VLM 精判），首次问新物体时更准但更慢。 */
export const whereIs = (name, deep = false) =>
  get("/v1/memory/objects/where-is", { name, deep });

/** 最近摄入帧 + 感知积压量（联调面板轮询用）。 */
export const recentFrames = (limit = 12) => get("/v1/memory/frames/recent", { limit });

export const healthz = () => get("/healthz");

/** 帧证据缩略图地址（TTL 删除后 404）。 */
export const evidenceUrl = (frameId) => `${BASE}/v1/memory/frames/${frameId}/evidence`;
