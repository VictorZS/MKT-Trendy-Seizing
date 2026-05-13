# 🔥 MKT-Trendy-Seizing

热点情报监测系统 — 抖音 / 微博 / B站 / 主流媒体 四路信源并行抓取，定时推送到飞书。

> **MKT = Market Intelligence**，核心定位：帮助市场/运营人员第一时间抓牢热点红利。

## 功能特性

| 信源 | 方式 | 默认数量 | 可配置 |
|------|------|---------|--------|
| 抖音实时上升热点 | Playwright Browser 模拟获取 Cookie → 调用 API | Top 20 | ✅ |
| 微博热搜 | API 直连（走代理） | Top 15 | ✅ |
| B站全站热榜 | API 直连 + 代理 Fallback | Top 15 | ✅ |
| 主流媒体 | RSS（36kr + 网易） | Top 5 | ✅ |

- **四路并行抓取**，总耗时 < 15s
- **Browser 模拟**解决抖音 API 鉴权问题
- 定时任务（每小时）推送到**飞书**
- 原始数据本地存储（JSON）
- 支持**选择性关闭**任意信源
- 支持**调整每个信源的条目数量**

---

## ⚙️ 安装与配置

### 快速安装

```bash
git clone https://github.com/YOUR_USER/MKT-Trendy-Seizing.git
cd MKT-Trendy-Seizing
bash install.sh
```

### 手动安装

```bash
pip install -r requirements.txt
playwright install chromium
cp config.example.json config.json
# 编辑 config.json
```

### config.json 配置项

```json
{
  "feishu_user_id": "飞书 open_id",
  "http_proxy": "http://127.0.0.1:1082",
  "socks5_proxy": "socks5://127.0.0.1:17890",
  "douyin_cookies": "",
  "sources": {
    "douyin":    { "enabled": true,  "rank_limit": 20 },
    "weibo":     { "enabled": true,  "rank_limit": 15 },
    "bilibili":  { "enabled": true,  "rank_limit": 15 },
    "mainstream":{ "enabled": true,  "rank_limit": 5  }
  }
}
```

**调整示例：**
- 只监测抖音和微博：`"bilibili": {"enabled": false}`, `"mainstream": {"enabled": false}`
- 抖音只抓 Top10：`"douyin": {"rank_limit": 10}`
- 微博只抓 Top5：`"weibo": {"rank_limit": 5}`

---

## 🚀 快速开始

```bash
# 运行一次
python scripts/hot_monitor_v1.py

# 定时任务（每小时）
0 * * * * /path/to/MKT-Trendy-Seizing/scripts/hot_monitor_v1.py
```

---

## 📡 飞书接入

确认 `config.json` 中 `feishu_user_id` 正确（必须是 lark-cli 应用下的 open_id）。

给机器人发送任意消息，通过 `lark-cli` 日志确认 open_id。

---

## 🔧 常见问题

**Q: 抖音返回空？**
A: 抖音 API 需要浏览器 Cookie 中的 `__ac_signature`。Playwright 自动获取，如持续失败可手动注入 Cookie（`config.douyin_cookies`）。

**Q: 微博返回空？**
A: 确保 HTTP 代理可用，微博 API 必须走代理。

**Q: B站一直是 0 条？**
A: 直连失败后自动走代理 Fallback，确认代理配置正确。

**Q: 飞书收不到消息？**
A: 确认 `feishu_user_id` 是 lark-cli 对应应用的 open_id（openclaw 和 lark-cli 是不同飞书应用，open_id 不互通）。

---

## 📦 其他 Agent 接入说明

MKT-Trendy-Seizing 可作为 **Hermes Agent Skill** 使用。

### 安装到 Hermes

```bash
# 把项目放入 Hermes skills 目录
cp -r MKT-Trendy-Seizing ~/.hermes/skills/
```

### 设置定时任务

在 Hermes 中创建 cron 任务：

```
/cron create --name "热点监测 · 每小时" \
  --schedule "0 * * * *" \
  --skills hot-monitor \
  --prompt "运行 hot_monitor_v1.py，抓取四路热点并推送飞书"
```

### Skill 触发词

- "热点监测"、"每小时热点"、"热点报告"
- "监测抖音+微博"、"只测微博热搜"

---

## 🗺️ 未来路线图

| 版本 | 功能 |
|------|------|
| v1.0 | 四路信源抓取 + 飞书推送（当前版本） |
| v1.1 | 直播间数据跟踪：淘宝/抖音/京东官方旗舰店 |
| v1.2 | 抖音达人直播数据抓取（GMV/在线人数/热度） |
| v2.0 | 多维度热度分析 + 趋势预测 |

---

## License

MIT
