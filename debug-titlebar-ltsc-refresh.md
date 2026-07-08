# Debug Session: titlebar-ltsc-refresh
- **Status**: [OPEN]
- **Issue**: Windows 10 IoT Enterprise LTSC 2021 (build 19044) 上切换深色主题后，标题栏不即时刷新，需手动晃动/调整窗口才更新。恢复 DwmFlush + SetWindowPos + RedrawWindow 三步组合后仍无效；改用 cloak/decloak 后标题栏即时变色但窗口闪烁。
- **Debug Server**: http://127.0.0.1:7777/event
- **Log File**: .dbg/trae-debug-log-titlebar-ltsc-refresh.ndjson
- **Env File**: .dbg/titlebar-ltsc-refresh.env

## Reproduction Steps
1. 启动 GUI：`venv\Scripts\python.exe -m arknights_video_pipeline.gui.app`
2. 进入 Settings 页
3. 拨动"深色主题"开关至开启
4. 观察：标题栏未立即变深色（原 bug）/ 变色但窗口闪烁（S4 副作用）
5. 拨回关闭，同样问题

## Environment
- OS: Windows 10 IoT Enterprise LTSC 2021 (build 19044)
- Python: 3.12.10 (venv)
- PyQt6: >=6.6.0

## Hypotheses & Verification
| ID | Hypothesis | Likelihood | Effort | Evidence |
|----|------------|------------|--------|----------|
| A | DwmFlush 在 LTSC 上不阻塞（DWM 行为差异，无 pending 工作时立即返回） | High | Low | **CONFIRMED** — flush_ms=1.3ms (dark=True) vs 预期 ~16.7ms |
| B | SetWindowPos 缺少 SWP_NOCOPYBITS | High | Medium | **REJECTED** — S2 加 NOCOPYBITS 后标题栏仍未变色 |
| C | 需要 cloak/decloak 强制 DWM 完全丢弃并重建窗口合成表面 | Medium | Medium | **CONFIRMED** — 仅 S4 触发标题栏变色 |
| D | RedrawWindow 缺少 RDW_ERASE | Medium | Low | **REJECTED** — S3 加 RDW_ERASE 后标题栏仍未变色 |
| E | 窗口在调用时 is_visible=False | Low | Low | **REJECTED** — is_visible=True 时 S1 仍不触发变色 |

## Pre-fix Evidence (runId: pre-fix)
策略测试日志（4 策略按 800ms 间隔依次执行）：

### dark=False → dark=True 切换（关键片段）
```
[18:19:09.145] DWMSET: attr=20 dark=True hresult=0x00000000 readback=1 build=19044 ✓
[18:19:09.157] CTX: _force_titlebar_redraw hwnd=263178 is_visible=True
[18:19:09.174] S1 开始: SWP[FRAMECHANGED]+RDW+DwmFlush
[18:19:09.195] S1 完成: swp=True rdw=True flush=0x00000000 flush_ms=1.3ms ← flush 立即返回
[18:19:09.369] S4 开始: cloak→DwmFlush→decloak→DwmFlush
[18:19:09.395] S4 cloak: ret=0x00000000 flush=0x00000000
[18:19:09.412] S4 decloak: ret=0x00000000 flush=0x00000000 total_ms=30.3ms
```
**结论**：S1/S2/S3 的 flush_ms 均 <15ms（DWM 无 pending 工作），标题栏未变色；
仅 S4（cloak/decloak + DwmFlush）触发变色。但 S4 中间有一次 DwmFlush 将
cloaked（不可见）状态合成到屏幕，造成 ~17ms 闪烁。

## Root Cause
1. **DwmFlush 在 LTSC 2021 上不阻塞**：当 DWM 无 pending 工作时，DwmFlush
   立即返回（~1-2ms），不等 vsync。DWM 继续使用缓存的标题栏位图。
2. **DWM 缓存标题栏位图**：SetWindowPos[FRAMECHANGED] + RedrawWindow
   仅触发应用侧 NC 重绘，但 DWM 不重新读取 `DWMWA_USE_IMMERSIVE_DARK_MODE`
   属性，继续使用缓存的标题栏位图。
3. **cloak/decloak 强制表面重建**：DWMWA_CLOAK=1 标记窗口为 cloaked，
   DWM 销毁合成表面；DWMWA_CLOAK=0 恢复，DWM 重建合成表面时读取最新属性。

## Fix Approach: Fix A (cloak → decloak → 单次 DwmFlush)
**与 S4 的区别**：cloak 和 decloak 之间**不**调用 DwmFlush，避免 DWM 将
cloaked 状态合成到屏幕。

**预期效果**：
- DWM 在下次合成周期前看到 cloak=1 → cloak=0 两次属性变更
- cloak=1 触发表面销毁，cloak=0 触发表面重建（读取新标题栏属性）
- 单次 DwmFlush 合成新帧时窗口已 decloak，用户看不到 cloaked 状态
- → 标题栏即时变色，无闪烁

**风险**：DWM 可能优化掉 cloak=1→cloak=0 的净零变更，不触发表面重建。
若如此，需回退到 Fix B（S4 原方案，接受闪烁）或探索其他方案。

## Post-fix Verification (runId: post-fix)
[待用户测试后收集]

## Verification Conclusion
[待分析]
