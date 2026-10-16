// SSE 解析器（阶段 5 F2）：fetch + ReadableStream，自写——EventSource 不能带 Authorization 头。
// 按 WHATWG 规范的子集：行以 \n、\r\n 或 \r 结尾；空行派发；data 多行用 \n 连接；":" 开头是注释；
// 字段名后的第一个空格去掉；没有 data 的块不派发。chunk 边界可以落在任何字节上（包括多字节 UTF-8 中间）。
export type SseMessage = { id: string; event: string; data: string };

export async function* parseSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
  const reader = body.getReader();
  const decoder = new TextDecoder(); // stream: true 处理跨 chunk 的多字节字符；ignoreBOM 默认 false = 去掉开头一个 BOM（规范要求）
  let buf = "";
  let id = "";
  let event = "";
  let data: string[] = [];
  let pendingCR = false; // 上个 chunk 以 \r 结尾：若下个 chunk 以 \n 开头，两者合成一个换行
  const line = (l: string): SseMessage | null => {
    if (l === "") {
      const out = data.length ? { id, event: event || "message", data: data.join("\n") } : null;
      event = "";
      data = [];
      return out;
    }
    if (l.startsWith(":")) return null;
    const i = l.indexOf(":");
    const field = i < 0 ? l : l.slice(0, i);
    let value = i < 0 ? "" : l.slice(i + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "data") data.push(value);
    else if (field === "event") event = value;
    else if (field === "id" && !value.includes("\0")) id = value;
    return null;
  };
  try {
    for (;;) {
      const { value, done } = await reader.read();
      let chunk = done ? decoder.decode() : decoder.decode(value, { stream: true });
      if (done && !chunk) break;
      if (pendingCR && chunk.startsWith("\n")) chunk = chunk.slice(1);
      pendingCR = chunk.endsWith("\r");
      buf += chunk;
      const parts = buf.split(/\r\n|\r|\n/);
      buf = parts.pop() ?? "";
      for (const l of parts) {
        const m = line(l);
        if (m) yield m;
      }
      if (done) break;
    }
    // 流结束时未以空行收尾的块按规范丢弃
  } finally {
    reader.releaseLock();
  }
}
