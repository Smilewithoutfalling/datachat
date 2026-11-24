// 阶段 7.6 U3 结果卡（docs/roadmap/phase76-ui.md §2 U3）：一句话结论、关键数字、校验徽章（N = unverified_numbers 条数，黄条不重复）、
// 静态图的「导出 PNG」、底部三个动作各自真实发出一条请求（换个口径 / 补一张图 = POST /sessions/{id}/messages，导出 = #110 的接口）。
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Api } from "../api";
import * as exp from "../charts/exportPng";
import { setPngSaver } from "../charts/pngSaver";
import { client } from "../client";
import { fakeBackend, sseStream } from "../fakeBackend";
import { conclusionOf, FOLLOW_UPS, keyNumbers, LEAD_MAX, type Turn, verifyState } from "../turn";
import type { Message } from "../types";
import { SessionView } from "./SessionView";
import { TurnView } from "./TurnView";

const OK = {
  ok: true, answer: "深圳销量最高，共 1,061 单。\n\n上海次之，82.2 万元。", error: null, error_kind: null,
  warnings: ["结果只显示了前 20 行"], charts: [], executed: true, code: "result = df.groupby('城市')['销量'].sum()",
};
const turn = (result: Record<string, unknown> | null, status = "ok"): Turn => ({ status, events: [], result, live: false }) as unknown as Turn;

describe("conclusionOf：结论第一句，逐字摘取", () => {
  test.each([
    ["深圳销量最高，共 1,061 单。上海次之。", "深圳销量最高，共 1,061 单。"],
    ["### 结论\n\n**深圳**销量最高！其余略", "深圳销量最高！"],
    ["- 深圳销量最高；上海次之", "深圳销量最高；"],
    ["1. 看 `明细` 可知深圳最高", "看 明细 可知深圳最高"], // #125 起：原例带链接，链接所在的句子不再摘（切走会丢链接），改用行内代码钉「去记号」
    ["单句没有句号的结论", "单句没有句号的结论"],
    ["均值为 3.14，标准差 0.5。", "均值为 3.14，标准差 0.5。"], // 小数点不断句
  ])("%j → %j", (answer, lead) => {
    expect(conclusionOf(answer).lead).toBe(lead);
  });
  test.each([
    ["| 城市 | 销量 |\n|---|---|", "表格打头"],
    ["```\ncode\n```", "代码块打头"],
    ["好。", "太短"],
    ["", "空"],
    ["长".repeat(LEAD_MAX + 1), "超过 LEAD_MAX"],
    ["1. 看 [明细](http://x) 可知深圳最高", "第一句带链接（#125 起）"],
  ])("取不到：%j（%s）→ null，正文原样", (answer) => {
    expect(conclusionOf(answer)).toEqual({ lead: null, body: answer });
  });
});

// U3-1（phase76-u3u5.md §1.1 做法 A）：body = 原文去掉 lead 在原始 Markdown 里对应的那段，其余逐字不变
describe("conclusionOf：body 隐去已摘出的那一句", () => {
  test.each([
    ["深圳销量最高，共 1,061 单。上海次之。", "深圳销量最高，共 1,061 单。", "上海次之。"],
    ["深圳销量最高，共 1,061 单。\n\n上海次之，82.2 万元。", "深圳销量最高，共 1,061 单。", "\n上海次之，82.2 万元。"], // 这一行只剩空白 → 整行删除（连同换行）
    ["### 结论\n\n**深圳**销量最高！其余略", "深圳销量最高！", "### 结论\n\n其余略"], // 小标题保留
    ["- 深圳销量最高；上海次之\n- 广州第三", "深圳销量最高；", "- 上海次之\n- 广州第三"], // 列表记号留在原处
    ["1. 深圳销量最高\n2. 其余略", "深圳销量最高", "2. 其余略"], // 这一行只剩记号 → 整行删除
    ["### 结论\n\n深圳销量最高。\n\n| 城市 | 销量 |\n|---|---|", "深圳销量最高。", "### 结论\n\n\n| 城市 | 销量 |\n|---|---|"],
    ["均值为 3.14，标准差 `0.5`。样本 7 行。", "均值为 3.14，标准差 0.5。", "样本 7 行。"],
  ])("%j → lead %j，body %j", (answer, lead, body) => {
    expect(conclusionOf(answer)).toEqual({ lead, body });
  });
  test("字面量 __ 不当强调剥掉：卡头逐字保留（f3-inject 的 window.__pwned 载荷），正文里也只隐去这一句", () => {
    const a = '（fake）结论：<img src=x onerror="window.__pwned=1"> javascript:window.__pwned=3 点我。其余略';
    expect(conclusionOf(a)).toEqual({ lead: '（fake）结论：<img src=x onerror="window.__pwned=1"> javascript:window.__pwned=3 点我。', body: "其余略" });
    expect(conclusionOf("列 __a__ 与 b__c__d 都在。其余略")).toEqual({ lead: "列 a 与 b__c__d 都在。", body: "其余略" });
  });
  test("一句话结论（fake 模型那种）：整句摘走，body 为空", () => {
    expect(conclusionOf("（fake）结论：数据共有若干行。")).toEqual({ lead: "（fake）结论：数据共有若干行。", body: "" });
  });
  test.each([
    ["**深圳销量最高！**其余略", "跨句的 ** 不成对"],
    ["__深圳销量最高。__其余略", "跨句的 __ 不成对"],
    ["`深圳销量最高。`其余略", "跨句的 ` 不成对"],
    ["看[深圳销量最高。](http://x)其余略", "链接被切断"],
    ["看 [明细](http://x) 可知深圳最高。其余略", "前缀里有链接，切走会丢掉可点的链接"],
    ["（fake）结论：x [点我](javascript:alert(1))", "被拦下的危险链接也不切（f3-inject 的 md-link-blocked）"],
  ])("隐不干净：%j（%s）→ lead 为 null，正文完整", (answer) => {
    expect(conclusionOf(answer)).toEqual({ lead: null, body: answer });
  });
});

