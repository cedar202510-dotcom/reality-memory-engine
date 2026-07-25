import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Box, RotateCcw, Search, X } from "lucide-react";
import { apiUrl, objectGraph } from "./api";

// 层的颜色只是分辨用的，没有语义（真实数据里没有「品类」这个维度）。
const PALETTE = ["#5fd7c0", "#69a8ff", "#f4c56a", "#ef8c94", "#b998ef", "#72c9e8"];

const SINGLE_LAYER = "__single__";
const UNKNOWN_LAYER = "__unknown__";

/** 把 /objects 的返回投成三维图要的 {layers, nodes, relations}。
 *
 *  层 = 放了 2 件以上东西的位置，加上「单独存放」和「位置未知」两个兜底层。
 *  不给每个位置都开一层：真实数据里一多半位置只有一件东西，全开出来图会被压成
 *  十几张几乎空的平面，什么都看不出来。
 *
 *  边 = 同一位置内两两相连。这是用户选定的语义：连线代表「这些东西放在一起」，
 *  不代表用途相关、也不代表先后顺序——所以是完全图，不是链。 */
function deriveGraph(data) {
  if (!data) return { layers: [], nodes: [], relations: [] };

  const grouped = new Map(data.groups.map(g => [g.location, g.entity_ids]));
  const layers = data.groups.map((g, i) => ({
    id: `loc:${g.location}`,
    label: `${g.location}（${g.entity_ids.length} 件）`,
    color: PALETTE[i % PALETTE.length],
  }));

  const layerOf = (node) => {
    if (!node.location) return UNKNOWN_LAYER;
    return grouped.has(node.location) ? `loc:${node.location}` : SINGLE_LAYER;
  };

  const nodes = data.nodes.map(n => ({
    id: n.entity_id,
    name: n.canonical_name,
    layer: layerOf(n),
    location: n.location || "没有解析出位置",
    seen: n.last_seen_time,
    eventCount: n.event_count,
    confidence: n.confidence,
    corrected: n.corrected,
    thumb: apiUrl(n.thumb_url),
  }));

  // 兜底层只在真的有成员时才加，否则图里会挂着空平面
  if (nodes.some(n => n.layer === SINGLE_LAYER)) {
    layers.push({ id: SINGLE_LAYER, label: "各自单独放着", color: "#8ea2c6" });
  }
  if (nodes.some(n => n.layer === UNKNOWN_LAYER)) {
    layers.push({ id: UNKNOWN_LAYER, label: "位置未知", color: "#5b6480" });
  }

  const relations = [];
  for (const [location, ids] of grouped) {
    for (let i = 0; i < ids.length; i += 1) {
      for (let j = i + 1; j < ids.length; j += 1) {
        relations.push({ source: ids[i], target: ids[j], label: `同在${location}`, weight: 3, type: "same" });
      }
    }
  }
  return { layers, nodes, relations };
}

function seenText(iso) {
  if (!iso) return "没有观察记录";
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return iso;
  const sameDay = t.toDateString() === new Date().toDateString();
  const clock = t.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  return sameDay ? `今天 ${clock}` : `${t.toLocaleDateString("zh-CN", { month: "long", day: "numeric" })} ${clock}`;
}

function createTextSprite(text, color, small = false) {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 96;
  const context = canvas.getContext("2d");
  context.font = `${small ? 500 : 650} ${small ? 22 : 27}px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif`;
  context.textAlign = "center";
  context.textBaseline = "middle";
  const width = Math.min(context.measureText(text).width + 32, 480);
  context.fillStyle = "rgba(5, 8, 16, .78)";
  context.roundRect(256 - width / 2, 20, width, 56, 14);
  context.fill();
  context.fillStyle = color;
  context.fillText(text, 256, 49);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }));
  sprite.scale.set(small ? 23 : 28, small ? 4.3 : 5.2, 1);
  return sprite;
}

