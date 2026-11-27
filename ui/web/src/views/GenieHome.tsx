// 原型（proto/genie-shell）：首页参考 Databricks Genie 的结构——居中问候 + 大输入框 + 推荐问题 + 最近。
// 只借鉴布局和交互，图标、文案都是自己的。输入框在有数据集时就能用，数据集在框内切换，解决旧首页「使用中 / 未选择数据源」自相矛盾。
import { type ReactNode, useState } from "react";
import type { Dataset, DatasetProfile, Session } from "../types";
import { IconChat, IconSend, IconTable } from "./icons";
import { assetLine, greeting, STARTERS } from "./StarterCards";
import { relTime } from "./ui";
import "./genie.css";

export function GenieHome({ datasets, label, profiles, sessions, busy, upload, onAsk, onOpenSession, onOpenDataset, onAllDatasets }: {
  datasets: Dataset[]; // 已排除读取失败的
  label: Record<string, string>;
  profiles: Record<string, DatasetProfile>;
  sessions: Session[];
  busy: boolean;
  upload: ReactNode; // 没有数据集时代替输入框的上传卡
  onAsk: (datasetId: string, question: string) => void;
  onOpenSession: (id: string) => void;
  onOpenDataset: (id: string) => void;
  onAllDatasets: () => void;
}) {
  const [picked, setDs] = useState("");
  const [q, setQ] = useState("");
  const ds = datasets.some((d) => d.id === picked) ? picked : (datasets[0]?.id ?? ""); // 选过的被删了就回到最新一个
  const ready = !!ds && !busy;
  const send = (text: string) => {
    const t = text.trim();
    if (ready && t) onAsk(ds, t);
  };

  return (
    <div className="g-home" data-testid="genie-home">
      <div className="g-hero">
        <h2 className="g-hello">{greeting()}，今天想分析什么？</h2>
        {datasets.length === 0 ? upload : (
          <form className="g-ask" onSubmit={(e) => (e.preventDefault(), send(q))}>
            <textarea aria-label="提问" rows={2} value={q} placeholder="用一句话描述你想知道的，比如：上个月哪个地区销量下滑最多？"
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send(q);
                }
              }} />
            <div className="g-ask-row">
              <label className="g-ds-pick">
                <IconTable size={13} />
                <select aria-label="数据集" value={ds} onChange={(e) => setDs(e.target.value)}>
                  {datasets.map((d) => <option key={d.id} value={d.id}>{label[d.id]}</option>)}
                </select>
              </label>
              <span className="g-hint">Enter 发送 · Shift + Enter 换行</span>
              <button type="submit" className="primary g-send" aria-label="发送" disabled={!ready || !q.trim()}><IconSend size={15} /></button>
            </div>
          </form>
        )}
      </div>

      {datasets.length > 0 && (
        <section className="g-sec" aria-label="推荐问题">
          <h3 className="g-sec-title">推荐问题</h3>
          <ul className="g-cards">
            {STARTERS.map((s) => (
              <li key={s.id}>
                <button type="button" className="g-card" disabled={!ready} title={s.question} data-testid={`starter-${s.id}`} onClick={() => send(s.question)}>
                  <span className="g-card-title">{s.title}</span>
                  <span className="g-card-desc">{s.desc}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {(sessions.length > 0 || datasets.length > 0) && (
        <div className="g-recent">
          <section className="g-sec" aria-label="最近对话">
            <h3 className="g-sec-title">最近对话</h3>
            {sessions.length === 0 ? <p className="g-empty">还没有对话</p> : (
              <ul className="g-list">
                {sessions.slice(0, 5).map((s) => (
                  <li key={s.id}>
                    <button type="button" className="g-item" onClick={() => onOpenSession(s.id)}>
                      <IconChat size={14} />
                      <span className="g-item-title">{s.title || "未命名会话"}</span>
                      <span className="g-item-meta">{relTime(s.updated_at)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="g-sec" aria-label="数据集">
            <h3 className="g-sec-title">数据集<button type="button" className="link g-more" onClick={onAllDatasets}>全部</button></h3>
            <ul className="g-list">
              {datasets.slice(0, 5).map((d) => (
                <li key={d.id}>
                  <button type="button" className="g-item" onClick={() => onOpenDataset(d.id)}>
                    <IconTable size={14} />
                    <span className="g-item-title">{label[d.id]}</span>
                    <span className="g-item-meta">{profiles[d.id] ? assetLine(profiles[d.id]) : `${d.files.length} 个文件`}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </div>
  );
}
