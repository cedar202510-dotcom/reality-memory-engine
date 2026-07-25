import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { HDRLoader } from "three/examples/jsm/loaders/HDRLoader.js";
import {
  ArrowLeft,
  BadgeCheck,
  BatteryMedium,
  Boxes,
  CalendarClock,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Droplets,
  LocateFixed,
  MapPin,
  Mic,
  PackageOpen,
  Pause,
  Play,
  Search,
  Shirt,
  Smartphone,
  Sparkles,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

const HDRI_URL = "/assets/xr-room/polyhaven/_hdris/relax_inn_seaview_suite_2k.hdr";
const WARDROBE_ASSET = "/assets/pico/wardrobe/items";
const INVENTORY_ASSET = "/assets/pico/inventory/items";
const ASSET_VERSION = "v=4";
const wardrobeImage = (name) => `${WARDROBE_ASSET}/${name}.png?${ASSET_VERSION}`;
const inventoryImage = (name) => `${INVENTORY_ASSET}/${name}.png?${ASSET_VERSION}`;

const locateItems = [
  { id: "diffuser", label: "香薰", query: "香薰在哪？", location: "书桌左侧靠镜子", confidence: 0.86, direction: [0.7835, -0.3988, -0.4766], box: [74, 132] },
  { id: "desk-remote", label: "遥控器", query: "遥控器在哪？", location: "书桌右侧桌面", confidence: 0.88, direction: [0.8816, -0.421, -0.2132], box: [150, 46] },
  { id: "magazine", label: "书册", query: "我刚看的书在哪？", location: "书桌中央叠放", confidence: 0.84, direction: [0.8316, -0.3888, -0.3965], box: [170, 72] },
  { id: "teacups", label: "茶杯", query: "茶杯在哪？", location: "右侧柜顶黑色托盘", confidence: 0.8, direction: [0.9825, -0.1718, 0.0725], box: [174, 72] },
  { id: "kettle", label: "水壶", query: "水壶在哪？", location: "书桌右后侧", confidence: 0.82, direction: [0.9277, -0.3236, -0.1864], box: [106, 134] },
];

const clothingItems = {
  tops: [
    { id: "white-shirt", name: "白色衬衫", meta: "今天 · 通勤", image: wardrobeImage("white-shirt"), location: "主卧衣柜左侧", updated: "今天穿过" },
    { id: "black-knit", name: "黑色针织衫", meta: "3 天前 · 卧室", image: wardrobeImage("black-knit"), location: "主卧衣柜第二层", updated: "3 天前穿过" },
    { id: "blue-hoodie", name: "雾蓝卫衣", meta: "周末 · 休闲", image: wardrobeImage("blue-hoodie"), location: "衣柜右侧挂区", updated: "上周日穿过" },
    { id: "beige-cardigan", name: "燕麦开衫", meta: "昨天 · 衣柜", image: wardrobeImage("beige-cardigan"), location: "衣柜左侧挂区", updated: "昨天整理" },
  ],
  bottoms: [
    { id: "indigo-jeans", name: "深蓝牛仔裤", meta: "高频穿搭", image: wardrobeImage("indigo-jeans"), location: "衣柜下层左侧", updated: "今天 08:10 穿过" },
    { id: "black-trousers", name: "黑色阔腿裤", meta: "路演 · 正式", image: wardrobeImage("black-trousers"), location: "衣柜裤架第 2 位", updated: "周一穿过" },
    { id: "camel-skirt", name: "驼色半裙", meta: "上周 · 衣柜", image: wardrobeImage("camel-skirt"), location: "衣柜裤架第 4 位", updated: "上周五穿过" },
    { id: "ivory-trousers", name: "米白休闲裤", meta: "周末 · 轻松", image: wardrobeImage("ivory-trousers"), location: "衣柜下层右侧", updated: "6 天前穿过" },
  ],
  outfits: [
    {
      id: "pitch-outfit",
      name: "明天路演",
      meta: "白衬衫 + 黑色阔腿裤",
      images: [wardrobeImage("white-shirt"), wardrobeImage("black-trousers")],
      location: "两件都在主卧衣柜",
      updated: "Agent 推荐搭配",
    },
    {
      id: "weekend-outfit",
      name: "周末散步",
      meta: "雾蓝卫衣 + 深蓝牛仔裤",
      images: [wardrobeImage("blue-hoodie"), wardrobeImage("indigo-jeans")],
      location: "两件都在主卧衣柜",
      updated: "高频组合",
    },
    {
      id: "soft-outfit",
      name: "轻松见面",
      meta: "燕麦开衫 + 驼色半裙",
      images: [wardrobeImage("beige-cardigan"), wardrobeImage("camel-skirt")],
      location: "两件都在主卧衣柜",
      updated: "根据天气推荐",
    },
  ],
};

const electronics = [
  { id: "phone", name: "备用手机", meta: "电量 68%", image: inventoryImage("phone"), location: "书房抽屉", updated: "今天 09:12 在线", battery: 68 },
  { id: "headphones", name: "头戴耳机", meta: "上次使用 · 昨天", image: inventoryImage("headphones"), location: "书桌左侧挂架", updated: "昨天 22:18 使用", battery: 42 },
  { id: "laptop", name: "轻薄电脑", meta: "保修至 2027.03", image: inventoryImage("laptop"), location: "书房电脑包", updated: "今天 10:02 在线", battery: 83 },
  { id: "smartwatch", name: "运动手表", meta: "今日活动 63%", image: inventoryImage("smartwatch"), location: "卧室床头柜", updated: "12 分钟前同步", battery: 35 },
];

const careItems = [
  { id: "serum", name: "夜间精华", meta: "剩余约 42%", image: inventoryImage("serum"), location: "浴室镜柜", updated: "昨晚使用", opened: "2026.06.18", remaining: 42, estimate: "预计还能使用 18 天" },
  { id: "sunscreen", name: "日用防晒", meta: "剩余约 28%", image: inventoryImage("sunscreen"), location: "玄关随身包", updated: "今天 08:26 使用", opened: "2026.05.30", remaining: 28, estimate: "预计 11 天后用完" },
  { id: "face-cream", name: "保湿面霜", meta: "剩余约 71%", image: inventoryImage("face-cream"), location: "浴室镜柜", updated: "今天 07:48 使用", opened: "2026.07.12", remaining: 71, estimate: "预计还能使用 34 天" },
  { id: "perfume", name: "日常香氛", meta: "剩余约 64%", image: inventoryImage("perfume"), location: "卧室梳妆台", updated: "昨天使用", opened: "2026.03.09", remaining: 64, estimate: "按当前频率可用 5 个月" },
];

const dailyItems = [
  { id: "keys", name: "家门钥匙", meta: "随身物品", image: inventoryImage("keys"), location: "玄关右侧托盘", updated: "今天 10:08 放下" },
  { id: "umbrella", name: "折叠伞", meta: "今天可能下雨", image: inventoryImage("umbrella"), location: "玄关柜第二层", updated: "4 天前使用" },
  { id: "water-bottle", name: "保温水瓶", meta: "日常高频", image: inventoryImage("water-bottle"), location: "书桌右下方", updated: "今天 09:51 记录" },
];

const documentItems = [
  { id: "passport", name: "护照", meta: "有效期至 2031.08", image: inventoryImage("passport"), location: "卧室保险盒", updated: "42 天前确认", expiry: "2031.08.19" },
];

const inventoryGroups = {
  clothing: {
    label: "衣物",
    title: "衣物库",
    count: 27,
    icon: Shirt,
    defaultCategory: "tops",
    description: "衣服、搭配和最近穿着记录。",
    categories: {
      tops: { label: "上衣", total: 12, items: clothingItems.tops },
      bottoms: { label: "下装", total: 9, items: clothingItems.bottoms },
      outfits: { label: "搭配", total: 6, items: clothingItems.outfits },
    },
  },
  electronics: {
    label: "电子",
    title: "电子用品",
    count: 14,
    icon: Smartphone,
    defaultCategory: "all",
    description: "设备位置、电量和最近在线状态。",
    categories: {
      all: { label: "全部", total: 14, items: electronics },
      carry: { label: "随身", total: 8, items: [electronics[0], electronics[1], electronics[3]] },
      desktop: { label: "桌面", total: 6, items: [electronics[2], electronics[1]] },
    },
  },
  care: {
    label: "个护",
    title: "个护与消耗品",
    count: 18,
    icon: Droplets,
    defaultCategory: "all",
    description: "记录开封日期、剩余量和预计用完时间。",
    categories: {
      all: { label: "全部", total: 18, items: careItems },
      skincare: { label: "护肤", total: 13, items: careItems.slice(0, 3) },
      fragrance: { label: "香氛", total: 5, items: [careItems[3]] },
    },
  },
  daily: {
    label: "日用",
    title: "日常用品",
    count: 36,
    icon: PackageOpen,
    defaultCategory: "carry",
    description: "高频使用、容易遗忘位置的生活物品。",
    categories: {
      carry: { label: "随身", total: 17, items: [dailyItems[0], dailyItems[2]] },
      travel: { label: "出行", total: 9, items: [dailyItems[1], dailyItems[0], dailyItems[2]] },
    },
  },
  documents: {
    label: "证件",
    title: "证件与重要物品",
    count: 8,
    icon: BadgeCheck,
    defaultCategory: "identity",
    description: "重要证件的位置、有效期和确认记录。",
    categories: {
      identity: { label: "身份", total: 4, items: documentItems },
      cards: { label: "卡片", total: 4, items: documentItems },
    },
  },
};

const replayEvents = [
  { id: "r1", time: "10:18", date: "今天", itemId: "desk-remote", title: "遥控器最后出现", detail: "书桌右侧桌面，靠近椅背。" },
  { id: "r2", time: "09:42", date: "今天", itemId: "diffuser", title: "香薰位置确认", detail: "书桌左侧，镜子下方。" },
  { id: "r3", time: "21:46", date: "昨天", itemId: "teacups", title: "茶杯已经收纳", detail: "右侧柜顶黑色托盘。" },
];

const modeCopy = {
  locate: {
    eyebrow: "空间定位",
    title: (active) => active.query,
    body: (active) => `我记得它最后在${active.location}。`,
  },
  closet: {
    eyebrow: "物品全览",
    title: (_, category) => `正在看${category.label}`,
    body: (_, category, group) => `${group.label}类共有 ${category.total} 件记录，向左右移动视线浏览。`,
  },
  replay: {
    eyebrow: "记忆回放",
    title: () => "我带你回到记录发生的那一刻",
    body: (active) => `这条视觉证据指向${active.location}。`,
  },
};

function directionToScreen(camera, direction, width, height) {
  const dir = new THREE.Vector3(...direction).normalize();
  const forward = new THREE.Vector3();
  camera.getWorldDirection(forward);
  const point = camera.position.clone().add(dir.multiplyScalar(12));
  point.project(camera);

  return {
    x: (point.x * 0.5 + 0.5) * width,
    y: (-point.y * 0.5 + 0.5) * height,
    viewportWidth: width,
    viewportHeight: height,
    visible:
      forward.dot(new THREE.Vector3(...direction).normalize()) > 0.18 &&
      point.z < 1 &&
      point.x > -1 &&
      point.x < 1 &&
      point.y > -1 &&
      point.y < 1,
  };
}

export default function PicoMode() {
  const navigate = useNavigate();
  const pageRef = useRef(null);
  const mountRef = useRef(null);
  const cameraRef = useRef(null);
  const controlsRef = useRef(null);
  const closetStageRef = useRef(null);
  const conversationTimersRef = useRef([]);
  const [mode, setMode] = useState("locate");
  const [activeItem, setActiveItem] = useState("desk-remote");
  const [activeReplay, setActiveReplay] = useState("r1");
  const [inventoryGroup, setInventoryGroup] = useState("clothing");
  const [inventoryCategory, setInventoryCategory] = useState("tops");
  const [selectedObject, setSelectedObject] = useState("white-shirt");
  const [agentState, setAgentState] = useState("ready");
  const [labelPositions, setLabelPositions] = useState({});
  const [loading, setLoading] = useState(true);
  const [isPlaying, setIsPlaying] = useState(false);

  const active = useMemo(
    () => locateItems.find((item) => item.id === activeItem) || locateItems[0],
    [activeItem],
  );
  const group = inventoryGroups[inventoryGroup];
  const collection = group.categories[inventoryCategory];
  const selected = collection.items.find((item) => item.id === selectedObject) || collection.items[0];
  const currentReplay = replayEvents.find((event) => event.id === activeReplay) || replayEvents[0];
  const copy = modeCopy[mode];

  useEffect(() => {
    const mount = mountRef.current;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xdfe7e6);

    const camera = new THREE.PerspectiveCamera(54, mount.clientWidth / mount.clientHeight, 0.1, 100);
    camera.position.set(2.8, 1.65, 3.25);
    camera.lookAt(camera.position.clone().add(new THREE.Vector3(...active.direction).normalize()));
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.08;
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.copy(camera.position).add(new THREE.Vector3(...active.direction).normalize());
    controls.enableDamping = true;
    controls.enablePan = false;
    controls.enableZoom = false;
    controls.rotateSpeed = -0.28;
    controlsRef.current = controls;

    new HDRLoader().load(
      HDRI_URL,
      (texture) => {
        texture.mapping = THREE.EquirectangularReflectionMapping;
        scene.environment = texture;
        scene.background = texture;
        scene.backgroundIntensity = 1.04;
        setLoading(false);
      },
      undefined,
      () => setLoading(false),
    );

    let frameId = 0;
    let lastLabelUpdate = 0;
    const updateLabels = () => {
      if (performance.now() - lastLabelUpdate < 80) return;
      lastLabelUpdate = performance.now();
      const positions = {};
      for (const item of locateItems) {
        positions[item.id] = directionToScreen(camera, item.direction, mount.clientWidth, mount.clientHeight);
      }
      setLabelPositions(positions);
    };
    const animate = () => {
      frameId = window.requestAnimationFrame(animate);
      controls.update();
      updateLabels();
      renderer.render(scene, camera);
    };
    animate();

    const onResize = () => {
      const width = mount.clientWidth;
      const height = mount.clientHeight;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.cancelAnimationFrame(frameId);
      window.removeEventListener("resize", onResize);
      controls.dispose();
      renderer.dispose();
      mount.removeChild(renderer.domElement);
    };
  }, []);

  useEffect(() => {
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!camera || !controls) return undefined;
    const direction =
      mode === "closet"
        ? new THREE.Vector3(0.72, -0.2, -0.66).normalize()
        : new THREE.Vector3(...active.direction).normalize();
    const start = controls.target.clone();
    const end = camera.position.clone().add(direction);
    const startedAt = performance.now();
    const duration = mode === "replay" ? 720 : 460;
    let animationFrame = 0;

    const moveView = (time) => {
      const progress = Math.min((time - startedAt) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      controls.target.lerpVectors(start, end, eased);
      controls.update();
      if (progress < 1) animationFrame = window.requestAnimationFrame(moveView);
    };
    animationFrame = window.requestAnimationFrame(moveView);
    return () => window.cancelAnimationFrame(animationFrame);
  }, [mode, active]);

  useEffect(() => {
    setSelectedObject(collection.items[0].id);
    closetStageRef.current?.scrollTo({ left: 0, behavior: "smooth" });
  }, [inventoryGroup, inventoryCategory, collection.items]);

  useEffect(() => {
    if (!isPlaying || mode !== "replay") return undefined;
    const index = replayEvents.findIndex((event) => event.id === activeReplay);
    const timer = window.setTimeout(() => {
      if (index >= replayEvents.length - 1) {
        setIsPlaying(false);
        return;
      }
      const nextEvent = replayEvents[index + 1];
      setActiveReplay(nextEvent.id);
      setActiveItem(nextEvent.itemId);
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [isPlaying, mode, activeReplay]);

  useEffect(
    () => () => {
      conversationTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    },
    [],
  );

  const updateAgentParallax = (event) => {
    const page = pageRef.current;
    if (!page) return;
    const x = (event.clientX / window.innerWidth - 0.5) * 22;
    const y = (event.clientY / window.innerHeight - 0.5) * 14;
    page.style.setProperty("--agent-x", `${x}px`);
    page.style.setProperty("--agent-y", `${y}px`);
  };

  const runAgentResponse = () => {
    conversationTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    setAgentState("thinking");
    const speakingTimer = window.setTimeout(() => setAgentState("speaking"), 650);
    const readyTimer = window.setTimeout(() => setAgentState("ready"), 2600);
    conversationTimersRef.current = [speakingTimer, readyTimer];
  };

  const toggleConversation = () => {
    if (agentState === "listening") {
      runAgentResponse();
      return;
    }
    conversationTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    setAgentState("listening");
    const autoReplyTimer = window.setTimeout(runAgentResponse, 3200);
    conversationTimersRef.current = [autoReplyTimer];
  };

  const selectLocateItem = (item) => {
    setActiveItem(item.id);
    runAgentResponse();
  };

  const selectReplay = (event) => {
    setActiveReplay(event.id);
    setActiveItem(event.itemId);
    setIsPlaying(false);
  };

  const toggleReplay = () => {
    if (isPlaying) {
      setIsPlaying(false);
      return;
    }
    const firstEvent = replayEvents[0];
    setActiveReplay(firstEvent.id);
    setActiveItem(firstEvent.itemId);
    setIsPlaying(true);
  };

  const selectGroup = (id) => {
    const nextGroup = inventoryGroups[id];
    setInventoryGroup(id);
    setInventoryCategory(nextGroup.defaultCategory);
  };

  const scrollCloset = (direction) => {
    closetStageRef.current?.scrollBy({ left: direction * 260, behavior: "smooth" });
  };

  const agentContent =
    agentState === "listening"
      ? { eyebrow: "正在聆听", title: "请直接说，我在听", body: "说完后再轻点光球，或停顿片刻。" }
      : agentState === "thinking"
        ? { eyebrow: "正在理解", title: "我在查找相关记忆", body: "正在连接物品、位置和时间证据。" }
        : {
            eyebrow: agentState === "speaking" ? "正在回答" : copy.eyebrow,
            title: copy.title(active, collection, group),
            body: copy.body(active, collection, group),
          };

  return (
    <div
      ref={pageRef}
      className={`pico-page is-${mode} is-agent-${agentState} ${isPlaying ? "is-playing" : ""}`}
      onPointerMove={updateAgentParallax}
    >
      <div ref={mountRef} className="pico-canvas" />
      <div className="pico-atmosphere" />
      {mode === "replay" && <div key={activeReplay} className="pico-replay-transition" />}
      {loading && <div className="pico-loading">正在进入空间...</div>}

      <header className="pico-topbar">
        <button className="pico-round-button" onClick={() => navigate("/agent")} aria-label="返回应用">
          <ArrowLeft size={19} />
        </button>
        <div className="pico-brand">
          <span>REALITY MEMORY</span>
          <strong>空间助手</strong>
        </div>
        <nav className="pico-mode-nav" aria-label="PICO 模式">
          <button className={mode === "locate" ? "is-active" : ""} onClick={() => setMode("locate")} aria-label="打开空间定位">
            <LocateFixed size={18} />
            <span>定位</span>
          </button>
          <button className={mode === "closet" ? "is-active" : ""} onClick={() => setMode("closet")} aria-label="打开虚拟物品库">
            <Boxes size={18} />
            <span>物品库</span>
          </button>
          <button className={mode === "replay" ? "is-active" : ""} onClick={() => setMode("replay")} aria-label="打开时光回溯">
            <Clock3 size={18} />
            <span>回溯</span>
          </button>
        </nav>
      </header>

      <div className="pico-agent" aria-live="polite">
        <button
          className="pico-orb"
          onClick={toggleConversation}
          aria-label={agentState === "listening" ? "结束说话并让 Agent 回答" : "开始和 Agent 对话"}
        >
          <i className="pico-orb-ring pico-orb-ring-one" />
          <i className="pico-orb-ring pico-orb-ring-two" />
          <i className="pico-orb-halo" />
          <span />
        </button>
        <div className="pico-agent-utterance">
          <small>{agentContent.eyebrow}</small>
          <strong>{agentContent.title}</strong>
          <p>{agentContent.body}</p>
          <button className="pico-agent-voice-hint" onClick={toggleConversation}>
            <Mic size={13} />
            {agentState === "listening" ? "说完了" : "进入页面即可直接说话"}
            <span>也可注视光球 1 秒</span>
          </button>
        </div>
      </div>

      {mode === "locate" && (
        <>
          <div className="pico-locate-status">
            <LocateFixed size={19} />
            <div>
              <span>已定位 · {Math.round(active.confidence * 100)}%</span>
              <strong>{active.label}</strong>
              <p>{active.location}</p>
            </div>
          </div>
          <div className="pico-query-dock">
            <button className="pico-query-prompt" onClick={toggleConversation}>
              <Mic size={17} />
              <span>{agentState === "listening" ? "正在听你说话..." : "直接说出要找的物品"}</span>
            </button>
            <div className="pico-query-list">
              {locateItems.map((item) => (
                <button
                  key={item.id}
                  className={activeItem === item.id ? "is-active" : ""}
                  onClick={() => selectLocateItem(item)}
                >
                  {item.query}
                </button>
              ))}
            </div>
          </div>
          <DetectionLayer items={locateItems} activeItem={activeItem} labelPositions={labelPositions} onSelect={setActiveItem} />
        </>
      )}

      {mode === "closet" && (
        <section className="pico-closet">
          <div className="pico-closet-heading">
            <span>SPATIAL INVENTORY</span>
            <h1>{group.title}</h1>
            <p>{group.description}</p>
          </div>

          <div className="pico-library-groups" role="tablist" aria-label="物品大类">
            {Object.entries(inventoryGroups).map(([id, itemGroup]) => {
              const Icon = itemGroup.icon;
              return (
                <button key={id} className={inventoryGroup === id ? "is-active" : ""} onClick={() => selectGroup(id)}>
                  <Icon size={17} />
                  <strong>{itemGroup.label}</strong>
                  <span>{String(itemGroup.count).padStart(2, "0")}</span>
                </button>
              );
            })}
          </div>

          <div className="pico-subcategory-tabs" role="tablist" aria-label={`${group.label}分类`}>
            {Object.entries(group.categories).map(([id, category]) => (
              <button
                key={id}
                className={inventoryCategory === id ? "is-active" : ""}
                onClick={() => setInventoryCategory(id)}
              >
                {category.label}
                <span>{String(category.total).padStart(2, "0")}</span>
              </button>
            ))}
          </div>

          <button className="pico-closet-arrow is-left" onClick={() => scrollCloset(-1)} aria-label="上一件">
            <ChevronLeft size={22} />
          </button>
          <div ref={closetStageRef} className={`pico-closet-stage is-${inventoryGroup} is-${inventoryCategory}`}>
            {collection.items.map((item, index) => (
              <button
                key={item.id}
                className={`pico-garment-item pico-object-item ${selectedObject === item.id ? "is-active" : ""}`}
                style={{ "--garment-index": index }}
                onClick={() => setSelectedObject(item.id)}
              >
                {item.images ? (
                  <span className="pico-outfit-stack">
                    <img src={item.images[0]} alt="" />
                    <img src={item.images[1]} alt="" />
                  </span>
                ) : (
                  <img src={item.image} alt="" />
                )}
                <span className="pico-garment-shadow" />
                <span className="pico-garment-copy">
                  <strong>{item.name}</strong>
                  <small>{item.meta}</small>
                </span>
              </button>
            ))}
          </div>
          <button className="pico-closet-arrow is-right" onClick={() => scrollCloset(1)} aria-label="下一件">
            <ChevronRight size={22} />
          </button>

          <ItemInsight item={selected} group={inventoryGroup} />

          <div className="pico-closet-footer">
            <span>
              <Sparkles size={15} />
              选择物品后，可以继续询问位置、状态或使用建议
            </span>
            <button aria-label="搜索物品库">
              <Search size={17} />
            </button>
          </div>
        </section>
      )}

      {mode === "replay" && (
        <>
          <div className="pico-memory-marker">
            <span>{currentReplay.date}</span>
            <strong>{currentReplay.time}</strong>
            <p>{currentReplay.title}</p>
            <i />
          </div>
          <div className="pico-replay-controls">
            <button className="pico-play-button" onClick={toggleReplay} aria-label={isPlaying ? "暂停回放" : "播放回放"}>
              {isPlaying ? <Pause size={18} /> : <Play size={18} />}
            </button>
            <div className="pico-replay-track">
              <div className="pico-replay-progress" />
              {replayEvents.map((event) => (
                <button key={event.id} className={activeReplay === event.id ? "is-active" : ""} onClick={() => selectReplay(event)}>
                  <i />
                  <em>{event.time}</em>
                  <strong>{event.title}</strong>
                  <span>{event.detail}</span>
                </button>
              ))}
            </div>
          </div>
          <DetectionLayer
            items={locateItems.filter((item) => item.id === activeItem)}
            activeItem={activeItem}
            labelPositions={labelPositions}
            onSelect={setActiveItem}
          />
        </>
      )}
    </div>
  );
}

function ItemInsight({ item, group }) {
  const isCare = group === "care";
  const isElectronic = group === "electronics";

  return (
    <aside className="pico-item-insight">
      <span>当前物品</span>
      <strong>{item.name}</strong>
      {isCare && (
        <>
          <div className="pico-remaining">
            <div>
              <em>{item.remaining}%</em>
              <span>剩余</span>
            </div>
            <i>
              <b style={{ width: `${item.remaining}%` }} />
            </i>
          </div>
          <dl>
            <div>
              <dt><CalendarClock size={13} /> 开封日期</dt>
              <dd>{item.opened}</dd>
            </div>
            <div>
              <dt><Droplets size={13} /> 使用预估</dt>
              <dd>{item.estimate}</dd>
            </div>
          </dl>
        </>
      )}
      {isElectronic && (
        <>
          <div className="pico-remaining">
            <div>
              <em>{item.battery}%</em>
              <span>电量</span>
            </div>
            <i>
              <b style={{ width: `${item.battery}%` }} />
            </i>
          </div>
          <dl>
            <div>
              <dt><BatteryMedium size={13} /> 设备状态</dt>
              <dd>{item.updated}</dd>
            </div>
          </dl>
        </>
      )}
      {!isCare && !isElectronic && (
        <dl>
          <div>
            <dt><MapPin size={13} /> 记录位置</dt>
            <dd>{item.location}</dd>
          </div>
          <div>
            <dt><Clock3 size={13} /> 最近记录</dt>
            <dd>{item.updated}</dd>
          </div>
          {item.expiry && (
            <div>
              <dt><CalendarClock size={13} /> 有效期</dt>
              <dd>{item.expiry}</dd>
            </div>
          )}
        </dl>
      )}
    </aside>
  );
}

function DetectionLayer({ items, activeItem, labelPositions, onSelect }) {
  return (
    <div className="xr-label-layer">
      {items.map((item) => {
        const pos = labelPositions[item.id];
        if (!pos?.visible) return null;
        const [boxWidth, boxHeight] = item.box;
        const fullyInView =
          pos.x - boxWidth / 2 >= 8 &&
          pos.x + boxWidth / 2 <= pos.viewportWidth - 8 &&
          pos.y - boxHeight / 2 >= 8 &&
          pos.y + boxHeight / 2 <= pos.viewportHeight - 8;
        if (!fullyInView) return null;
        return (
          <button
            key={item.id}
            className={`xr-detect-box pico-detect-box ${activeItem === item.id ? "is-active" : ""}`}
            style={{
              width: boxWidth,
              height: boxHeight,
              transform: `translate(${pos.x}px, ${pos.y}px)`,
            }}
            onClick={() => onSelect(item.id)}
          >
            <span className="xr-detect-label">{item.label}</span>
          </button>
        );
      })}
    </div>
  );
}
