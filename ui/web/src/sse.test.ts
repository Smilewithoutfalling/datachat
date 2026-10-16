import { parseSse, type SseMessage } from "./sse";

function streamOf(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(c) {
      chunks.forEach((x) => c.enqueue(x));
      c.close();
    },
  });
}
async function collect(chunks: Uint8Array[]) {
  const out: SseMessage[] = [];
  for await (const m of parseSse(streamOf(chunks))) out.push(m);
  return out;
}

const TEXT =
  ": 注释行\r\n" +
  "id: 0\r\nevent: plan\r\ndata: {\"text\":\"按城市汇总销量\"}\r\n\r\n" +
  "id: 1\nevent: answer\ndata: 第一行\ndata: 第二行\n\n" +
  "id: 2\revent: code\rdata:无空格\r\r" +
  "event: lonely\n\n" + // 没有 data 的块不派发
  "id: 3\nevent: tail\ndata: 未以空行收尾\n"; // 流结束时丢弃

const EXPECTED = [
  { id: "0", event: "plan", data: '{"text":"按城市汇总销量"}' },
  { id: "1", event: "answer", data: "第一行\n第二行" },
  { id: "2", event: "code", data: "无空格" },
];

test("SSE：CRLF / LF / CR 三种换行、注释、多行 data、无 data 块、未收尾块", async () => {
  expect(await collect([new TextEncoder().encode(TEXT)])).toEqual(EXPECTED);
});

test("SSE：响应体以 UTF-8 BOM 开头时，第一行字段名不带 BOM（TextDecoder 默认去 BOM），BOM 单独成块也一样", async () => {
  const bom = new Uint8Array([0xef, 0xbb, 0xbf]);
  const body = new TextEncoder().encode("data: x\n\n");
  const joined = new Uint8Array([...bom, ...body]);
  expect(await collect([joined])).toEqual([{ id: "", event: "message", data: "x" }]);
  expect(await collect([bom, body])).toEqual([{ id: "", event: "message", data: "x" }]);
  expect(await collect([joined.slice(0, 1), joined.slice(1)])).toEqual([{ id: "", event: "message", data: "x" }]);
  // 只去开头一个：正文里的 U+FEFF 原样保留
  expect(await collect([new TextEncoder().encode("data: \ufeffy\n\n")])).toEqual([{ id: "", event: "message", data: "\ufeffy" }]);
});

test("SSE：在任意字节处切 chunk（含多字节 UTF-8 中间、\\r 与 \\n 之间）结果都一样", async () => {
  const bytes = new TextEncoder().encode(TEXT);
  for (let i = 1; i < bytes.length; i++) {
    expect(await collect([bytes.slice(0, i), bytes.slice(i)])).toEqual(EXPECTED);
  }
  // 逐字节
  expect(await collect(Array.from(bytes, (b) => new Uint8Array([b])))).toEqual(EXPECTED);
});