/** 实拍缩略图 → 圆形贴片。后端裁出来的就是正方形，这里只负责套圆 + 描边。
 *
 *  描边用所在层的颜色：套上照片之后，节点原来靠球体颜色传达的「在哪一层」就没了，
 *  一圈色环把这个信息补回来，同时让深色照片不至于糊进深色背景里。 */
function createThumbSprite(image, color, size) {
  const canvas = document.createElement("canvas");
  const side = 256;
  canvas.width = side;
  canvas.height = side;
  const context = canvas.getContext("2d");
  const radius = side / 2 - 9;
  context.save();
  context.beginPath();
  context.arc(side / 2, side / 2, radius, 0, Math.PI * 2);
  context.clip();
  context.drawImage(image, 0, 0, side, side);
  context.restore();
  context.beginPath();
  context.arc(side / 2, side / 2, radius, 0, Math.PI * 2);
  context.lineWidth = 8;
  context.strokeStyle = color;
  context.stroke();

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }),
  );
  // 贴片要盖住整个球，否则会看见球从照片边缘露出来一圈
  sprite.scale.set(size * 2.4, size * 2.4, 1);
  return sprite;
}

function Scene({ layers, nodes, relations, activeLayer, focusId, onNode, onHover, focusSignal, resetSignal }) {
  const mountRef = useRef(null);
  const apiRef = useRef(null);
  const onNodeRef = useRef(onNode);
  const onHoverRef = useRef(onHover);
  onNodeRef.current = onNode;
  onHoverRef.current = onHover;

  // 依赖真实数据：第一次拿到 /objects 时重建整个场景。数据是异步来的，
  // 空依赖数组会让场景永远停在「零个节点」。
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount || nodes.length === 0) return undefined;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#070611");
    scene.fog = new THREE.FogExp2("#070611", 0.0045);
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 900);
    camera.position.set(88, 72, 108);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.2;
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.07;
    controls.minDistance = 58;
    controls.maxDistance = 235;
    controls.target.set(0, 3, 0);
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.24;
    scene.add(new THREE.HemisphereLight("#dceaff", "#160b24", 2));
    const light = new THREE.PointLight("#6de4c3", 75, 300);
    light.position.set(45, 85, 70);
    scene.add(light);

    const root = new THREE.Group();
    scene.add(root);
    const layerGroups = new Map();
    const nodeObjects = new Map();
    const linkObjects = [];
    const clickTargets = [];
    let disposed = false;
    const spacing = 15;
    const top = ((layers.length - 1) * spacing) / 2;

    layers.forEach((layer, layerIndex) => {
      const group = new THREE.Group();
      group.position.y = top - layerIndex * spacing;
      const plane = new THREE.Mesh(
        new THREE.PlaneGeometry(92, 62),
        new THREE.MeshBasicMaterial({ color: layer.color, transparent: true, opacity: 0.04, side: THREE.DoubleSide, depthWrite: false }),
      );
      plane.rotation.x = -Math.PI / 2;
      group.add(plane);
      const grid = new THREE.GridHelper(92, 10, layer.color, layer.color);
      grid.scale.z = 0.67;
      grid.material.transparent = true;
      grid.material.opacity = 0.09;
      group.add(grid);
      const label = createTextSprite(layer.label, layer.color, true);
      label.position.set(-39, 2.1, -25);
      group.add(label);
      root.add(group);
      layerGroups.set(layer.id, group);
    });

    nodes.forEach((node) => {
      const layerIndex = Math.max(layers.findIndex((layer) => layer.id === node.layer), 0);
      const peers = nodes.filter((entry) => entry.layer === node.layer);
      const index = peers.findIndex((entry) => entry.id === node.id);
      const angle = index / peers.length * Math.PI * 2 + layerIndex * 0.7;
      const radius = peers.length === 2 ? 18 : 18 + (index % 2) * 9;
      const position = new THREE.Vector3(
        Math.cos(angle) * radius + (layerIndex % 2 ? 5 : -5),
        top - layerIndex * spacing + 2.7,
        Math.sin(angle) * radius * 0.72,
      );
      const degree = relations.filter((relation) => relation.source === node.id || relation.target === node.id).length;
      const size = 1.8 + Math.min(degree, 4) * 0.42;
      const color = layers[layerIndex].color;
      const material = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.78, roughness: 0.28, transparent: true });
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(size, 22, 18), material);
      mesh.position.copy(position);
      mesh.userData.nodeId = node.id;
      const halo = new THREE.Mesh(new THREE.SphereGeometry(size * 1.7, 16, 12), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.09, depthWrite: false }));
      mesh.add(halo);
      const label = createTextSprite(node.name, "#f4f8ff", degree < 2);
      label.position.set(0, size + 3.2, 0);
      mesh.add(label);
      root.add(mesh);
      clickTargets.push(mesh);
      const entry = { mesh, material, halo, label, position, node, thumb: null };
      nodeObjects.set(node.id, entry);

      // 实拍图异步进来：不能进 useEffect 依赖，否则每张图加载完都要重建整个场景。
      // 先显示纯色球，图到了再换成圆形贴片——加载失败/没有图就一直是球，
      // 不放占位图（占位图会让「没拍到这件东西」看起来像「拍到了，长这样」）。
      if (node.thumb) {
        const image = new Image();
        image.onload = () => {
          if (disposed) return;
          const sprite = createThumbSprite(image, color, size);
          sprite.material.opacity = material.opacity;
          mesh.add(sprite);
          entry.thumb = sprite;
          // 球退成纯粹的点击靶：留着可见就会从贴片边缘露出一圈色环
          material.opacity = 0;
          material.depthWrite = false;
        };
        image.src = node.thumb;
      }
    });

    relations.forEach((relation) => {
      const source = nodeObjects.get(relation.source);
      const target = nodeObjects.get(relation.target);
      if (!source || !target) return;
      const midpoint = source.position.clone().add(target.position).multiplyScalar(0.5);
      midpoint.y += 2;
      midpoint.x += (source.position.z - target.position.z) * 0.12;
      const curve = new THREE.QuadraticBezierCurve3(source.position, midpoint, target.position);
      const material = new THREE.LineBasicMaterial({ color: "#74e4c4", transparent: true, opacity: 0.52 });
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(22)), material);
      line.userData = { ...relation, baseOpacity: material.opacity };
      root.add(line);
      linkObjects.push(line);
    });

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2(8, 8);
    let hovered = null;
    const updatePointer = (event) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    };
    const move = (event) => updatePointer(event);
    const leave = () => pointer.set(8, 8);
    const click = (event) => {
      updatePointer(event);
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(clickTargets, false)[0];
      if (hit) onNodeRef.current(hit.object.userData.nodeId);
    };
    renderer.domElement.addEventListener("pointermove", move);
    renderer.domElement.addEventListener("pointerleave", leave);
    renderer.domElement.addEventListener("click", click);
    const resize = () => {
      const width = Math.max(mount.clientWidth, 1);
      const height = Math.max(mount.clientHeight, 1);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    resize();
    let frame;
    const render = () => {
      if (disposed) return;
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(clickTargets, false)[0];
      const next = hit?.object.userData.nodeId || null;
      if (next !== hovered) { hovered = next; onHoverRef.current(next); }
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(render);
    };
    render();
    apiRef.current = { camera, controls, nodeObjects, layerGroups, linkObjects };
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      renderer.domElement.removeEventListener("pointermove", move);
      renderer.domElement.removeEventListener("pointerleave", leave);
      renderer.domElement.removeEventListener("click", click);
      controls.dispose();
      scene.traverse((object) => {
        object.geometry?.dispose();
        object.material?.map?.dispose();
        object.material?.dispose();
      });
      renderer.dispose();
      renderer.domElement.remove();
      apiRef.current = null;
    };
  }, [layers, nodes, relations]);

  useEffect(() => {
    const api = apiRef.current;
    if (!api) return;
    const connected = new Set([focusId]);
    api.linkObjects.forEach((line) => {
      if (line.userData.source === focusId) connected.add(line.userData.target);
      if (line.userData.target === focusId) connected.add(line.userData.source);
    });
    api.nodeObjects.forEach((entry, id) => {
      const layerVisible = activeLayer === "all" || entry.node.layer === activeLayer;
      const related = !focusId || connected.has(id);
      entry.mesh.visible = layerVisible;
      // 有实拍图时球本身是透明的点击靶，淡入淡出要作用在贴片上，
      // 否则筛选一层会把别的层的球重新点亮成色块
      entry.material.opacity = entry.thumb ? 0 : related ? 1 : 0.11;
      if (entry.thumb) entry.thumb.material.opacity = related ? 1 : 0.13;
      entry.label.material.opacity = related ? 1 : 0.13;
      entry.halo.material.opacity = id === focusId ? 0.24 : related ? 0.09 : 0.01;
      entry.mesh.scale.setScalar(id === focusId ? 1.3 : 1);
    });
    api.layerGroups.forEach((group, id) => { group.visible = activeLayer === "all" || activeLayer === id; });
    api.linkObjects.forEach((line) => {
      const source = nodes.find((node) => node.id === line.userData.source);
      const target = nodes.find((node) => node.id === line.userData.target);
      const layerVisible = activeLayer === "all" || source?.layer === activeLayer || target?.layer === activeLayer;
      const related = !focusId || line.userData.source === focusId || line.userData.target === focusId;
      line.visible = layerVisible;
      line.material.opacity = related ? Math.min(line.userData.baseOpacity * 1.45, 1) : line.userData.baseOpacity * 0.08;
    });
  }, [activeLayer, focusId, nodes]);

  useEffect(() => {
    const api = apiRef.current;
    const entry = api?.nodeObjects.get(focusSignal?.id);
    if (!api || !entry || !focusSignal.tick) return;
    api.controls.autoRotate = false;
    api.controls.target.copy(entry.position);
    api.camera.position.copy(entry.position.clone().add(new THREE.Vector3(48, 35, 54)));
    api.controls.update();
  }, [focusSignal]);

  useEffect(() => {
    const api = apiRef.current;
    if (!api || !resetSignal) return;
    api.camera.position.set(88, 72, 108);
    api.controls.target.set(0, 3, 0);
    api.controls.autoRotate = true;
    api.controls.update();
  }, [resetSignal]);

  return <div className="graph-webgl" ref={mountRef} aria-label="三维现实记忆拓扑图"/>;
}

