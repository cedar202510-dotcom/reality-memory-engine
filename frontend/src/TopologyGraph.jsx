import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Box, RotateCcw, Search, X, ChevronDown, ChevronUp } from "lucide-react";
import { apiUrl, objectGraph } from "./api";

// 层的颜色只是分辨用的，没有语义（真实数据里没有「品类」这个维度）。
const PALETTE = ["#5fd7c0", "#69a8ff", "#f4c56a", "#ef8c94", "#b998ef", "#72c9e8"];

const SINGLE_LAYER = "__single__";
const UNKNOWN_LAYER = "__unknown__";

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
    controls.dampingFactor = 0.04;
    controls.maxDistance = 300;
    controls.minDistance = 20;
    controls.maxPolarAngle = Math.PI / 2 + 0.1;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.4;

    const layerPlanes = new Map();
    const layerObjects = new THREE.Group();
    scene.add(layerObjects);
    
    // The background mesh representing a layer's physical bound (the user wanted the "colored 3D backgrounds" preserved or brought back if missing)
    layers.forEach((layer, i) => {
      const plane = new THREE.Mesh(
        new THREE.PlaneGeometry(92, 62),
        new THREE.MeshBasicMaterial({ color: layer.color, transparent: true, opacity: 0.04, side: THREE.DoubleSide, depthWrite: false })
      );
      plane.rotation.x = -Math.PI / 2;
      plane.position.y = i * 26;
      
      const grid = new THREE.GridHelper(92, 10, layer.color, layer.color);
      grid.scale.z = 0.67;
      grid.material.opacity = 0.09;
      grid.material.transparent = true;
      grid.position.y = plane.position.y;
      
      layerPlanes.set(layer.id, { y: plane.position.y, mesh: plane, grid });
      layerObjects.add(plane);
      layerObjects.add(grid);
    });

    const nodeObjects = new Map();
    const linkObjects = new THREE.Group();
    scene.add(linkObjects);

    const loader = new THREE.ImageLoader();

    nodes.forEach((node) => {
      const layerPlane = layerPlanes.get(node.layer);
      if (!layerPlane) return;
      const angle = Math.random() * Math.PI * 2;
      const radius = Math.random() * 32 + 4;
      const position = new THREE.Vector3(Math.cos(angle) * radius, layerPlane.y + 3, Math.sin(angle) * radius);
      
      const group = new THREE.Group();
      group.position.copy(position);
      group.userData = { id: node.id, originalPosition: position.clone(), layer: node.layer };

      const layerColor = layers.find(l => l.id === node.layer)?.color || "#ffffff";
      
      // Node sphere (fallback while loading or if no thumb)
      const core = new THREE.Mesh(
        new THREE.SphereGeometry(3, 32, 32),
        new THREE.MeshBasicMaterial({ color: layerColor })
      );
      
      const halo = new THREE.Mesh(
        new THREE.SphereGeometry(4.2, 32, 32),
        new THREE.MeshBasicMaterial({ color: layerColor, transparent: true, opacity: 0.15, blending: THREE.AdditiveBlending, depthWrite: false })
      );
      
      group.add(core);
      group.add(halo);

      // Label sprite
      const labelSprite = createTextSprite(node.name, layerColor);
      labelSprite.position.set(0, 7, 0);
      group.add(labelSprite);
      
      // Subtitle sprite
      const subSprite = createTextSprite(node.location, "#8b949e", true);
      subSprite.position.set(0, -6, 0);
      group.add(subSprite);

      // Async load image
      if (node.thumb) {
        loader.load(node.thumb, (img) => {
           const sprite = createThumbSprite(img, layerColor, 3.2);
           group.add(sprite);
           core.visible = false;
        });
      }

      scene.add(group);
      nodeObjects.set(node.id, group);
    });

    const lineMaterial = new THREE.LineBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0.1 });
    relations.forEach((relation) => {
      const source = nodeObjects.get(relation.source);
      const target = nodeObjects.get(relation.target);
      if (source && target) {
        const points = [];
        const yOffset = relation.type === "cross" ? 8 : 1;
        const midPoint = new THREE.Vector3().addVectors(source.position, target.position).multiplyScalar(0.5);
        midPoint.y += yOffset;
        points.push(source.position);
        points.push(midPoint);
        points.push(target.position);
        const curve = new THREE.QuadraticBezierCurve3(...points);
        const geometry = new THREE.BufferGeometry().setFromPoints(curve.getPoints(20));
        const line = new THREE.Line(geometry, lineMaterial.clone());
        line.userData = { source: relation.source, target: relation.target, type: relation.type };
        linkObjects.add(line);
      }
    });

    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    let hoveredMesh = null;
    let isDragging = false;

    const getIntersect = (e) => {
      const rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      const targets = Array.from(nodeObjects.values()).flatMap(g => g.children.filter(c => c.type === 'Mesh' || c.type === 'Sprite'));
      const intersects = raycaster.intersectObjects(targets);
      return intersects.length > 0 ? intersects[0].object.parent : null;
    };

    const handlePointerDown = () => { isDragging = false; };
    const handlePointerMove = (e) => {
      isDragging = true;
      const group = getIntersect(e);
      if (group !== hoveredMesh) {
        if (hoveredMesh) hoveredMesh.children[1].scale.set(1, 1, 1);
        if (group) group.children[1].scale.set(1.4, 1.4, 1.4);
        hoveredMesh = group;
        renderer.domElement.style.cursor = group ? "pointer" : "default";
        onHoverRef.current(group ? group.userData.id : null);
      }
    };
    const handlePointerUp = (e) => {
      if (!isDragging) {
        const group = getIntersect(e);
        if (group) onNodeRef.current(group.userData.id);
      }
    };

    mount.addEventListener("pointerdown", handlePointerDown);
    mount.addEventListener("pointermove", handlePointerMove);
    mount.addEventListener("pointerup", handlePointerUp);

    const resize = () => {
      if (!mount) return;
      const width = mount.clientWidth;
      const height = mount.clientHeight;
      renderer.setSize(width, height);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(mount);
    resize();

    let reqId;
    const animate = () => {
      reqId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    apiRef.current = { camera, controls, nodeObjects, linkObjects, layerObjects, layerPlanes };

    return () => {
      ro.disconnect();
      mount.removeEventListener("pointerdown", handlePointerDown);
      mount.removeEventListener("pointermove", handlePointerMove);
      mount.removeEventListener("pointerup", handlePointerUp);
      cancelAnimationFrame(reqId);
      renderer.dispose();
      scene.clear();
      if (mount.contains(renderer.domElement)) mount.removeChild(renderer.domElement);
    };
  }, [layers, nodes, relations]);

  useEffect(() => {
    const api = apiRef.current;
    if (!api) return;
    
    // Only isolate nodes of the active layer, else show all
    api.nodeObjects.forEach((group, id) => {
      const isLayerMatch = activeLayer === "all" || group.userData.layer === activeLayer;
      const isFocused = focusId === id;
      const isRelated = focusId ? api.linkObjects.children.some(l => (l.userData.source === focusId && l.userData.target === id) || (l.userData.target === focusId && l.userData.source === id)) : false;
      const isVisible = isLayerMatch || isFocused || isRelated;
      
      const targetOpacity = isVisible ? (focusId ? (isFocused || isRelated ? 1 : 0.15) : 1) : 0.05;
      group.children.forEach((child) => {
        if (child.material && child.material.opacity !== undefined) {
          if (child === group.children[1]) {
             child.material.opacity = targetOpacity * 0.15; // halo
          } else {
             child.material.opacity = targetOpacity;
          }
        }
      });
      group.position.y = THREE.MathUtils.lerp(group.position.y, isVisible ? group.userData.originalPosition.y : group.userData.originalPosition.y - 15, 0.1);
    });

    api.linkObjects.children.forEach((line) => {
      const sourceGroup = api.nodeObjects.get(line.userData.source);
      const targetGroup = api.nodeObjects.get(line.userData.target);
      const isVisible = (activeLayer === "all" || (sourceGroup.userData.layer === activeLayer && targetGroup.userData.layer === activeLayer)) && 
                        (!focusId || line.userData.source === focusId || line.userData.target === focusId);
      line.material.opacity = THREE.MathUtils.lerp(line.material.opacity, isVisible ? (focusId ? 0.35 : 0.1) : 0, 0.1);
    });

    api.layerObjects.children.forEach((obj) => {
      if (obj.type === "Mesh") { // Plane
         const layerId = Array.from(api.layerPlanes.entries()).find(([_, v]) => v.mesh === obj)?.[0];
         obj.material.opacity = (activeLayer === "all" || activeLayer === layerId) ? 0.04 : 0.005;
      }
      if (obj.type === "LineSegments") { // GridHelper is LineSegments
         const layerId = Array.from(api.layerPlanes.entries()).find(([_, v]) => v.grid === obj)?.[0];
         if (layerId) {
            obj.material.opacity = (activeLayer === "all" || activeLayer === layerId) ? 0.09 : 0.01;
         }
      }
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
  const [isSearchExpanded, setIsSearchExpanded] = useState(false);
  const [isLayerDropdownOpen, setIsLayerDropdownOpen] = useState(false);
  const [focusSignal, setFocusSignal] = useState({ id: null, tick: 0 });
  const [resetSignal, setResetSignal] = useState(0);

  useEffect(() => {
    let alive = true;
    objectGraph()
      .then(d => { if (alive) { setData(d); setError(null); } })
      .catch(e => { if (alive) setError(String(e.message || e)); });
    return () => { alive = false; };
  }, []);

  const { layers, nodes, relations } = useMemo(
    () => (data ? deriveGraph(data) : { layers: [], nodes: [], relations: [] }),
    [data],
  );

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

  const renderStage = () => {
    if (error) {
      return <div className="graph-empty">
        <p>暂时拿不到物品分布。</p>
        <small>{error}</small>
      </div>;
    }
    if (!data && !error) {
      return <div className="graph-empty"><p>正在读物品分布…</p></div>;
    }
    if (nodes.length === 0) {
      return <div className="graph-empty">
        <p>还没有任何物品。</p>
        <small>去「采集」页拍一张，感知跑完这里就会长出来。</small>
      </div>;
    }
    return (
      <>
        <Scene layers={layers} nodes={nodes} relations={relations} activeLayer={activeLayer} focusId={hoveredId || (focusSignal.tick ? selectedId : null)} onNode={focusNode} onHover={setHoveredId} focusSignal={focusSignal} resetSignal={resetSignal}/>
        <div className="graph-count">{nodes.length} 节点 · {relations.length} 关系</div>
        
        {selected && selectedLayer && (
          <aside className="graph-inspector">
            <div className="graph-node-title">
              <span style={{ background: selectedLayer.color }}>
                {selected.thumb ? <img src={selected.thumb} alt=""/> : <Box size={14}/>}
              </span>
              <div><small>{selectedLayer.label}</small><h2>{selected.name}</h2></div>
              <button onClick={() => onOpenItem(selected.id)}>详情</button>
            </div>
            <p>{selected.location}<span>最后确认 {seenText(selected.seen)} · {selected.eventCount} 条事件{selected.corrected ? " · 你纠正过" : ""}</span></p>
            <div className="graph-relations">
              {related.slice(0, 3).map((relation) => 
                <button key={`${relation.source}-${relation.target}`} onClick={() => focusNode(relation.node.id)}>
                  <i className={relation.type}/><span>{relation.node.name}</span><small>{relation.label}</small>
                </button>
              )}
            </div>
          </aside>
        )}
      </>
    );
  };

  return <div className="graph-shell">
    <div className="graph-layer-dropdown-container">
      <div className={`layer-dropdown ${isLayerDropdownOpen ? 'open' : ''}`}>
        <button className="layer-dropdown-toggle" onClick={() => setIsLayerDropdownOpen(!isLayerDropdownOpen)}>
          <span className="layer-dropdown-label">
            {activeLayer === "all" ? "全部层级" : layers.find(l => l.id === activeLayer)?.label || "全部层级"}
          </span>
          {isLayerDropdownOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
        {isLayerDropdownOpen && (
          <div className="layer-dropdown-menu">
            <button className={activeLayer === "all" ? "active" : ""} onClick={() => { setActiveLayer("all"); setIsLayerDropdownOpen(false); }}>全部层级</button>
            {layers.map((layer) => (
              <button key={layer.id} className={activeLayer === layer.id ? "active" : ""} onClick={() => { setActiveLayer(layer.id); setIsLayerDropdownOpen(false); }}>
                <i style={{ background: layer.color }}/>{layer.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>

    <div className="graph-toolbar">
      <div className={`graph-search-container ${isSearchExpanded ? 'expanded' : ''}`} onClick={() => setIsSearchExpanded(true)}>
        <span className="search-icon"><Search size={16}/></span>
        <input className="search-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索物品..." aria-label="搜索物品或位置" onBlur={() => { if(!query) setIsSearchExpanded(false); }} />
        {query && <button className="clear-btn" onClick={(e) => { e.stopPropagation(); setQuery(""); setIsSearchExpanded(false); }} aria-label="清空搜索"><X size={13}/></button>}
        {results.length > 0 && <span className="graph-results">{results.map((node) => <button key={node.id} onClick={(e) => { e.stopPropagation(); focusNode(node.id); setQuery(""); setIsSearchExpanded(false); }}><i style={{ background: (layers.find((layer) => layer.id === node.layer) || layers[0]).color }}/><b>{node.name}</b><small>{node.location}</small></button>)}</span>}
      </div>
      <button className="graph-reset" onClick={() => {
        setResetSignal((value) => value + 1);
        setActiveLayer("all");
        setSelectedId(null);
        setQuery("");
        setIsSearchExpanded(false);
      }} aria-label="复位视角"><RotateCcw size={15}/></button>
    </div>
    
    <div className="graph-stage">
      {renderStage()}
    </div>
  </div>;
}
