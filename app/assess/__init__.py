"""阶段 7.5 第 1 步：评估地基（docs/roadmap/phase75-assess.md §0、§2、§4）。

- snapshot：节点边界快照（AgentState + 耗时 + token + today），默认关闭，只观测；
- replay：单节点回放（codegen 的 prompt 逐字节比对、executor 结果比对）；
- contracts：各节点的确定性契约（ok / warn / fail + 原因）；
- runner：对快照目录跑契约、`--diff` 两份快照集。

评估的任何数字都不是准确率（§0 规则 1），不进对外报告、README 或基线文件。
"""
