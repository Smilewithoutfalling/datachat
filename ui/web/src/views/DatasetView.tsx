import { useEffect, useState } from "react";
import { type Client, errText, formatSize } from "../client";
import type { Agent, DatasetDetail, Preview } from "../types";
import { ConfirmButton } from "./ConfirmButton";
import { PreviewTable } from "./PreviewTable";

type Props = {
  c: Client;
  id: string;
  onDeleted: () => void;
  onNewSession: (datasetId: string, agent: Agent) => void;
};

export function DatasetView({ c, id, onDeleted, onNewSession }: Props) {
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [tab, setTab] = useState(0);
  const [agent, setAgent] = useState<Agent>("workflow");
  const [error, setError] = useState("");

  useEffect(() => {
    // Shell 按 id 设了 key，换数据集会重新挂载，这里不用手动复位状态
    let live = true;
    Promise.all([c.dataset(id), c.preview(id)])
      .then(([d, p]) => live && (setDetail(d), setPreview(p)))
      .catch((e) => live && setError(errText(e)));
    return () => {
      live = false;
    };
  }, [c, id]);

  if (error) return <section className="view" role="alert">加载数据集失败：{error}</section>;
  if (!detail || !preview) return <section className="view" aria-busy="true">加载中…</section>;

  const current = preview.tables[Math.min(tab, preview.tables.length - 1)];
  return (
    <section className="view" data-testid="dataset-view">
      <header className="view-head">
        <h2>{detail.name}</h2>
        <div className="actions">
          <select aria-label="分析方式" value={agent} onChange={(e) => setAgent(e.target.value as Agent)}>
            <option value="workflow">工作流</option>
            <option value="react">ReAct</option>
          </select>
          <button type="button" onClick={() => onNewSession(id, agent)}>
            新建会话
          </button>
          <ConfirmButton
            label="删除数据集"
            confirmLabel="再点一次确认删除"
            onConfirm={() => c.deleteDataset(id).then(onDeleted, (e) => setError(errText(e)))}
          />
        </div>
      </header>
      <p className="muted">
        {detail.summary ?? ""}
        {detail.error ? <span className="warn">（读取出错：{detail.error}）</span> : null}
      </p>
      <ul className="files">
        {detail.files.map((f) => (
          <li key={f.filename}>
            {f.filename} <span className="muted">{formatSize(f.size)}</span>
          </li>
        ))}
      </ul>
      {preview.dicts.length > 0 && <p className="muted">字典文件：{preview.dicts.join("、")}</p>}
      {preview.tables.length > 1 && (
        <div className="tabs" role="tablist">
          {preview.tables.map((t, i) => (
            <button key={t.name} type="button" role="tab" aria-selected={i === tab} onClick={() => setTab(i)}>
              {t.name}
            </button>
          ))}
        </div>
      )}
      {current && <PreviewTable table={current} />}
    </section>
  );
}