describe("verifyState：只在真的核过时出徽章", () => {
  test("没执行成功（executed 不是 true）、反问、非 ok：不出", () => {
    expect(verifyState(turn({ ...OK, executed: false }))).toBeNull();
    expect(verifyState(turn({ ...OK, executed: undefined }))).toBeNull();
    expect(verifyState(turn({ ...OK, clarify: true }))).toBeNull();
    expect(verifyState(turn({ ...OK }, "error"))).toBeNull();
  });
  test("没有未核实数字 → 全部可溯源；有 → 列出原文", () => {
    expect(verifyState(turn(OK))).toEqual({ kind: "ok" });
    expect(verifyState(turn({ ...OK, unverified_numbers: ["1,061", "82.2 万"] }))).toEqual({ kind: "unverified", numbers: ["1,061", "82.2 万"] });
  });
});

describe("keyNumbers：只认结构化字段，不从正文里猜", () => {
  test("后端没有 key_numbers 字段（现状）→ 不出数字", () => {
    expect(keyNumbers(turn(OK))).toEqual([]);
    render(<TurnView turn={turn(OK)} />);
    expect(screen.queryByTestId("key-numbers")).toBeNull();
  });
  test("最多 3 个；形状不对的丢掉；未核实的不放大", () => {
    const t = turn({
      ...OK, unverified_numbers: ["999"],
      // 形状照 app/server/key_numbers.py（K3）：Series 的口径是「索引 · Series 名」，dict / 单行表是键名
      key_numbers: [{ value: "1,061", label: "深圳 · 销量" }, { value: "999", label: "未核实" }, { value: "", label: "空" }, { label: "缺值" },
        { value: "82.2 万", label: "上海 · 销量" }, { value: "22.30%", label: "占比" }, { value: "7", label: "第四个" }],
    });
    expect(keyNumbers(t)).toEqual([
      { value: "1,061", label: "深圳 · 销量" }, { value: "82.2 万", label: "上海 · 销量" }, { value: "22.30%", label: "占比" },
    ]);
    render(<TurnView turn={t} />);
    const box = screen.getByTestId("key-numbers");
    expect([...box.querySelectorAll(".kn-value")].map((x) => x.textContent)).toEqual(["1,061", "82.2 万", "22.30%"]);
    expect([...box.querySelectorAll(".kn-label")].map((x) => x.textContent)).toEqual(["深圳 · 销量", "上海 · 销量", "占比"]);
  });
});

