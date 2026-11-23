# cellphone_as_typer：手机 → Ubuntu 光标处输入

手机浏览器打字 / 语音听写，文本自动粘贴到 Ubuntu 当前光标处。
安卓 / iPhone 通吃，不装 app；纯 Python 标准库，零 pip 依赖。

## 原理

**传"已上屏文本"，不传按键。** 中文转换在手机输入法完成（语音听写也用输入法的），
Ubuntu 侧收到最终文本后写入剪贴板并模拟粘贴键，文本落在当前焦点窗口光标处。

双后端自动选择（启动时按图形会话 seat 归属判别）：

| 后端 | 适用会话 | 剪贴板 | 按键 |
|---|---|---|---|
| `native-uinput` | 本地图形会话（Seat=seat0） | wl-copy | /dev/uinput 常驻虚拟键盘 |
| `headless-dbus` | GRD 远程登录 headless 会话（Seat 为空） | Mutter RemoteDesktop D-Bus 剪贴板所有权 | NotifyKeyboardKeysym |

原生后端搬运自 [kangfp/voice-type](https://github.com/kangfp/voice-type)（已验证），
改造为常驻键盘设备（启动付一次 0.3s 注册等待）。headless 后端走 GRD 自己的
compositor 层通道：`CreateSession → Start → EnableClipboard → SetSelection`
成为剪贴板所有者，应用粘贴时响应 `SelectionTransfer → SelectionWrite → SelectionWriteDone`；
按键用 keysym（与键盘布局无关）。单次发送实测 ~0.5–0.7s。

为什么不用别的：Wayland 禁 xdotool 全局注入；Ubuntu 24.04 仓库 ydotool 是 0.1.8
化石版本；蓝牙 HID 键盘只能发扫描码，中文是灾难；headless 会话无 seat，
wl-clipboard 与 uinput 都失效，只有 mutter D-Bus 通道可用。

### headless 后端血泪坑（改代码前必读）

1. **选项键名是 `mime-types`（连字符）**。传 `mime_types` 会被 mutter 静默忽略，
   SetSelection 清空所有权还返回 OK，永远等不到 SelectionTransfer
   （mutter 46 `meta-remote-desktop-session.c:1511` 核实）。
2. **不能用 wl-paste 报错判别 headless**：D-Bus 注入创建过 clutter 虚拟键盘后
   seat 获得 keyboard 能力，wl-paste 恢复正常，但 uinput 依然不被消费。
   必须查 `loginctl show-session <id> -p Seat`（空 = headless）。
3. python3-dbus 的 UnixFd 用 `.take()` 取 fd，不能 `int()`。
4. 依赖 python3-dbus + python3-gi（Ubuntu 桌面版预装，无需 pip/venv）。
5. 诊断工具：`deploy/probe_entry.py`（GTK Entry 记录器，记 FOCUS_IN/KEY/ENTRY，
   X11 与 Wayland 后端均可）、`deploy/inject_paste.py`、`deploy/probe_keys.py`。
   GNOME 46 的 Screenshot/GetWindows D-Bus 接口有白名单，普通客户端被拒。

## 安装（Ubuntu 桌面）

### deb 包安装（推荐）

从 [GitHub Release](https://github.com/kangfp/cellphone_as_typer/releases) 下载
`cellphone-as-typer_<版本>_all.deb`，然后：

```bash
sudo apt install ./cellphone-as-typer_1.2.0_all.deb
```

包自动完成：装依赖（python3-dbus / python3-gi / wl-clipboard）→ udev 规则落位 →
安装用户加 input 组 → enable + 启动用户服务 → 初始化每用户 token →
**安装输出里直接打印访问 URL 与终端二维码**，扫完即用。
旧的手动部署 / 旧包 cellphone-mic 自动迁移（保留 token，手机免重配）。

**加 input 组后必须注销重登**，再 `systemctl --user restart cellphone-as-typer`。

**打开位置**：应用菜单 → 「Cellphone As Typer / 手机输入」——配对窗口直接显示
二维码与 URL（手机扫码即用），「打开输入页」让桌面浏览器也能输入/分享二维码，
「轮换 token」一键换码；**「停止服务」按钮**可按喜好随时停用（停止后变为
「启动服务」一键恢复；只 stop 不 disable，下次登录会话仍自启）。
终端等价命令：`cellphone-as-typer-qr`。

日常命令（桌面用户身份，无需 sudo）：

```bash
cellphone-as-typer-qr           # 打印 URL / 终端二维码
cellphone-as-typer-qr --rotate  # 轮换 token 并重启服务
systemctl --user status cellphone-as-typer
```

卸载：`sudo apt remove cellphone-as-typer`；`purge` 会连用户配置（token）一起清除。

> 命名约定：项目/仓库名 `cellphone_as_typer`；deb 包名、服务名、命令用连字符
> `cellphone-as-typer`（Debian 包名规范不允许下划线）。

### 源码构建 deb（Debian/Ubuntu 上运行）

```bash
bash build-deb.sh    # 产出 build/deb/cellphone-as-typer_1.2.0_all.deb（Architecture: all）
```

### 手动部署（不用 deb 时）

```bash
bash deploy/setup.sh
```

setup.sh 会：装 wl-clipboard → 装 udev 规则 + 加 input 组 →
部署到 `~/.local/share/cellphone-as-typer/` → 生成 token（`~/.config/cellphone-as-typer/config.json`，0600）→
装 systemd 用户服务 → 打印手机 URL + **无条件输出终端二维码**。

若机器已具备 udev 规则 / input 组 / wl-clipboard（或只走 headless 后端），
可用免 sudo 版：`bash deploy/install-nosudo.sh`。

### 远程部署（可选）

从另一台机器经 SSH 一键推送源码并安装（需先打通 SSH 密钥）：

```bash
./deploy/deploy.sh <user>@<host>
```

### 冒烟测试（部署后第一件事）

在桌面上：

```bash
python3 deploy/smoke_test.py            # 3 秒内焦点点到 Text Editor → 光标处出中文
python3 deploy/smoke_test.py --terminal # 焦点放 GNOME Terminal → Ctrl+Shift+V
```

## 二维码（零依赖，装完即扫）

安装脚本无条件打印终端二维码（ANSI 白底黑块，深色终端下也可扫）。编码核心为
`third_party/qrcodegen.py`（Project Nayuki，MIT，v1.8.0，Python 3.8+），输出层
`qr.py` 纯标准库（终端 ANSI / 手写 PNG）——**不需要 qrencode、pip、额外 sudo**，
任何有 python3 的设备装完即有二维码。

三个入口：
- 安装时终端二维码（SSH 里直接扫）
- GTK 配对窗口 / `cellphone-as-typer-qr`：桌面随时调出二维码
- 网页「显示二维码」按钮 / `GET /qr.png?k=<token>`：分享给第二台设备的二维码图（需 token）

正确性验证：`tests/test_qr.py` 用 OpenCV 独立解码器回环（可选开发依赖
`opencv-python-headless`）。历史教训：曾与 segno 逐模块对照，发现 segno 在
terminator 后多插一个全零填充字节（与规范手算不符）——矩阵相等不是可靠判据，
独立解码器还原原文才是铁证。

## 使用

1. 电脑上也点好目标输入框（光标在哪，字就落在哪）
2. 手机打开 `http://<电脑局域网IP>:8765/?k=<token>`（扫安装时的二维码即可）
3. 打字或按输入法麦克风听写 → 「发送到电脑」

网页开关：
- **终端模式**：GNOME Terminal 等终端用 Ctrl+Shift+V 粘贴
- **发送后追加回车**：终端里直接跑命令（默认关；多行粘贴有终端确认弹窗兜底）
- **回车即发送**：默认关（手机回车应换行；中文输入法组合中的回车不会误触发）

token 记在手机 localStorage，杀后台重开不用重输。
轮换：`cellphone-as-typer-qr --rotate`（手动部署用 `bash deploy/setup.sh --rotate-token`）。

## 限制与已知副作用（读我）

- **焦点前提**：文本粘贴到 Ubuntu 当前焦点窗口，发送前先点好目标位置。
- **iPhone 不自动弹键盘**：iOS 只在用户手势中 focus 才弹软键盘，进页面先点一下输入框。
- **键盘布局依赖**：注入发的是扫描码（KEY_V），依赖 XKB 布局；默认 US/中文布局没问题，
  改冷门布局可能导致粘贴键失效。
- **会话生命周期**：服务挂 graphical-session.target，随图形会话起停，登录桌面即自启。
  headless GRD 会话断开 RDP 后仍存续，服务不掉。
- **注入失败不丢字**：按键注入失败时文本已在剪贴板，网页提示手动粘贴。

## 故障排查

| 症状 | 处置 |
|---|---|
| 状态灯绿但提示"键盘注入不可用" | `/dev/uinput` 权限：udev 规则 + input 组 + **注销重登** + 重启服务 |
| 文本只到剪贴板、光标处不出现 | 同上 |
| wl-copy 报找不到 display | run.sh 三级兜底应已覆盖；确认在图形会话内 `systemctl --user` |
| 手机打不开网页 | 电脑与手机是否同一局域网（`ip -4 addr` 查电脑 IP）；ufw 是否放行 8765 |
| 401 | token 轮换过 → 用新完整 URL 重开 |

## 安全

威胁模型是家庭局域网（家人/访客误触），不是对抗攻击者：
随机 token 门禁（X-Token 头 + 常数时间比较，顺带挡跨站伪造）、config 0600、
日志不落 token 不落内容、ufw 限源局域网网段、**不做路由器端口映射**。
粘贴内容无法逃逸成任意按键（只发 Ctrl+V / Ctrl+Shift+V / 可选回车）。

## 开发

```bash
python3 tests/test_server.py   # 任意有 python3 的机器可跑：fake injector 测路由/鉴权/并发
python3 tests/test_qr.py       # QR 回环（需可选开发依赖 opencv-python-headless）
python3 server.py --bind 127.0.0.1 --port 8765   # 本机前台起服务调网页（注入需 Ubuntu 图形会话）
```

文件：`server.py`（HTTP）、`injector.py`（原生后端 + 后端工厂）、`headless.py`
（D-Bus 后端）、`qr.py`（二维码输出层）、`third_party/`（Nayuki QR，MIT）、
`static/index.html`（网页）、`deploy/`（安装/探针/systemd）、`tests/`。

## v2 路线

实时模式（compositionend + 防抖，只追加不同步退格）、剪贴板回读校验加固、
PWA 图标、发送历史。
