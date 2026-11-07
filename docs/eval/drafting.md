# 👎 → 草稿用例（EV-D4）

题集老化的两个来源：题太简单（→ EV-D3 毕业）和新场景没人出题。后者靠用户差评回流：
用户点了 👎 的那次问答，往往正好是题集没覆盖的形态——多表、口径歧义、图表要求、口语化提问。

这个脚本把一条 👎 消息变成一份**待补 gold 的草稿**，不是一条能直接进集的题。

```bash
# 默认：脱敏输出到 stdout
python scripts/draft_case.py --message-id <助手消息 id>

# 写到 docs/eval/drafts/（自动接着编号）
python scripts/draft_case.py --message-id <id> --out docs/eval/drafts/draft_001.yaml

# 连原始答案一起看（会带出数据值，进仓库前必须自己读一遍）
python scripts/draft_case.py --message-id <id> --raw
```

`--db` 默认取桌面版的数据目录（`%LOCALAPPDATA%\datachat\datachat.db`）。
没有 👎 的消息要出草稿得加 `--any-rating`。

## 脱敏契约（这个脚本最重要的部分）

它是**唯一会把用户数据写出仓库的路径**，所以默认路径的规则是"不读，而不是读了再擦"：

| 字段 | 默认 | `--raw` |
|---|---|---|
| `question` | 用户问题原文（**必须留**，它就是用例本身） | 同左 |
| `dataset` | 只留文件名/目录名 | 同左 |
| `schema` | 列名 + 形状（多表按表分开） | 同左 |
| 答案正文 / `result_text` / 代码 | **完全不读进内存** | 答案前 200 字进 `note`，stderr 打警告 |
| `note` | 反馈备注 + "原始答案已省略" | 反馈备注 + 原始答案前 200 字 |

两个坑是实测踩出来的，写在这里防回归：

1. **真实记录里的 `dataset` 是绝对路径**（`C:\Users\<用户名>\AppData\...\datasets\<id>`）。
   原样写进草稿等于把用户名和安装路径带进仓库。只留 basename（数据集 id 本身就是个哈希，
   不泄露内容）。同一条理由见 EV-B10 出境审计的 ④。
2. **数据库只以 `mode=ro` 打开**。这个脚本没有任何写库路径——跑错了也动不了用户数据。

`ground_truth` 恒为空。**不要自动生成 gold**：猜出来的标准答案会让这道题变成"测模型和猜测
是否一致"，比没有这道题更糟。`schema` 只给列名与形状，就是为了让人照着补 gold，而不是照着
答案抄。

## 入集流程

1. 生成草稿 → 人读一遍问题，判断这是"模型错"还是"题本身有歧义"。后者不该进集。
2. 补 `ground_truth`（pandas 代码，执行后 `result = 期望结果`），补 `category` / `dataset`。
3. 抄进对应的 `app/eval/cases*.py`，跑 `python -c "from app.eval.validate import ..."` 或
   `python run_eval.py --oracle --case <新 id>` 确认 gold 能跑通。
4. 在 `docs/eval/registry.json` 里记一笔 `candidate`（`scripts/eval/registry.py --set`），
   观察若干轮再转 `active`——刚起草的题最容易是"模型对、gold 错"。

## 当前状态（2026-11-07）

本机库有 42 条消息、**0 条反馈**，所以这个脚本还没有真实 👎 输入。验收靠
`tests/test_draft_case.py`（临时 sqlite + 真表结构），重点测的是"默认路径不泄露数据值"，
不是"YAML 长得对"。
