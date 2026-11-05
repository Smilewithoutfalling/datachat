import { type FormEvent, useEffect, useRef, useState } from "react";
import { ApiError } from "../api";
import { download } from "../charts/exportPng";
import { type Client, errText } from "../client";
import type { DatasetNote, NoteIn, NoteKind } from "../types";
import { ConfirmButton } from "./ConfirmButton";

// 批 4b M2 / M10（docs/roadmap/memory-batch4.md §3.4.1）：数据集页的「口径与规则」。
// 在用口径的只读列表 + 添加 / 编辑表单 + 停用 + 导入导出。口径挂在数据集上，同一数据集的所有会话共用；
// 只在会话记忆不是「关闭」时生效。body 只是文本（后端永不执行），这里也一律按纯文本渲染。
// 按钮不叫「删除」：数据集页已有「删除数据集」，e2e 用 getByRole("button") 定位，重名会匹配到两个。

const LIMITS = { name: 64, body: 2000, unit: 16, synonyms: 200 } as const;
const EMPTY: NoteIn = { kind: "metric", name: "", body: "", unit: "", synonyms: "" };
const KIND_TEXT: Record<NoteKind, string> = { metric: "指标", rule: "规则" };

export function validateNote(n: NoteIn): string {
  if (!n.name.trim()) return "名称不能为空";
  if (!n.body.trim()) return n.kind === "metric" ? "公式不能为空" : "规则不能为空";
  if (n.name.trim().length > LIMITS.name) return `名称不能超过 ${LIMITS.name} 字`;
  if (n.body.trim().length > LIMITS.body) return `${n.kind === "metric" ? "公式" : "规则"}不能超过 ${LIMITS.body} 字`;
  if (n.unit.trim().length > LIMITS.unit) return `单位不能超过 ${LIMITS.unit} 字`;
  if (n.synonyms.trim().length > LIMITS.synonyms) return `别名不能超过 ${LIMITS.synonyms} 字`;
  return "";
}

type Form = { mode: "add" } | { mode: "edit"; id: string } | null;

