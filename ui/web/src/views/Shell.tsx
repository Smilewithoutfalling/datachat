import { type DragEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../api";
import { setPngSaver } from "../charts/pngSaver";
import { inDesktopShell, UPDATE_POLL_MS, UPDATE_URL } from "../desktop";
import { exportPng } from "../charts/exportPng";
import { type ChartInput, DEFAULT_UI } from "../charts/prepare";
import { getChartTheme } from "../charts/themes";
import { type Client, errText, formatSize } from "../client";
import { titleEdit } from "../titles";
import type { Agent, Dataset, DatasetDetail, DatasetProfile, KeyStatus, Session, SessionDetail } from "../types";
import { DatasetView } from "./DatasetView";
import { GenieHome } from "./GenieHome";
import { IconChat, IconDownload, IconGear, IconHome, IconPencil, IconPlus, IconSidebar, IconSpark, IconTable, IconTrash, IconUpload } from "./icons";
import { SessionView } from "./SessionView";
import { SettingsView } from "./SettingsView";
import { createdSuffix, Dialog, MoreMenu, relTime, Topbar } from "./ui";

type View = { kind: "home" } | { kind: "datasets" } | { kind: "dataset"; id: string; focus?: "notes" } | { kind: "session"; id: string } | { kind: "settings" };

const isDict = (f: string) => /\.dict\.csv$/i.test(f);
const stem = (f: string) => f.replace(/\.(csv|xlsx)$/i, "");

export function Shell({ c, initialKey, desktop = inDesktopShell() }: { c: Client; initialKey: KeyStatus; desktop?: boolean }) {
  // 阶段 6 收尾：桌面壳里导出 PNG 改由后端写进「下载」文件夹（charts/pngSaver.ts）；浏览器模式不注册，照旧 <a download>
  useEffect(() => {
    if (!desktop) return;
    setPngSaver(c.savePng);
    return () => setPngSaver(null);
  }, [c, desktop]);
  // 阶段 6 D3（#149）：壳启动 10 秒后查更新，查到就告诉后端；这里每分钟问一次后端，有了就在顶部提示，点了才更新。
  // 不静默更新（phase6 §4 第 1 条，S 11-27 确认「提示后点一下」）。请求失败（旧后端 404 等）不打扰用户。
  const [update, setUpdate] = useState<{ version: string; notes: string } | null>(null);
  useEffect(() => {
    if (!desktop) return;
    let alive = true;
    const poll = () =>
      c.desktopUpdate()
        .then((r) => alive && r.available && setUpdate(r.available))
        .catch(() => undefined);
    poll();
    const t = window.setInterval(poll, UPDATE_POLL_MS);
    return () => ((alive = false), window.clearInterval(t));
  }, [c, desktop]);
  const [updating, setUpdating] = useState(false);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [view, setView] = useState<View>(initialKey.configured ? { kind: "home" } : { kind: "settings" });
  const [key, setKey] = useState(initialKey);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    if (!notice) return;
    const t = window.setTimeout(() => setNotice(""), 6000);
    return () => window.clearTimeout(t);
  }, [notice]);
  const [error, setError] = useState("");
  const [uploaded, setUploaded] = useState<DatasetDetail | undefined>(); // 上传响应（带预览）
  // 读取失败的数据集（phase5 V2a §3.1）：列表接口不带 error，只在拿到详情（上传响应、打开详情）后知道
  const [failed, setFailed] = useState<Record<string, string>>({});
  // 阶段 7.6 U2 数据资产卡：只用已经拿到的详情（上传响应、打开数据集页、点「剖析」）里的 profile。
  // 列表接口不读文件，这里也不为侧栏逐个去读（F1.1「每个文件只读一遍」）；没拿到之前卡片写明「点剖析读取概要」。
  const [profiles, setProfiles] = useState<Record<string, DatasetProfile>>({});
  const [profiling, setProfiling] = useState<string | null>(null);
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
  const noteDetail = (d: DatasetDetail) => (
    d.profile ? setProfiles((p) => ({ ...p, [d.id]: d.profile! })) : undefined,
    setFailed((f) => {
      const has = d.id in f;
      if (d.error && f[d.id] !== d.error) return { ...f, [d.id]: d.error };
      if (!d.error && has) {
        const g = { ...f };
        delete g[d.id];
        return g;
      }
      return f;
    })
  );
  // 「剖析」：GET /datasets/{id}（不带 rows）真实读一遍文件，拿回概要填进卡片；读坏了照旧进 failed
  const profileDataset = (id: string) => (
    setProfiling(id),
    c.datasetProfile(id)
      .then(noteDetail, (e) => setError(errText(e)))
      .finally(() => setProfiling((x) => (x === id ? null : x)))
  );

  // 阶段 7.6 U4：首页提问卡。建会话（POST /sessions）后把这句话交给 SessionView，由它走现有提问链路发出去（E1）
  const [starterAsk, setStarterAsk] = useState<{ session: string; question: string } | null>(null);
  const [starting, setStarting] = useState(false);
  const askStarter = (datasetId: string, question: string) => (
    setStarting(true),
    c.createSession(datasetId, "workflow")
      .then((s) => (touched(), setSessions((xs) => [s, ...xs]), setStarterAsk({ session: s.id, question }), go({ kind: "session", id: s.id })),
        (e) => setError(errText(e)))
      .finally(() => setStarting(false))
  );
  
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

  const dsCard = (d: Dataset) => {
            const err = failed[d.id];
            const tables = d.files.filter((f) => !isDict(f.filename.toLowerCase()));
            const dicts = d.files.length - tables.length;
            const active = activeDs === d.id;
            const p = profiles[d.id];
            const tableCount = p ? p.table_count : tables.length;
            const fileName = tables.length === 1 ? tables[0].filename : "";
            return (
              <li key={d.id} className={`ds-card${active ? " active" : ""}${err ? " failed" : ""}`} data-testid="asset-card">
                <button type="button" className={`ds-row${active ? " active" : ""}${err ? " failed" : ""}`}
                  aria-current={view.kind === "dataset" && view.id === d.id ? "page" : undefined}
                  onClick={() => go({ kind: "dataset", id: d.id })}>
                  <span className="ds-line">
                    <IconTable size={14} />
                    <span className="ds-name">{label[d.id]}</span>
                    {err ? <span className="ds-tag">读取失败</span> : active ? <span className="ds-tag">使用中</span> : null}
                  </span>
                  <span className="ds-meta" style={{ display: "block" }}>
                    {err ? "打开查看原因" : `${tableCount} 个表${dicts ? " · 带字典" : ""}`}
                  </span>
                  {!err && tables.length > 1 ? (
                    <span className="ds-chips">
                      {tables.map((f) => <span key={f.filename} className="ds-chip">{stem(f.filename)}</span>)}
                    </span>
                  ) : null}
                  {!err && fileName && fileName !== label[d.id] ? (
                    <span className="ds-chips"><span className="ds-chip" title={fileName}>{fileName}</span></span>
                  ) : null}
                </button>
                {err ? null : (
                  <>
                    {/* 阶段 7.6 U2：卡片上的每个数字都来自 GET /datasets/{id} 的 profile（u2-asset-card.test.tsx 钉住） */}
                    <div className="ds-stats ds-meta" data-testid="asset-stats">
                      {p ? (
                        <>
                          <span>{p.rows.toLocaleString()} 行 · {p.columns} 列 · {p.missing_columns ? `${p.missing_columns} 列有缺失` : "无缺失列"}</span>
                          <span>{p.time_range ? `${p.time_range.min} ~ ${p.time_range.max}` : "没有日期列"}</span>
                        </>
                      ) : (
                        <span>还没读取概要，点「剖析」</span>
                      )}
                    </div>
                    <div className="ds-actions">
                      <button type="button" className="link" aria-label={`剖析「${label[d.id]}」`} disabled={profiling === d.id}
                        onClick={() => profileDataset(d.id)}>
                        {profiling === d.id ? "剖析中…" : "剖析"}
                      </button>
                      <button type="button" className="link" aria-label={`就「${label[d.id]}」提问`} onClick={() => newSession(d.id, "workflow")}>
                        提问
                      </button>
                      <button type="button" className="link" aria-label={`「${label[d.id]}」的口径导入导出`} title="口径与规则的导入、导出"
                        onClick={() => go({ kind: "dataset", id: d.id, focus: "notes" })}>
                        口径
                      </button>
                    </div>
                  </>
                )}
              </li>
            );
  };

  const pickSide = (list: File[]) => {
    if (!list.length) return;
    const e = checkFiles(list);
    if (e) return setError(e);
    setError("");
    onPick(list);
  };
  const onPick = setPending;
  const sideInput = useRef<HTMLInputElement>(null);
  const inDatasets = view.kind === "datasets" || view.kind === "dataset";

  // 原型（proto/genie-shell）：侧栏参考 Genie——上面是固定入口（首页 / 数据集 / 上传），中间「新对话」+ 对话列表，底部设置。
  // 数据集卡片从侧栏挪到「数据集」页，侧栏只留对话，像聊天软件的会话列表。
  const sidebar = (
    <aside className="sidebar g-side" aria-label="侧栏">
      <div className="brand">
        <span className="brand-logo"><IconSpark size={16} /></span>
        <h1 className="brand-name">datachat</h1>
        <button type="button" className="icon collapse-btn" aria-label="收起侧栏" onClick={() => (setCollapsed(true), setRailOpen(false))}>
          <IconSidebar />
        </button>
      </div>

      <nav className="g-nav" aria-label="主导航">
        <button type="button" className={`nav-row${view.kind === "home" ? " active" : ""}`} aria-current={view.kind === "home" ? "page" : undefined}
          onClick={() => go({ kind: "home" })}><IconHome />首页</button>
        <button type="button" className={`nav-row${inDatasets ? " active" : ""}`} onClick={() => go({ kind: "datasets" })}>
          <IconTable />数据集<span className="g-count">{datasets.length}</span>
        </button>
        <button type="button" className="nav-row" onClick={() => sideInput.current?.click()}><IconUpload />上传数据</button>
        <input ref={sideInput} type="file" accept=".csv,.xlsx" multiple hidden aria-label="选择 CSV 文件"
          onChange={(e) => (pickSide(Array.from(e.target.files ?? [])), (e.target.value = ""))} />
      </nav>

      <button type="button" className="g-new" onClick={() => go({ kind: "home" })}><IconPlus size={14} />新对话</button>

      <nav aria-label="会话" className="g-chats">
        <div className="side-head"><span>对话</span><span className="count">{sessions.length}</span></div>
        {sessions.length === 0 ? <p className="side-empty">还没有对话</p> : null}
        <ul className="side-list">
          {sessions.map((s) => (
            <SessionRow key={s.id} s={s} active={view.kind === "session" && view.id === s.id} dsName={label[s.dataset_id] ?? ""}
              onOpen={() => go({ kind: "session", id: s.id })} onRename={(t) => renameSession(s.id, t)} onDelete={() => deleteSession(s.id)}
              onExport={() => exportSession(c, s.id).then(setNotice, (e) => setNotice(`导出失败：${errText(e)}`))} />
          ))}
        </ul>
      </nav>

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
        <button type="button" className={`icon${inDatasets ? " on" : ""}`} aria-label="数据集" onClick={() => go({ kind: "datasets" })}><IconTable /></button>
        <button type="button" className={`icon${view.kind === "session" ? " on" : ""}`} aria-label="会话列表" onClick={() => setRailOpen(true)}><IconChat /></button>
        <span className="side-spacer" />
        <button type="button" className={`icon${view.kind === "settings" ? " on" : ""}`} aria-label="打开设置" onClick={() => go({ kind: "settings" })}><IconGear /></button>
      </nav>
      {sidebar}
      {railOpen ? <div className="rail-scrim" onClick={() => setRailOpen(false)} /> : null}

      <section className="workspace">
        {update && (
          <p className="update-bar" role="status" data-testid="update-bar">
            有新版本 {update.version}，更新后会自动重启，数据和会话都会保留。{" "}
            <button type="button" className="primary" disabled={updating}
              onClick={() => (setUpdating(true), window.location.assign(UPDATE_URL))}>
              {updating ? "正在准备更新…" : "更新并重启"}
            </button>
          </p>
        )}
        {error && (
          <p className="toast" role="alert">
            {error}{" "}
            <button type="button" className="link" onClick={() => setError("")}>关闭</button>
          </p>
        )}
        {view.kind === "home" && (
          <div className="main g-main">
            <GenieHome datasets={datasets.filter((d) => !failed[d.id])} label={label} profiles={profiles} sessions={sessions} busy={starting}
              upload={<HeroUpload onPick={setPending} />}
              onAsk={askStarter} onOpenSession={(id) => go({ kind: "session", id })} onOpenDataset={(id) => go({ kind: "dataset", id })}
              onAllDatasets={() => go({ kind: "datasets" })} />
          </div>
        )}
        {view.kind === "datasets" && (
          <>
            <Topbar title="数据集" sub={`${datasets.length} 个数据集`} />
            <div className="main">
              <div className="g-ds-page">
                <Upload onPick={setPending} err={pickErr} setErr={setPickErr} />
                {datasets.length === 0 ? <p className="g-empty">还没有数据集，先上传一份 CSV 或 Excel。</p> : (
                  <nav aria-label="数据集"><ul className="g-ds-grid">{datasets.map(dsCard)}</ul></nav>
                )}
              </div>
            </div>
          </>
        )}
        {view.kind === "dataset" && (
          <DatasetView
            key={view.id}
            focusNotes={view.focus === "notes"}
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
            initialQuestion={starterAsk?.session === view.id ? starterAsk.question : undefined}
            onInitialAsked={() => setStarterAsk(null)}
            onGoSettings={() => go({ kind: "settings" })}
            onChanged={(s) => (touched(), setSessions((xs) => xs.map((x) => (x.id === s.id ? s : x))))}
            onDeleted={() => (touched(), setView({ kind: "home" }), setSessions((xs) => xs.filter((x) => x.id !== view.id)))}
          />
        )}
        {view.kind === "settings" && <SettingsView c={c} onKeyChange={setKey} onBack={onBack} />}
      </section>
      {notice ? <div className="g-toast" role="status">{notice}</div> : null}
      <UploadDialog key={pending.map((f) => f.name).join("|")} c={c} files={pending} onClose={() => setPending([])} onDone={onUploaded} />
    </div>
  );
}

