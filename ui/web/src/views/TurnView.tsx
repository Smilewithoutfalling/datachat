// 一轮助手回答（阶段 5 F2/F3；V2a §2、§3）。卡片结构固定：头 → 步骤条（默认折叠，展开是事件流）→ 警示条 → 结论 → 图表 → 尾。
// 图表按 result.charts 的顺序：option 项用 EChart，png 项用同源 <img>。截断提示只走后端 result.warnings（单一来源）。
// 终止原因只按 status / error_kind / llm_kind 分支（turn.ts 的 outcome），不对文案做匹配。所有用户数据按文本渲染（T9）。
import { type ReactNode, useEffect, useState } from "react";
import { type ChartSpec, EChart } from "../charts/EChart";
import { answerText, type Ev, MESSAGES, outcome, partialSignals, type Step, steps, totalSeconds, type Turn, turnMeta, turnTokens } from "../turn";
import { IconAlert, IconChevronDown, IconChevronUp, IconPlay, IconRetry, IconSpark, IconWarn, Spinner, StepIcon } from "./icons";
import { llmErrorText } from "./llmErrorText";
import { Markdown } from "./Markdown";

const SOURCE: Record<string, string> = { codegen: "生成代码", reviewer: "修正代码", tool_call: "执行代码" };

function EventView({ ev }: { ev: Ev }) {
  switch (ev.type) {
    case "plan":
      return (
        <details className="ev plan" open>
          <summary>分析计划</summary>
          <div className="text">{ev.data.text}</div>
        </details>
      );
    case "code":
      return (
        <details className="ev code">
          <summary>
            {SOURCE[ev.data.source] ?? ev.data.source}
            {ev.data.attempt > 0 ? `（第 ${ev.data.attempt + 1} 次）` : ""}
          </summary>
          {ev.data.thought ? <div className="text muted">{ev.data.thought}</div> : null}
          <pre>{ev.data.code}</pre>
        </details>
      );
    case "exec":
      return (
        <details className={`ev exec ${ev.data.ok ? "" : "failed"}`}>
          <summary>
            {ev.data.ok ? "执行成功" : "执行出错"} · {Number(ev.data.duration_s ?? 0).toFixed(1)}s
          </summary>
          {ev.data.stdout ? <pre>{ev.data.stdout}</pre> : null}
          {ev.data.result_text ? <pre>{ev.data.result_text}</pre> : null}
          {ev.data.error ? <pre className="err">{ev.data.error}</pre> : null}
        </details>
      );
    case "error":
      // 致命错误由错误卡统一展示（与 done 里的 error 相同），这里只画可恢复的
      return ev.data.fatal ? null : <div className="ev warn" role="note">{ev.data.message}</div>;
    default:
      return null; // answer 在下面单独渲染；done 不进 events
  }
}

// 不到 0.05s 的不写（验收 P2-23：「总结 · 0.0s」和「总结」混着出现）
const sec = (s: number | null) => (s === null || s < 0.05 ? "" : ` · ${s < 10 ? s.toFixed(1) : Math.round(s)}s`);

function StepBar({ list, open, onToggle, canOpen }: { list: Step[]; open: boolean; onToggle: () => void; canOpen: boolean }) {
  return (
    <div className="stepbar" data-testid="stepbar">
      {list.map((s, i) => (
        <span key={s.key} style={{ display: "contents" }}>
          {i > 0 ? <span className="step-sep" aria-hidden="true" /> : null}
          <span className={`step ${s.state}`} data-step={s.key} data-state={s.state}>
            <StepIcon state={s.state === "stopped" ? "pending" : s.state} />
            {s.name}
            {s.count > 1 ? ` ×${s.count}` : ""}
            {s.state === "done" || s.state === "failed" ? sec(s.seconds) : ""}
            {s.state === "stopped" ? "（已中断）" : ""}
          </span>
        </span>
      ))}
      {canOpen ? (
        <button type="button" className="link toggle" aria-expanded={open} onClick={onToggle}>
          {open ? "收起过程" : "查看过程"}
          {open ? <IconChevronUp size={11} /> : <IconChevronDown size={11} />}
        </button>
      ) : null}
    </div>
  );
}

