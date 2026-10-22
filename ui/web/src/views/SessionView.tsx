import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api";
import { type Client, errText } from "../client";
import { emptyTurn, reduce, replay, settle, type Turn } from "../turn";
import type { Message, Session, SessionDetail } from "../types";
import { FeedbackBar } from "./FeedbackBar";
import { IconArrowUp, IconStop, IconTable, IconTrash, IconWarn } from "./icons";
import { ThemePicker } from "./ThemePicker";
import { TurnView } from "./TurnView";
import { Dialog, MoreMenu, Topbar } from "./ui";

// 会话：顶栏（标题原地编辑、主题、···）、历史（重放）、提问（SSE 实时）、停止、重新生成、👍👎。
// status 是最终真相源（phase5-frontend.md §1）：流结束后重新拉会话，用库里的 status 收尾本页实时收到的轮次。
type Live = { question: string; messageId: string; turn: Turn; startedAt: number };
export function SessionView({ c, id, datasetName, title: titleProp, keyConfigured = true, onGoSettings, onChanged, onDeleted }: {
  c: Client;
  id: string;
  datasetName: string;
  title?: string; // 侧栏改名后同步过来
  keyConfigured?: boolean;
  onGoSettings?: () => void;
  onChanged: (s: Session) => void;
  onDeleted: () => void;
}) {
  const [s, setS] = useState<SessionDetail | null>(null);
  const [title, setTitle] = useState("");
  const editingTitle = useRef(false);
  const [error, setError] = useState("");
  const [askError, setAskError] = useState("");
  const [draft, setDraft] = useState("");
  const [live, setLive] = useState<Live | null>(null); // 正在流式接收的一轮
  const [liveTurns, setLiveTurns] = useState<Record<string, Turn>>({}); // 本页实时收到、已结束的轮次（按助手消息 id）
  const [stopping, setStopping] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [flash, setFlash] = useState(0);
  const mounted = useRef(true);
  const box = useRef<HTMLTextAreaElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);

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

  // 验收 P0-1：打开会话落在最新一轮（原来停在顶部，最后一张图被视口下沿切掉，看起来像被输入区压住）。
  // 贴底：用户在底部附近（≤ 80px）时，内容长高（结论流出来、图画出来、这一轮换成库里的版本）就跟到底；
  // 翻上去看旧内容时不打扰。f4-layout.spec 钉住几何。
  const mainRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const loaded = s !== null;
  useEffect(() => {
    const main = mainRef.current;
    if (!main) return;
    const toEnd = () => { main.scrollTop = main.scrollHeight; };
    const onScroll = () => { stick.current = main.scrollHeight - main.scrollTop - main.clientHeight <= 80; };
    main.addEventListener("scroll", onScroll, { passive: true });
    toEnd();
    if (typeof ResizeObserver === "undefined") return () => main.removeEventListener("scroll", onScroll);
    // 只盯消息列表本身（空会话时是占位）：别的东西塞进 .main 不触发贴底
    const ro = new ResizeObserver(() => { if (stick.current) toEnd(); });
    const watch = () => main.querySelectorAll(":scope > .messages, :scope > .empty-session").forEach((el) => ro.observe(el));
    watch();
    const mo = new MutationObserver(watch);
    mo.observe(main, { childList: true });
    return () => { main.removeEventListener("scroll", onScroll); ro.disconnect(); mo.disconnect(); };
  }, [loaded]);

  // 侧栏里改了名：没在编辑时同步过来
  useEffect(() => {
    if (titleProp !== undefined && !editingTitle.current) {
      setTitle(titleProp);
      setS((x) => (x && x.title !== titleProp ? { ...x, title: titleProp } : x));
    }
  }, [titleProp]);

  const ask = useCallback(
    async (question: string) => {
      setAskError("");
      let turn = emptyTurn(true);
      let messageId = "";
      const startedAt = Date.now();
      setLive({ question, messageId, turn, startedAt });
      requestAnimationFrame(() => bottom.current?.scrollIntoView?.({ block: "end" }));
      try {
        const res = await c.ask(id, question);
        messageId = res.messageId;
        setLive({ question, messageId, turn, startedAt });
        // 首问时后端已把标题设成问题前 60 字（app.py:407）：顶栏和侧栏现在就跟上，不等这一轮结束
        setS((x) => {
          if (x && !x.title) {
            const t = question.slice(0, 60);
            if (!editingTitle.current) setTitle(t);
            onChanged({ id: x.id, dataset_id: x.dataset_id, agent: x.agent, title: t, created_at: x.created_at, updated_at: new Date().toISOString() });
            return { ...x, title: t };
          }
          return x;
        });
        for await (const ev of res.events) {
          turn = reduce(turn, ev);
          if (mounted.current) setLive({ question, messageId, turn, startedAt });
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
        // P1-3（phase5 V2a §1.7）：首问时后端把标题设成问题前 60 字（app.py:407），这里同步标题输入框；正在编辑时不覆盖
        if (!editingTitle.current) setTitle(d.title);
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

  if (error) return <div className="main"><p role="alert" className="banner danger">{error}</p></div>;
  if (!s) return <div className="main" aria-busy="true">加载中…</div>;

  const runningMsg = s.messages.find((m) => m.role === "assistant" && m.status === "running");
  const running = !!live || !!runningMsg;
  const stopTarget = live ? live.messageId : runningMsg?.id ?? "";
  const rephrase = (q: string) => {
    setDraft(q);
    requestAnimationFrame(() => box.current?.focus());
  };
  const submit = () => {
    const q = draft.trim();
    if (!q || running) return;
    if (!keyConfigured) {
      setFlash((n) => n + 1); // 未配置凭证：前端拦下，不发请求（V2a §1.9）
      return;
    }
    setDraft("");
    void ask(q);
  };
  const questionBefore = (i: number) => {
    for (let j = i - 1; j >= 0; j--) if (s.messages[j].role === "user") return s.messages[j].content;
    return "";
  };
  const turns = s.messages.filter((m) => m.role === "user").length + (live ? 1 : 0);

  const renderAssistant = (m: Message, i: number) => {
    const t = liveTurns[m.id] ? settle(liveTurns[m.id], m) : replay(m);
    const q = questionBefore(i);
    return (
      <TurnView
        turn={t}
        agent={s.agent}
        messageId={m.id}
        chartSrc={c.chartSrc}
        stopping={m.status === "running" && stopping}
        onRetry={!running && q ? () => void ask(q) : undefined}
        busy={running && !!q}
        onRephrase={q ? () => rephrase(q) : undefined}
        onGoSettings={onGoSettings}
        foot={m.status === "ok" || m.status === "error" ? <FeedbackBar c={c} messageId={m.id} initial={m.feedback} /> : undefined}
      />
    );
  };

  const rename = () => {
    editingTitle.current = false;
    const t = title.trim();
    if (t === s.title) return;
    c.renameSession(id, t).then(
      (r) => (setS({ ...s, title: r.title }), setTitle(r.title), onChanged(r)),
      (e) => setError(errText(e)),
    );
  };

  return (
    <div className="view-root" data-testid="session-view">
      <Topbar
        title={
          <input
            ref={titleRef}
            className="title-input"
            aria-label="会话标题"
            value={title}
            maxLength={120}
            placeholder="未命名会话"
            onFocus={() => (editingTitle.current = true)}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={rename}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
              if (e.key === "Escape") {
                const el = e.target as HTMLInputElement;
                setTitle(s.title);
                setTimeout(() => el.blur());
              }
            }}
          />
        }
        sub={`${datasetName} · ${turns} 轮对话`}
        actions={
          <>
            <ThemePicker />
            <MoreMenu label="会话操作" items={[
              { label: "重命名", onClick: () => titleRef.current?.focus() },
              { label: "删除会话", onClick: () => setConfirmDelete(true), danger: true },
            ]} />
          </>
        }
      />
      <div className="main" ref={mainRef}>
        {!keyConfigured ? (
          <div key={flash} className={`banner${flash ? " flash" : ""}`} role="status" data-testid="key-banner">
            <IconWarn size={13} />
            <span className="grow">未配置模型凭证{flash ? "，这次提问没有发出" : ""}</span>
            {onGoSettings ? <button type="button" className="link" onClick={onGoSettings}>去设置 →</button> : null}
          </div>
        ) : null}
        {s.messages.length === 0 && !live ? (
          <div className="empty-session">
            <p>还没有消息</p>
            <p className="sub">在下面输入一个关于 {datasetName} 的问题，按 Ctrl + Enter 发送</p>
          </div>
        ) : (
          <ol className="messages">
            {s.messages.map((m, i) => (
              <li key={m.id} className={`msg ${m.role}`} data-testid={m.role === "assistant" ? "assistant-msg" : undefined}>
                {m.role === "user" ? <div className="bubble">{m.content}</div> : renderAssistant(m, i)}
              </li>
            ))}
            {live ? (
              <>
                <li className="msg user">
                  <div className="bubble">{live.question}</div>
                </li>
                <li className="msg assistant" data-testid="live-msg">
                  <TurnView turn={live.turn} agent={s.agent} chartSrc={c.chartSrc} stopping={stopping} startedAt={live.startedAt} />
                </li>
              </>
            ) : null}
          </ol>
        )}
        <div ref={bottom} />
      </div>
      <div className="composer-wrap">
        <form
          className="composer ask"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <textarea
            ref={box}
            aria-label="提问"
            rows={1}
            placeholder={running ? "分析进行中…" : "问一个关于这份数据的问题…"}
            value={draft}
            maxLength={4000}
            onChange={(e) => {
              setDraft(e.target.value);
              const t = e.target;
              t.style.height = "auto";
              t.style.height = `${Math.min(t.scrollHeight, 160)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <div className="composer-row">
            <span className="ctx-pill" title="会话创建时已绑定数据集"><IconTable size={12} /><span>{datasetName}</span></span>
            <span className="kbd-hint">Ctrl + Enter 发送</span>
            {running ? (
              <button type="button" className="send stop" disabled={!stopTarget || stopping} onClick={() => void stop(stopTarget)}>
                <IconStop size={11} />
                {/* 验收 r2：不用省略号，免得缩放后分不清中英文 */}{stopping ? "停止中" : "停止"}
              </button>
            ) : (
              <button type="submit" className="send primary" disabled={!draft.trim()}>
                发送 <IconArrowUp size={13} />
              </button>
            )}
          </div>
          {askError ? <p role="alert" className="err">{askError}</p> : null}
        </form>
      </div>
      <Dialog open={confirmDelete} onClose={() => setConfirmDelete(false)} label="删除会话">
        <div className="dialog-icon"><IconTrash size={18} /></div>
        <h2>删除「{s.title || "未命名会话"}」？</h2>
        <p>这个会话的 {turns} 轮对话会一起删除，无法恢复。{datasetName} 和表里的数据不受影响。</p>
        <div className="dialog-actions">
          <button type="button" onClick={() => setConfirmDelete(false)}>取消</button>
          <button type="button" className="destroy"
            onClick={() => (setConfirmDelete(false), c.deleteSession(id).then(onDeleted, (e) => setError(errText(e))))}>
            删除会话
          </button>
        </div>
      </Dialog>
    </div>
  );
}
