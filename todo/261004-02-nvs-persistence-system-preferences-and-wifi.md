# 任务规划: 基于 NVS 的系统偏好设置持久化与 Wi-Fi 凭据自动重连

- **所属模块**: `pomelo-firmware/board_hal`, `pomelo-hal`, `pomelo-apps/app-launcher`, `pomelo-apps/settings`
- **目标平台**: ESP32-S3 (16MB Flash, 24KB NVS 分区) + Desktop Simulator
- **创建日期**: 2026-10-04
- **状态**: 待办规划 (Proposed)

---

## 一、 背景与现状剖析

当前系统在掉电与重启场景下存在两处未闭环的持久化体验问题：

### 1.1 系统偏好设置（SystemPreferences）掉电即失
- **现状**: 在 [`app-launcher/src/lib.rs`](../../pomelo-apps/app-launcher/src/lib.rs#L214) 中，每次开机固定构造 `SystemPreferences::default()`（中文、暗黑主题、标准 24px 字号）。
- **影响**: 用户在 Settings App 中对语言、主题外观、字体大小所做的修改，仅在内存中通过 `propagate_preferences()` 分发给各子应用；设备关机或软重启后，所有自定义设置均被重置。

### 1.2 Wi-Fi 凭证已存但未自动重连
- **现状**: 在 [`board_wifi.c`](../../pomelo-firmware/firmware/components/board_hal/board_wifi.c#L352) 中调用 `esp_wifi_set_config(WIFI_IF_STA, &wc)` 时，ESP-IDF 底层（默认 `WIFI_STORAGE_FLASH` 模式）已将上一次连接成功的 SSID 与密码加密保存在 NVS 分区的 `nvs.net80211` 内部空间。
- **缺陷**: 
  1. 开机时，`board_wifi_init()` 将无线网卡初始化为 Radio Off；
  2. 当系统或用户开启 Wi-Fi（`hal_wifi_set_enabled(true)`）时，驱动仅调用了 `esp_wifi_start()`，**未主动发起 `esp_wifi_connect()`**；
  3. 内存中的 `s_ssid` 与状态初始化为空，导致开机后上层状态栏和 Settings 显示为“未连接”，必须由用户再次点击连网。

### 1.3 存储介质选型：为什么选择 NVS？
开发板在 [`partitions.csv`](../../pomelo-firmware/firmware/partitions.csv) 中已规划并格式化了 `0x6000`（24 KB）的 `nvs` 分区，且 `nvs_flash_init()` 在开机时已由 Wi-Fi 模块初始化就绪：
- **原生 Key-Value 接口**: 天然契合几字节的小配置项存储（`theme`, `language`, `font_tier`, `volume`）。
- **掉电原子性与磨损均衡 (Wear-Leveling)**: 具有校验和与日志回滚机制，即使在用户刚切完主题的一瞬间拔电池断电，也不会破坏存储。
- **零系统开销**: 无需依赖 VFS 与 SPIFFS 文件系统挂载，零内存堆栈负担。

---

## 二、 架构设计与实现方案

```text
┌────────────────────────────────────────────────────────┐
│               Settings App / 用户交互层                │
└───────────────────────────┬────────────────────────────┘
                            │ 发送 Message::SetTheme / SetLanguage / CycleFontTier
┌───────────────────────────▼────────────────────────────┐
│                  Launcher::update()                    │
│           (检测到 new_prefs != old_prefs)              │
└─────────────┬────────────────────────────┬─────────────┘
              │ 内存分发                   │ 触发持久化
┌─────────────▼──────────────┐ ┌───────────▼─────────────┐
│  各子应用 (Calculator/     │ │    Board::preferences   │
│  Terminal/Music/Settings)  │ │   .save(&preferences)   │
└────────────────────────────┘ └───────────┬─────────────┘
                                           │
         ┌─────────────────────────────────┴─────────────────────────────────┐
         ▼ (桌面端 Simulator)                                                ▼ (ESP32 实机)
┌──────────────────────────────────┐                       ┌──────────────────────────────────┐
│ pomelo-hal/sim:                  │                       │ pomelo-hal-esp32:                │
│ 读写本地 ~/.pomelo/config.json    │                       │ FFI 调用 hal_pref_save()         │
└──────────────────────────────────┘                       └─────────────────┬────────────────┘
                                                                             │
                                                           ┌─────────────────▼────────────────┐
                                                           │ board_hal / NVS 命名空间:        │
                                                           │   "sys_pref" (theme, lang, font) │
                                                           └──────────────────────────────────┘
```

---

## 三、 详细设计

### 3.1 NVS 命名空间与数据格式

#### 1. 系统偏好命名空间: `"sys_pref"`
| 键名 (Key) | 类型 | 取值范围 | 说明 |
| :--- | :--- | :--- | :--- |
| `magic` | `u16` | `0x504F` ("PO") | 校验魔数，用于识别 NVS 中是否已写入有效偏好 |
| `lang` | `u8` | 0: Chinese, 1: English | 界面语言 |
| `theme` | `u8` | 0: Dark, 1: Light | 主题外观 (AMOLED 深色 / 浅色) |
| `font_tier` | `u8` | 0: 18px, 1: 20px, 2: 24px, 3: 30px | 全局正文字号阶次 |
| `volume` | `u8` | 0 ~ 100 | 系统媒体音量 (可选) |

C 端传输结构体定义（紧凑排列）：
```c
typedef struct __attribute__((packed)) {
    uint16_t magic;
    uint8_t  language;
    uint8_t  theme;
    uint8_t  font_tier;
    uint8_t  volume;
} hal_sys_pref_t;
```

#### 2. Wi-Fi 凭证与自动重连命名空间
- 维持 ESP-IDF 内部 `nvs.net80211` 对 SSID / Password 的自动保存。
- 另增可选项（例如 `"wifi_pref"` -> `auto_connect: u8`），用于控制是否开机自动启用无线。

---

### 3.2 模块实现步骤

#### 任务 1: C 驱动层实现偏好存取与 Wi-Fi 自动连网
1. **新建 [board_pref.c](file:///home/edward/Projects/pomelo-ui/pomelo-firmware/firmware/components/board_hal/board_pref.c)**:
   - 提供 `esp_err_t hal_pref_load(hal_sys_pref_t *out_pref);`
   - 提供 `esp_err_t hal_pref_save(const hal_sys_pref_t *pref);`
   - 若 `load` 时发现 NVS 无数据或魔数不匹配，返回 `ESP_ERR_NOT_FOUND`，由上层回退至默认配置。
2. **完善 [board_wifi.c](file:///home/edward/Projects/pomelo-ui/pomelo-firmware/firmware/components/board_hal/board_wifi.c)**:
   - 在 `hal_wifi_set_enabled(true)` 执行 `esp_wifi_start()` 成功后，通过 `esp_wifi_get_config(WIFI_IF_STA, &wc)` 检查 NVS 中是否已有配置好的 SSID。
   - 若存在有效 SSID（长度 $>0$），自动触发 `esp_wifi_connect()`，将 `s_conn_state` 置为 `CONNECTING`，并拷贝已存 SSID 至 `s_ssid`。
   - 监听 `WIFI_EVENT_STA_START` 事件以支持事件驱动重连。

#### 任务 2: Rust HAL 层（`pomelo-hal`）扩展配置抽象
1. 在 `pomelo-hal` 的 `Board` 或新增 `PreferencesBackend` trait：
   ```rust
   pub trait PreferencesBackend: Send + Sync {
       fn load(&self) -> Option<SystemPreferences>;
       fn save(&self, prefs: &SystemPreferences) -> Result<(), HalError>;
   }
   ```
2. **ESP32 实机实现** (`pomelo-hal-esp32`):
   - FFI 绑定 `hal_pref_load` 和 `hal_pref_save`。
3. **桌面模拟器实现** (`pomelo-hal/src/sim`):
   - 优先读写项目根目录或配置目录（`./.pomelo_preferences.json`），如无权限则回退内存存储，保证桌面测试与模拟器的良好体验。

#### 任务 3: 上层启动器（`app-launcher`）接管加载与保存
1. **开机加载**:
   ```rust
   let initial_preferences = board.preferences()
       .and_then(|p| p.load())
       .unwrap_or_default();
   ```
2. **变更实时防抖保存**:
   - 在 `Launcher::update` 处理 `Message::Settings` 时，一旦检测到偏好发生变化（`self.preferences != new_prefs`），除了调用 `propagate_preferences()` 之外，调用 `board.preferences().save(&new_prefs)`。

---

## 四、 验收测试标准

1. **偏好设置掉电保持测试**:
   - 在 Settings App 中将语言切换为 English，主题切换为 Light，字号切换为 Large (30px)。
   - 按下 Reset 按键或断开供电重新上电。
   - **预期**: 系统开机第一帧即呈现英文、浅色模式与大号字体，设置项无缝继承。
2. **Wi-Fi 断电自动重连测试**:
   - 在 Settings App 中连接目标 Wi-Fi 路由器并成功获取 IP。
   - 重启设备，进入系统或开启 Wi-Fi 开关。
   - **预期**: 无需用户再次输入密码或点击连接，系统在 3~5 秒内自动连接至该路由器并获取 IP，状态栏正确点亮 Wi-Fi 信号图标。
3. **桌面模拟器测试**:
   - 运行 `cargo test -p app-launcher` 与 `cargo test -p settings`，验证所有测试用例继续保持 100% 通过。
