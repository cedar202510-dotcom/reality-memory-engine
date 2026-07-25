import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleCheckBig,
  HousePlug,
  NotebookPen,
  Plus,
  RadioTower,
  ShoppingBag,
  X,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

const INITIAL_SHOPPING_ITEMS = [
  { id: "detergent", name: "洗衣液", detail: "刚刚通过眼镜加入", quantity: "× 1", done: false },
  { id: "tissue", name: "纸巾", detail: "昨天手动加入", quantity: "× 2", done: false },
  { id: "coffee", name: "咖啡豆", detail: "根据余量提醒加入", quantity: "250g", done: false },
  { id: "milk", name: "牛奶", detail: "今天 09:12", quantity: "× 1", done: true },
];

const INITIAL_TASKS = [
  { id: "materials", name: "把资料给小王", detail: "到公司后提醒", source: "眼镜提醒", done: false },
  { id: "parcel", name: "回家前取快递", detail: "18:30 前", source: "", done: false },
];

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

function todayText() {
  const now = new Date();
  return `${now.getMonth() + 1}月${now.getDate()}日 · ${WEEKDAYS[now.getDay()]}`;
}

function Metric({ value, unit, label }) {
  return (
    <div className="life-metric">
      <b>{value}<small>{unit}</small></b>
      <span>{label}</span>
    </div>
  );
}

function ModuleTitle({ icon: Icon, children, count }) {
  return (
    <div className="life-module-head">
      <span className="life-module-title">
        <Icon size={16} strokeWidth={1.8} />
        {children}
      </span>
      {count != null && <span className="life-module-count">{count} 项</span>}
    </div>
  );
}

