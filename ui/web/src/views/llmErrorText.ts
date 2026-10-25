/** 按 llm_kind 给错误的标题和建议（V2a §3.3 错误卡；V2c §2 设置页「测试连接」失败共用）。
 *  where：turn 是分析里的错误卡（建议指向重试 / 去设置 / 换问法）；settings 是设置页（人已经在设置里，建议指向表单本身）。 */
export type LlmErrorText = { title: string; hint: string; rate: boolean; auth: boolean; badReq: boolean; server: boolean };

export function llmErrorText(k: string, where: "turn" | "settings" = "turn"): LlmErrorText {
  const http = /^http_(\d{3})$/.exec(k)?.[1];
  const rate = k === "rate_limit" || http === "429";
  const auth = k === "auth" || k === "no_key" || http === "401" || http === "403";
  const badReq = k === "bad_request" || (http !== undefined && http.startsWith("4") && !rate && !auth);
  const server = k === "server" || (http !== undefined && http.startsWith("5"));
  const s = where === "settings";
  const [title, hint] = rate
    ? ["模型服务限流了", s ? "等一会儿再测。" : "等一会儿再试。"]
    : k === "no_key"
      ? ["还没有配置 API Key", s ? "先填写并保存 Key。" : "到设置里填写后再提问。"]
      : auth
        ? ["模型服务不认这个 API Key", s ? "检查或更换上面的 Key。" : "到设置里检查或更换 Key。"]
        : badReq
          ? ["模型服务拒绝了这次请求", s ? "检查模型名和 Base URL。" : "换个问法通常能过。"]
          : server
            ? ["模型服务出错了", s ? "通常是临时的，稍后再测。" : "通常是临时的，可以重试。"]
            : k === "timeout"
              ? ["模型服务响应超时", s ? "网络慢时可以调大下面的超时。" : "可以重试；网络慢时可以在设置里调大超时。"]
              : k === "connection"
                ? ["连不上模型服务", s ? "检查网络和 Base URL。" : "检查网络和 Base URL 后重试。"]
                : ["模型调用失败", s ? "稍后再测。" : "可以重试。"];
  return { title, hint, rate, auth, badReq, server };
}
