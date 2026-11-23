// 一轮助手回答（阶段 5 F2/F3；V2a §2、§3）。卡片结构固定：头 → 步骤条（默认折叠，展开是事件流）→ 警示条 → 结论 → 图表 → 尾。
// 阶段 7.6 U3 结果卡（phase76-ui.md §2 U3）：ok 时结论前面加「一句话结论 · 关键数字 · 校验徽章」，图表统一成同一种卡（都有「导出 PNG」），
// 尾部前加三个动作「换个口径」「补一张图」「导出」。未核实数字只在徽章里列，黄条只放 warnings（turn.ts partialSignals）。
// 图表按 result.charts 的顺序：option 项用 EChart，png 项用同源 <img>。截断提示只走后端 result.warnings（单一来源）。
// 终止原因只按 status / error_kind / llm_kind 分支（turn.ts 的 outcome），不对文案做匹配。所有用户数据按文本渲染（T9）。
import { type ReactNode, useEffect, useRef, useState } from "react";
import { ApiError } from "../api";
import { type ChartSpec, EChart } from "../charts/EChart";
import { download } from "../charts/exportPng";
import { safeFilename } from "../charts/filename";
import { getPngSaver } from "../charts/pngSaver";
import {
  answerText, canExport, conclusionOf, type Ev, FOLLOW_UPS, isPartial, keyNumbers, MESSAGES, outcome, partialSignals, type Step, steps,
  totalSeconds, type Turn, turnMeta, turnTokens, verifyState,
} from "../turn";
import { IconAlert, IconChevronDown, IconChevronUp, IconDownload, IconPlay, IconRetry, IconSpark, IconWarn, Spinner, StepIcon } from "./icons";
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
  onFollowUp?: (question: string) => void; // U3「换个口径」「补一张图」：照常提问（SessionView.ask），会话里有轮次在跑时不给
  onExport?: (what: ExportKind) => Promise<string>; // U3「导出」：#110 的 /messages/{id}/export/code|result，返回保存路径
};