export default function LifeHome() {
  const navigate = useNavigate();
  const [shoppingOpen, setShoppingOpen] = useState(false);
  const [shoppingItems, setShoppingItems] = useState(INITIAL_SHOPPING_ITEMS);
  const [tasks, setTasks] = useState(INITIAL_TASKS);
  const [composerOpen, setComposerOpen] = useState(false);
  const [newItem, setNewItem] = useState("");
  const [toast, setToast] = useState("");
  const toastTimer = useRef(null);

  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  const pendingShopping = useMemo(
    () => shoppingItems.filter((item) => !item.done),
    [shoppingItems],
  );
  const completedShopping = useMemo(
    () => shoppingItems.filter((item) => item.done),
    [shoppingItems],
  );
  const pendingTasks = tasks.filter((task) => !task.done);

  const showToast = (message) => {
    setToast(message);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(""), 2200);
  };

  const toggleTask = (id) => {
    setTasks((current) => current.map((task) => (
      task.id === id ? { ...task, done: !task.done } : task
    )));
    const target = tasks.find((task) => task.id === id);
    showToast(target?.done ? "任务已恢复" : "任务已完成，并记录到轨迹");
  };

  const toggleShopping = (id) => {
    setShoppingItems((current) => current.map((item) => (
      item.id === id ? { ...item, done: !item.done } : item
    )));
    const target = shoppingItems.find((item) => item.id === id);
    showToast(target?.done ? "已恢复为待购买" : "已标记为已购买");
  };

  const addShoppingItem = (event) => {
    event.preventDefault();
    const name = newItem.trim();
    if (!name) return;
    setShoppingItems((current) => [
      { id: `manual-${Date.now()}`, name, detail: "刚刚手动加入", quantity: "× 1", done: false },
      ...current,
    ]);
    setNewItem("");
    setComposerOpen(false);
    showToast(`${name}已加入采购清单`);
  };

  return (
    <div className="page-view life-page">
      <div className="life-scroll">
        <header className="life-header">
          <div>
            <h1>生活</h1>
            <p>{todayText()}</p>
          </div>
          <button
            type="button"
            className="life-source-button"
            aria-label="查看连接设备"
            title="连接设备"
            onClick={() => navigate("/my")}
          >
            <RadioTower size={18} />
          </button>
        </header>

        <section className="life-body-band" aria-labelledby="life-body-title">
          <div className="life-band-head">
            <strong id="life-body-title">身体状态</strong>
            <span>手环与体脂秤 · 8分钟前</span>
          </div>
          <div className="life-metric-row">
            <Metric value="68" unit="bpm" label="静息心率" />
            <Metric value="7" unit="h 12m" label="睡眠" />
            <Metric value="21.4" unit="%" label="体脂" />
            <Metric value="6.4" unit="k" label="活动" />
          </div>
          <div className="life-trend" aria-label="今日活动趋势">
            {[26, 34, 30, 48, 62, 52, 72, 56, 68, 84, 58, 38].map((height, index) => (
              <i key={index} style={{ height: `${height}%` }} />
            ))}
          </div>
        </section>

        <div className="life-grid">
          <section className="life-module life-schedule">
            <ModuleTitle icon={CalendarDays} count={2}>接下来</ModuleTitle>
            <div className="life-module-list">
              <div className="life-schedule-row">
                <span className="life-time">10:00</span>
                <span>产品讨论<small>线上会议</small></span>
              </div>
              <div className="life-schedule-row">
                <span className="life-time">18:30</span>
                <span>取快递<small>东门柜 08-12</small></span>
              </div>
            </div>
          </section>

          <button
            type="button"
            className="life-module life-shopping-preview"
            onClick={() => setShoppingOpen(true)}
          >
            <ModuleTitle icon={ShoppingBag} count={pendingShopping.length}>采购清单</ModuleTitle>
            <div className="life-module-list">
              {pendingShopping.slice(0, 2).map((item) => (
                <div className="life-mini-row" key={item.id}>
                  <span>{item.name}</span>
                  <small>{item.quantity}</small>
                </div>
              ))}
            </div>
            <span className="life-module-footer">查看清单 <ChevronRight size={14} /></span>
          </button>

          <section className="life-module life-tasks">
            <ModuleTitle icon={CircleCheckBig} count={pendingTasks.length}>待你处理</ModuleTitle>
            <div className="life-module-list">
              {tasks.map((task) => (
                <div className={`life-task-row ${task.done ? "is-done" : ""}`} key={task.id}>
                  <button
                    type="button"
                    className="life-check-button"
                    aria-label={task.done ? `恢复${task.name}` : `完成${task.name}`}
                    onClick={() => toggleTask(task.id)}
                  >
                    <Check size={13} />
                  </button>
                  <span>{task.name}<small>{task.detail}</small></span>
                  {task.source && <em>{task.source}</em>}
                </div>
              ))}
            </div>
          </section>

          <section className="life-module life-home-state">
            <ModuleTitle icon={HousePlug}>家庭状态</ModuleTitle>
            <div className="life-module-list">
              <div className="life-mini-row"><span>空气质量</span><small>优</small></div>
              <div className="life-mini-row"><span>客厅温度</span><small>24°C</small></div>
            </div>
          </section>

          <section className="life-module life-memo">
            <ModuleTitle icon={NotebookPen}>备忘</ModuleTitle>
            <div className="life-module-list">
              <div className="life-mini-row"><span>续费停车</span><small>明天</small></div>
              <div className="life-mini-row"><span>预约洗牙</span><small>本周</small></div>
            </div>
          </section>
        </div>
      </div>

      <AnimatePresence>
        {shoppingOpen && (
          <motion.section
            className="life-shopping-page"
            aria-label="采购清单"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 360, damping: 38 }}
          >
            <header className="life-subpage-header">
              <button type="button" aria-label="返回生活页" onClick={() => setShoppingOpen(false)}>
                <ChevronLeft size={20} />
              </button>
              <h2>采购清单</h2>
              <button
                type="button"
                aria-label={composerOpen ? "关闭添加采购项目" : "添加采购项目"}
                onClick={() => setComposerOpen((open) => !open)}
              >
                {composerOpen ? <X size={19} /> : <Plus size={19} />}
              </button>
            </header>

            <div className="life-shopping-content">
              <AnimatePresence initial={false}>
                {composerOpen && (
                  <motion.form
                    className="life-shopping-composer"
                    onSubmit={addShoppingItem}
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                  >
                    <input
                      autoFocus
                      value={newItem}
                      onChange={(event) => setNewItem(event.target.value)}
                      placeholder="添加采购项目"
                      aria-label="采购项目名称"
                    />
                    <button type="submit" disabled={!newItem.trim()}>添加</button>
                  </motion.form>
                )}
              </AnimatePresence>

              <div className="life-shopping-summary">
                <div>
                  <b>{pendingShopping.length} 项</b>
                  <p>最近一次更新：刚刚</p>
                </div>
                <span>待买</span>
              </div>

              <ShoppingGroup
                title="待购买"
                items={pendingShopping}
                onToggle={toggleShopping}
              />
              <ShoppingGroup
                title="已购买"
                items={completedShopping}
                onToggle={toggleShopping}
              />
            </div>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {toast && (
          <motion.div
            className="life-toast"
            role="status"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
          >
            <CircleCheckBig size={16} />
            <span>{toast}</span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function ShoppingGroup({ title, items, onToggle }) {
  return (
    <section className="life-shopping-group">
      <h3>{title}</h3>
      <div>
        {items.length === 0 && <p className="life-list-empty">这里还没有项目。</p>}
        {items.map((item) => (
          <div className={`life-shopping-item ${item.done ? "is-done" : ""}`} key={item.id}>
            <button
              type="button"
              className="life-check-button"
              aria-label={item.done ? `恢复${item.name}为待购买` : `标记${item.name}已购买`}
              onClick={() => onToggle(item.id)}
            >
              <Check size={13} />
            </button>
            <span>
              <b>{item.name}</b>
              <small>{item.detail}</small>
            </span>
            <em>{item.quantity}</em>
          </div>
        ))}
      </div>
    </section>
  );
}
