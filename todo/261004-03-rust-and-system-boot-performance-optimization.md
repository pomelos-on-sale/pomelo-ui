# 任务规划: Rust 应用层与软硬件协同的启动性能极致优化

- **所属模块**: `pomelo-firmware/board_hal`, `pomelo-firmware/rust_main`, `pomelo-hal`, `pomelo-apps/app-launcher`
- **目标平台**: ESP32-S3 (Xtensa Dual-Core LX7, 8MB Octal PSRAM, 16MB Flash, 480x480 AMOLED)
- **创建日期**: 2026-10-04
- **状态**: 待办规划 (Proposed)

---

## 一、 背景与第一阶段成效回顾

### 1.1 第一阶段优化成效
通过实机基准测试与性能采样，已成功解决初版的重大启动阻塞：
1. **消除 CO5300 冗余延时**：将屏幕初始化命令序列中原硬编码的 `0x11`（Sleep Out 600ms）降至硬件规范的 `120ms`，`0x29`（Display ON 600ms）消除，单点节省 **1080 ms**。
2. **根治首帧绿光与杂波闪烁**：采用开机静默待机（Blanked Standby）+ 16ms DMA 纯黑预清屏 + 首帧写入完成后原子点亮（Atomic Unblanking）策略，消除了 AMOLED 上电电荷泵爬升期的偏色闪烁。
3. **性能飞跃**：冷启动到 AMOLED 呈现首帧的时间从 **1743 ms 压减到 686 ms（提速 60.6%）**。

### 1.2 当前各阶段耗时基准（总耗时 686 ms）

```text
 0 ms ───────► 上电复位 / ROM 引导 (5 ms)
 5 ms ───────► app_main() 启动
 5~423 ms ───► board_hal_init() (418 ms)
               ├─ hal_power_init: 4 ms
               ├─ hal_rtc_init: 3 ms
               ├─ board_display_init: 320 ms (含硬件复位 160ms + 120ms 休眠等待 + 16ms 黑屏清屏)
               ├─ board_touch_init: 80 ms (CST9217 I2C 硬件复位与探测)
               └─ board_button_init: 0 ms
423~487 ms ──► fs_init() (63 ms，挂载 LittleFS 分区)
487~537 ms ──► Rust board.init() (50 ms)
               ├─ ES8311 音频 Codec 初始化: 14 ms
               └─ Wi-Fi / NVS 协议栈初始化: 36 ms
537~686 ms ──► app-launcher 启动与首帧渲染 (149 ms)
               ├─ 静态字体载入与 Compositor 构建: 2 ms
               ├─ Launcher 及 6 个子应用实例化: 12 ms
               └─ 控件树构建、软件光栅化与 QSPI DMA 首帧刷写: 135 ms
686 ms ──────► 首帧在 AMOLED 屏幕点亮
```

在 686 ms 中，Rust 层及紧密协同的软件链路占据了约 **260 ms**（fs: 63ms + rust init: 50ms + launcher first frame: 149ms），具备显著的二次压减空间。

---

## 二、 架构设计与并行优化全景

通过**软硬件并行重叠**、**非关键服务异步化**以及**应用状态懒加载**，将原本串行的各个初始化阶段深度折叠：

```text
【当前串行执行流程】 (~686 ms)
├── 屏幕复位与休眠等待 (280ms) ──► 触控 (80ms) ──► LittleFS (63ms) ──► Wi-Fi初始化 (36ms) ──► 构造所有App (12ms) ──► 绘制首帧 (135ms) ──► 呈现
                                                                                                                      
【优化后折叠执行流程】 (预计 < 530 ms)
├── 屏幕复位 (160ms) ──────────────────────────┐
│   └── 触发 120ms 休眠等待 (FreeRTOS 让出 CPU)│
│       ├── [并发折叠 1] 挂载 LittleFS (63ms)  │ (完全隐藏在 120ms 硬件休眠期内)
│       └── [并发折叠 2] 异步初始化 CST 触控    │
├── 极速进入 Rust 运行时 ──────────────────────┴─► Core 1 (UI 主线程)
│                                                 ├─ 跳过 Wi-Fi 同步阻塞 ──► [并发折叠 3] (分流至 Core 0 异步初始化)
│                                                 ├─ 仅构造 Launcher 桌面 (子应用懒加载，~2ms)
│                                                 └─ 专注光栅化首帧九宫格与 DMA 并发
▼
AMOLED 首帧瞬时点亮 (预计 ~520 ms)
```

