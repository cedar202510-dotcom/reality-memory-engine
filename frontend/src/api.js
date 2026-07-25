// memory-platform API 客户端（owner 直通：不带 Authorization 头）。
// dev 下走 Vite 代理 /api → 8000；部署时由反向代理保持同一前缀。
const BASE = "/api";

async function request(method, path, { params, body } = {}) {
  const qs = params ? `?${new URLSearchParams(params)}` : "";
  const resp = await fetch(`${BASE}${path}${qs}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`);
  return resp.json();
}

const get = (path, params) => request("GET", path, { params });
const post = (path, body) => request("POST", path, { body });
const patch = (path, body) => request("PATCH", path, { body });

/** 找物查询。deep=true 走通道 2（混合召回 + VLM 精判），首次问新物体时更准但更慢。 */
export const whereIs = (name, deep = false) =>
  get("/v1/memory/objects/where-is", { name, deep });

/** 最近摄入帧 + 感知积压量（联调面板轮询用）。 */
export const recentFrames = (limit = 12) => get("/v1/memory/frames/recent", { limit });

export const healthz = () => get("/healthz");

/** 帧证据缩略图地址（TTL 删除后 404）。 */
export const evidenceUrl = (frameId) => `${BASE}/v1/memory/frames/${frameId}/evidence`;

// ---------------------------------------------------------------- 采集控制
//
// 这里下发的是**请求**不是命令：通信架构 §8 规定云端不能远程强制打开相机或麦克风，
// 设备端本地策略有完整的拒绝权，拒绝会回一条 REJECTED 回执。所以按钮点下去只代表
// 「请求已受理」，界面必须等回执才能说采到了。

export const listDevices = () => get("/internal/v1/devices");

/** 绑定设备到眼镜 App 运行时（探针/正式 App）与控制通道（adb/inbox）。 */
export const bindDevice = (deviceId, binding) =>
  patch(`/internal/v1/devices/${deviceId}/binding`, binding);

/** 下发一次采集请求。action: CAPTURE_PHOTO/CAPTURE_AUDIO/START_PERIODIC/PAUSE/RESUME/STOP */
export const createCaptureRequest = (deviceId, body) =>
  post(`/internal/v1/devices/${deviceId}/capture-requests`, body);

/** 近期采集请求与回执（控制台轮询）。 */
export const listCaptureRequests = (deviceId, limit = 20) =>
  get(`/internal/v1/devices/${deviceId}/capture-requests`, { limit });
