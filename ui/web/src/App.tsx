import { useEffect, useMemo, useState } from "react";
import { Api } from "./api";
import { client } from "./client";
import type { KeyStatus } from "./types";
import { IconClock } from "./views/icons";
import { Shell } from "./views/Shell";

type State = { kind: "checking" } | { kind: "ready"; key: KeyStatus } | { kind: "expired" } | { kind: "error"; message: string };

const CMD = "python -m app.server --open";

/** 会话失效页（V2a §5.4）：命令可复制。
 *  「重试连接」（S 10-22 r2 第 ③ 条）：用手上的令牌再请求一次，成功就回到应用；失败在旁边说清是哪种失败。
 *  后端换了令牌的情况它救不回来（那只能重跑命令），但后端只是暂时没响应时有用。按了没用的「重新打开应用」不画。 */
export function ExpiredPage({ onRetry }: { onRetry?: () => Promise<string | null> }) {
  const [copied, setCopied] = useState(false);
  const [retry, setRetry] = useState<{ busy: boolean; note: string }>({ busy: false, note: "" });
  const doRetry = () => {
    if (!onRetry || retry.busy) return;
    setRetry({ busy: true, note: "" });
    onRetry().then((note) => setRetry({ busy: false, note: note ?? "" }));
  };
  return (
    <div className="expired-wrap">
      <main className="expired" role="alert">
        <span className="ex-icon"><IconClock size={22} /></span>{/* 验收 r3 #9：失效是"过期"，不是链接 */}
        <h1>会话已失效</h1>
        <p>后端重启过，或者这是新开的标签页，页面拿不到访问令牌。</p>
        <p>数据集和会话都还在本地，没有丢失。</p>
        <div className="cmd">
          <span className="dot" aria-hidden="true" />
          <code>{CMD}</code>
          <button type="button" onClick={() => navigator.clipboard?.writeText(CMD).then(() => setCopied(true), () => undefined)}>
            {copied ? "已复制" : "复制"}
          </button>
        </div>
        {onRetry ? (
          <div className="actions-row">
            <button type="button" className="primary" disabled={retry.busy} onClick={doRetry}>
              {retry.busy ? "连接中…" : "重试连接"}
            </button>
          </div>
        ) : null}
        {retry.note ? <p className="retry-note" role="status">{retry.note}</p> : null}
        <p className="foot">重试不行，就回到命令行重新运行上面的命令，它会自动打开一个可用的页面。</p>
      </main>
    </div>
  );
}

export default function App({ api }: { api: Api }) {
  const [state, setState] = useState<State>({ kind: "checking" });
  const c = useMemo(() => client(api), [api]);

  useEffect(() => {
    const off = api.onUnauthorized(() => setState({ kind: "expired" }));
    c.keyStatus()
      .then((key) => setState({ kind: "ready", key }))
      .catch((e: unknown) => {
        if (e instanceof Error && e.name !== "Unauthorized") setState({ kind: "error", message: e.message });
      });
    return () => {
      off();
    };
  }, [api, c]);

  switch (state.kind) {
    case "expired":
      return (
        <ExpiredPage
          onRetry={() =>
            c.keyStatus().then(
              (key) => (setState({ kind: "ready", key }), null),
              (e: unknown) =>
                e instanceof Error && e.name === "Unauthorized"
                  ? "还是连不上：后端换了访问令牌，需要用上面的命令重新打开。"
                  : "还是连不上：后端没有响应，确认它还在运行。",
            )
          }
        />
      );
    case "checking":
      return <main aria-busy="true">连接后端…</main>;
    case "error":
      return <main role="alert">连接后端失败：{state.message}</main>;
    case "ready":
      return <Shell c={c} initialKey={state.key} />;
  }
}
