// 结论的 markdown 渲染（phase5-frontend.md §2.3）：react-markdown 不开 raw HTML（不装 rehype-raw），
// 默认 urlTransform 过滤 javascript: 等危险协议（版本和行为在测试里钉住）；链接一律新标签页 + noreferrer noopener；
// img 不做特殊处理，靠 CSP 的 img-src 'self' data: blob: 兜底（外链图片加载不出来，见 THREAT_MODEL §2.3）。
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const components: Components = {
  // node 是 mdast/hast 节点，不能透传到 DOM
  a: ({ node, ...props }) => (void node, <a {...props} target="_blank" rel="noreferrer noopener" />),
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
