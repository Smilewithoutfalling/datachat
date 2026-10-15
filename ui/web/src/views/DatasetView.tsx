import { useEffect, useState } from "react";
import { type Client, errText, formatSize } from "../client";
import type { Agent, DatasetDetail } from "../types";
import { ConfirmButton } from "./ConfirmButton";
import { PreviewTable } from "./PreviewTable";

type Props = {
  c: Client;
  id: string;
  initial?: DatasetDetail; // 上传响应已带预览时直接用，省一次整表读取
  onDeleted: () => void;
  onNewSession: (datasetId: string, agent: Agent) => void;
};

export function DatasetView({ c, id, initial, onDeleted, onNewSession }: Props) {
  // Shell 按 id 设了 key，换数据集会重新挂载，这里不用手动复位状态
  const [detail, setDetail] = useState<DatasetDetail | null>(initial?.id === id && initial.preview ? initial : null);
  const [tab, setTab] = useState(0);
  const [agent, setAgent] = useState<Agent>("workflow");
  const [error, setError] = useState("");
  const have = detail !== null;

  useEffect(() => {
    if (have) return;
    let live = true;
    c.dataset(id) // 详情 + 预览一个请求（F1.1）
      .then((d) => live && setDetail(d))
      .catch((e) => live && setError(errText(e)));
    return () => {
      live = false;
    };
  }, [c, id, have]);

  if (error) return <section className="view" role="alert">加载数据集失败：{error}</section>;
  if (!detail) return <section className="view" aria-busy="true">加载中…</section>;

  const preview = detail.preview ?? { rows: 0, tables: [], dicts: [] };
  const multi = preview.tables.length > 1;
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
      {/* 行列数与编码在预览提示行和多表 tab 上；summary 不再单列（单表时与提示行重复） */}
      {detail.error && (
        <p className="warn" role="alert">
          有表读取失败，分析会失败：{detail.error}
        </p>
      )}
      <ul className="files">
        {detail.files.map((f) => (
          <li key={f.filename}>
            {f.filename} <span className="muted">{formatSize(f.size)}</span>
          </li>
        ))}
      </ul>
      {preview.dicts.length > 0 && <p className="muted">字典文件：{preview.dicts.join("、")}</p>}
      {multi && (
        <div className="tabs" role="tablist">
          {preview.tables.map((t, i) => (
            <button key={t.name} type="button" role="tab" aria-selected={i === tab} onClick={() => setTab(i)}>
              {t.name}
              <span className="muted small">
                {t.error !== undefined ? " 读取失败" : ` ${t.total_rows}×${t.total_columns} · ${t.encoding}`}
              </span>
            </button>
          ))}
        </div>
      )}
      {current && <PreviewTable table={current} />}
    </section>
  );
}
