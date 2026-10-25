import { useEffect, useState } from "react";
import { type Client, errText, formatSize } from "../client";
import type { Agent, DatasetDetail } from "../types";
import { IconCheck, IconFileAlert, IconPlus, IconTrash } from "./icons";
import { PreviewTable } from "./PreviewTable";
import { Dialog, MoreMenu, relTime, Topbar } from "./ui";

type Props = {
  c: Client;
  id: string;
  initial?: DatasetDetail; // 上传响应已带预览时直接用，省一次整表读取
  displayName?: string; // 重名时带创建时间（Shell 算）
  sessionCount?: number; // 删除确认里写明会一起删掉几个会话（V2a §5.2）
  onLoaded?: (d: DatasetDetail) => void;
  onDeleted: () => void;
  onNewSession: (datasetId: string, agent: Agent) => void;
  onBack?: () => void; // V2c §3
};

export function DatasetView({ c, id, initial, displayName, sessionCount = 0, onLoaded, onDeleted, onNewSession, onBack }: Props) {
  // Shell 按 id 设了 key，换数据集会重新挂载，这里不用手动复位状态
  const [detail, setDetail] = useState<DatasetDetail | null>(initial?.id === id && initial.preview ? initial : null);
  const [tab, setTab] = useState(0);
  const [agent, setAgent] = useState<Agent>("workflow");
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [typed, setTyped] = useState("");
  const have = detail !== null;

  useEffect(() => {
    if (have) return;
    let live = true;
    c.dataset(id) // 详情 + 预览一个请求（F1.1）
      .then((d) => live && (setDetail(d), onLoaded?.(d)))
      .catch((e) => live && setError(errText(e)));
    return () => {
      live = false;
    };
  }, [c, id, have]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error && !detail) return <div className="main"><p className="banner danger" role="alert">加载数据集失败：{error}</p></div>;
  if (!detail) return <div className="main" aria-busy="true">加载中…</div>;

  const name = displayName ?? detail.name;
  const preview = detail.preview ?? { rows: 0, tables: [], dicts: [] };
  const okTables = preview.tables.filter((t) => t.error === undefined);
  const allFailed = !!detail.error && okTables.length === 0;
  const current = preview.tables[Math.min(tab, preview.tables.length - 1)];
  const size = detail.files.reduce((a, f) => a + f.size, 0);
  const rowsTotal = okTables.reduce((a, t) => a + (t.error === undefined ? t.total_rows : 0), 0);
  const del = () => c.deleteDataset(id).then(onDeleted, (e) => (setConfirm(false), setError(errText(e))));

  const sub = allFailed
    ? "读取失败，修好之前不能新建会话"
    : `${okTables.length} 个表${preview.dicts.length ? ` · 带字典` : ""} · ${rowsTotal.toLocaleString()} 行 · ${relTime(detail.created_at)}上传`;

  return (
    <div className="view-root" data-testid="dataset-view">
      <Topbar
        onBack={onBack}
        title={name}
        sub={sub}
        actions={
          <>
            {!allFailed ? (
              <>
                {/* 验收 P1-12：「工作流」是内部叫法。新会话用哪种分析方式，按用户能理解的差别来写 */}
                <label className="pill" title="标准：先列计划再写代码，稳；边想边做：每步看结果再决定下一步，适合探索">
                  模式
                  <select aria-label="分析模式" value={agent} onChange={(e) => setAgent(e.target.value as Agent)}>
                    <option value="workflow">标准</option>
                    <option value="react">边想边做</option>
                  </select>
                </label>
                <button type="button" className="pill-outline" onClick={() => onNewSession(id, agent)}>
                  <IconPlus size={12} />新建会话
                </button>
              </>
            ) : null}
            <MoreMenu label="数据集操作" items={[{ label: "删除数据集", onClick: () => setConfirm(true), danger: true }]} />
          </>
        }
      />
      <div className="main">
        {error ? <p className="banner danger" role="alert">{error}</p> : null}
        {allFailed ? (
          <div className="failwrap">{/* 验收 r3 #8：和失效页一样垂直居中 */}
          <div className="failcard" role="alert">
            <span className="fc-icon"><IconFileAlert size={22} /></span>
            <h2>{detail.files.length === 1 ? detail.files[0].filename : name} 读取失败</h2>
            <p className="reason">{detail.error}</p>
            <span className="chips">
              {detail.files.length} 个文件 · {formatSize(size)}
            </span>
            <div className="actions-row">
              {/* 验收 r2 §2.3：用户先想修好它，再想扔掉它。重新上传是主操作；删除降为文字按钮，放远一点 */}
              <button type="button" className="primary" onClick={() => document.querySelector<HTMLInputElement>('input[aria-label="选择 CSV 文件"]')?.click()}>
                重新上传
              </button>
              <button type="button" className="link fc-delete" onClick={() => setConfirm(true)}>删除这个数据集</button>
            </div>
            <p className="fc-tip">{failTip(detail.error ?? "")}</p>
          </div>
          </div>
        ) : (
          <div className="ds-layout">
            <div className="ds-col">
              {detail.error ? (
                <p className="banner danger" role="alert">有表读取失败，分析会失败：{detail.error}</p>
              ) : null}
              <div className="ds-toolbar">
                {preview.tables.length > 1 ? (
                  <div className="segmented tabs" role="tablist">
                    {preview.tables.map((t, i) => (
                      <button key={t.name} type="button" role="tab" aria-selected={i === tab} className={t.error !== undefined ? "failed" : undefined}
                        onClick={() => setTab(i)}>
                        {t.name}
                        <span className="tab-meta">
                          {t.error !== undefined ? " 读取失败" : ` ${t.total_rows}×${t.total_columns} · ${t.encoding}`}
                        </span>
                      </button>
                    ))}
                  </div>
                ) : null}
                {current && current.error === undefined ? (
                  <span className="note">
                    {current.rows.length < current.total_rows
                      ? `预览前 ${current.rows.length} 行（共 ${current.total_rows.toLocaleString()} 行）· 只读`
                      : `共 ${current.total_rows.toLocaleString()} 行，已全部显示 · 只读`}
                  </span>
                ) : null}
              </div>
              {current ? (
                current.error !== undefined ? (
                  <PreviewTable table={current} />
                ) : (
                  <div className="table-card"><PreviewTable table={current} /></div>
                )
              ) : null}
              {/* 验收 P1-13：只在识别出非 UTF-8 编码时提示 */}
              {current && current.error === undefined && !/^(utf-8|utf-8-sig|ascii)$/i.test(current.encoding) ? (
                <p className="enc-note">这张表按 {current.encoding} 读取。预览里出现乱码时，请在 Excel 里另存为 CSV（UTF-8）后重新上传。</p>
              ) : null}
            </div>
            <aside className="ds-col">
              <section className="side-card">
                <div className="card-head"><h3 className="card-title">来源</h3><span className="count">本地</span></div>
                <dl style={{ margin: 0 }}>
                  {detail.files.map((f) => (
                    <div className="kv" key={f.filename}>
                      <dt>{/\.dict\.csv$/i.test(f.filename) ? "字典文件" : "数据文件"}</dt>
                      <dd title={f.filename}>{f.filename} <span className="muted">{formatSize(f.size)}</span></dd>
                    </div>
                  ))}
                  <div className="kv"><dt>工作表</dt><dd>{okTables.map((t) => t.name).join(" · ") || "—"}</dd></div>
                  <div className="kv"><dt>上传时间</dt><dd>{relTime(detail.created_at)}</dd></div>
                </dl>
                {preview.dicts.length > 0 ? <p className="muted small" style={{ margin: "6px 0 0" }}>字典文件：{preview.dicts.join("、")}</p> : null}
              </section>
              {current && current.error === undefined ? (
                <section className="side-card">
                  <div className="card-head"><h3 className="card-title">字段</h3><span className="count">{current.columns.length} 个</span></div>
                  <ul className="field-list">
                    {current.columns.map((col, i) => (
                      <li key={i}><span className="fname" title={col}>{col}</span><span className="ftype">{current.dtypes[i]}</span></li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </aside>
          </div>
        )}
      </div>
      <Dialog open={confirm} onClose={() => (setConfirm(false), setTyped(""))} label="删除数据集">
        <div className="dialog-icon"><IconTrash size={18} /></div>
        <h2>删除 {detail.name}？</h2>
        <p>
          {detail.files.length} 个文件{sessionCount ? `、${sessionCount} 个会话` : ""}会一并删除，无法恢复。本地原始 CSV 文件不受影响。
        </p>
        <label>
          {/* 验收 r2：写明要输入的完整名称，不一致时说出来，免得按钮灰着不知道为什么 */}
          输入「{detail.name}」以确认
          <span className="confirm-field">
            <input aria-label="输入数据集名称以确认" value={typed} autoFocus className={typed === detail.name ? "match" : undefined}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && typed === detail.name && del()} />
            {typed === detail.name ? <IconCheck size={14} /> : null}
            {typed && typed !== detail.name ? <span className="confirm-miss">还差：要和「{detail.name}」完全一致</span> : null}
          </span>
        </label>
        <div className="dialog-actions">
          <button type="button" onClick={() => (setConfirm(false), setTyped(""))}>取消</button>
          <button type="button" className="destroy" disabled={typed !== detail.name} onClick={del}>删除数据集</button>
        </div>
      </Dialog>
    </div>
  );
}

/** 读取失败的建议（验收 P1-6）。匹配的是我们自己的常量文案（app/core/errors.py dataset_message），不是上游原文；
 *  认不出就给通用建议。 */
function failTip(err: string): string {
  if (err.includes("文件是空的")) return "打开文件看看是否有内容，或者换一个文件。";
  if (err.includes("编码")) return "在 Excel 里另存为 CSV（UTF-8）后重新上传，通常能解决。";
  if (err.includes("无法解析")) return "检查报错的那一行：引号是否成对、列数是否和表头一致。";
  return "确认文件是逗号分隔的 CSV，再重新上传。";
}