export type ExportKind = "code" | "csv" | "xlsx";
const EXPORT_LABEL: Record<ExportKind, string> = { code: "分析代码（.py）", csv: "结果表（CSV）", xlsx: "结果表（Excel）" };

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
  const verify = verifyState(turn);
  const lead = o.kind === "ok" && r?.clarify !== true ? conclusionOf(answer) : null;
  const nums = keyNumbers(turn);
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
        ? isPartial(turn)
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

      {o.kind === "ok" && (lead || nums.length || verify) ? (
        <ResultHead lead={lead} nums={nums} verify={verify} />
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
        <div className="charts" data-testid="charts">
          {r.charts.map((c, i) => {
            if (c.option) return <EChart key={i} spec={c.option as unknown as ChartSpec} editKey={messageId ? `${messageId}:${i}` : undefined} />;
            const src = c.png && chartSrc ? chartSrc(c.png) : null;
            // U3：matplotlib 的静态图和交互图同一种卡、同一个「导出 PNG」入口（原来是「可右键另存为」的说明，phase76 §1 最后一行）
            return src ? <StaticChart key={i} src={src} index={i} /> : null;
          })}
        </div>
      ) : null}

      {o.kind === "ok" && messageId && (act.onFollowUp || act.onExport || act.busy) ? (
        <ResultActions turn={turn} act={act} />
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

/** U3 结果卡的头：一句话结论、最多 3 个关键数字（大字号 + 口径小字）、校验徽章。 */
function ResultHead({ lead, nums, verify }: {
  lead: string | null; nums: { value: string; label: string }[]; verify: ReturnType<typeof verifyState>;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="result-head" data-testid="result-head">
      {lead ? <p className="answer result-lead" data-testid="result-lead">{lead}</p> : null}
      {nums.length ? (
        <dl className="key-numbers" data-testid="key-numbers">
          {nums.map((n, i) => (
            <div key={i} className="kn">
              <dt className="kn-label">{n.label}</dt>
              <dd className="kn-value">{n.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {verify ? (
        verify.kind === "ok" ? (
          <span className="verify ok" data-testid="verify-badge" title="结论里的数字都能在执行结果里找到">✓ 全部可溯源</span>
        ) : (
          <div className="verify-wrap">
            <button type="button" className="verify unverified" data-testid="verify-badge" aria-expanded={open}
              onClick={() => setOpen(!open)}>
              △ {verify.numbers.length} 个数字未核实{open ? <IconChevronUp size={10} /> : <IconChevronDown size={10} />}
            </button>
            {open ? (
              <div className="verify-list" data-testid="verify-list">
                <p>结论里这些数字在执行结果中没找到，请核对：</p>
                <ul>{verify.numbers.map((n, i) => <li key={i} className="mono">{n}</li>)}</ul>
              </div>
            ) : null}
          </div>
        )
      ) : null}
    </div>
  );
}

/** matplotlib 静态图：和交互图同一种卡，卡底一行工具栏放「导出 PNG」。
 *  浏览器：同源 /charts/<name>?token= 直接 <a download>；桌面壳（WebView2 里 <a download> 没反应）：取回字节交给 PngSaver 写进下载文件夹。 */
function StaticChart({ src, index }: { src: string; index: number }) {
  const [failed, setFailed] = useState(false);
  const [savedTo, setSavedTo] = useState("");
  const name = safeFilename(undefined, `静态图${index + 1}`);
  const onExport = async () => {
    setFailed(false);
    setSavedTo("");
    const saver = getPngSaver();
    try {
      if (!saver) return download(src, name);
      const bytes = new Uint8Array(await (await fetch(src, { credentials: "omit", referrerPolicy: "no-referrer" })).arrayBuffer());
      let bin = "";
      for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      setSavedTo(await saver(`data:image/png;base64,${btoa(bin)}`, name));
    } catch {
      setFailed(true);
    }
  };
  return (
    <figure className="echart-wrap chart-static-wrap" data-testid="chart-static">
      <img className="chart-png" src={src} alt="图表" />
      <figcaption className="chart-controls" data-testid="chart-static-controls">
        <span className="chart-hint">静态图（matplotlib）</span>
        <span className="chart-export">
          <button type="button" onClick={() => void onExport()}><IconDownload size={11} />导出 PNG</button>
          {failed && <span className="warn small" role="alert">导出失败</span>}
          {savedTo && <span className="hint small" role="status" data-testid="export-saved" title={savedTo}>已保存到 {savedTo}</span>}
        </span>
      </figcaption>
    </figure>
  );
}

/** U3 底部三个动作。每个都真实发出一条请求（phase76 §3「不加点了没反应的入口」）：
 *  换个口径 / 补一张图 = 一次提问（POST /sessions/{id}/messages）；导出 = POST /messages/{id}/export/code|result。 */
function ResultActions({ turn, act }: { turn: Turn; act: TurnActions }) {
  const [menu, setMenu] = useState(false);
  const [state, setState] = useState<{ kind: "idle" } | { kind: "busy" } | { kind: "saved"; path: string } | { kind: "failed"; msg: string }>({ kind: "idle" });
  const box = useRef<HTMLSpanElement>(null);
  const exportable = canExport(turn) && !!act.onExport;
  useEffect(() => {
    if (!menu) return;
    const down = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setMenu(false);
    const key = (e: KeyboardEvent) => e.key === "Escape" && setMenu(false);
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", key);
    };
  }, [menu]);
  const run = (what: ExportKind) => {
    setMenu(false);
    setState({ kind: "busy" });
    act.onExport!(what).then(
      (path) => setState({ kind: "saved", path }),
      (e: unknown) => setState({ kind: "failed", msg: e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e) }),
    );
  };
  const follow = act.onFollowUp;
  return (
    <div className="actions-row result-actions" data-testid="result-actions">
      <button type="button" disabled={!follow} onClick={() => follow?.(FOLLOW_UPS.metric)} title={FOLLOW_UPS.metric}>换个口径</button>
      <button type="button" disabled={!follow} onClick={() => follow?.(FOLLOW_UPS.chart)} title={FOLLOW_UPS.chart}>补一张图</button>
      <span ref={box} className="export-menu">
        <button type="button" aria-haspopup="menu" aria-expanded={menu} disabled={!exportable || state.kind === "busy"}
          title={exportable ? undefined : "这一轮没有执行成功的代码，无法导出"} onClick={() => setMenu(!menu)}>
          <IconDownload size={11} />{state.kind === "busy" ? "导出中" : "导出"}<IconChevronDown size={9} />
        </button>
        {menu ? (
          <div className="menu" role="menu" style={{ position: "absolute", bottom: "calc(100% + 4px)", left: 0, top: "auto" }}>
            {(Object.keys(EXPORT_LABEL) as ExportKind[]).map((k) => (
              <button key={k} type="button" role="menuitem" onClick={() => run(k)}>{EXPORT_LABEL[k]}</button>
            ))}
          </div>
        ) : null}
      </span>
      {state.kind === "saved" ? <span className="aside" role="status" data-testid="export-result" title={state.path}>已保存到 {state.path}</span> : null}
      {state.kind === "failed" ? <span className="aside export-failed" role="alert" data-testid="export-result">导出失败：{state.msg}</span> : null}
    </div>
  );
}
