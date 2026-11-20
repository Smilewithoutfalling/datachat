// 阶段 7.6 U1：字阶表（docs/roadmap/phase76-ui.md §2 U1）。数值是根字号 13 时的设计像素（styles.css 里写成 calc(N * var(--px))）。
// 四级五档：标题 20/22，正文 13，聊天阅读 14，辅助 12。styles.css 的 :root 里 --fs-* 必须与这里一致，其余 font-size 只许引用 var(--fs-*)（typeScale.test.ts）。
// read 14 是 S 11-20 定的（C1）：只给聊天阅读区（气泡、回答正文和其中的 Markdown、输入框），见 READ_SELECTORS；其余正文仍用 body 13。
export const TYPE_SCALE = {
  aux: 12,
  body: 13,
  read: 14,
  title: 20,
  "title-lg": 22,
} as const;

export type TypeStep = keyof typeof TYPE_SCALE;

/** 允许用 var(--fs-read) 的选择器，typeScale.test.ts 钉住：别处要用 14，得先改这张表并说明理由。 */
export const READ_SELECTORS = [".bubble", ".answer", ".md h3, .md h4", ".composer textarea"] as const;
