// 内联 SVG 图标（每个都带 data-icon：e2e 注入测试据此区分产品自己的静态图标和注入出来的 <svg>）（phase5「F4 迭代 V2a」§0.4）：stroke=currentColor、viewBox 16、线宽 1.5（13px 以下用 1.3）。
// 不引 lucide-react；超过 30 个再议。图标不单独承担语义：旁边必须有文字，或者按钮有 aria-label。
import type { ReactNode, SVGProps } from "react";

type P = SVGProps<SVGSVGElement> & { size?: number; sw?: number };

function Svg({ size = 16, sw = 1.5, children, ...rest }: P & { children: ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={sw}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" data-icon="" {...rest}>
      {children}
    </svg>
  );
}

export const IconSpark = (p: P) => (
  <Svg {...p} sw={0}>
    <path d="M8 2.2c.35 2.6 1.2 3.45 3.8 3.8-2.6.35-3.45 1.2-3.8 3.8-.35-2.6-1.2-3.45-3.8-3.8 2.6-.35 3.45-1.2 3.8-3.8Z"
      fill="currentColor" transform="translate(0 2)" />
  </Svg>
);
export const IconUpload = (p: P) => (
  <Svg {...p}><path d="M8 10.5V2.8M5 5.6 8 2.6l3 3M2.8 10v2.2c0 .6.5 1 1 1h8.4c.6 0 1-.4 1-1V10" /></Svg>
);
export const IconTable = (p: P) => (
  <Svg {...p}><rect x="2.3" y="3" width="11.4" height="10" rx="1.6" /><path d="M2.3 6.4h11.4" /></Svg>
);
export const IconChat = (p: P) => (
  <Svg {...p}><path d="M3 3.5h10c.4 0 .7.3.7.7v6c0 .4-.3.7-.7.7H7l-3 2.4V10.9H3c-.4 0-.7-.3-.7-.7v-6c0-.4.3-.7.7-.7Z" /></Svg>
);
export const IconGear = (p: P) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="2" />
    <path d="M8 1.8v1.6M8 12.6v1.6M14.2 8h-1.6M3.4 8H1.8M12.4 3.6l-1.1 1.1M4.7 11.3l-1.1 1.1M12.4 12.4l-1.1-1.1M4.7 4.7 3.6 3.6" />
  </Svg>
);
export const IconSidebar = (p: P) => (
  <Svg {...p}><rect x="2" y="3" width="12" height="10" rx="1.8" /><path d="M6 3v10" /></Svg>
);
export const IconMore = (p: P) => (
  <Svg {...p} sw={0}>
    <circle cx="3.5" cy="8" r="1.1" fill="currentColor" /><circle cx="8" cy="8" r="1.1" fill="currentColor" />
    <circle cx="12.5" cy="8" r="1.1" fill="currentColor" />
  </Svg>
);
export const IconPlus = (p: P) => <Svg {...p}><path d="M8 3v10M3 8h10" /></Svg>;
export const IconArrowUp = (p: P) => <Svg {...p}><path d="M8 13V3.5M4 7.2 8 3.2l4 4" /></Svg>;
export const IconChevronRight = (p: P) => <Svg {...p}><path d="m6 3.5 4.5 4.5L6 12.5" /></Svg>;
export const IconChevronDown = (p: P) => <Svg {...p}><path d="m3.5 6 4.5 4.5L12.5 6" /></Svg>;
export const IconChevronUp = (p: P) => <Svg {...p}><path d="m3.5 10 4.5-4.5 4.5 4.5" /></Svg>;
export const IconPalette = (p: P) => (
  <Svg {...p}><path d="M8 2.3a5.7 5.7 0 1 0 0 11.4c.8 0 1.2-.6 1-1.3-.3-.9.3-1.8 1.3-1.8h1.3c1.2 0 2.1-1 2.1-2.2C13.7 4.9 11.2 2.3 8 2.3Z" /><circle cx="5.2" cy="7" r=".7" /><circle cx="7.6" cy="4.9" r=".7" /><circle cx="10.4" cy="5.6" r=".7" /></Svg>
);
export const IconClock = (p: P) => <Svg {...p}><circle cx="8" cy="8" r="5.75" /><path d="M8 4.8V8l2.2 1.4" /></Svg>;
export const IconClose = (p: P) => <Svg {...p}><path d="m4 4 8 8M12 4l-8 8" /></Svg>;
export const IconCheck = (p: P) => <Svg {...p}><path d="m3.5 8.3 3 3 6-6.6" /></Svg>;
export const IconStop = (p: P) => (
  <Svg {...p} sw={0}><rect x="4" y="4" width="8" height="8" rx="1.4" fill="currentColor" /></Svg>
);
export const IconPlay = (p: P) => <Svg {...p} sw={0}><path d="M5.5 4v8l6.5-4-6.5-4Z" fill="currentColor" /></Svg>;
export const IconRetry = (p: P) => (
  // refresh-cw：两段箭头，小尺寸下也不会像"禁止"（验收 r3 #1）
  <Svg {...p}><path d="M2.5 8a5.5 5.5 0 0 1 9.4-3.9L13.5 5.5M13.5 2v3.5H10M13.5 8a5.5 5.5 0 0 1-9.4 3.9L2.5 10.5M2.5 14v-3.5H6" /></Svg>
);
export const IconThumbUp = (p: P) => (
  <Svg {...p}><path d="M5 7v6H3V7h2Zm0 0 2.6-4.3c.9 0 1.5.7 1.3 1.6L8.5 6.5h3.7c.8 0 1.4.8 1.2 1.6l-1 4c-.2.6-.7.9-1.3.9H5" /></Svg>
);
export const IconThumbDown = (p: P) => (
  <Svg {...p}><path d="M5 9V3H3v6h2Zm0 0 2.6 4.3c.9 0 1.5-.7 1.3-1.6L8.5 9.5h3.7c.8 0 1.4-.8 1.2-1.6l-1-4C12.2 3.3 11.7 3 11.1 3H5" /></Svg>
);
export const IconWarn = (p: P) => (
  <Svg {...p}><path d="M8 2.5 14 13H2L8 2.5Z" /><path d="M8 6.6v3M8 11.4v.1" /></Svg>
);
export const IconAlert = (p: P) => (
  <Svg {...p} sw={0}>
    <circle cx="8" cy="8" r="7" fill="currentColor" />
    <path d="M8 4.4v4.4M8 10.9v.3" stroke="#fff" strokeWidth={1.6} strokeLinecap="round" />
  </Svg>
);
export const IconTrash = (p: P) => (
  <Svg {...p}><path d="M3 4.5h10M6.3 4.5V3h3.4v1.5M4.3 4.5l.6 8.2c0 .5.5.8 1 .8h4.2c.5 0 .9-.3 1-.8l.6-8.2M6.8 7v4M9.2 7v4" /></Svg>
);
export const IconFileAlert = (p: P) => (
  <Svg {...p}><path d="M9.5 2H4.5c-.6 0-1 .4-1 1v10c0 .6.4 1 1 1h7c.6 0 1-.4 1-1V5L9.5 2Z" /><path d="M9.5 2v3h3M8 7v3M8 11.8v.1" /></Svg>
);
export const IconLink = (p: P) => (
  <Svg {...p}><rect x="1.8" y="6" width="5.6" height="4" rx="2" /><rect x="8.6" y="6" width="5.6" height="4" rx="2" /></Svg>
);
export const IconDownload = (p: P) => (
  <Svg {...p}><path d="M8 2.8v7.4M5 7.4l3 3 3-3M2.8 12.8h10.4" /></Svg>
);
export const IconCode = (p: P) => <Svg {...p}><path d="m5.5 4.5-3 3.5 3 3.5M10.5 4.5l3 3.5-3 3.5" /></Svg>;

