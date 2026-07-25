// memory-platform API 客户端（owner 直通：不带 Authorization 头）。
// dev 下走 Vite 代理 /api → 8000；部署时由反向代理保持同一前缀。
const BASE = "/api";
const AGENT_BASE = "/agent-api";

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

/** 把一段录音转成字（采集调试与兼容链路保留）。
 *
 *  只转写，不入库：这段音频在后端用完即弃，不进 evidence_items、不生成记忆候选。
 *  顾问页使用浏览器实时语音识别，不经过这条上传链路。
 *  ASR 没配起来时后端回 503 而不是空串——空串会被界面显示成「你没说话」，那是在撒谎。 */
export const transcribe = async (blob) => {
  const form = new FormData();
  // 文件名只是给 multipart 用的占位；后端按 Content-Type 与容器嗅探解码
  form.append("audio", blob, "clip.webm");
  const resp = await fetch(`${BASE}/v1/memory/transcribe`, { method: "POST", body: form });
  if (!resp.ok) {
    // FastAPI 的 detail 是人话，原样往上抛；解析不出来才退回状态码
    const detail = await resp.json().then(d => d?.detail).catch(() => null);
    throw new Error(detail || `转写失败（${resp.status}）`);
  }
  return resp.json();
};

/** 向顾问提问。事实查询由 Agent Gateway 通过受限 AgentGrant 调用记忆平台。 */
export const askAgent = async (message, sessionId = null) => {
  const resp = await fetch(`${AGENT_BASE}/v1/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      session_id: sessionId || undefined,
      source: "WEB_APP",
      response_channel: "CALLER",
    }),
  });
  if (!resp.ok) {
    const detail = await resp.json().then((data) => data?.detail).catch(() => null);
    throw new Error(detail || `顾问请求失败（${resp.status}）`);
  }
  const payload = await resp.json();
  if (typeof payload.reply !== "string" || !payload.reply.trim()) {
    throw new Error("顾问返回了不兼容的回答");
  }
  return payload;
};

/** 最近摄入帧 + 感知积压量（联调面板轮询用）。 */
export const recentFrames = (limit = 12) => get("/v1/memory/frames/recent", { limit });

export const healthz = () => get("/healthz");

/** 帧证据缩略图地址（TTL 删除后 404）。 */
export const evidenceUrl = (frameId) => `${BASE}/v1/memory/frames/${frameId}/evidence`;

/** 后端返回的媒体路径（thumb_url / evidence_url 这类）补上 /api 前缀。
 *  后端一律给 /v1/... 的相对路径，不硬编码前缀——部署时前缀由反向代理决定。 */
export const apiUrl = (path) => (path ? `${BASE}${path}` : null);

// ---------------------------------------------------------------- 采集媒体总览
//
// 建在 evidence_items 上，所以能看到音频、视频和还在排队的条目——recentFrames 建在
// frame_assets 上，只看得到已完成感知的图片。
//
// 原始媒体有 TTL：过期后条目仍在（caption/转写/向量是长期表示），但 raw_url 为 null。

/** params: {kind, since, until, available_only, limit, offset} */
export const listMedia = (params = {}) =>
  get(
    "/v1/memory/media",
    Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== "")),
  );

/** 原始字节地址，任意模态，Content-Type 按真实扩展名。TTL 删除后 404。 */
export const mediaRawUrl = (evidenceItemId) =>
  `${BASE}/v1/memory/media/${evidenceItemId}/raw`;

// ---------------------------------------------------------------- 喜好度洞察
//
// 与 /preferences 的区别：那个按名字查某个物体说过什么，这个是聚合视图——
// 四路证据（口头评价/行动意图/实际使用/画面停留）融合成 0~100 的分数。
// 只有过了候选门的事件参与打分；还在等人确认的线索只体现在 pending_count 上。

/** params: {limit, min_confidence, with_verdict_only} */
export const preferenceInsights = (params = {}) =>
  get(
    "/v1/memory/insights/preferences",
    Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== "")),
  );

// ---------------------------------------------------------------- 记忆浏览
//
// 这几个是「翻记忆本身」而不是「问一件事」：确定性、不经 LLM，刷新两次结果一样。

/** 跨实体的近期事件流（上下文页）。含已被取代的事件，带 superseded 标记。 */
export const recentEvents = (limit = 30) => get("/v1/memory/events/recent", { limit });

/** 全部物品 + 当前位置，并按位置聚成组（全览页的连线就是这些组）。 */
export const objectGraph = (locatedOnly = false) =>
  get("/v1/memory/objects", locatedOnly ? { located_only: true } : undefined);

/** 单个物品的完整事件轨迹 + 当前投影（物品抽屉）。 */
export const objectTimeline = (entityId) => get(`/v1/memory/objects/${entityId}/timeline`);

/** 待确认线索：候选门没敢自动接受的记忆（置信度不够或撞了冲突）。 */
export const listClues = (limit = 50) => get("/v1/memory/clues", { limit });

/** 确认或忽略一条线索。decision: CONFIRM（升级为事件）| REJECT（判否，不写事件）。 */
export const resolveClue = (candidateId, decision, reason = "") =>
  post(`/v1/memory/clues/${candidateId}/resolve`, { decision, reason });

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