type Badge = { cls: string; text: string; icon?: ReactNode };

export type TurnActions = {
  onRetry?: () => void; // 用原问题重新提问（重新生成 / 重试 / 重新问一次）
  busy?: boolean; // 会话里有别的轮次在跑：重试按钮照常显示但置灰（验收 P2-24：同一种错误按钮组合不变）
  onRephrase?: () => void; // 把原问题填回输入框
  onGoSettings?: () => void;
  stopping?: boolean;
  startedAt?: number; // 实时轮次的开始时刻（Date.now），running 时算已用时
  foot?: ReactNode; // 👍👎
};

export function TurnView({ turn, chartSrc, messageId, agent, ...act }: {
  turn: Turn;
  agent?: string; // workflow 时步骤条从「理解问题」开始

  chartSrc?: (path: string) => string | null;
  messageId?: string; // F4：层 1 改动按 <message_id>:<图序号> 存
} & TurnActions) {
  const o = outcome(turn);
  const answer = answerText(turn);
  const r = turn.result;
  const list = steps(turn, agent);
  const partial = partialSignals(turn);
  const [open, setOpen] = useState(false);
  const [moreWarn, setMoreWarn] = useState(false);
  const now = useTicker(o.kind === "running" && act.startedAt !== undefined);
  const total = totalSeconds(turn);
  const llmKind = r?.llm_kind ?? null;

  const badge: Badge =
    o.kind === "running"
      ? act.stopping
        ? { cls: "stopping", text: "停止中", icon: <Spinner size={9} /> }
        : { cls: "running", text: "分析中", icon: <Spinner size={9} /> }
      : o.kind === "ok"
        ? partial.length
          ? { cls: "partial", text: "部分完成", icon: <IconWarn size={10} /> }
          : { cls: "ok", text: "已完成" }
        : o.kind === "error"
          ? { cls: "error", text: "失败" }
          : o.kind === "cancelled"
            ? { cls: "cancelled", text: "已取消" }
            : { cls: "interrupted", text: "已中断" };

  const time =
    o.kind === "running"
      ? act.startedAt !== undefined
        ? `已用时 ${((now - act.startedAt) / 1000).toFixed(1)}s`
        : ""
      : total !== null
        ? `用时 ${total < 10 ? total.toFixed(2) : total.toFixed(1)}s` // 验收 r2 #6：写明是用时
        : "";
  const hasCode = turn.events.some((e) => e.type === "code");
  const tokens = o.kind === "running" ? null : turnTokens(turn);
  const meta = turnMeta(turn);

  return (
    <div className="acard turn" data-status={turn.status}>
      <div className="acard-head">
        <span className="avatar"><IconSpark size={13} /></span>
        <span className="acard-name">datachat</span>
        <span className={`badge ${badge.cls}`} data-testid="turn-badge">{badge.icon}{badge.text}</span>
        {/* 阶段 6.5：这一轮用的连接和模型。只放 title（悬停可见）和「查看过程」里，不改卡头宽度（视觉基线 25 屏不动） */}
        <span className="acard-time" title={meta ? `连接：${meta.connection_name} · 模型：${meta.model}` : undefined}>
          {time}
          {tokens ? (
            <span
              className="acard-tokens"
              data-testid="turn-tokens"
              title={tokens.estimated ? "服务商未返回用量，按字数估算" : undefined}
            >
              {time ? " · " : ""}{tokens.estimated ? "≈" : ""}{tokens.n.toLocaleString("en-US")} tokens
            </span>
          ) : null}
        </span>
      </div>

      {list.length ? <StepBar list={list} open={open} onToggle={() => setOpen(!open)} canOpen={turn.events.length > 0} /> : null}
      {open ? (
        <div className="process" data-testid="process">
          {meta ? <p className="hint" data-testid="turn-meta">连接：{meta.connection_name} · 模型：<span className="mono">{meta.model}</span></p> : null}
          {turn.events.map((ev) => <EventView key={ev.seq} ev={ev} />)}
        </div>
      ) : null}

      {partial.length ? (
        <div className="wbar warnings" role="note">
          <IconWarn size={14} />
          <div className="wbar-body">
            <div className="wbar-title">{partial[0]}</div>
            {moreWarn && partial.length > 1 ? (
              <ul>{partial.slice(1).map((w, i) => <li key={i}>{w}</li>)}</ul>
            ) : null}
          </div>
          {partial.length > 1 ? (
            <button type="button" className="link" aria-expanded={moreWarn} onClick={() => setMoreWarn(!moreWarn)}>
              {moreWarn ? "收起" : `还有 ${partial.length - 1} 条`}
            </button>
          ) : null}
        </div>
      ) : null}

      {o.kind === "running" ? (
        <div className="running-hint" aria-busy="true">
          <span className="sr-only">分析中…</span>
          {act.stopping ? <p className="outcome-text">已发送停止，当前这一步结束后生效。</p> : null}
          {/* 验收 P0-9：没有真实进度，不画任何像进度条的东西，只用骨架占位 */}
          {/* 停止中不再放加载动效（验收 r2 #2）；骨架尺寸贴近成品：两行结论 + 一张图（图高 360，见 .echart） */}
          {act.stopping ? null : <div className="skeleton" aria-hidden="true"><i /><i /><i /><i /></div>}
        </div>
      ) : null}

      {answer ? <div className="answer"><Markdown text={answer} /></div> : null}

      {o.kind === "cancelled" ? (
        o.unsavedAnswer ? (
          <div className="unsaved" data-testid="unsaved-answer">
            <div className="badge cancelled">已取消（未保存）</div>
            <div className="text">{o.unsavedAnswer}</div>
          </div>
        ) : (
          <p className="outcome-text"><span className="outcome cancelled">{MESSAGES.cancelled}</span>，没有生成结论。</p>
        )
      ) : null}
      {o.kind === "interrupted" ? (
        <p className="outcome interrupted outcome-text" role="status">{o.message}</p>
      ) : null}
      {o.kind === "cancelled" || o.kind === "interrupted" ? (
        <div className="actions-row">
          {act.onRetry || act.busy ? (
            <button type="button" className="primary" disabled={!act.onRetry} onClick={act.onRetry}>
              <IconPlay size={11} />重新问一次
            </button>
          ) : null}
          {act.onRephrase ? <button type="button" onClick={act.onRephrase}>换个问法</button> : null}
          {hasCode ? <button type="button" className="link" onClick={() => setOpen(true)}>查看已生成的代码</button> : null}
        </div>
      ) : null}

      {o.kind === "error" ? (
        <ErrorCard errorKind={o.errorKind} llmKind={llmKind} message={o.message} messageId={messageId} act={act} />
      ) : null}

      {o.kind === "ok" && r?.charts?.length ? (
        <div className="charts">
          {r.charts.map((c, i) => {
            if (c.option) return <EChart key={i} spec={c.option as unknown as ChartSpec} editKey={messageId ? `${messageId}:${i}` : undefined} />;
            const src = c.png && chartSrc ? chartSrc(c.png) : null;
            // matplotlib 的静态图没有导出按钮：标注出来，免得和旁边带"导出 PNG"的交互图比着以为按钮坏了（F3 第六步，S 10-19）
            return src ? (
              <figure key={i} className="chart-static-wrap" data-testid="chart-static">
                <img className="chart-png" src={src} alt="图表" />
                <figcaption className="chart-static">静态图（由 matplotlib 生成），可右键另存为</figcaption>
              </figure>
            ) : null;
          })}
        </div>
      ) : null}

      {(o.kind === "ok" || o.kind === "error") && (act.foot || act.onRetry) ? (
        <div className="acard-foot">
          {act.foot}
          {o.kind === "ok" && (act.onRetry || act.busy) ? (
            <button type="button" className="link regen" disabled={!act.onRetry} onClick={act.onRetry}>重新生成</button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** 错误卡（V2a §3.3）：error_kind 4 类；llm 类再按 llm_kind 给出口（S 10-22 已定第 1 条）。 */
/** 错误卡（V2a §3.3）：error_kind 4 类；llm 类再按 llm_kind 给标题、建议和出口（S 10-22 已定第 1 条）。
 *  验收 P1-2/3：正文只放用户要的（发生了什么、能做什么、编号），后端原文（含上游 message）收进「技术详情」。
 *  编号就是助手消息 id 的前 8 位（app.py 以 msg_id 作 trace_id，user_error 末尾的「编号」同源）。 */
function ErrorCard({ errorKind, llmKind, message, messageId, act }: {
  errorKind: string | null; llmKind: string | null; message: string; messageId?: string; act: TurnActions;
}) {
  const k = errorKind === "llm" ? llmKind ?? "unknown" : null;
  const lt = k ? llmErrorText(k) : null;
  const { rate, auth, badReq } = lt ?? { rate: false, auth: false, badReq: false };
  const [title, hint] = lt
    ? [lt.title, lt.hint]
    : errorKind === "execution"
      ? ["代码没跑通", "可以重试，或者换个问法。"]
      : errorKind === "dataset"
        ? ["数据读取失败", ""]
        : ["分析流程出错", "可以重试。"];
  // dataset 的文案是我们自己的常量（errors.dataset_message），本身就是给用户看的，直接放正文
  const body = errorKind === "dataset" ? message : hint;
  const [tech, setTech] = useState(false);
  const code = messageId ? `（编号 ${messageId.slice(0, 8)}）` : "";
  return (
    <div className="errcard outcome error" role="alert">
      <IconAlert size={18} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <p className="errcard-title">{title}</p>
        <p className="errcard-detail">{body}{errorKind === "dataset" ? "" : code}</p>
        {errorKind !== "dataset" ? (
          // 和「查看过程」同一种折叠图标（下 / 上箭头，验收 r2 #4）
          <>
            <button type="button" className="tech-toggle" aria-expanded={tech} onClick={() => setTech(!tech)}>
              技术详情{tech ? <IconChevronUp size={10} /> : <IconChevronDown size={10} />}
            </button>
            <p className="tech-body" hidden={!tech}>{message}</p>
          </>
        ) : null}
        <div className="actions-row" style={{ marginTop: 10 }}>
          {rate ? <Countdown seconds={10} onDone={act.onRetry} /> : null}
          {auth && act.onGoSettings ? <button type="button" className="primary" onClick={act.onGoSettings}>去设置</button> : null}
          {!rate && !auth && (act.onRetry || act.busy) ? (
            <button type="button" className="primary" disabled={!act.onRetry} onClick={act.onRetry}><IconRetry size={12} />重试</button>
          ) : null}
          {(badReq || errorKind === "execution") && act.onRephrase ? (
            <button type="button" onClick={act.onRephrase}>换个问法</button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/** 429：按钮先置灰倒计时，结束后可点，点了等于重新生成。 */
function Countdown({ seconds, onDone }: { seconds: number; onDone?: () => void }) {
  const [left, setLeft] = useState(seconds);
  useEffect(() => {
    if (left <= 0) return;
    const t = setTimeout(() => setLeft(left - 1), 1000);
    return () => clearTimeout(t);
  }, [left]);
  if (!onDone) return null;
  return (
    <button type="button" className="primary" disabled={left > 0} onClick={onDone}>
      <IconRetry size={12} />{left > 0 ? `${left} 秒后可重试` : "稍后再试"}
    </button>
  );
}

function useTicker(on: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!on) return;
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, [on]);
  return now;
}
