import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Box, RotateCcw, Search, X } from "lucide-react";

const layers = [
  { id: "digital", label: "数码设备", color: "#5fd7c0" },
  { id: "power", label: "电源线材", color: "#69a8ff" },
  { id: "carry", label: "随身物品", color: "#f4c56a" },
  { id: "daily", label: "居家日用", color: "#ef8c94" },
  { id: "media", label: "影音娱乐", color: "#b998ef" },
  { id: "study", label: "阅读工具", color: "#72c9e8" },
];

const nodes = [
  ["charger", "充电器", "power", "书房", "工作桌下方", "10:18"],
  ["cable", "数据线", "power", "卧室", "床头柜抽屉", "周一"],
  ["laptop", "笔记本电脑", "digital", "书房", "工作桌中央", "10:21"],
  ["mouse", "鼠标", "digital", "书房", "工作桌右侧", "10:21"],
  ["keyboard", "键盘", "digital", "书房", "工作桌中央", "10:21"],
  ["drive", "移动硬盘", "digital", "书房", "左侧抽屉", "周二"],
  ["headphones", "耳机", "digital", "书房", "显示器旁", "09:12"],
  ["watch", "手表", "carry", "卧室", "床头柜上", "07:48"],
  ["glasses", "眼镜", "carry", "卧室", "床头柜上", "07:51"],
  ["wallet", "钱包", "carry", "玄关", "托盘左侧", "08:12"],
  ["keys", "钥匙", "carry", "玄关", "玄关托盘", "08:12"],
  ["access", "门禁卡", "carry", "玄关", "钱包夹层", "08:12"],
  ["backpack", "背包", "carry", "玄关", "换鞋凳旁", "08:15"],
  ["umbrella", "雨伞", "carry", "玄关", "入户门右侧", "周四"],
  ["cup", "水杯", "daily", "书房", "工作桌右侧", "10:04"],
  ["tissue", "纸巾盒", "daily", "客厅", "茶几上", "08:40"],
  ["perfume", "香水", "daily", "卧室", "衣柜内侧", "周四"],
  ["medicine", "药盒", "daily", "卧室", "床头柜第二层", "周四"],
  ["remote", "遥控器", "media", "客厅", "沙发右侧", "昨晚"],
  ["controller", "游戏手柄", "media", "客厅", "电视柜第二层", "周三"],
  ["book", "《设计中的设计》", "study", "书房", "书架第二层", "昨晚"],
  ["pen", "钢笔", "study", "书房", "笔筒里", "周四"],
  ["scissors", "剪刀", "study", "书房", "工具抽屉", "周三"],
].map(([id, name, layer, room, location, seen]) => ({ id, name, layer, room, location, seen }));

const relations = [
  ["laptop", "keyboard", "配套使用", 3], ["laptop", "mouse", "配套使用", 3],
  ["laptop", "charger", "供电", 3], ["laptop", "drive", "数据备份", 2],
  ["laptop", "headphones", "音频输出", 2], ["charger", "cable", "组合收纳", 3],
  ["remote", "controller", "客厅娱乐", 2], ["wallet", "access", "随身收纳", 3],
  ["wallet", "keys", "共同携带", 2], ["wallet", "backpack", "出门携带", 2],
  ["keys", "access", "进出家门", 3], ["umbrella", "backpack", "雨天出门", 2],
  ["watch", "glasses", "晨间佩戴", 2], ["perfume", "glasses", "出门准备", 1],
  ["medicine", "cup", "服药", 3], ["book", "pen", "阅读批注", 3],
  ["scissors", "tissue", "日常整理", 1], ["cup", "laptop", "桌面相邻", 1],
  ["tissue", "remote", "客厅同区", 1], ["cable", "drive", "数据连接", 2],
].map(([source, target, label, weight]) => {
  const sourceNode = nodes.find((node) => node.id === source);
  const targetNode = nodes.find((node) => node.id === target);
  return { source, target, label, weight, type: sourceNode.layer === targetNode.layer ? "same" : "cross" };
});

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

