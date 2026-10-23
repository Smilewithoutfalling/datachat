// 结论的 markdown 渲染（phase5-frontend.md §2.3）：react-markdown 不开 raw HTML（不装 rehype-raw），
// 默认 urlTransform 过滤 javascript: 等危险协议（版本和行为在测试里钉住）；链接一律新标签页 + noreferrer noopener；
// img 不做特殊处理，靠 CSP 的 img-src 'self' data: blob: 兜底（外链图片加载不出来，见 THREAT_MODEL §2.3）。
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const components: Components = {
  // node 是 mdast/hast 节点，不能透传到 DOM
  // V2a 验收 P0-4：只有 http(s) / mailto 渲染成链接；其余（javascript:、data:、相对路径、被 urlTransform 清空的）
  // 只保留文字，不画成可点的样子。注意：站内锚点（#chart-3）也被挡；以后要让结论引用图表可点，先在这里放行 ^#
  a: ({ node, href, children }) =>
    (void node,
    typeof href === "string" && /^(https?:|mailto:)/i.test(href) ? (
      <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>
    ) : (
      <span className="md-link-blocked">{children}</span>
    )),
};

export function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
