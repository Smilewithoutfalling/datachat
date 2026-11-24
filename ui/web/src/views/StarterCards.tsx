import type { DatasetProfile } from "../types";
import { IconTable } from "./icons";
import "./starter.css";

// 阶段 7.6 U4 空态卡（docs/roadmap/phase76-ui.md §2 U4、§2.1 Folio 一行）：有数据集时首页按「问候 → 数据资产 → 三张提问卡」排。
// 三张卡点了都真实发出一句提问：复用 POST /sessions 建会话 + POST /sessions/{id}/messages 的现有提问链路（E1），不另开接口。
// 不放点了没反应的入口（phase76 §3）：资产区没有概要时给「剖析」，它真实读一遍文件（U2 同一个 GET /datasets/{id}）。
// 样式只在 starter.css（以后 rebase 到新 U2 上少冲突）；字号用 U1 的 --fs-* 变量，带回退值。

export type Starter = { id: "overview" | "outliers" | "compare"; title: string; desc: string; question: string };

/** 三张卡：标题是卡面上的字，question 是点了之后真实发出去的那句话（会话标题由后端按本地规则从它生成，见 app/server/titles.py：取第一个分句）。 */
export const STARTERS: readonly Starter[] = [
  {
    id: "overview",
    title: "看看这份数据有什么",
    desc: "表、字段、覆盖范围，先摸个底",
    question: "看看这份数据有什么：有哪些表和字段、各列大概是什么意思、覆盖的范围，先给我一个整体概览。",
  },
  {
    id: "outliers",
    title: "找出异常值",
    desc: "哪些数明显偏离，落在哪几行",
    question: "找出这份数据里的异常值：哪些数值列有明显偏离的值，具体是哪几行，可能是什么原因。",
  },
  {
    id: "compare",
    title: "两期对比",
    desc: "最近两期，关键指标变了多少",
    question: "做一个两期对比：按时间取最近的两期，对比关键指标的变化，并说明变化最大的是哪些。",
  },
] as const;

/** 问候语按本地时段（凌晨也算晚上，免得「早上好」出现在 2 点）。 */
export function greeting(now: Date = new Date()): string {
  const h = now.getHours();
  if (h >= 5 && h < 11) return "早上好";
  if (h >= 11 && h < 13) return "中午好";
  if (h >= 13 && h < 18) return "下午好";
  return "晚上好";
}

/** 资产区的一行概要。数字全部来自 profile（和 U2 侧栏卡同一来源），没有 profile 就不编。 */
export function assetLine(p: DatasetProfile): string {
  const parts = [`${p.table_count} 个表`, `${p.rows.toLocaleString()} 行`, `${p.columns} 列`, p.missing_columns ? `${p.missing_columns} 列有缺失` : "无缺失列"];
  return parts.join(" · ");
}

export function StarterHome({ name, profile, tableCount, now, busy, profiling, onAsk, onProfile, onOpen }: {
  name: string; // 数据集显示名（重名时带创建时间，Shell 的 label）
  profile?: DatasetProfile;
  tableCount: number; // 没有 profile 时用文件清单数出来的表数
  now?: Date;
  busy?: boolean; // 正在建会话：三张卡一起禁用，免得连点建出两个会话
  profiling?: boolean;
  onAsk: (question: string) => void;
  onProfile: () => void;
  onOpen: () => void; // 打开数据集页（预览、口径）
}) {
  return (
    <div className="starter" data-testid="starter-home">
      <header className="starter-hello">
        <h2>{greeting(now)}</h2>
        <p>数据已经就绪。从下面挑一个问题开始，或者新建会话自己问。</p>
      </header>

      <section className="starter-asset" aria-label="数据资产" data-testid="starter-asset">
        <div className="starter-asset-head">
          <span className="starter-asset-icon"><IconTable size={14} /></span>
          <span className="starter-asset-name" data-testid="starter-asset-name" title={name}>{name}</span>
          <span className="starter-tag">使用中</span>
          {/* 名字不做成按钮：侧栏数据集条目已是同名按钮，按名字找按钮的地方会撞（views.test 的 /^销量/） */}
          <button type="button" className="link starter-open" aria-label={`打开数据集「${name}」`} onClick={onOpen}>打开</button>
        </div>
        {profile ? (
          <div className="starter-asset-body">
            <span data-testid="starter-asset-line">{assetLine(profile)}</span>
            <span className="starter-aux">{profile.time_range ? `${profile.time_range.min} ~ ${profile.time_range.max}` : "没有日期列"}</span>
          </div>
        ) : (
          <div className="starter-asset-body">
            <span data-testid="starter-asset-line">{tableCount} 个表 · 还没读取概要</span>
            <button type="button" className="link" disabled={profiling} onClick={onProfile}>{profiling ? "剖析中…" : "剖析"}</button>
          </div>
        )}
      </section>

      <ul className="starter-cards" aria-label="提问卡">
        {STARTERS.map((s) => (
          <li key={s.id}>
            <button type="button" className="starter-card" data-testid={`starter-${s.id}`} disabled={busy} title={s.question}
              onClick={() => onAsk(s.question)}>
              <span className="starter-card-title">{s.title}</span>
              <span className="starter-card-desc">{s.desc}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
