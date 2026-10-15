import { useEffect, useMemo, useState } from "react";
import { Api } from "./api";
import { client } from "./client";
import type { KeyStatus } from "./types";
import { Shell } from "./views/Shell";

type State = { kind: "checking" } | { kind: "ready"; key: KeyStatus } | { kind: "expired" } | { kind: "error"; message: string };

export function ExpiredPage() {
  return (
    <main className="expired" role="alert">
      <h1>会话已失效</h1>
      <p>后端重启过，或者这是新开的标签页，页面拿不到访问令牌。</p>
      <p>
        请回到命令行重新运行 <code>python -m app.server --open</code>，它会自动打开一个可用的页面。
      </p>
    </main>
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
      return <ExpiredPage />;
    case "checking":
      return <main aria-busy="true">连接后端…</main>;
    case "error":
      return <main role="alert">连接后端失败：{state.message}</main>;
    case "ready":
      return <Shell c={c} initialKey={state.key} />;
  }
}
