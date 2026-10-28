import { useState } from "react";
import type { ConnectionTest } from "../types";
import { IconCheck, IconChevronDown, IconChevronUp } from "./icons";
import { llmErrorText } from "./llmErrorText";

const sec = (ms: number) => `${(ms / 1000).toFixed(1)}s`;

/** 阶段 6.5 §5：测试结果两行——连接、工具调用。失败沿用 V2c §2：标题 + 建议 + 编号，后端原文（含上游 message，
 *  Key 已打码）收进默认折叠的「技术详情」。工具调用 ✗ 时写明后果：边想边做不可用。 */
export function TestResult({ r }: { r: ConnectionTest }) {
  const t = r.tools;
  return (
    <div className="test-conn" data-testid="test-result">
      <div className="test-row" data-testid="test-connect">
        <span className="test-label">连接</span>
        {r.connect.ok ? (
          <span className="key-ok" role="status"><IconCheck size={11} />连接正常 · {sec(r.connect.latency_ms)} · {r.model}</span>
        ) : (
          <Fail kind={r.connect.llm_kind} message={r.connect.message} />
        )}
      </div>
      <div className="test-row" data-testid="test-tools">
        <span className="test-label">工具调用</span>
        {t === null ? (
          <span className="hint">没有测（先要连得上）</span>
        ) : t.ok === true ? (
          <span className="key-ok"><IconCheck size={11} />支持 · {sec(t.latency_ms)}</span>
        ) : t.ok === false ? (
          <Fail kind={t.llm_kind ?? "unsupported"} message={t.message ?? ""}
            title="不支持工具调用" hint="「边想边做」需要工具调用，用这个连接时只能选「标准」模式。" />
        ) : (
          <Fail kind={t.llm_kind ?? "unknown"} message={t.message ?? ""} title="工具调用没测出来" />
        )}
      </div>
    </div>
  );
}

function Fail({ kind, message, title, hint }: { kind: string; message: string; title?: string; hint?: string }) {
  const [tech, setTech] = useState(false);
  const t = llmErrorText(kind, "settings");
  const code = /（编号 ([0-9a-f]+)）$/.exec(message)?.[1];
  return (
    <div className="banner danger test-fail" role="alert">
      <p className="test-fail-title">{title ?? t.title}</p>
      <p className="test-fail-hint">{hint ?? t.hint}{code ? `（编号 ${code}）` : ""}</p>
      {message ? (
        <>
          <button type="button" className="tech-toggle" aria-expanded={tech} onClick={() => setTech(!tech)}>
            技术详情{tech ? <IconChevronUp size={10} /> : <IconChevronDown size={10} />}
          </button>
          <p className="tech-body" hidden={!tech} data-testid="test-tech">{message}</p>
        </>
      ) : null}
    </div>
  );
}