describe("结果卡头：一句话结论与校验徽章", () => {
  test("一句话结论在卡片顶部；正文里隐去这一句（出现 0 次），其余照常显示", () => {
    render(<TurnView turn={turn(OK)} />);
    const lead = screen.getByTestId("result-lead").textContent!;
    expect(lead).toBe("深圳销量最高，共 1,061 单。");
    const md = document.querySelector(".answer .md")!.textContent!;
    expect(md.split(lead).length - 1).toBe(0);
    expect(md).toContain("上海次之");
  });
  test("隐不干净：卡头不出结论，正文完整显示", () => {
    render(<TurnView turn={turn({ ...OK, answer: "**深圳销量最高！**其余略" })} />);
    expect(screen.queryByTestId("result-lead")).toBeNull();
    // CommonMark 里「！**其」的 ** 不算右侧定界符，原样显示；这里只断言内容完整，不断言粗体
    const md = document.querySelector(".answer .md")!.textContent!;
    expect(md).toContain("深圳销量最高！");
    expect(md).toContain("其余略");
  });
  test("一句话结论（body 为空）：不渲染正文块", () => {
    render(<TurnView turn={turn({ ...OK, answer: "（fake）结论：数据共有若干行。" })} />);
    expect(screen.getByTestId("result-lead").textContent).toBe("（fake）结论：数据共有若干行。");
    expect(document.querySelector(".answer .md")).toBeNull();
  });
  test("反问（clarify）不摘结论，正文完整显示", () => {
    render(<TurnView turn={turn({ ...OK, clarify: true, executed: false, answer: "你指的是哪个销量？按金额还是按单数。" })} />);
    expect(document.querySelector(".answer .md")!.textContent).toContain("你指的是哪个销量？");
  });
  test("反问（clarify）不出一句话结论，也不出徽章", () => {
    render(<TurnView turn={turn({ ...OK, clarify: true, executed: false })} />);
    expect(screen.queryByTestId("result-head")).toBeNull();
  });
  test("全部可溯源：✓ 徽章，不可点", () => {
    render(<TurnView turn={turn(OK)} />);
    const b = screen.getByTestId("verify-badge");
    expect(b.textContent).toBe("✓ 全部可溯源");
    expect(b.tagName).toBe("SPAN");
  });
  test("△ N 个数字未核实：N = unverified_numbers 条数，点开列出这几个；黄条只放 warnings，不重复列数字", () => {
    const nums = ["1,061", "82.2 万", "37.5%"];
    render(<TurnView turn={turn({ ...OK, unverified_numbers: nums })} />);
    const b = screen.getByTestId("verify-badge");
    expect(b.textContent).toBe(`△ ${nums.length} 个数字未核实`);
    expect(screen.queryByTestId("verify-list")).toBeNull();
    fireEvent.click(b);
    expect(b.getAttribute("aria-expanded")).toBe("true");
    const items = within(screen.getByTestId("verify-list")).getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toEqual(nums);
    const wbar = document.querySelector(".wbar")!;
    expect(wbar.textContent).toContain("结果只显示了前 20 行");
    for (const n of nums) expect(wbar.textContent).not.toContain(n);
    expect(screen.getByTestId("turn-badge").textContent).toBe("部分完成");
  });
});

