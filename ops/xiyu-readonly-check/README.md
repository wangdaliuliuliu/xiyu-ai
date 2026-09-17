# 溪语只读体检工具

这个文件夹是**一次性配置 + 一键体检**的工具，**不是溪语的项目代码**。

- 只读服务器：只查询、只查看、只算指纹
- **不修改、不重启、不删除**服务器上任何东西
- **不读取、不保存任何密码或密钥**
- **不碰 LIMI 和 capybara-game** 的任何目录、数据库、服务

---

## 服务器上有哪些项目

| 项目 | 目录 | 服务 | 端口 | 本次范围 |
|---|---|---|---|---|
| **溪语** | `/opt/xiyu-ai` | `xiyu-ai.service` | 3000 | ✅ 本次对象 |
| **经营工作台** | `/opt/yuanqu-workbench-api` | `yuanqu-workbench-api.service` | 4175 | ✅ 溪语业务链 |
| **LIMI** | `/home/admin/LIMIbackend` | `limi-backend.service` | 8000 | ❌ **绝对不动** |
| **Capybara Game** | `/opt/capybara-game` | PM2 `limi-kid` | 18001 | ❌ **绝对不动** |

**关键事实**：登录账号是 `admin`，而 LIMI 的目录正好在 `/home/admin/` 下 ——
也就是说 `admin` 对 LIMI 是有权限的。所以本工具**不靠"保证不碰"，而是把命令写死**：
不列 LIMI 路径、不开 LIMI 的库、不显示 LIMI 的进程。

**权限切换**：溪语服务以系统用户 `xiyu` 运行，读生产数据库时需要
`sudo -u xiyu ...` 切换，但**登录账号始终是 `admin`**。不尝试 root 登录。

---

## 第一步：让服务器认识这台电脑

### 1-1 密钥已经生成好了 ✅

`C:\Users\Administrator\.ssh\` 下有两把溪语只读专用密钥，**用免密那把**：

| 密钥 | 状态 | 用途 |
|---|---|---|
| `xiyu-readonly-nopass` | ✅ 免密，**当前在用** | 自动化登录，无需任何交互 |
| `xiyu-readonly` | ❌ 带 passphrase，passphrase 已丢失 | 已废置，仅留作历史 |

**免密密钥的公钥**（可以公开）：

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDq/tXv6JvJkM5iFn4GQfG5L0Sif/TCjAwDun98UpGHC xiyu-readonly-nopass
```

### 1-2 把公钥贴到服务器上（在服务器执行一次）

**用 `admin` 登录**服务器后，粘贴这一整段：

```bash
mkdir -p /home/admin/.ssh
chmod 700 /home/admin/.ssh
echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDq/tXv6JvJkM5iFn4GQfG5L0Sif/TCjAwDun98UpGHC xiyu-readonly-nopass' >> /home/admin/.ssh/authorized_keys
chmod 600 /home/admin/.ssh/authorized_keys
```

### 1-3 为什么原来那把会失败（重要，别再误诊）

旧密钥 `xiyu-readonly` 是**带 passphrase 加密**的。配合 `BatchMode=yes`
（绝不弹密码提示）会产生一个**极具误导性**的报错：

```
admin@39.106.153.59: Permission denied (publickey,password)
```

它看起来像「公钥没装好」或「权限不对」，**但两个都不是**。
用 `ssh -vvv` 看真实过程：

```
debug1: Server accepts key: ... xiyu-readonly ...      <-- 服务器已经认可这把公钥
debug3: sign_and_send_pubkey: signing using ssh-ed25519 ...
debug2: we did not send a packet, disable method       <-- 客户端放弃发送签名
admin@39.106.153.59: Permission denied (publickey,password).
```

也就是说：服务器说「这把钥匙可以」，客户端此时需要用 passphrase 解密私钥
才能完成签名，但 BatchMode 下无法询问，于是 OpenSSH **静默放弃**。

**判据**（不要再用「文件里有没有 `bcrypt` 字样」判断，私钥是 base64
编码，KDF 名不以明文出现）：

- 私钥头部前缀是 `b3BlbnNzaC1rZXktdjEAAAAABG5vbmU` → `cipher=none`，**未加密**
- 出现 `YWVzMjU2` / `YmNyeXB0` → `aes256-ctr` + `bcrypt`，**已加密**
- 或者直接跑 `ssh-keygen -y -f <私钥>`：**秒回=未加密；卡住不动=在等 passphrase**

若将来还想用带 passphrase 的密钥，先把 `ssh-agent` 服务设为自启
（`Set-Service ssh-agent -StartupType Automatic; Start-Service ssh-agent`），
再 `ssh-add` 一次并输入 passphrase，之后即可免交互使用。

### 1-4 让只读数据库查询免密（可选）

没报错就是成功了。这是唯一需要"写"的操作，只写 `admin` 自己的 `.ssh` 目录，
**完全不涉及 LIMI 和 capybara-game**。

### 1-3 让只读数据库查询免密（可选）

体检要读溪语的数据库，用 `sudo -u xiyu`。如果每次都要输密码会卡住脚本。
在服务器上执行：

```bash
sudo visudo -f /etc/sudoers.d/xiyu-readonly
```

写入（把 `admin` 换成你的真实登录名，如果就是 admin 则不用改）：

```
admin ALL=(xiyu) NOPASSWD: /usr/bin/sqlite3
```

> 这条只允许 `admin` 以 `xiyu` 身份运行 `sqlite3`，**权限极小**。
> 不加也能跑，只是报告里 G 段会显示读取失败。

---

## 第二步：跑体检

### 2-1 先测连接

双击：

```
1-test-connection.bat
```

- 看到 **`CONNECTION OK`** → 通了，继续
- 看到 **`Permission denied`** → **不要直接断定「公钥没贴对」**。先看脚本有没有打出
  `LOCAL CAUSE FOUND: this private key is passphrase-protected`；有就是密钥带
  passphrase 的问题（见 1-3），公钥其实是好的
- 看到 **`FAILED`** → 网络问题，把屏幕上的字发我

### 2-2 再跑体检

双击：

```
2-run-check.bat
```

同文件夹会生成一个报告文件：

```
xiyu-check-result-日期-时间.txt
```

**用记事本打开它，把内容发我**（拖进聊天窗口即可）。里面不含密码和密钥。

---

## 关于中文显示

为了兼容所有 Windows 版本，**屏幕上显示的是英文**（避免乱码）。
**中文全部写在报告文件里**，用记事本打开就是正常中文。

所以你不用管屏幕上写了什么英文，**只要看到 `CONNECTION OK` 或
`REPORT SAVED` 就说明成功了**。

---

## 体检具体查什么

| 段 | 内容 | 对其他项目 |
|---|---|---|
| A | 服务器身份 | — |
| B | 溪语和工作台两个服务活着没有 | 只查这两个 |
| C | 溪语相关目录在不在 | 只查溪语目录 |
| D | `/opt` 下的目录 | **排除** capybara-game |
| E | 溪语相关服务清单 | 只列溪语两个服务 |
| F | **分区隔离检查** | 只显示溪语进程 |
| G | 溪语数据库有哪些表 | **只列表名** |
| H | 关键开关开关状态 | **值全部隐藏** |
| I | 生产文件指纹 | 只算溪语文件 |
| J | 溪语最近 30 行日志 | 只查溪语服务 |

**F 段最关键** —— 你印象中做过分区，这一段就是去证实它。
