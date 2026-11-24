/** 阶段 7.6 U5：会话标题的编辑规则，侧栏（Shell.tsx SessionRow）和会话页（SessionView.tsx 标题框）共用这一份。
 *  §4 已定 3：清空 = 还原自动标题。两处都可以提交空串，后端 PATCH 收到空串时用该会话的第一问重新生成（app/server/titles.py）。
 *  返回 null = 不发请求（没改）；否则返回要提交的标题（trim 过，可能是空串）。 */
export function titleEdit(draft: string, current: string): string | null {
  const t = draft.trim();
  return t === current ? null : t;
}

/** X-Session-Title 响应头（百分号编码，HTTP 头只能是 latin-1）→ 标题；没有这个头时 null。 */
export function decodeTitleHeader(raw: string | null): string | null {
  if (raw === null) return null;
  try {
    return decodeURIComponent(raw);
  } catch {
    return null; // 编码坏了就当没给，流结束后再从库里同步
  }
}
