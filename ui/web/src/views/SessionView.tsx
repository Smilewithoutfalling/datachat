import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api";
import { type Client, errText } from "../client";
import { emptyTurn, reduce, replay, settle, type Turn } from "../turn";
import type { Message, Session, SessionDetail } from "../types";
import { ConfirmButton } from "./ConfirmButton";
import { FeedbackBar } from "./FeedbackBar";
import { TurnView } from "./TurnView";

const STATUS: Record<string, string> = { ok: "", error: "失败", cancelled: "已取消", interrupted: "已中断", running: "分析中" };
const AGENT: Record<string, string> = { workflow: "工作流", react: "ReAct" };

// 会话：头（改名、删除）、历史（重放）、提问（SSE 实时）、停止、重试、👍👎。图表在 F3。
// status 是最终真相源（phase5-frontend.md §1）：流结束后重新拉会话，用库里的 status 收尾本页实时收到的轮次。
type Live = { question: string; messageId: string; turn: Turn };
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
  const [askError, setAskError] = useState("");
  const [draft, setDraft] = useState("");
  const [live, setLive] = useState<Live | null>(null); // 正在流式接收的一轮
  const [liveTurns, setLiveTurns] = useState<Record<string, Turn>>({}); // 本页实时收到、已结束的轮次（按助手消息 id）
  const [stopping, setStopping] = useState(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    let alive = true; // Shell 按 id 设了 key，换会话会重新挂载
    c.session(id)
      .then((d) => alive && (setS(d), setTitle(d.title)))
      .catch((e) => alive && setError(errText(e)));
    return () => {
      alive = false;
      mounted.current = false;
    };
  }, [c, id]);

  const ask = useCallback(
    async (question: string) => {
      setAskError("");
      let turn = emptyTurn(true);
      let messageId = "";
      setLive({ question, messageId, turn });
      try {
        const res = await c.ask(id, question);
        messageId = res.messageId;
        setLive({ question, messageId, turn });
        for await (const ev of res.events) {
          turn = reduce(turn, ev);
          if (mounted.current) setLive({ question, messageId, turn });
        }
      } catch (e) {
        if (!messageId) {
          // 没建起来（409 有分析在跑、401 等）：没有落库的轮次
          if (mounted.current) {
            setLive(null);
            setAskError(errText(e));
          }
          return;
        }
      }
      // 流结束（或中途断）：以库里的 status 收尾
      try {
        const d = await c.session(id);
        if (!mounted.current) return;
        const m = d.messages.find((x) => x.id === messageId);
        if (m) setLiveTurns((lt) => ({ ...lt, [messageId]: settle(turn, m) }));
        setS(d);
        onChanged({ id: d.id, dataset_id: d.dataset_id, agent: d.agent, title: d.title,
          created_at: d.created_at, updated_at: d.updated_at }); // 左栏按最近分析时间排序，updated_at 变了
      } catch (e) {
        if (mounted.current) setAskError(errText(e));
      } finally {
        if (mounted.current) {
          setLive(null);
          setStopping(false);
        }
      }
    },
    [c, id, onChanged],
  );

  // 停止：先等 cancel 返回（CAS 落库 cancelled），不主动断开流，等流里的 error + done 自然结束。
  // 409 = 已经结束，交给流结束后的收尾。顺序反了（先断开）库里会落 interrupted。
  const stop = async (messageId: string) => {
    setStopping(true);
    try {
      await c.cancel(messageId);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 409)) setAskError(errText(e));
    }
    if (!live || live.messageId !== messageId) {
      // 停的是历史里的 running（比如别的标签页发起的）：直接刷新
      c.session(id).then((d) => mounted.current && (setS(d), setStopping(false)), () => setStopping(false));
    }
  };

  if (error) return <section className="view" role="alert">{error}</section>;
  if (!s) return <section className="view" aria-busy="true">加载中…</section>;

  const running = !!live || s.messages.some((m) => m.role === "assistant" && m.status === "running");
  const submit = () => {
    const q = draft.trim();
    if (!q || running) return;
    setDraft("");
    void ask(q);
  };
  const questionBefore = (i: number) => {
    for (let j = i - 1; j >= 0; j--) if (s.messages[j].role === "user") return s.messages[j].content;
    return "";
  };
  const renderAssistant = (m: Message, i: number) => {
    const t = liveTurns[m.id] ? settle(liveTurns[m.id], m) : replay(m);
    const q = questionBefore(i);
    return (
      <>
        <TurnView turn={t} onRetry={!running && q ? () => void ask(q) : undefined} />
        {m.status === "running" ? (
          <button type="button" className="stop" disabled={stopping} onClick={() => void stop(m.id)}>
            停止
          </button>
        ) : null}
        {m.status === "ok" || m.status === "error" ? <FeedbackBar c={c} messageId={m.id} initial={m.feedback} /> : null}
      </>
    );
  };

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
      {s.messages.length === 0 && !live ? (
        <p className="muted">还没有消息。</p>
      ) : (
        <ol className="messages">
          {s.messages.map((m, i) => (
            <li key={m.id} className={`msg ${m.role}`} data-testid={m.role === "assistant" ? "assistant-msg" : undefined}>
              <div className="who">
                {m.role === "user" ? "你" : "datachat"}
                {m.role === "assistant" && STATUS[m.status] ? <span className={`badge ${m.status}`}>{STATUS[m.status]}</span> : null}
              </div>
              {m.role === "user" ? <div className="text">{m.content}</div> : renderAssistant(m, i)}
            </li>
          ))}
          {live ? (
            <>
              <li className="msg user">
                <div className="who">你</div>
                <div className="text">{live.question}</div>
              </li>
              <li className="msg assistant" data-testid="live-msg">
                <div className="who">
                  datachat<span className="badge running">{STATUS.running}</span>
                </div>
                <TurnView turn={live.turn} />
                <button type="button" className="stop" disabled={!live.messageId || stopping} onClick={() => void stop(live.messageId)}>
                  {stopping ? "正在停止…" : "停止"}
                </button>
              </li>
            </>
          ) : null}
        </ol>
      )}
      <form
        className="ask"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <textarea
          aria-label="提问"
          placeholder={running ? "分析进行中…" : "问一个关于这份数据的问题（Ctrl+Enter 发送）"}
          value={draft}
          maxLength={4000}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button type="submit" disabled={running || !draft.trim()}>
          提问
        </button>
        {askError ? <p role="alert" className="err">{askError}</p> : null}
      </form>
    </section>
  );
}