export default function TopologyGraph({ onOpenItem }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [activeLayer, setActiveLayer] = useState("all");
  const [selectedId, setSelectedId] = useState(null);
  const [hoveredId, setHoveredId] = useState(null);
  const [query, setQuery] = useState("");
  const [focusSignal, setFocusSignal] = useState({ id: null, tick: 0 });
  const [resetSignal, setResetSignal] = useState(0);

  useEffect(() => {
    let alive = true;
    objectGraph()
      .then(d => { if (alive) { setData(d); setError(null); } })
      .catch(e => { if (alive) setError(String(e.message || e)); });
    return () => { alive = false; };
  }, []);

  const { layers, nodes, relations } = useMemo(() => deriveGraph(data), [data]);

  // 默认选中最近看到的那个（后端已按新鲜度排序），而不是写死某个物品
  useEffect(() => {
    if (!selectedId && nodes.length > 0) setSelectedId(nodes[0].id);
  }, [nodes, selectedId]);

  const selected = nodes.find((node) => node.id === selectedId) || nodes[0];
  const selectedLayer = layers.find((layer) => layer.id === selected?.layer) || layers[0];
  const related = useMemo(() => {
    if (!selected) return [];
    return relations
      .filter((relation) => relation.source === selected.id || relation.target === selected.id)
      .map((relation) => ({
        ...relation,
        node: nodes.find((node) => node.id === (relation.source === selected.id ? relation.target : relation.source)),
      }))
      .filter(r => r.node);
  }, [selected, relations, nodes]);

  const results = query.trim()
    ? nodes.filter((node) => `${node.name}${node.location}`.includes(query.trim())).slice(0, 5)
    : [];
  const focusNode = (id) => {
    setSelectedId(id);
    setFocusSignal({ id, tick: Date.now() });
  };

  if (error) {
    return <div className="graph-shell"><div className="graph-empty">
      <p>拿不到物品分布。</p>
      <small>确认 memory-platform 在跑，且 <code>/api</code> 代理指向它。<br />{error}</small>
    </div></div>;
  }
  if (!data) {
    return <div className="graph-shell"><div className="graph-empty"><p>正在读物品分布…</p></div></div>;
  }
  if (nodes.length === 0) {
    return <div className="graph-shell"><div className="graph-empty">
      <p>还没有任何物品。</p>
      <small>去「采集」页拍一张，感知跑完这里就会长出来。</small>
    </div></div>;
  }

  return <div className="graph-shell">
    <div className="graph-toolbar">
      <label className="graph-search"><Search size={14}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索物品" aria-label="搜索物品"/>{query && <button onClick={() => setQuery("")} aria-label="清空搜索"><X size={13}/></button>}
        {results.length > 0 && <span className="graph-results">{results.map((node) => <button key={node.id} onClick={() => { focusNode(node.id); setQuery(""); }}><i style={{ background: (layers.find((layer) => layer.id === node.layer) || layers[0]).color }}/><b>{node.name}</b><small>{node.location}</small></button>)}</span>}
      </label>
      {/* 「同层/跨层」在真实数据下没有意义了：所有连线都是同一位置内的，本来就只有一种 */}
      <button className="graph-reset" onClick={() => setResetSignal((value) => value + 1)} aria-label="复位视角"><RotateCcw size={15}/></button>
    </div>
    <div className="graph-layer-strip"> <button className={activeLayer === "all" ? "active" : ""} onClick={() => setActiveLayer("all")}>全部层</button>{layers.map((layer) => <button key={layer.id} className={activeLayer === layer.id ? "active" : ""} onClick={() => setActiveLayer(layer.id)}><i style={{ background: layer.color }}/>{layer.label}</button>)}</div>
    <div className="graph-stage">
      <Scene layers={layers} nodes={nodes} relations={relations} activeLayer={activeLayer} focusId={hoveredId || (focusSignal.tick ? selectedId : null)} onNode={focusNode} onHover={setHoveredId} focusSignal={focusSignal} resetSignal={resetSignal}/>
      <div className="graph-count">{nodes.length} 件物品 · {relations.length} 组同位关系</div>
      {selected && selectedLayer && (
        <aside className="graph-inspector">
          <div className="graph-node-title"><span style={{ background: selectedLayer.color }}>{selected.thumb ? <img src={selected.thumb} alt=""/> : <Box size={14}/>}</span><div><small>{selectedLayer.label}</small><h2>{selected.name}</h2></div><button onClick={() => onOpenItem(selected.id)}>详情</button></div>
          <p>{selected.location}<span>最后确认 {seenText(selected.seen)} · {selected.eventCount} 条事件{selected.corrected ? " · 你纠正过" : ""}</span></p>
          <div className="graph-relations">{related.slice(0, 3).map((relation) => <button key={`${relation.source}-${relation.target}`} onClick={() => focusNode(relation.node.id)}><i className={relation.type}/><span>{relation.node.name}</span><small>{relation.label}</small></button>)}</div>
        </aside>
      )}
    </div>
  </div>;
}
