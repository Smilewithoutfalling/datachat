import { type DragEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../api";
import { setPngSaver } from "../charts/pngSaver";
import { inDesktopShell } from "../desktop";
import { type Client, errText, formatSize } from "../client";
import type { Agent, Dataset, DatasetDetail, KeyStatus, Session } from "../types";
import { DatasetView } from "./DatasetView";
import { IconChat, IconGear, IconPlus, IconSidebar, IconSpark, IconTable, IconUpload } from "./icons";
import { SessionView } from "./SessionView";
import { SettingsView } from "./SettingsView";
import { createdSuffix, Dialog, MoreMenu, relTime, Topbar } from "./ui";
import { ThemePicker } from "./ThemePicker";

type View = { kind: "home" } | { kind: "dataset"; id: string } | { kind: "session"; id: string } | { kind: "settings" };

const isDict = (f: string) => /\.dict\.csv$/i.test(f);
const stem = (f: string) => f.replace(/\.csv$/i, "");

export function Shell({ c, initialKey, desktop = inDesktopShell() }: { c: Client; initialKey: KeyStatus; desktop?: boolean }) {
  // 阶段 6 收尾：桌面壳里导出 PNG 改由后端写进「下载」文件夹（charts/pngSaver.ts）；浏览器模式不注册，照旧 <a download>
  useEffect(() => {
    if (!desktop) return;
    setPngSaver(c.savePng);
    return () => setPngSaver(null);
  }, [c, desktop]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [view, setView] = useState<View>(initialKey.configured ? { kind: "home" } : { kind: "settings" });
  const [key, setKey] = useState(initialKey);
  const [error, setError] = useState("");
  const [uploaded, setUploaded] = useState<DatasetDetail | undefined>(); // 上传响应（带预览）
  // 读取失败的数据集（phase5 V2a §3.1）：列表接口不带 error，只在拿到详情（上传响应、打开详情）后知道
  const [failed, setFailed] = useState<Record<string, string>>({});
  const [railOpen, setRailOpen] = useState(false); // 窄屏：图标条点开的浮层侧栏
  const [collapsed, setCollapsed] = useState(false); // 宽屏下手动收起
  const [pending, setPending] = useState<File[]>([]); // 选好、等确认上传的文件（上传对话框）
  const [pickErr, setPickErr] = useState("");

  // 代际：本地改过任一列表（上传、新建/改名/删除会话）后，在那之前发出的 reload 结果是旧快照，整体丢弃，两个列表一起丢，
  // 不能只丢一边（r4 e2e 偶发：首屏列表还没回来就上传完，新数据集被旧列表冲掉；PR #70 评审：会话侧同源）。
  // 以后 reload 里加第三个列表，同样只在 gen 相等时写；本地写列表的地方都要先 touched()。
  // 入口共 6 处：上传、数据集删除（先 touched 再 reload）、新建/改名/删除会话、SessionView 的 onChanged/onDeleted。
  const listGen = useRef(0);
  const touched = () => void (listGen.current += 1);
  const reload = useCallback(() => {
    const gen = listGen.current;
    return Promise.all([c.datasets(), c.sessions()])
      .then(([d, s]) => {
        if (gen !== listGen.current) return;
        setDatasets(d);
        setSessions(s);
      })
      .catch((e) => {
        if (gen === listGen.current) setError(errText(e)); // 过时请求的失败也不报：列表可能早已刷新成功
      });
  }, [c]);
  useEffect(() => {
    reload();
  }, [reload]);

  // 重名的数据集在名称后追加创建时间（phase5 V2a §1.4），只改显示
  const label = useMemo(() => {
    const n: Record<string, number> = {};
    datasets.forEach((d) => (n[d.name] = (n[d.name] ?? 0) + 1));
    return Object.fromEntries(datasets.map((d) => [d.id, n[d.name] > 1 ? `${d.name} · ${createdSuffix(d.created_at)}` : d.name]));
  }, [datasets]);
  const sessionCount = (dsId: string) => sessions.filter((s) => s.dataset_id === dsId).length;
  const current = view.kind === "session" ? sessions.find((s) => s.id === view.id) : undefined;
  const activeDs = view.kind === "dataset" ? view.id : current?.dataset_id;

  // V2c §3：设置页、数据集页的「← 返回」回到最近一次停留的首页或会话（锚点）。从首页 / 会话离开时记下；
  // 设置 ↔ 数据集之间来回不改锚点。首次启动自动进的设置页没有锚点，不显示返回。锚点会话被删了就回首页。
  const [anchor, setAnchor] = useState<View | null>(null);
  const go = (v: View) => (view.kind === "home" || view.kind === "session" ? setAnchor(view) : null, setView(v), setRailOpen(false));
  const backTo: View | null = !anchor ? null : anchor.kind === "session" && !sessions.some((s) => s.id === anchor.id) ? { kind: "home" } : anchor;
  const onBack = backTo ? () => go(backTo) : undefined;
  const noteDetail = (d: DatasetDetail) =>
    setFailed((f) => {
      const has = d.id in f;
      if (d.error && f[d.id] !== d.error) return { ...f, [d.id]: d.error };
      if (!d.error && has) {
        const g = { ...f };
        delete g[d.id];
        return g;
      }
      return f;
    });

  const newSession = (datasetId: string, agent: Agent) =>
    c.createSession(datasetId, agent).then(
      (s) => (touched(), setSessions((xs) => [s, ...xs]), go({ kind: "session", id: s.id })),
      (e) => setError(errText(e)),
    );
  const onUploaded = (d: DatasetDetail) => (setPending([]), setPickErr(""), setUploaded(d), noteDetail(d), touched(), setDatasets((xs) => [d, ...xs]), go({ kind: "dataset", id: d.id }));
  const renameSession = (id: string, title: string) =>
    c.renameSession(id, title).then(
      (r) => (touched(), setSessions((xs) => xs.map((x) => (x.id === id ? r : x)))),
      (e) => setError(errText(e)),
    );
  const deleteSession = (id: string) =>
    c.deleteSession(id).then(
      () => {
        touched();
        setSessions((xs) => xs.filter((x) => x.id !== id));
        if (view.kind === "session" && view.id === id) setView({ kind: "home" });
      },
      (e) => setError(errText(e)),
    );

  const sidebar = (
    <aside className="sidebar" aria-label="侧栏">
      <div className="brand">
        <span className="brand-logo"><IconSpark size={16} /></span>
        <h1 className="brand-name">datachat</h1>
        <button type="button" className="icon collapse-btn" aria-label="收起侧栏" onClick={() => (setCollapsed(true), setRailOpen(false))}>
          <IconSidebar />
        </button>
      </div>

      <div className="side-head"><span>数据源</span><span className="count">{datasets.length}</span></div>
      <Upload onPick={setPending} err={pickErr} setErr={setPickErr} />
      <nav aria-label="数据集">
        {datasets.length === 0 ? <p className="side-empty">还没有数据集</p> : null}
        <ul className="side-list">
          {datasets.map((d) => {
            const err = failed[d.id];
            const tables = d.files.filter((f) => !isDict(f.filename.toLowerCase()));
            const dicts = d.files.length - tables.length;
            const active = activeDs === d.id;
            return (
              <li key={d.id}>
                <button type="button" className={`ds-row${active ? " active" : ""}${err ? " failed" : ""}`}
                  aria-current={view.kind === "dataset" && view.id === d.id ? "page" : undefined}
                  onClick={() => go({ kind: "dataset", id: d.id })}>
                  <span className="ds-line">
                    <IconTable size={14} />
                    <span className="ds-name">{label[d.id]}</span>
                    {err ? <span className="ds-tag">读取失败</span> : active ? <span className="ds-tag">使用中</span> : null}
                  </span>
                  <span className="ds-meta" style={{ display: "block" }}>
                    {err ? "打开查看原因" : `${tables.length} 个表${dicts ? " · 带字典" : ""}`}
                  </span>
                  {!err && tables.length > 1 ? (
                    <span className="ds-chips">
                      {tables.map((f) => <span key={f.filename} className="ds-chip">{stem(f.filename)}</span>)}
                    </span>
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="side-sep" />
      <nav aria-label="会话">
        <div className="side-head"><span>会话</span><span className="count">{sessions.length}</span></div>
        {sessions.length === 0 ? <p className="side-empty">还没有会话</p> : null}
        <ul className="side-list">
          {sessions.map((s) => (
            <SessionRow key={s.id} s={s} active={view.kind === "session" && view.id === s.id} dsName={label[s.dataset_id] ?? ""}
              onOpen={() => go({ kind: "session", id: s.id })} onRename={(t) => renameSession(s.id, t)} onDelete={() => deleteSession(s.id)} />
          ))}
        </ul>
      </nav>

      <div className="side-spacer" />
      <div className="side-foot">
        <button type="button" className={`nav-row${view.kind === "settings" ? " active" : ""}`} onClick={() => go({ kind: "settings" })}>
          <IconGear />
          设置
          {key.configured ? null : <span className="badge-dot" aria-label="未设置 Key" />}
        </button>
      </div>
    </aside>
  );

  return (
    <div className={`shell${collapsed ? " collapsed" : ""}${railOpen ? " rail-open" : ""}`} data-testid="ready">
      <nav className="rail" aria-label="快捷导航">
        <button type="button" className="brand-logo rail-logo" aria-label="展开侧栏" onClick={() => (collapsed ? setCollapsed(false) : setRailOpen(!railOpen))}>
          <IconSpark size={16} />
        </button>
        <button type="button" className={`icon${view.kind === "dataset" ? " on" : ""}`} aria-label="数据集" onClick={() => setRailOpen(true)}><IconTable /></button>
        <button type="button" className={`icon${view.kind === "session" ? " on" : ""}`} aria-label="会话列表" onClick={() => setRailOpen(true)}><IconChat /></button>
        <span className="side-spacer" />
        <button type="button" className={`icon${view.kind === "settings" ? " on" : ""}`} aria-label="打开设置" onClick={() => go({ kind: "settings" })}><IconGear /></button>
      </nav>
      {sidebar}
      {railOpen ? <div className="rail-scrim" onClick={() => setRailOpen(false)} /> : null}

      <section className="workspace">
        {error && (
          <p className="toast" role="alert">
            {error}{" "}
            <button type="button" className="link" onClick={() => setError("")}>关闭</button>
          </p>
        )}
        {view.kind === "home" && <Home empty={datasets.length === 0} onPick={setPending} />}
        {view.kind === "dataset" && (
          <DatasetView
            key={view.id}
            c={c}
            id={view.id}
            initial={uploaded}
            displayName={label[view.id]}
            sessionCount={sessionCount(view.id)}
            onLoaded={noteDetail}
            onBack={onBack}
            onNewSession={newSession}
            onDeleted={() => (touched(), setView({ kind: "home" }), reload())} // 先作废更早在飞的 reload，免得删掉的数据集被旧快照带回来
          />
        )}
        {view.kind === "session" && (
          <SessionView
            key={view.id}
            c={c}
            id={view.id}
            datasetName={label[current?.dataset_id ?? ""] ?? ""}
            title={current?.title}
            keyConfigured={key.configured}
            onGoSettings={() => go({ kind: "settings" })}
            onChanged={(s) => (touched(), setSessions((xs) => xs.map((x) => (x.id === s.id ? s : x))))}
            onDeleted={() => (touched(), setView({ kind: "home" }), setSessions((xs) => xs.filter((x) => x.id !== view.id)))}
          />
        )}
        {view.kind === "settings" && <SettingsView c={c} onKeyChange={setKey} onBack={onBack} />}
      </section>
      <UploadDialog key={pending.map((f) => f.name).join("|")} c={c} files={pending} onClose={() => setPending([])} onDone={onUploaded} />
    </div>
  );
}

function SessionRow({ s, active, dsName, onOpen, onRename, onDelete }: {
  s: Session; active: boolean; dsName: string; onOpen: () => void; onRename: (t: string) => void; onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(s.title);
  const [confirm, setConfirm] = useState(false);
  const title = s.title || "未命名会话";
  const save = () => {
    setEditing(false);
    const t = draft.trim();
    if (t && t !== s.title) onRename(t);
  };
  return (
    <li className="sess-item">
      {editing ? (
        <div className="sess-edit">
          <input aria-label="重命名会话" autoFocus value={draft} maxLength={24}
            onChange={(e) => setDraft(e.target.value)} onBlur={save}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
              if (e.key === "Escape") {
                setDraft(s.title);
                setEditing(false);
              }
            }} />
          <span className="hint"><span>Enter 保存 · Esc 取消</span><span>{draft.length}/24</span></span>
        </div>
      ) : (
        <>
          <button type="button" className={`sess-row${active ? " active" : ""}`} aria-current={active ? "page" : undefined}
            onClick={onOpen} onDoubleClick={() => (setDraft(s.title), setEditing(true))}>
            <span className="sess-title">{title}</span>
            <span className="sess-meta">{dsName}{dsName ? " · " : ""}{relTime(s.updated_at)}</span>
          </button>
          <MoreMenu label="更多操作" className="sess-more" align="left" items={[
            { label: "重命名", onClick: () => (setDraft(s.title), setEditing(true)) },
            { label: "删除", onClick: () => setConfirm(true), danger: true },
          ]} />
        </>
      )}
      {confirm ? (
        <div className="popconfirm" role="alertdialog" aria-label={`删除「${title}」`}>
          <h3>删除这个会话？</h3>
          <p>「{title}」的对话记录会一起删除。{dsName ? `${dsName} 和表里的数据不受影响。` : "数据集不受影响。"}</p>
          <div className="dialog-actions">
            <button type="button" onClick={() => setConfirm(false)} autoFocus>取消</button>
            <button type="button" className="destroy" onClick={() => (setConfirm(false), onDelete())}>删除</button>
          </div>
        </div>
      ) : null}
    </li>
  );
}

const MAX = 1024 ** 3; // 与后端 MAX_FILE_BYTES 一致（app.py），前端只做提示，后端仍会拒

/** 选中的文件先过前端检查：非 .csv、超过 1 GB 直接拦下（后端仍会再拒一次）。返回错误文案或 null。 */
function checkFiles(list: File[]): string | null {
  const bad = list.filter((f) => !/\.csv$/i.test(f.name));
  if (bad.length) return `只支持 .csv；${bad.map((f) => f.name).join("、")} 不支持`;
  const huge = list.find((f) => f.size > MAX);
  if (huge) return `${huge.name} 超过 1 GB`;
  return null;
}

/** 侧栏上传区（phase5 V2a §1.2、§6）：点击或拖放选文件，交给上传对话框；被拦下的原因显示在卡片下面。 */
function Upload({ onPick, err, setErr }: { onPick: (f: File[]) => void; err: string; setErr: (s: string) => void }) {
  const [drag, setDrag] = useState(false);
  const pick = (list: File[]) => {
    if (!list.length) return;
    const e = checkFiles(list);
    setErr(e ?? "");
    if (!e) onPick(list);
  };
  return (
    <div className="upload">
      <label className={`upload-zone${drag ? " drag" : ""}${err ? " error" : ""}`} data-testid="upload-zone"
        onDragOver={(e) => (e.preventDefault(), setDrag(true))} onDragLeave={() => setDrag(false)}
        onDrop={(e: DragEvent) => (e.preventDefault(), setDrag(false), pick(Array.from(e.dataTransfer.files)))}>
        <span className="upload-icon"><IconUpload size={15} /></span>
        <span className="upload-text">
          <span className="upload-main">拖入文件或点击上传</span>
          <span className="upload-sub">仅 CSV，单个文件不超过 1 GB</span>
        </span>
        <input type="file" accept=".csv" multiple aria-label="选择 CSV 文件"
          onChange={(e) => (pick(Array.from(e.target.files ?? [])), (e.target.value = ""))} />
      </label>
      {err ? <p className="upload-err" role="alert">{err}</p> : null}
    </div>
  );
}

/** 上传对话框（验收 P2-36/37/38）：两个入口选的文件都到这里，名称、文件清单、进度都在一处，不挤在侧栏里。 */
function UploadDialog({ c, files, onClose, onDone }: { c: Client; files: File[]; onClose: () => void; onDone: (d: DatasetDetail) => void }) {
  const [name, setName] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const busy = progress !== null;
  const submit = () => {
    if (busy) return;
    setErr("");
    setProgress(0);
    c.upload(files, name.trim(), (p) => setProgress(p))
      .then((d) => (setName(""), onDone(d)), (e) => setErr(uploadErr(e)))
      .finally(() => setProgress(null));
  };
  return (
    <Dialog open={files.length > 0} onClose={() => !busy && onClose()} label="上传数据集">
      <form className="upload-dialog" onSubmit={(e) => (e.preventDefault(), submit())}>
        <div className="dialog-icon"><IconUpload size={18} /></div>
        <h2>上传 {files.length} 个文件</h2>
        <p>多张表会放在同一个数据集里；文件名以 .dict.csv 结尾的会当作数据字典。</p>
        {/* THREAT_MODEL §4 (a)（阶段 6 D2）：常驻一行，不做弹窗、不做「不再提示」 */}
        <p className="small muted" data-testid="upload-trust">只分析你自己的数据。不要加载来路不明的 CSV：表里的内容会被模型读到。</p>
        <ul>
          {files.map((f) => (
            <li key={f.name}><IconTable size={13} />{f.name}<span className="size">{formatSize(f.size)}</span></li>
          ))}
        </ul>
        <label>
          数据集名称
          <input placeholder="数据集名称（可选）" value={name} maxLength={100} autoFocus onChange={(e) => setName(e.target.value)} />
        </label>
        {busy ? (
          <>
            <div className="upload-progress" aria-label="上传进度"><i style={{ width: `${Math.round(progress! * 100)}%` }} /></div>
            <p className="small muted" style={{ marginTop: 6 }}>{progress! < 1 ? `上传中 ${Math.round(progress! * 100)}%` : "上传完成，正在读取…"}</p>
          </>
        ) : null}
        {err ? <p className="upload-err" role="alert" style={{ marginTop: 10 }}>{err}</p> : null}
        <div className="dialog-actions">
          <button type="button" disabled={busy} onClick={onClose}>取消</button>
          <button type="submit" className="primary" disabled={busy}>{busy ? "上传中…" : "上传"}</button>
        </div>
      </form>
    </Dialog>
  );
}

function uploadErr(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 413) return `上传失败：文件太大（${e.detail}）`;
    return `上传失败：${e.detail}`;
  }
  return `上传失败：${errText(e)}`;
}

/** 首屏（phase5 V2a §7）。有数据集时换一句引导。 */
function Home({ empty, onPick }: { empty: boolean; onPick: (f: File[]) => void }) {
  return (
    <>
      <Topbar title="新会话" sub={empty ? "上传一个数据集开始分析" : "选择一个数据集开始分析"} actions={<ThemePicker />} />
      <div className="main">
        <div className="empty">
          <h2>把表丢进来，直接问</h2>
          <p className="lead">读表、写代码、出图，一条提问跑完。数据不出本地。</p>
          <HeroUpload onPick={onPick} />
          <p className="tip">
            {empty ? "可多选：多张表一起上传，或者加上 *.dict.csv 作数据字典" : "或者在左侧选一个数据集，新建会话后提问"}
          </p>
        </div>
      </div>
      <div className="composer-wrap">
        <div className="composer disabled">
          <textarea aria-label="提问" disabled placeholder={empty ? "上传数据集后即可提问…" : "先选择一个数据集…"} rows={1} />
          <div className="composer-row">
            <span className="ctx-pill"><span>未选择数据源</span></span>
            <button type="button" className="send primary" disabled>发送</button>
          </div>
        </div>
      </div>
    </>
  );
}

function HeroUpload({ onPick }: { onPick: (f: File[]) => void }) {
  const [drag, setDrag] = useState(false);
  const [err, setErr] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const send = (list: File[]) => {
    if (!list.length) return;
    const e = checkFiles(list);
    setErr(e ?? "");
    if (!e) onPick(list);
  };
  return (
    <div className={`empty-card${drag ? " drag" : ""}`} onDragOver={(e) => (e.preventDefault(), setDrag(true))}
      onDragLeave={() => setDrag(false)} onDrop={(e) => (e.preventDefault(), setDrag(false), send(Array.from(e.dataTransfer.files)))}>
      <span className="upload-icon"><IconUpload size={18} /></span>
      <span className="em-main">拖入文件到此处</span>
      <span className="em-sub">CSV · 可多选 · 单个文件不超过 1 GB</span>
      <button type="button" className="primary" onClick={() => input.current?.click()}>
        <IconPlus size={13} />选择文件
      </button>
      <input ref={input} type="file" accept=".csv" multiple hidden aria-label="选择文件（首屏）"
        onChange={(e) => (send(Array.from(e.target.files ?? [])), (e.target.value = ""))} />
      {err ? <p className="upload-err" role="alert">{err}</p> : null}
    </div>
  );
}
