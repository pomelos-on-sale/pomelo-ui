# 待办规划: 让 iced 的 `text_input` 可用 —— 并用它替换 Settings 里手搓的密码框

- **所属模块**: `pomelo-apps/settings/src/pages/wifi.rs`, `ui-framework/iced-pomelo-winit/src/hosting.rs`, `pomelo-widgets/touch_keyboard`
- **目标平台**: ESP32-S3（480×480 AMOLED；无物理键盘、无系统剪贴板、无输入法）+ Desktop Simulator
- **创建日期**: 2026-10-06
- **状态**: 待办规划 (Proposed)
- **关联**: `261004-01`（开源库集成与架构）、`261004-02`（NVS 持久化 —— 密码将来要存这里）、`iced-pomelo-winit` 的 `Clipboard`/`Proxy` 命名对齐（未开工）

---

## 一、 结论摘要

1. **iced 有 `text_input`，本仓库一处没用。** 它就在依赖里（`ui-framework/iced/widget/src/lib.rs:41` `pub mod text_input;`、`:103` `pub use text_input::TextInput;`），但整个 `pomelo-apps/settings` 对它做 `grep`：**0 处**。今天那个"密码框"和 iced 的文本控件没有任何关系。

2. **平台侧的缺口比预想的小得多。** 剪贴板**已经接好了**，只是空实现（`iced-pomelo-winit/src/application.rs:41` `clipboard: clipboard::Null`，`:196` 递进 `UserInterface`）；焦点**是 `text_input` 自己的**（`State::is_focused`，点击时置位 `text_input.rs:725`，键盘事件按它过滤 `:1252`）。两者都不需要我们新造。

3. **光标闪烁不需要订阅帧。** 这是本次调研最重要的一条：`text_input` 把闪烁实现成**自我排程的重绘请求**，而不是定时器 —— 见 `text_input.rs:1330`，收到 `Event::Window(RedrawRequested(now))` 时算到下个 500 ms 边界，调 `shell.request_redraw_at(now + 剩余毫秒)`；而可见性只是那次事件自带时间的纯函数（`:515`，`(focus.now - focus.updated_at) / 500ms` 是否为偶数）。**没有 tokio、没有 subscription、没有帧循环。**

   也就是说：当初为"手搓光标闪烁"付不起的那笔账（每帧重跑 view + damage diff，见 `settings/src/lib.rs` 里 `is_waiting_on_wifi` 的注释），**换成 `text_input` 就免费了** —— 前提是平台肯收下那个重绘请求。

4. **而平台现在把它丢掉了。** `iced-pomelo-winit/src/hosting.rs:243` 的 `Action::Window(_)` 和 `Action::Clipboard(_)`、`System(_)`、`Image(_)` 一起被忽略（那里有注释说明这是决定而非疏漏）。**重绘请求就走在 `Window` 这一支里。** 这和当初"widget operation 被无声丢弃"是同一类问题：不是不能做，是没人接。

---

## 二、 现状（核实过的事实）

今天这个"输入框"由三样东西拼成，没有一样来自 iced 的文本控件：

| 部分 | 位置 | 是什么 |
| :--- | :--- | :--- |
| **值** | `wifi.rs` `Wifi::password: String` | 字符串由 app 自己拿着，不在树里 |
| **画** | `wifi.rs` `password_line()` | 一堆画出来的 `container` 圆点（密文）或明文，外加一个画出来的光标 `caret()` |
| **键** | `pomelo_widgets::touch_keyboard` | 和 terminal 共用的那把键盘 |
| **承接** | `wifi.rs` `Wifi::key(KeyAction)` | `Char` / `Space` / `Backspace` / `Enter` |

iced 那边已经现成的东西：

| 能力 | 现状 | 位置 |
| :--- | :--- | :--- |
| `TextInput` widget | **有，未用** | `iced/widget/src/lib.rs:41`, `:103` |
| `secure(true)`（自己画圆点） | 有 | `text_input.rs:163` |
| `id()` / `on_input()` | 有 | `:157` / `:172` |
| 焦点 | `text_input` 自己维护 | `:725`（点击置位）、`:1252`（按焦点过滤事件）、`:1465` `State` |
| 光标闪烁 | **有，事件驱动** | `:515`（可见性）、`:1330`（`request_redraw_at`）、`:1693`（500 ms） |
| 选中 / 复制 / 粘贴 / 全选 | 有，走 `Clipboard` | `:921` / `:941` / `:970` |
| `Clipboard` 实现 | **已有，是空实现** | `iced-pomelo-winit/src/application.rs:41` `clipboard::Null` |
| `Action::Clipboard(_)` | **被丢弃** | `hosting.rs:242` |
| `Action::Window(_)`（含重绘请求） | **被丢弃** | `hosting.rs:243` |
| 物理键盘 / 输入法 / 异步运行时 | **没有** | 见 `settings/src/lib.rs` 关于 `iced::time::every` 需要 tokio/smol 的注释 |

---

## 三、 真正缺的东西：把板上的按键变成事件

`text_input` 消费的是 `iced::Event::Keyboard`；板上唯一的输入源 `touch_keyboard` 产出的是**消息**（`KeyAction`）。今天这条消息被直接接到 `Wifi::password` 上。要让 `text_input` 用上，二选一：

