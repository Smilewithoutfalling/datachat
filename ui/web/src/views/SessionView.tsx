import { useEffect, useState } from "react";
import { type Client, errText } from "../client";
import type { Session, SessionDetail } from "../types";
import { ConfirmButton } from "./ConfirmButton";

const STATUS: Record<string, string> = { ok: "", error: "失败", cancelled: "已取消", running: "分析中" };
const AGENT: Record<string, string> = { workflow: "工作流", react: "ReAct" };

// F1：会话头（改名、删除）和历史消息的纯文本。事件流、图表、提问、停止、👍👎 在 F2 / F3。
export function SessionView({ c, id, datasetName, onChanged, onDeleted }: {
  c: Client;
  id: string;
  datasetName: string;
  onChanged: (s: Session) => void;
  onDeleted: () => void;
}) {
  const [s, setS] = useState<SessionDetail | null>(null);
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true; // Shell 按 id 设了 key，换会话会重新挂载
    c.session(id)
      .then((d) => live && (setS(d), setTitle(d.title)))
      .catch((e) => live && setError(errText(e)));
    return () => {
      live = false;
    };
  }, [c, id]);

  if (error) return <section className="view" role="alert">{error}</section>;
  if (!s) return <section className="view" aria-busy="true">加载中…</section>;

  const rename = () => {
    const t = title.trim();
    if (t === s.title) return;
    c.renameSession(id, t).then(
      (r) => (setS({ ...s, title: r.title }), setTitle(r.title), onChanged(r)),
      (e) => setError(errText(e)),
    );
  };

  return (
    <section className="view" data-testid="session-view">
      <header className="view-head">
        <input
          className="title-input"
          aria-label="会话标题"
          value={title}
          maxLength={120}
          placeholder="未命名会话"
          onChange={(e) => setTitle(e.target.value)}
          onBlur={rename}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
        />
        <div className="actions">
          <ConfirmButton
            label="删除会话"
            confirmLabel="再点一次确认删除"
            onConfirm={() => c.deleteSession(id).then(onDeleted, (e) => setError(errText(e)))}
          />
        </div>
      </header>
      <p className="muted">
        数据集：{datasetName} · {AGENT[s.agent] ?? s.agent}
      </p>
      {s.messages.length === 0 ? (
        <p className="muted">还没有消息。</p>
      ) : (
        <ol className="messages">
          {s.messages.map((m) => (
            <li key={m.id} className={`msg ${m.role}`}>
              <div className="who">
                {m.role === "user" ? "你" : "datachat"}
                {STATUS[m.status] ? <span className={`badge ${m.status}`}>{STATUS[m.status]}</span> : null}
              </div>
              <div className="text">{m.content}</div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
