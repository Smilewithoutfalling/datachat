// 阶段 7.6 U5 会话标题（docs/roadmap/phase76-u3u5.md §2）：前端不再另写一份标题规则（删掉了 question.slice(0, 60)），
// 首问时读响应头 X-Session-Title；清空标题 = 还原自动标题，侧栏和会话页同一条规则（titleEdit），都能提交空串。
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Api } from "../api";
import { client } from "../client";
import { fakeBackend, sseStream } from "../fakeBackend";
import { decodeTitleHeader, titleEdit } from "../titles";
import type { Session } from "../types";
import { conn, connRoutes } from "./connFixtures";
import { SessionView } from "./SessionView";
import { Shell } from "./Shell";

const Q = "各地区销售额是多少，按降序排一下";
const AUTO = "地区销售额"; // app/server/titles.py 对 Q 的结果（tests/test_titles.py 对照表第 1 行同一规则）
const EMPTY = { id: "s1", dataset_id: "d1", agent: "workflow", title: "", created_at: "t", updated_at: "t" };

describe("titleEdit：侧栏和会话页共用的编辑规则", () => {
  test.each([
    ["新名字", "旧名字", "新名字"],
    ["  新名字  ", "旧名字", "新名字"],
    ["", "旧名字", ""], // 清空 = 还原自动标题：提交空串
    ["   ", "旧名字", ""],
    ["旧名字", "旧名字", null], // 没改：不发请求
    [" 旧名字 ", "旧名字", null],
    ["", "", null],
  ])("draft %j、当前 %j → %j", (draft, current, out) => {
    expect(titleEdit(draft, current)).toBe(out);
  });
});

describe("decodeTitleHeader：百分号编码的响应头", () => {
  test("中文、空格、括号都能解回；没有这个头 → null；坏编码 → null", () => {
    expect(decodeTitleHeader(encodeURIComponent("生成你认为重要的分析图表（2）"))).toBe("生成你认为重要的分析图表（2）");
    expect(decodeTitleHeader(encodeURIComponent("画 5000 点"))).toBe("画 5000 点");
    expect(decodeTitleHeader("")).toBe("");
    expect(decodeTitleHeader(null)).toBeNull();
    expect(decodeTitleHeader("%E5%9C")).toBeNull();
  });
});

describe("首问：标题取自响应头 X-Session-Title，不再是问题原话", () => {
  const mount = (header: string | undefined) => {
    const stream = sseStream("a1", header);
    const changed: Session[] = [];
    const be = fakeBackend({
      "GET /sessions/s1": () => ({ ...EMPTY, messages: [] }),
      "POST /sessions/s1/messages": () => stream.response(),
    });
    render(<SessionView c={client(new Api("t", be.fetchImpl))} id="s1" datasetName="销量" onChanged={(s) => changed.push(s)} onDeleted={() => {}} />);
    return { stream, changed, be };
  };
  const send = async () => {
    fireEvent.change(await screen.findByLabelText("提问"), { target: { value: Q } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: /发送/ })));
  };

  test("流还没结束，顶栏和侧栏（onChanged）就已经是后端给的标题", async () => {
    const { changed } = mount(AUTO);
    await send();
    const input = screen.getByLabelText("会话标题") as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe(AUTO));
    expect(screen.getByTestId("live-msg")).toBeTruthy(); // 这一轮还在跑
    expect(changed.map((s) => s.title)).toEqual([AUTO]);
    // 删掉的那份前端规则：原话前 60 字不会再出现在标题里
    expect(input.value).not.toBe(Q.slice(0, 60));
  });

  test("没有响应头（旧后端）：不自己编标题，等流结束后从库里同步", async () => {
    const { changed } = mount(undefined);
    await send();
    await screen.findByTestId("live-msg");
    expect((screen.getByLabelText("会话标题") as HTMLInputElement).value).toBe("");
    expect(changed).toEqual([]);
  });

  test("正在编辑标题时，响应头不覆盖输入框（侧栏照样跟上）", async () => {
    const { changed } = mount(AUTO);
    const input = (await screen.findByLabelText("会话标题")) as HTMLInputElement;
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "我自己起的" } });
    fireEvent.change(screen.getByLabelText("提问"), { target: { value: Q } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: /发送/ })));
    await waitFor(() => expect(changed.map((s) => s.title)).toEqual([AUTO]));
    expect(input.value).toBe("我自己起的");
  });
});

describe("清空标题 = 还原自动标题：侧栏和会话页都提交空串", () => {
  const SESSION = { ...EMPTY, title: "我改过的名字" };
  const setup = () => {
    const be = fakeBackend({
      "GET /datasets": [{ id: "d1", name: "销量", created_at: "t", files: [] }],
      "GET /sessions": [SESSION],
      "GET /sessions/s1": { ...SESSION, messages: [{ id: "m1", role: "user", content: Q, status: "ok", created_at: "t" }] },
      // 后端：空串 → 用第一问重新生成（app.py rename_session）
      "PATCH /sessions/s1": (b: unknown) => ({ ...SESSION, title: (b as { title: string }).title || AUTO }),
      "GET /settings/api-key": { configured: true, source: "keyring" },
      ...connRoutes([conn({ name: "网关", provider: "custom", model: "m", base_url: "https://x/v1" })]).routes,
    });
    render(<Shell c={client(new Api("t", be.fetchImpl))} initialKey={{ configured: true, source: "keyring" }} />);
    return be;
  };
  const patches = (be: ReturnType<typeof fakeBackend>) => be.calls.filter((x) => x.method === "PATCH").map((x) => x.body);

  test("侧栏：双击改名、清空、失焦 → PATCH {title: \"\"}，行上显示还原后的自动标题", async () => {
    const be = setup();
    fireEvent.doubleClick(await within(await screen.findByRole("navigation", { name: "会话" })).findByRole("button", { name: /^我改过的名字/ }));
    const input = screen.getByLabelText("重命名会话");
    fireEvent.change(input, { target: { value: "" } });
    await act(async () => fireEvent.blur(input));
    expect(patches(be)).toEqual([{ title: "" }]);
    expect(await within(screen.getByRole("navigation", { name: "会话" })).findByRole("button", { name: new RegExp(`^${AUTO}`) })).toBeTruthy();
  });

  test("会话页：标题框清空、失焦 → 同样 PATCH {title: \"\"}，标题框显示还原后的自动标题", async () => {
    const be = setup();
    fireEvent.click(await within(await screen.findByRole("navigation", { name: "会话" })).findByRole("button", { name: /^我改过的名字/ }));
    const view = await screen.findByTestId("session-view");
    const input = within(view).getByLabelText("会话标题") as HTMLInputElement;
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "  " } });
    await act(async () => fireEvent.blur(input));
    expect(patches(be)).toEqual([{ title: "" }]);
    await waitFor(() => expect(input.value).toBe(AUTO));
  });
});