export function NotesSection({ c, datasetId }: { c: Client; datasetId: string }) {
  const [notes, setNotes] = useState<DatasetNote[] | null>(null);
  const [memoryOff, setMemoryOff] = useState(false);
  const [form, setForm] = useState<Form>(null);
  const [draft, setDraft] = useState<NoteIn>(EMPTY);
  const [formError, setFormError] = useState("");
  const [error, setError] = useState(""); // 操作失败（导入 / 停用 / 导出）：role=alert
  const [loadError, setLoadError] = useState(""); // 读取列表失败：只写一行说明，不抢 alert（数据集页其他 alert 有固定顺序）
  const [msg, setMsg] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const reload = () => c.notes(datasetId).then((l) => (setNotes(l), setLoadError("")), (e) => setLoadError(`读取口径失败：${errText(e)}`));
  useEffect(() => {
    let live = true;
    c.notes(datasetId).then((l) => live && setNotes(l), (e) => live && setLoadError(`读取口径失败：${errText(e)}`));
    c.settings().then((s) => live && setMemoryOff((s.memory?.mode ?? "off") === "off"), () => undefined);
    return () => {
      live = false;
    };
  }, [c, datasetId]);

  const open = (f: Form, n: NoteIn = EMPTY) => (setForm(f), setDraft(n), setFormError(""), setMsg(""));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const bad = validateNote(draft);
    if (bad) return setFormError(bad);
    const req = form?.mode === "edit" ? c.updateNote(datasetId, form.id, draft) : c.addNote(datasetId, draft);
    req.then(
      () => (setForm(null), setDraft(EMPTY), setMsg(form?.mode === "edit" ? "口径已更新。" : "口径已添加。"), reload()),
      (err) => setFormError(err instanceof ApiError && err.status === 409
        ? `已经有一条在用的「${draft.name.trim()}」，请在列表里点它的「编辑」。`
        : err instanceof ApiError ? err.detail : errText(err)),
    );
  };
  const retire = (n: DatasetNote) =>
    c.retireNote(datasetId, n.id).then(() => (setMsg(`已停用「${n.name}」。`), reload()), (e) => setError(errText(e)));
  const onImport = (f: File | undefined) => {
    if (!f) return;
    setMsg("");
    setError("");
    c.importNotes(datasetId, f).then(
      (r) => (setMsg(`导入完成：新增 ${r.added} 条，更新 ${r.updated} 条，未变 ${r.unchanged} 条。`), reload()),
      (e) => setError(e instanceof ApiError ? e.detail : errText(e)),
    );
    if (fileRef.current) fileRef.current.value = "";
  };
  const onExport = (format: "csv" | "json") =>
    c.exportNotes(datasetId, format).then(
      (text) => download(`data:${format === "csv" ? "text/csv" : "application/json"};charset=utf-8,${encodeURIComponent(text)}`, `口径.${format}`),
      (e) => setError(errText(e)),
    );

  const set = (k: keyof NoteIn) => (e: { target: { value: string } }) => setDraft({ ...draft, [k]: e.target.value });

  return (
    <section className="side-card notes-card" data-testid="notes-section" aria-label="口径与规则">
      <div className="card-head">
        <h3 className="card-title">口径与规则</h3>
        <span className="count">{notes ? `${notes.length} 条` : ""}</span>
      </div>
      <p className="muted small notes-intro">
        写下这个数据集的指标定义和业务规则，这个数据集的所有会话都会按它来算。口径里用到的字段必须在表里真实存在，否则照样回答不了。
      </p>
      {memoryOff ? <p className="hint notes-off" data-testid="notes-off">会话记忆关闭时口径不生效，可在「设置」里开启。</p> : null}
      {loadError ? <p className="hint" data-testid="notes-load-error">{loadError}</p> : null}
      {error ? <p className="banner danger" role="alert">{error}</p> : null}
      {msg ? <p className="muted small" role="status">{msg}</p> : null}
      {notes && notes.length ? (
        <table className="notes-table">
          <thead>
            <tr><th>名称</th><th>类型</th><th>公式 / 规则</th><th>单位</th><th>别名</th><th><span className="sr-only">操作</span></th></tr>
          </thead>
          <tbody>
            {notes.map((n) => (
              <tr key={n.id} data-testid="note-row">
                <td className="n-name">{n.name}</td>
                <td>{KIND_TEXT[n.kind] ?? n.kind}</td>
                <td className="n-body">{n.body}</td>
                <td>{n.unit || "—"}</td>
                <td>{n.synonyms ? n.synonyms.split(",").join("、") : "—"}</td>
                <td className="n-actions">
                  <button type="button" className="link" aria-label={`编辑「${n.name}」`}
                    onClick={() => open({ mode: "edit", id: n.id }, { kind: n.kind, name: n.name, body: n.body, unit: n.unit, synonyms: n.synonyms })}>
                    编辑
                  </button>
                  <ConfirmButton label="停用" confirmLabel="确认停用" onConfirm={() => retire(n)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : notes ? (
        <p className="muted small" data-testid="notes-empty">还没有口径。</p>
      ) : null}
      {form ? (
        <form className="note-form" onSubmit={submit} aria-label={form.mode === "edit" ? "编辑口径" : "添加口径"} noValidate>
          <label>
            类型
            <select aria-label="口径类型" value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value as NoteKind })}>
              <option value="metric">指标（有公式）</option>
              <option value="rule">规则（一句话）</option>
            </select>
          </label>
          <label>名称<input aria-label="口径名称" value={draft.name} maxLength={LIMITS.name} onChange={set("name")} placeholder="如：利润" /></label>
          <label>
            {draft.kind === "metric" ? "公式" : "规则"}
            <textarea aria-label="公式或规则" value={draft.body} maxLength={LIMITS.body} rows={2} onChange={set("body")}
              placeholder={draft.kind === "metric" ? "如：销售额 - 成本（用表里的列名）" : "如：退款单不计入销售额"} />
          </label>
          {draft.kind === "metric" ? (
            <label>单位<input aria-label="单位" value={draft.unit} maxLength={LIMITS.unit} onChange={set("unit")} placeholder="如：元" /></label>
          ) : null}
          <label>别名<input aria-label="别名" value={draft.synonyms} maxLength={LIMITS.synonyms} onChange={set("synonyms")} placeholder="逗号分隔，如：净利，净利润" /></label>
          {formError ? <p className="banner danger" role="alert" data-testid="note-form-error">{formError}</p> : null}
          <div className="note-form-actions">
            <button type="submit" className="primary">{form.mode === "edit" ? "保存修改" : "保存口径"}</button>
            <button type="button" onClick={() => (setForm(null), setFormError(""))}>取消</button>
          </div>
        </form>
      ) : (
        <div className="notes-actions">
          <button type="button" className="pill-outline" onClick={() => open({ mode: "add" })}>添加口径</button>
          <button type="button" onClick={() => fileRef.current?.click()}>导入</button>
          <button type="button" disabled={!notes?.length} onClick={() => onExport("csv")}>导出 CSV</button>
          <button type="button" disabled={!notes?.length} onClick={() => onExport("json")}>导出 JSON</button>
          <input ref={fileRef} type="file" accept=".csv,.json" aria-label="选择口径文件" hidden
            onChange={(e) => onImport(e.target.files?.[0])} />
        </div>
      )}
    </section>
  );
}