describe("静态图：统一的「导出 PNG」", () => {
  const T = turn({ ...OK, charts: [{ png: "/charts/a.png", option: null }] });
  afterEach(() => {
    setPngSaver(null);
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
  test("浏览器：同源地址直接下载，文件名「静态图1.png」", () => {
    const dl = vi.spyOn(exp, "download").mockImplementation(() => {});
    render(<TurnView turn={T} chartSrc={(p) => `${p}?token=t`} />);
    const fig = screen.getByTestId("chart-static");
    expect(fig.className).toContain("echart-wrap"); // 和交互图同一种卡
    fireEvent.click(within(fig).getByRole("button", { name: "导出 PNG" }));
    expect(dl).toHaveBeenCalledWith("/charts/a.png?token=t", "静态图1.png");
  });
  test("桌面壳：取回字节交给 PngSaver，显示保存路径", async () => {
    const bytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);
    const fetchMock = vi.fn(async () => new Response(bytes));
    vi.stubGlobal("fetch", fetchMock);
    const saver = vi.fn(async () => "C:\\Users\\u\\Downloads\\静态图1.png");
    setPngSaver(saver);
    render(<TurnView turn={T} chartSrc={(p) => `${p}?token=t`} />);
    fireEvent.click(screen.getByRole("button", { name: "导出 PNG" }));
    await screen.findByTestId("export-saved");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(saver).toHaveBeenCalledWith(`data:image/png;base64,${btoa("\x89PNG")}`, "静态图1.png");
  });
});

describe("底部三个动作：各自真实发出一条请求", () => {
  const SESSION = { id: "s1", dataset_id: "d1", agent: "workflow", title: "t", created_at: "t", updated_at: "t" };
  const msgs: Message[] = [
    { id: "u1", role: "user", content: "各城市销量？", status: "ok", created_at: "t" },
    { id: "a1", role: "assistant", content: OK.answer, status: "ok", created_at: "t", events: [], result: { ...OK, unverified_numbers: ["1,061"] }, feedback: null },
  ];
  const answerNow = (id: string) => () => {
    const s = sseStream(id);
    s.push("done", { result: OK });
    s.end();
    return s.response();
  };
  const mount = (keyConfigured = true) => {
    let n = 0;
    const be = fakeBackend({
      "GET /sessions/s1": () => ({ ...SESSION, messages: msgs }),
      "POST /sessions/s1/messages": () => answerNow(`a${++n + 1}`)(),
      "POST /messages/a1/export/code": { path: "D:\\下载\\t_a1.py", filename: "t_a1.py" },
      "POST /messages/a1/export/result?format=csv": { path: "D:\\下载\\t_a1.csv", filename: "t_a1.csv", rows: 2, columns: 2, matches_original: true },
      "POST /messages/a1/export/result?format=xlsx": { path: "D:\\下载\\t_a1.xlsx", filename: "t_a1.xlsx", rows: 2, columns: 2, matches_original: true },
    });
    render(<SessionView c={client(new Api("t", be.fetchImpl))} id="s1" datasetName="销量" keyConfigured={keyConfigured}
      onChanged={() => {}} onDeleted={() => {}} />);
    return be;
  };
  const posts = (be: ReturnType<typeof fakeBackend>) => be.calls.filter((c) => c.method === "POST");

  test("换个口径 / 补一张图：各一次提问，内容是固定的追问；导出代码 / 结果表：各一次 #110 请求", async () => {
    const be = mount();
    const actions = await screen.findByTestId("result-actions");
    fireEvent.click(within(actions).getByRole("button", { name: "换个口径" }));
    await waitFor(() => expect(posts(be)).toHaveLength(1));
    expect(posts(be)[0]).toMatchObject({ path: "/sessions/s1/messages", body: { content: FOLLOW_UPS.metric } });
    await waitFor(() => expect(screen.queryByTestId("live-msg")).toBeNull());

    fireEvent.click(within(await screen.findByTestId("result-actions")).getByRole("button", { name: "补一张图" }));
    await waitFor(() => expect(posts(be)).toHaveLength(2));
    expect(posts(be)[1]).toMatchObject({ path: "/sessions/s1/messages", body: { content: FOLLOW_UPS.chart } });
    await waitFor(() => expect(screen.queryByTestId("live-msg")).toBeNull());

    const exportBtn = within(screen.getByTestId("result-actions")).getByRole("button", { name: "导出" });
    fireEvent.click(exportBtn);
    fireEvent.click(screen.getByRole("menuitem", { name: "分析代码（.py）" }));
    expect((await screen.findByTestId("export-result")).textContent).toBe("已保存到 D:\\下载\\t_a1.py");
    fireEvent.click(exportBtn);
    fireEvent.click(screen.getByRole("menuitem", { name: "结果表（CSV）" }));
    await waitFor(() => expect(screen.getByTestId("export-result").textContent).toBe("已保存到 D:\\下载\\t_a1.csv"));
    expect(posts(be).map((c) => c.path)).toEqual([
      "/sessions/s1/messages", "/sessions/s1/messages", "/messages/a1/export/code", "/messages/a1/export/result?format=csv",
    ]);
  });

  test("导出失败：显示后端的 detail", async () => {
    const be = fakeBackend({
      "GET /sessions/s1": () => ({ ...SESSION, messages: msgs }),
      "POST /messages/a1/export/code": () => new Response(JSON.stringify({ detail: "代码里有沙箱拦下的操作" }), { status: 422 }),
    });
    render(<SessionView c={client(new Api("t", be.fetchImpl))} id="s1" datasetName="销量" onChanged={() => {}} onDeleted={() => {}} />);
    fireEvent.click(within(await screen.findByTestId("result-actions")).getByRole("button", { name: "导出" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "分析代码（.py）" }));
    expect((await screen.findByTestId("export-result")).textContent).toBe("导出失败：代码里有沙箱拦下的操作");
  });

  test("没配凭证：换个口径不发请求（与手动发送同一规矩）", async () => {
    const be = mount(false);
    fireEvent.click(within(await screen.findByTestId("result-actions")).getByRole("button", { name: "换个口径" }));
    await act(async () => {});
    expect(posts(be)).toHaveLength(0);
    expect(screen.getByTestId("key-banner").textContent).toContain("这次提问没有发出");
  });

  test("没有执行成功的代码：导出置灰；实时轮次（还没有 messageId）不出动作行", () => {
    render(<TurnView turn={turn({ ...OK, executed: false })} messageId="a1" onFollowUp={() => {}} onExport={async () => ""} />);
    expect((screen.getByRole("button", { name: "导出" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "换个口径" }) as HTMLButtonElement).disabled).toBe(false);
  });

  test("实时轮次不出动作行；有别的轮次在跑时追问置灰", () => {
    const { unmount } = render(<TurnView turn={turn(OK)} onFollowUp={() => {}} />);
    expect(screen.queryByTestId("result-actions")).toBeNull();
    unmount();
    render(<TurnView turn={turn(OK)} messageId="a1" busy onExport={async () => ""} />);
    expect((screen.getByRole("button", { name: "换个口径" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "补一张图" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