**甲、平台侧：合成键盘事件。**
触摸键盘的一次按键 → 合成 `Event::Keyboard(KeyPressed { .. })` → 喂进树。`Host::push_event` 已经存在（截图/测试也在用），缺的是"从触摸按键到事件"的这条通路，以及它该由谁触发（app 够不到 `Host`）。
- 好处：焦点、选中、光标、滚动全部归 iced 管，一行都不用手搓。
- 代价：要在真机上验证合成事件的字段（`key` / `modified_key` / `physical_key` / `text`）够不够 `text_input` 用；`iced_test` 覆盖不到这条路径。

**乙、应用侧：用 widget operation 驱动。**
键盘按键 → `Message` → 一个 `Task` 发 `widget::operation`，去改 `text_input` 的值/光标。
- 好处：不碰平台，全在 app 内，`iced_test` 能测。
- 代价：`settings` 需要重新打开 `advanced` feature（`widget::operation` 在 `iced::advanced` 下）；而且等于把 `text_input` 当画框用，编辑逻辑还是我们写的 —— 那这次替换的收益就只剩"圆点和光标是 iced 画的"。

> 建议先做甲的最小版本（只做 `KeyPressed`，不做输入法），因为它才是"用上 iced 的能力"而不是"换个画法"。

---

## 四、 要拍板的决策

1. **走甲（合成事件）还是乙（operation）？** 见 §三。
2. **平台要不要收下重绘请求？** 这不只是为 `text_input`：任何"到点再画一帧"的需求（动画、节流）都要它。收下的形状是给 `Host` 的循环加一条"下一次唤醒时间"，`Board::wait_touch(timeout_ms)` 已经能睡到某个时刻。
3. **剪贴板怎么办？** 板子没有系统剪贴板。三个选项：(a) 接受空实现（复制/粘贴静默无效，但**不能**让程序崩溃或卡住 —— 需要确认 `Null` 的行为）；(b) 做一个应用内单槽剪贴板，存在 `Settings` 里；(c) 干脆不给选中/复制入口。
4. **密文圆点用谁的？** `secure(true)` 让 iced 自己遮盖。**风险**：本板字体是一个中英子集，没有 `•`（今天的圆点是**画**出来的，正是因为这个）。iced 的遮盖若也是画一个字符，板上就是**豆腐块**。必须在真机上看过再定。
5. **键盘继续用共享的 `touch_keyboard` 吗？** 板上没有系统输入法，所以答案基本是"是"，但要明确：焦点在 `text_input` 上、字符由共享键盘送进去。
6. **`settings` 要不要重新开 `advanced` feature？** 只在选乙时需要。它当初被删掉是因为 `src/page.rs` 没了（见 `settings/Cargo.toml` 的注释）。
7. **旧的实现何时删？** 目的不是"两个并存"。落地后 `Wifi::password`、`Wifi::key()`、`password_line()`、`caret()`、`CARET_*`/`LINE_H`/`PASSWORD_DOT*` 这些常量应当一并消失。

---

## 五、 实施步骤（建议顺序）

1. **先在桌面把 `text_input` 跑起来。** 桌面上有物理键盘、有焦点、有窗口，是验证行为最便宜的地方：用 `secure(true)` 换掉 `password_line()`，密码仍存在 `Wifi::password`（`on_input` 回填），跑通 `settings_tests`。
2. **平台侧收下重绘请求**（决策 2），顺带确认光标真的闪 —— 这一步和 `text_input` 解耦，单独可测。
3. **板上打通输入**（决策 1）：合成 `KeyPressed`，或走 operation。
4. **剪贴板决策落地**（决策 3）。
5. **删掉手搓的那一套**（决策 7）。

---

## 六、 代价与风险

- **镜像体积**：`iced_widget` 本来就在镜像里（其它 app 也在用），增量是这个 widget 自己的排版/编辑/光标代码，量级待实测。要记进 `firmware.bin` 的账，别当成回归。
- **`secure(true)` 的圆点可能不成立**（决策 4）—— 这是本次最可能翻车的一条，且只能在真机上看。
- **测试面要重写**：`settings_tests.rs` 里有按明文找文字的断言（`ui.find("hunter2")`、`ui.find("Show password")`），`secure` 会改变可查找的内容；`the_prompt_has_the_whole_keyboard` 一类按键盘标签找键的测试也会受影响。
- **行为面的"新增"未必是好事**：今天的框**没有**选中、没有粘贴、没有长按；换上之后这些都会出现，按键冲突（比如回车既连接又换行）要重新定。
- **合成事件的字段**：`text_input` 会读 `key` / `modified_key` / `physical_key` / `text`，板上合成时容易只填一个，导致"能打字但退格/回车不灵"这类半通状态。

---

## 七、 不做这件事的代价（也就是维持现状）

- 板上永远没有选中、粘贴、输入法、系统级文本编辑。
- **每加一个要输入的地方就要再手搓一遍**：terminal 已经搓了第二遍（它自己的输入行）；再来一个搜索框就是第三遍。
- 输入法的世界进不来：中文输入在板上不是"以后再说"，而是"这条路上永远不会出现"。