function Scene({ activeLayer, relationMode, focusId, onNode, onHover, focusSignal, resetSignal }) {
  const mountRef = useRef(null);
  const apiRef = useRef(null);
  const onNodeRef = useRef(onNode);
  const onHoverRef = useRef(onHover);
  onNodeRef.current = onNode;
  onHoverRef.current = onHover;

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;
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
      const layerIndex = layers.findIndex((layer) => layer.id === node.layer);
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
      nodeObjects.set(node.id, { mesh, material, halo, label, position, node });
    });

    relations.forEach((relation) => {
      const source = nodeObjects.get(relation.source);
      const target = nodeObjects.get(relation.target);
      const midpoint = source.position.clone().add(target.position).multiplyScalar(0.5);
      midpoint.y += relation.type === "cross" ? 6 : 2;
      midpoint.x += (source.position.z - target.position.z) * 0.12;
      const curve = new THREE.QuadraticBezierCurve3(source.position, midpoint, target.position);
      const material = new THREE.LineBasicMaterial({
        color: relation.type === "cross" ? "#7da9ff" : "#74e4c4",
        transparent: true,
        opacity: relation.weight === 3 ? 0.72 : relation.weight === 2 ? 0.42 : 0.2,
      });
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
    let disposed = false;
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
  }, []);

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
      entry.material.opacity = related ? 1 : 0.11;
      entry.label.material.opacity = related ? 1 : 0.13;
      entry.halo.material.opacity = id === focusId ? 0.24 : related ? 0.09 : 0.01;
      entry.mesh.scale.setScalar(id === focusId ? 1.3 : 1);
    });
    api.layerGroups.forEach((group, id) => { group.visible = activeLayer === "all" || activeLayer === id; });
    api.linkObjects.forEach((line) => {
      const modeVisible = relationMode === "all" || relationMode === line.userData.type;
      const source = nodes.find((node) => node.id === line.userData.source);
      const target = nodes.find((node) => node.id === line.userData.target);
      const layerVisible = activeLayer === "all" || source.layer === activeLayer || target.layer === activeLayer;
      const related = !focusId || line.userData.source === focusId || line.userData.target === focusId;
      line.visible = modeVisible && layerVisible;
      line.material.opacity = related ? Math.min(line.userData.baseOpacity * 1.45, 1) : line.userData.baseOpacity * 0.08;
    });
  }, [activeLayer, focusId, relationMode]);

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
  const [activeLayer, setActiveLayer] = useState("all");
  const [relationMode, setRelationMode] = useState("all");
  const [selectedId, setSelectedId] = useState("laptop");
  const [hoveredId, setHoveredId] = useState(null);
  const [query, setQuery] = useState("");
  const [focusSignal, setFocusSignal] = useState({ id: "laptop", tick: 0 });
  const [resetSignal, setResetSignal] = useState(0);
  const selected = nodes.find((node) => node.id === selectedId) || nodes[0];
  const selectedLayer = layers.find((layer) => layer.id === selected.layer);
  const related = useMemo(() => relations.filter((relation) => relation.source === selected.id || relation.target === selected.id).map((relation) => ({
    ...relation,
    node: nodes.find((node) => node.id === (relation.source === selected.id ? relation.target : relation.source)),
  })), [selected.id]);
  const results = query.trim() ? nodes.filter((node) => `${node.name}${node.room}${node.location}`.includes(query.trim())).slice(0, 5) : [];
  const focusNode = (id) => {
    setSelectedId(id);
    setFocusSignal({ id, tick: Date.now() });
  };
  return <div className="graph-shell">
    <div className="graph-toolbar">
      <label className="graph-search"><Search size={14}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索物品或位置" aria-label="搜索物品或位置"/>{query && <button onClick={() => setQuery("")} aria-label="清空搜索"><X size={13}/></button>}
        {results.length > 0 && <span className="graph-results">{results.map((node) => <button key={node.id} onClick={() => { focusNode(node.id); setQuery(""); }}><i style={{ background: layers.find((layer) => layer.id === node.layer).color }}/><b>{node.name}</b><small>{node.room}</small></button>)}</span>}
      </label>
      <div className="graph-mode">{[["all","全部"],["same","同类"],["cross","跨类"]].map(([id,label]) => <button key={id} className={relationMode === id ? "active" : ""} onClick={() => setRelationMode(id)}>{label}</button>)}</div>
      <button className="graph-reset" onClick={() => setResetSignal((value) => value + 1)} aria-label="复位视角"><RotateCcw size={15}/></button>
    </div>
    <div className="graph-layer-strip"> <button className={activeLayer === "all" ? "active" : ""} onClick={() => setActiveLayer("all")}>全部</button>{layers.map((layer) => <button key={layer.id} className={activeLayer === layer.id ? "active" : ""} onClick={() => setActiveLayer(layer.id)}><i style={{ background: layer.color }}/>{layer.label}</button>)}</div>
    <div className="graph-stage">
      <Scene activeLayer={activeLayer} relationMode={relationMode} focusId={hoveredId || (focusSignal.tick ? selectedId : null)} onNode={focusNode} onHover={setHoveredId} focusSignal={focusSignal} resetSignal={resetSignal}/>
      <div className="graph-count">{nodes.length} 节点 · {relations.length} 关系</div>
      <aside className="graph-inspector">
        <div className="graph-node-title"><span style={{ background: selectedLayer.color }}><Box size={14}/></span><div><small>{selectedLayer.label}</small><h2>{selected.name}</h2></div><button onClick={() => onOpenItem(selected.name)}>详情</button></div>
        <p>{selected.room} · {selected.location}<span>最后确认 {selected.seen}</span></p>
        <div className="graph-relations">{related.slice(0, 3).map((relation) => <button key={`${relation.source}-${relation.target}`} onClick={() => focusNode(relation.node.id)}><i className={relation.type}/><span>{relation.node.name}</span><small>{relation.label}</small></button>)}</div>
      </aside>
    </div>
  </div>;
}
