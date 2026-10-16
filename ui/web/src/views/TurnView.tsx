// 一轮助手回答（阶段 5 F2）：plan、code（折叠）、exec（折叠）、可恢复 error（黄）、answer（markdown）、done（警告；图表在 F3）。
// 终止原因只按 status / error_kind 分支（turn.ts 的 outcome），不对文案做匹配。所有用户数据按文本渲染（T9）。
import { answerText, type Ev, MESSAGES, outcome, type Turn } from "../turn";
import { Markdown } from "./Markdown";

const SOURCE: Record<string, string> = { codegen: "生成代码", reviewer: "修正代码", tool_call: "执行代码" };
const KIND: Record<string, string> = { dataset: "数据集", llm: "模型调用", execution: "代码执行", agent: "分析流程" };

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
      // 致命错误由下面的终止原因统一展示（与 done 里的 error 相同），这里只画可恢复的
      return ev.data.fatal ? null : <div className="ev warn" role="note">{ev.data.message}</div>;
    default:
      return null; // answer 在下面单独渲染；done 不进 events
  }
}

export function TurnView({ turn, onRetry }: { turn: Turn; onRetry?: () => void }) {
  const o = outcome(turn);
  const answer = answerText(turn);
  const r = turn.result;
  return (
    <div className="turn" data-status={turn.status}>
      {turn.events.map((ev) => (
        <EventView key={ev.seq} ev={ev} />
      ))}
      {o.kind === "running" ? (
        <div className="muted" aria-busy="true">分析中…</div>
      ) : null}
      {answer ? <Markdown text={answer} /> : null}
      {o.kind === "cancelled" ? (
        o.unsavedAnswer ? (
          <div className="unsaved" data-testid="unsaved-answer">
            <div className="badge cancelled">已取消（未保存）</div>
            <div className="text">{o.unsavedAnswer}</div>
          </div>
        ) : (
          <div className="outcome cancelled">{MESSAGES.cancelled}</div>
        )
      ) : null}
      {o.kind === "interrupted" ? (
        <div className="outcome interrupted" role="status">
          {o.message}
          {onRetry ? (
            <button type="button" onClick={onRetry}>
              重试
            </button>
          ) : null}
        </div>
      ) : null}
      {o.kind === "error" ? (
        <div className="outcome error" role="alert">
          {o.errorKind && KIND[o.errorKind] ? <strong>{KIND[o.errorKind]}失败：</strong> : null}
          {o.message}
        </div>
      ) : null}
      {o.kind === "ok" && r?.warnings?.length ? (
        <ul className="warnings">
          {r.warnings.map((w, i) => (
            <li key={i} className="warn">{w}</li>
          ))}
        </ul>
      ) : null}
      {o.kind === "ok" && r?.unverified_numbers?.length ? (
        <p className="warn small">结论里这些数字在执行结果中没找到，请核对：{r.unverified_numbers.join("、")}</p>
      ) : null}
      {o.kind === "ok" && r?.charts?.length ? (
        <p className="muted small">本轮有 {r.charts.length} 张图表（图表渲染在 F3）。</p>
      ) : null}
    </div>
  );
}
