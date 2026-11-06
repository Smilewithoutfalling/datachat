"""会话记忆（阶段 6.6，docs/roadmap/memory-system-spec.md）。

批 1：开关（config）、预算（budget）、工作状态（working_state，M1）、回合快照与失败轮（snapshots，M3/M5）、
组装（context：把以上拼成送进模型的块，并给出 result_json 的 memory_* 字段）。
批 4a：改写（rewrite，M7）、遮罩（compact，M4）。批 4b：口径（metrics，M2 / M10）、写入门槛（gate，M6）、
参考写法（pairs，M9）。
默认 off：所有新逻辑短路，prompt 与改动前逐字节一致（P8）。
"""
