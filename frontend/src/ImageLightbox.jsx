import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X, ZoomIn, ZoomOut, Download, Maximize2 } from "lucide-react";

/**
 * 全站统一的「点缩略图看原图」。
 *
 * 缩略图为了列表能扫得动都做了 object-fit: cover 的小方块——看清细节必须另开一层。
 * 这里只做一个全屏浮层：任何页面用 <PreviewImage> 换掉 <img> 就能点开，
 * 不用每处各写一套 modal。
 */

const LightboxContext = createContext(null);

const MIN_SCALE = 1;
const MAX_SCALE = 8;
const DOUBLE_CLICK_SCALE = 2.5;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

export function useLightbox() {
  // 没套 Provider 时退化成「图还在，只是点不开」，不至于整页崩掉
  return useContext(LightboxContext) || { open: () => {} };
}

function LightboxOverlay({ item, onClose }) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [failed, setFailed] = useState(false);
  const drag = useRef(null);

  // 换图要回到初始视图，否则上一张放大平移过的位置会带到下一张
  useEffect(() => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
    setFailed(false);
  }, [item.src]);

  const zoomBy = useCallback((factor) => {
    setScale((s) => {
      const next = clamp(s * factor, MIN_SCALE, MAX_SCALE);
      // 缩回原尺寸就把平移一起清掉，不然图会停在屏幕外
      if (next === MIN_SCALE) setOffset({ x: 0, y: 0 });
      return next;
    });
  }, []);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "+" || e.key === "=") zoomBy(1.25);
      else if (e.key === "-" || e.key === "_") zoomBy(1 / 1.25);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    // 浮层期间锁住背景滚动，否则滚轮缩放会连带把底下的列表滚跑
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose, zoomBy]);

  const onPointerDown = (e) => {
    if (scale === MIN_SCALE) return; // 没放大就没什么可拖的
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, base: offset };
  };

  const onPointerMove = (e) => {
    if (!drag.current) return;
    setOffset({
      x: drag.current.base.x + (e.clientX - drag.current.x),
      y: drag.current.base.y + (e.clientY - drag.current.y),
    });
  };

  const endDrag = (e) => {
    if (!drag.current) return;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    drag.current = null;
  };

  return createPortal(
    <div
      className="lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={item.alt || "查看原图"}
      // 只有点到背景本身才关；点图片和工具条不关
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="lightbox-bar">
        <span className="lightbox-scale">{Math.round(scale * 100)}%</span>
        <button title="缩小" onClick={() => zoomBy(1 / 1.25)} disabled={scale <= MIN_SCALE}>
          <ZoomOut size={16} />
        </button>
        <button title="放大" onClick={() => zoomBy(1.25)} disabled={scale >= MAX_SCALE}>
          <ZoomIn size={16} />
        </button>
        <button title="还原" onClick={() => { setScale(1); setOffset({ x: 0, y: 0 }); }}>
          <Maximize2 size={16} />
        </button>
        <a title="下载原图" href={item.src} download={item.downloadName || ""} target="_blank" rel="noreferrer">
          <Download size={16} />
        </a>
        <button title="关闭（Esc）" onClick={onClose}>
          <X size={16} />
        </button>
      </div>

      <div
        className="lightbox-stage"
        onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
        onWheel={(e) => zoomBy(e.deltaY < 0 ? 1.12 : 1 / 1.12)}
      >
        {failed ? (
          <p className="lightbox-failed">
            原图取不到了。<br />
            <small>可能已按保留期删除，或后端没在跑。</small>
          </p>
        ) : (
          <img
            src={item.src}
            alt={item.alt || ""}
            className={`lightbox-img ${scale > MIN_SCALE ? "zoomed" : ""}`}
            style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})` }}
            draggable={false}
            onError={() => setFailed(true)}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            onDoubleClick={() => (scale > MIN_SCALE
              ? (setScale(1), setOffset({ x: 0, y: 0 }))
              : setScale(DOUBLE_CLICK_SCALE))}
          />
        )}
      </div>

      {item.caption && <p className="lightbox-caption">{item.caption}</p>}
    </div>,
    document.body,
  );
}

export function LightboxProvider({ children }) {
  const [item, setItem] = useState(null);
  const open = useCallback((next) => setItem(next), []);
  const close = useCallback(() => setItem(null), []);
  // open 恒等，消费方不用担心把整棵树重渲
  const value = useRef({ open }).current;

  return (
    <LightboxContext.Provider value={value}>
      {children}
      {item && <LightboxOverlay item={item} onClose={close} />}
    </LightboxContext.Provider>
  );
}

/**
 * 能点开看原图的缩略图。用法和 <img> 一样，额外接 caption（浮层底部的说明）。
 * className 照旧透传，各处原来的尺寸样式都不用改。
 */
export function PreviewImage({ src, alt, caption, className = "", onClick, ...rest }) {
  const { open } = useLightbox();
  const show = (e) => {
    // 缩略图常嵌在可点卡片里（点卡片=跳详情），放大不能顺带触发那个跳转
    e.stopPropagation();
    open({ src, alt, caption: caption ?? alt });
    onClick?.(e);
  };
  return (
    <img
      {...rest}
      src={src}
      alt={alt}
      className={`preview-img ${className}`.trim()}
      role="button"
      tabIndex={0}
      onClick={show}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") show(e);
      }}
    />
  );
}
