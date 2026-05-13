# 👋 欢迎参与 MKT-Trendy-Seizing

---

## 🎯 项目定位

帮助市场/运营/数据分析人员第一时间抓牢热点红利：

- **即时性**：每小时自动抓取，不错过任何热点
- **跨平台**：抖音、微博、B站、主流媒体，一套系统全覆盖
- **可扩展**：支持直播间跟踪、达人数据等未来扩展方向

---

## 📌 v1.0 能力清单（已实现）

| 能力 | 说明 | 可配置 |
|------|------|--------|
| 抖音实时上升热点 Top 20 | Playwright Browser 模拟获取 Cookie → 调用 API | ✅ 数量 / ✅ 关闭 |
| 微博热搜 Top 15 | API 直连（需 HTTP 代理） | ✅ 数量 / ✅ 关闭 |
| B站全站热榜 Top 15 | API 直连 + 代理 Fallback | ✅ 数量 / ✅ 关闭 |
| 主流媒体 Top 5 | RSS（36kr + 网易） | ✅ 数量 / ✅ 关闭 |
| 飞书推送 | lark-cli 发送到指定 open_id | ✅ 关闭 |
| 原始数据存储 | JSON 文件本地落盘 | — |

---

## ⚙️ 配置项说明

### sources（信源开关 + 数量）

```json
"sources": {
  "douyin":     { "enabled": true,  "rank_limit": 20 },
  "weibo":      { "enabled": true,  "rank_limit": 15 },
  "bilibili":   { "enabled": true,  "rank_limit": 15 },
  "mainstream": { "enabled": true,  "rank_limit": 5  }
}
```

| 配置 | 效果 |
|------|------|
| `enabled: false` | 完全关闭该信源 |
| `rank_limit: N` | 调整抓取数量（建议 5~30） |

**常用配置示例：**

```json
// 只测抖音和微博
{ "douyin": {"enabled": true, "rank_limit": 20}, "weibo": {"enabled": true, "rank_limit": 15}, "bilibili": {"enabled": false}, "mainstream": {"enabled": false} }

// 快速测试（微博5条）
{ "douyin": {"enabled": false}, "weibo": {"enabled": true, "rank_limit": 5}, "bilibili": {"enabled": false}, "mainstream": {"enabled": false} }
```

### 代理配置

```json
"http_proxy": "http://127.0.0.1:1082",    // 微博/抖音 API 请求用
"socks5_proxy": "socks5://127.0.0.1:17890" // Playwright Chromium 浏览器流量用
```

### 飞书配置

```json
"feishu_user_id": "ou_xxxxxxxxxxxx"  // lark-cli 对应应用的 open_id
```

> ⚠️ 注意：openclaw 和 lark-cli 是不同飞书应用，open_id 不互通。请用 lark-cli 确认正确的 open_id。

---

## 🔌 作为 Hermes Skill 使用

### 安装

```bash
cp -r MKT-Trendy-Seizing ~/.hermes/skills/hot-monitor
cd ~/.hermes/skills/hot-monitor
pip install -r requirements.txt
playwright install chromium
cp config.example.json config.json
# 编辑 config.json
```

### 创建定时任务

```
/cron create --name "热点监测 · 每小时" --schedule "0 * * * *" --skills hot-monitor --prompt "运行热点抓取脚本，四路信源并行抓取，结果推送飞书"
```

### 手动触发

说出触发词即可：
- "热点监测"
- "每小时热点"
- "抓热点"
- "测一下抖音+微博"

---

## 🐛 报告问题

请提供：
1. 操作系统和 Python 版本
2. 脚本完整报错日志
3. `config.json`（脱敏后）的代理和 open_id 配置
4. 如果是抖音问题，说明是否手动注入了 Cookie

---

## 💡 贡献方向

- 新的信源（小红书、知乎热榜等）
- 数据分析模块（热度趋势、话题生命周期）
- 可视化仪表盘
- Docker 部署优化
- **直播间数据抓取（进行中，v1.1）**
