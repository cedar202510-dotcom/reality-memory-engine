import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { HDRLoader } from "three/examples/jsm/loaders/HDRLoader.js";
import { ArrowLeft, BadgeCheck, LocateFixed, RotateCcw, ScanSearch } from "lucide-react";
import { useNavigate } from "react-router-dom";

const HDRI_URL = "/assets/xr-room/polyhaven/_hdris/relax_inn_seaview_suite_2k.hdr";

const panoramaItems = [
  {
    id: "diffuser",
    label: "香薰",
    location: "书桌左侧靠镜子",
    confidence: 0.86,
    direction: [0.7835, -0.3988, -0.4766],
    box: [74, 132],
  },
  {
    id: "desk-remote",
    label: "遥控器",
    location: "书桌右侧桌面",
    confidence: 0.88,
    direction: [0.8816, -0.421, -0.2132],
    box: [150, 46],
  },
  {
    id: "magazine",
    label: "书册",
    location: "书桌中央叠放",
    confidence: 0.84,
    direction: [0.8316, -0.3888, -0.3965],
    box: [170, 72],
  },
  {
    id: "teacups",
    label: "茶杯",
    location: "右侧柜顶黑色托盘",
    confidence: 0.8,
    direction: [0.9825, -0.1718, 0.0725],
    box: [174, 72],
  },
  {
    id: "kettle",
    label: "水壶",
    location: "书桌右后侧",
    confidence: 0.82,
    direction: [0.9277, -0.3236, -0.1864],
    box: [106, 134],
  },
];

function directionToScreen(camera, direction, width, height) {
  const dir = new THREE.Vector3(...direction).normalize();
  const forward = new THREE.Vector3();
  camera.getWorldDirection(forward);
  const visible = forward.dot(dir) > 0.18;
  const point = camera.position.clone().add(dir.multiplyScalar(12));
  point.project(camera);

  return {
    x: (point.x * 0.5 + 0.5) * width,
    y: (-point.y * 0.5 + 0.5) * height,
    viewportWidth: width,
    viewportHeight: height,
    visible: visible && point.z < 1 && point.x > -1 && point.x < 1 && point.y > -1 && point.y < 1,
  };
}

export default function XRRoomPreview() {
  const navigate = useNavigate();
  const mountRef = useRef(null);
  const cameraRef = useRef(null);
  const controlsRef = useRef(null);
  const rendererRef = useRef(null);
  const [activeItem, setActiveItem] = useState("diffuser");
  const [labelPositions, setLabelPositions] = useState({});
  const [loading, setLoading] = useState(true);
  const active = useMemo(() => panoramaItems.find((item) => item.id === activeItem) || panoramaItems[0], [activeItem]);

  useEffect(() => {
    const mount = mountRef.current;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x111514);

    const camera = new THREE.PerspectiveCamera(54, mount.clientWidth / mount.clientHeight, 0.1, 100);
    camera.position.set(2.8, 1.65, 3.25);
    camera.lookAt(new THREE.Vector3(-0.1, 0.55, -0.55));
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.95;
    mount.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.copy(camera.position).add(new THREE.Vector3(-0.55, -0.2, -1).normalize());
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
        scene.backgroundIntensity = 0.95;
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
      const width = mount.clientWidth;
      const height = mount.clientHeight;
      const positions = {};
      for (const item of panoramaItems) {
        positions[item.id] = directionToScreen(camera, item.direction, width, height);
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
    if (!camera || !controls) return;
    const direction = new THREE.Vector3(...active.direction).normalize();
    controls.target.copy(camera.position).add(direction);
    controls.update();
  }, [activeItem, active]);

  return (
    <div className="xr-room-page">
      <div ref={mountRef} className="xr-room-canvas" />
      {loading && <div className="xr-loading">加载真实全景...</div>}

      <header className="xr-topbar">
        <button className="xr-icon-button" onClick={() => navigate("/agent")} aria-label="返回应用">
          <ArrowLeft size={18} />
        </button>
        <div>
          <span>Reality Memory XR</span>
          <strong>真实全景物品识别标注</strong>
        </div>
        <button className="xr-icon-button" onClick={() => setActiveItem("diffuser")} aria-label="重置视角">
          <RotateCcw size={18} />
        </button>
      </header>

      <aside className="xr-panel">
        <div className="xr-active">
          <LocateFixed size={18} />
          <div>
            <span>正在定位</span>
            <strong>{active.label}</strong>
            <p>{active.location}</p>
          </div>
        </div>
        <div className="xr-item-list">
          {panoramaItems.map((item) => (
            <button
              key={item.id}
              className={`xr-item ${activeItem === item.id ? "is-active" : ""}`}
              onClick={() => setActiveItem(item.id)}
            >
              <ScanSearch size={15} />
              <span>{item.label}</span>
              <em>{Math.round(item.confidence * 100)}%</em>
            </button>
          ))}
        </div>
      </aside>

      <div className="xr-label-layer">
        {panoramaItems.map((item) => {
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
              className={`xr-detect-box ${activeItem === item.id ? "is-active" : ""}`}
              style={{
                width: boxWidth,
                height: boxHeight,
                transform: `translate(${pos.x}px, ${pos.y}px)`,
              }}
              onClick={() => setActiveItem(item.id)}
            >
              <span className="xr-detect-label">
                <BadgeCheck size={13} />
                {item.label}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
