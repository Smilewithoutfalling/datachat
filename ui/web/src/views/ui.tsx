// V2a 的小部件：顶栏、对话框（原生 <dialog> showModal，自带焦点圈和 Esc）、溢出菜单、相对时间。
import { type ReactNode, useEffect, useRef, useState } from "react";
import { IconClose, IconMore } from "./icons";

export function Topbar({ title, sub, actions }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="topbar">
      <div className="topbar-text">
        {typeof title === "string" ? <h1 className="topbar-title">{title}</h1> : title}
        {sub ? <div className="topbar-sub" data-testid="topbar-sub">{sub}</div> : null}
      </div>
      {actions ? <div className="topbar-actions">{actions}</div> : null}
    </header>
  );
}

/** 模态对话框。open 变 true 时 showModal()；Esc / 取消都走 onClose。jsdom 没有 showModal，退化为 open 属性。 */
export function Dialog({ open, onClose, label, children }: { open: boolean; onClose: () => void; label: string; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      if (typeof d.showModal === "function") d.showModal();
      else d.setAttribute("open", "");
    } else if (!open && d.open) {
      if (typeof d.close === "function") d.close();
      else d.removeAttribute("open");
    }
  }, [open]);
  return (
    <dialog ref={ref} className="dialog" aria-label={label} onCancel={(e) => (e.preventDefault(), onClose())}>
      {open ? (
        <>
          {/* 验收 r2 #8：有表单的对话框也要能一眼找到关闭 */}
          <button type="button" className="dialog-close" aria-label="关闭" onClick={onClose}><IconClose size={14} /></button>
          {children}
        </>
      ) : null}
    </dialog>
  );
}

/** ··· 菜单：点外面或 Esc 关闭。items 的 danger 项用 --danger。 */
export function MoreMenu({ label, items, className, align = "right" }: {
  label: string;
  items: { label: string; onClick: () => void; danger?: boolean }[];
  className?: string;
  align?: "right" | "left";
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const box = useRef<HTMLSpanElement>(null);
  // 验收 P0-5：菜单用 fixed 定位，按触发按钮的位置算，再夹在视口里（左右各留 8px），不会溢出到屏幕外
  const place = (btn: HTMLElement) => {
    const r = btn.getBoundingClientRect();
    const W = 200;
    const want = align === "right" ? r.right - W : r.left;
    const left = Math.max(8, Math.min(want, window.innerWidth - W - 8));
    const top = Math.min(r.bottom + 4, window.innerHeight - 8 - 40 * items.length);
    setPos({ top, left });
  };
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const key = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", key);
    };
  }, [open]);
  return (
    <span ref={box} style={{ position: "relative", display: "inline-flex" }}>
      <button type="button" className={`icon ${className ?? ""}`} aria-label={label} aria-haspopup="menu" aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          if (!open) place(e.currentTarget);
          setOpen(!open);
        }}>
        <IconMore />
      </button>
      {open ? (
        <div className="menu" role="menu" style={{ top: pos.top, left: pos.left }}>
          {items.map((it) => (
            <button key={it.label} type="button" role="menuitem" className={it.danger ? "danger-item" : undefined}
              onClick={() => (setOpen(false), it.onClick())}>
              {it.label}
            </button>
          ))}
        </div>
      ) : null}
    </span>
  );
}

/** 「刚刚 / 12 分钟前 / 昨天 18:20 / 10月19日」。后端时间是 UTC ISO。 */
export function relTime(iso: string, now = Date.now()): string {
  const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  if (!Number.isFinite(t)) return "";
  const s = Math.max(0, (now - t) / 1000);
  if (s < 60) return "刚刚";
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  const d = new Date(t);
  const today = new Date(now);
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (d.toDateString() === today.toDateString()) return hm;
  const y = new Date(now - 86400000);
  if (d.toDateString() === y.toDateString()) return `昨天 ${hm}`;
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

/** 重名数据集的区分后缀（phase5 V2a §1.4）：同一天写时刻，否则写日期。 */
export function createdSuffix(iso: string, now = Date.now()): string {
  const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  if (!Number.isFinite(t)) return "";
  const d = new Date(t);
  if (d.toDateString() === new Date(now).toDateString())
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}