/** 步骤图标（13×13）：done 绿勾圆、running 蓝弧（CSS 旋转）、pending 灰空心圆、failed 红叉圆。 */
export function StepIcon({ state }: { state: "done" | "running" | "pending" | "failed" }) {
  if (state === "running")
    return (
      <svg className="spin" width={13} height={13} viewBox="0 0 16 16" fill="none" aria-hidden="true" data-icon="">
        <circle cx="8" cy="8" r="6.2" stroke="#D8E8F8" strokeWidth={1.6} />
        <path d="M8 1.8a6.2 6.2 0 0 1 6.2 6.2" stroke="#0066CC" strokeWidth={1.6} strokeLinecap="round" />
      </svg>
    );
  const color = state === "done" ? "#34C759" : state === "failed" ? "#E5484D" : "#D8D8DC";
  return (
    <svg width={13} height={13} viewBox="0 0 16 16" fill="none" stroke={color} strokeWidth={1.4} strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true" data-icon="">
      <circle cx="8" cy="8" r="6.3" />
      {state === "done" ? <path d="m5.2 8.2 2 2 3.7-4" /> : null}
      {state === "failed" ? <path d="m5.8 5.8 4.4 4.4M10.2 5.8l-4.4 4.4" /> : null}
    </svg>
  );
}

export const Spinner = ({ size = 11 }: { size?: number }) => (
  <svg className="spin" width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden="true" data-icon="">
    <circle cx="8" cy="8" r="6" stroke="currentColor" strokeOpacity={0.25} strokeWidth={2} />
    <path d="M8 2a6 6 0 0 1 6 6" stroke="currentColor" strokeWidth={2} strokeLinecap="round" />
  </svg>
);