---

## 三、 详细优化方案与技术实现

### 3.1 优化点 1: Wi-Fi 协议栈后台异步/按需懒加载 (预计节省 30 ~ 36 ms)

#### 现状瓶颈
在 [`pomelo-firmware/firmware/components/rust_main/src/lib.rs`](../../pomelo-firmware/firmware/components/rust_main/src/lib.rs) 中，开机同步执行了 `board.init()`。
`board.init()` 内部调用了 [`self.wifi().init()`](../../pomelo-hal/src/board.rs#L98)：
- 调用 `nvs_flash_init()`
- 创建 Wi-Fi 核心守护任务（`wifi driver task`，栈 6656 字节，优先级 23）
- 分配 32 个动态收发 rx/tx 缓冲
- 这一连串底层协议栈操作**同步阻塞了 UI 主线程 36 ms**。而在用户开机看到主屏幕桌面（Launcher 九宫格）时，并不需要 Wi-Fi 已经进入连网就绪状态。

#### 改造方案
1. **方案 A（Core 0 后台并发，推荐）**：
   在 `rust_main_entry()` 中，将 Wi-Fi 初始化任务交给 FreeRTOS 后台线程或 Core 0 独立运行：
   ```rust
   // rust_main/src/lib.rs
   let board = pomelo_hal_esp32::board();
   
   // 音频/基础电源在主线程秒级就绪
   board.power().init().ok();
   
   // 将耗时的 Wi-Fi 协议栈下放至后台异步线程初始化
   let bg_board = Arc::clone(&board);
   std::thread::Builder::new()
       .name("wifi_init_worker".into())
       .spawn(move || {
           let _ = bg_board.wifi().init();
       })
       .expect("failed to spawn wifi init thread");
   
   // UI 线程立即启动 Launcher，节省 36ms 同步等待！
   app_launcher::program(board).run();
   ```
2. **方案 B（按需懒加载）**：
   在 `pomelo-hal-esp32` 的 `EspWifi` 实现中引入内部 `AtomicBool` 或 `OnceCell`，开机仅注册结构体，直到状态栏首次请求 Wi-Fi 信号或 Settings 开启 Wi-Fi 时再触发 `esp_wifi_init()`。

---

### 3.2 优化点 2: Launcher 子应用状态懒加载 (Lazy Apps) 【已完成 / In-Tree】
- **现状分析**：
  在 `Launcher::new` 中，一次性同步初始化了 6 个内置应用：
  - `Calculator::new()`
  - `Counter::new()`
  - `Hello::new()`
  - `Settings::new(Arc::clone(&board))`
  - `Player::new(Arc::clone(&board))`（同步扫描 LittleFS / SD 卡音轨）
  - `Terminal::new()`（分配虚拟终端 VT100 字符矩阵及按键布局）
  在开机启动阶段，处于前台的仅有 `Screen::Grid`（桌面九宫格）。开机同步构造全部 6 个应用消耗了 **~12 ms** 的 CPU 计算时间，且提前锁定了 PSRAM 堆空间。
- **落地改造方案**：
  1. 将 `Launcher` 结构体中的 6 个应用字段由直接持有修改为 `Option<App>`，开机 `Launcher::new()` 时全部置为 `None`。
  2. 实现惰性加载辅助器 `get_or_create_*(&mut self)`：仅在用户首次点击对应图标（`Message::Open(index)`）或收到该应用的直接事件时才按需实例化，并将当前的 `self.preferences` 和屏幕尺寸传入。
  3. 当应用退出/被清理（`kill_app(index)`）时，将其置回 `None`，真正释放其持有的堆内存与资源缓冲区。
  4. 首屏渲染与全局订阅仅对当前实际加载在内存中的应用进行遍历与处理。
- **达成成效**：
  - `Launcher::new()` 耗时由原先的 ~12 ms 压降至 **< 1 ms**（节省 ~11 ms 启动 CPU 时间）。
  - 开机瞬间避免了音乐播放器的文件系统扫描及终端字符缓冲区的 PSRAM 堆占用。
  - 所有单元测试（15/15 passed）100% 通过，并新增了懒加载与内存释放的自动化防回归测试。

---

### 3.3 优化点 3: 硬件休眠期的跨模块并发折叠 (预计折叠消除 50 ~ 63 ms)

#### 现状瓶颈
在 [`pomelo-firmware/firmware/main/main.c`](../../pomelo-firmware/firmware/main/main.c) 中：
```c
esp_err_t err = board_hal_init(); // 耗时 418 ms (包含屏幕 120ms 的 vTaskDelay 等待)
fs_init();                        // 耗时 63 ms (挂载 LittleFS)
rust_main_entry();                // 之后才进入 Rust
```
在 [`board_display.c`](../../pomelo-firmware/firmware/components/board_hal/board_display.c) 发送 `0x11`（Sleep Out）时，按照规格需要等待 120ms。在这 120ms 期间，屏幕控制器处于内部电荷泵升压阶段，CPU 完全处于 `vTaskDelay` 空闲状态！而随后执行的 `fs_init()` 耗时 63ms，两者完全是串行的。

#### 改造方案
调整 C 语言入口的调度流水线：
1. `board_display_init()` 发出 `0x11` 命令后，启动非阻塞定时器或将后续初始化异步化。
2. 利用这 120ms 的“硬件等待窗口”，**在 CPU 端同步执行 `fs_init()`（挂载 LittleFS）以及基础外设配置**。
3. 当 120ms 硬件等待期结束时，文件系统挂载正好完成！
- **收益**：直接将 `fs_init()` 的 **63 ms** 完全折叠消除在必须等待的屏幕硬件窗口中。

---

### 3.4 优化点 4: 首帧渲染管线与 DMA 光栅化吞吐优化 (预计节省 15 ~ 25 ms)

#### 现状瓶颈
首帧光栅化与 DMA 传输占据了 **135 ms**。
1. **PSRAM 缓存与总线抖动**：第一帧需要将整个 480×480（460 KB）的背景色、九宫格图标、阴影、圆角框从 PSRAM 逐像素光栅化。
2. **字体首载开销**：首帧包含桌面图标文字，`fontdb` 首次解构字形会有微小命中开销。

#### 改造方案
1. **QSPI 时钟频率稳健性验证**：
   目前 [board_display.c](../../pomelo-firmware/firmware/components/board_hal/board_display.c#L201) 配置的时钟为 `60MHz`。在硬件高驱动强度（High Drive Strength）下，测试 80MHz QSPI 的稳定性：
   - 60MHz DMA 460KB: ~15.3 ms (纯传输时间)
   - 80MHz DMA 460KB: ~11.5 ms (纯传输时间，节省 ~4ms)
2. **纯色背景快速填充指令**：
   在 `pomelo-gfx` 的清屏与矩形填充中，引入 Xtensa 32-bit 密集写与对齐展开，避免逐像素 16-bit 窄写引发的 PSRAM 缓存频繁写回。

---

## 四、 实施路线图与验收指标

### 4.1 实施阶段建议

- [x] **优化点 2（已完成）：Launcher 子应用懒加载（Lazy Hosted Apps）**:
  - `Launcher` 中所有子应用转为 `Option<T>` 并在用户点击图标时惰性加载，退出时清空引用释放 PSRAM 内存。
  - **实测收益**: 单元测试 15/15 全部通过，`Launcher::new()` 开机耗时降至 < 1 ms（节省 ~11 ms），避免开机文件扫描与虚拟控制台缓冲区分配。
- [ ] **优化点 1：Wi-Fi 协议栈后台异步初始化**: 
  - 将 `board.wifi().init()` 移至后台 FreeRTOS 任务异步启动。
  - **预期效果**: 启动时间压减 30~36 ms。
- [ ] **优化点 3：软硬件流水线深度折叠**:
  - 在 C 入口流水线中利用屏幕 120ms 延时空窗期并发执行 `fs_init()`。
  - **预期效果**: 消除 63 ms 串行等待，启动时间大幅压缩至 **~550 ms（约 0.55 秒）**。

### 4.2 验收指标
1. **启动时间指标**: 从冷启动上电（0 ms）到 480×480 AMOLED 完整点亮首帧，总耗时控制在 **550 ms** 以内。
2. **视觉无瑕体验**: 维持当前的 0 闪烁、0 绿光、纯黑无缝直出桌面的工业级视觉效果。
3. **功能完整性**: 异步化后 Wi-Fi 信号图标、设置页面配网、各个子应用首次点击响应无异常卡顿。