const parseIso = (iso: string) => Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
const fullTime = (iso: string) => {
  const t = parseIso(iso);
  if (!Number.isFinite(t)) return "";
  const d = new Date(t), z = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}/${z(d.getMonth() + 1)}/${z(d.getDate())} ${z(d.getHours())}:${z(d.getMinutes())}`;
};

/** 导出整段会话：ECharts 图用与屏幕同一条 prepare 离屏渲染成 PNG，连同会话交给后端拼成自包含 HTML。
 *  桌面壳里后端直接写进「下载」文件夹（WebView2 里 <a download> 不生效），浏览器里拿文件触发下载。返回给用户看的一句话。 */
async function exportSession(c: Client, id: string): Promise<string> {
  const d: SessionDetail = await c.session(id);
  const charts: Record<string, Record<string, string>> = {};
  const theme = getChartTheme();
  for (const m of d.messages) {
    const list = (m.result as { charts?: { png: string | null; option: unknown }[] } | null)?.charts ?? [];
    list.forEach((ch, i) => {
      if (ch.png || !ch.option) return;
      try {
        (charts[m.id] ??= {})[String(i)] = exportPng(ch.option as ChartInput, DEFAULT_UI, theme, { width: 960, height: 540 });
      } catch { /* 这一张交给后端标成「未能导出」 */ }
    });
  }
  if (inDesktopShell()) {
    const r = await c.exportSessionToDisk(id, charts);
    return `已导出到 ${r.path}`;
  }
  const blob = await c.exportSessionFile(id, charts);
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: `${(d.title || "会话").replace(/[\\/:*?"<>|]/g, "_")}.html` });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return "已导出为 HTML";
}

function SessionRow({ s, active, dsName, onOpen, onRename, onDelete, onExport }: {
  s: Session; active: boolean; dsName: string; onOpen: () => void; onRename: (t: string) => void; onDelete: () => void; onExport: () => void;
}) {
  const [tip, setTip] = useState<{ top: number; left: number } | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const showTip = (el: HTMLElement) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      if (window.innerWidth < 720) return; // 窄屏侧栏是抽屉，卡片没地方放
      const r = el.getBoundingClientRect();
      setTip({ top: r.top, left: r.right + 12 });
    }, 450);
  };
  const hideTip = () => (window.clearTimeout(timer.current), setTip(null));
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(s.title);
  const [confirm, setConfirm] = useState(false);
  const title = s.title || "未命名会话";
  const save = () => {
    setEditing(false);
    const t = titleEdit(draft, s.title); // U5：与会话页同一条规则，空串 = 还原自动标题（以前侧栏拦了空串，会话页不拦）
    if (t !== null) onRename(t);
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
            onClick={() => (hideTip(), onOpen())} onDoubleClick={() => (setDraft(s.title), setEditing(true))}
            onMouseEnter={(e) => showTip(e.currentTarget)} onMouseLeave={hideTip} onFocus={hideTip}>
            <span className="sess-title">{title}</span>
            <span className="sess-meta">{dsName}{dsName ? " · " : ""}{relTime(s.updated_at)}</span>
          </button>
          <MoreMenu label="更多操作" className="sess-more" align="left" items={[
            { label: "重命名", icon: <IconPencil size={14} />, onClick: () => (setDraft(s.title), setEditing(true)) },
            { label: "导出", icon: <IconDownload size={14} />, onClick: onExport },
            { label: "删除会话", icon: <IconTrash size={14} />, onClick: () => setConfirm(true), danger: true },
          ]} />
          {tip ? (
            <div className="sess-tip" role="tooltip" style={{ top: tip.top, left: tip.left }}>
              <strong>{title}</strong>
              <span>{dsName || "数据集已删除"}</span>
              {active ? <span className="sess-tip-now">当前会话</span> : null}
              <span>创建 {fullTime(s.created_at)}</span>
              <span>更新 {relTime(s.updated_at)}</span>
            </div>
          ) : null}
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

/** 选中的文件先过前端检查：非 .csv / .xlsx、超过 1 GB 直接拦下（后端仍会再拒一次；xlsx 解压后体积只有后端能判）。
 *  文案上的「Excel 解压后不超过 300 MB」对应后端 excel_io.MAX_XLSX_UNCOMPRESSED_BYTES（按解压后体积判），前端不拦。
 *  返回错误文案或 null。 */
function checkFiles(list: File[]): string | null {
  const xls = list.filter((f) => /\.xls$/i.test(f.name));
  if (xls.length) return `不支持旧版 .xls：${xls.map((f) => f.name).join("、")}，请在 Excel 里另存为 .xlsx 或 CSV`;
  const bad = list.filter((f) => !/\.(csv|xlsx)$/i.test(f.name));
  if (bad.length) return `只支持 .csv 和 .xlsx；${bad.map((f) => f.name).join("、")} 不支持`;
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
          <span className="upload-sub">CSV 不超过 1 GB，Excel 解压后不超过 300 MB</span>
        </span>
        <input type="file" accept=".csv,.xlsx" multiple aria-label="选择 CSV 文件"
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
      <span className="em-sub">CSV 不超过 1 GB · Excel 解压后不超过 300 MB · 可多选</span>
      <button type="button" className="primary" onClick={() => input.current?.click()}>
        <IconPlus size={13} />选择文件
      </button>
      <input ref={input} type="file" accept=".csv,.xlsx" multiple hidden aria-label="选择文件（首屏）"
        onChange={(e) => (send(Array.from(e.target.files ?? [])), (e.target.value = ""))} />
      {err ? <p className="upload-err" role="alert">{err}</p> : null}
    </div>
  );
}
