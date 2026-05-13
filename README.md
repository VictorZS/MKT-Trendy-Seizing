# 🔥 MKT-Trendy-Seizing

> **我是谁**：热点情报监测系统 v1.0
> **我能做什么**：抓取 抖音 / 微博 / B站 / 主流媒体 四路热点，汇总后推送到飞书
> **适用场景**：每小时自动监测热点，市场/运营人员第一时间发现热点红利

---

## ✅ v1.0 能力清单

| 能力 | 实现方式 | 默认数量 | 可关闭 |
|------|---------|---------|--------|
| 抖音实时上升热点 | Playwright 模拟浏览器获取 Cookie → 调用 API | Top 20 | ✅ |
| 微博热搜 | API 直连（需 HTTP 代理） | Top 15 | ✅ |
| B站全站热榜 | API 直连 + 代理 Fallback | Top 15 | ✅ |
| 主流媒体资讯 | RSS（36kr + 网易） | Top 5 | ✅ |
| 飞书推送 | lark-cli 发送消息到指定 open_id | — | ✅ |
| 原始数据存储 | JSON 文件本地落盘 | — | ✅ |

---

## ⚙️ 可配置项（config.json）

```json
{
  "feishu_user_id": "ou_xxxxxxxxxxxx",
  "http_proxy": "http://127.0.0.1:1082",
  "socks5_proxy": "socks5://127.0.0.1:17890",
  "douyin_cookies": "",
  "sources": {
    "douyin":     { "enabled": true,  "rank_limit": 20 },
    "weibo":      { "enabled": true,  "rank_limit": 15 },
    "bilibili":   { "enabled": true,  "rank_limit": 15 },
    "mainstream": { "enabled": true,  "rank_limit": 5  }
  }
}
```

### 信源开关

| 配置 | 效果 |
|------|------|
| `"douyin": {"enabled": false}` | 关闭抖音，只监测其他三路 |
| `"weibo": {"enabled": false}` | 关闭微博 |
| `"bilibili": {"enabled": false}` | 关闭B站 |
| `"mainstream": {"enabled": false}` | 关闭主流媒体 |

### 数量调整

| 配置 | 效果 |
|------|------|
| `"douyin": {"rank_limit": 10}` | 抖音只抓 Top 10 |
| `"weibo": {"rank_limit": 5}` | 微博只抓 Top 5 |
| `"bilibili": {"rank_limit": 10}` | B站只抓 Top 10 |
| `"mainstream": {"rank_limit": 3}` | 主流媒体只抓 Top 3 |

### 常用配置示例

```json
// 只监测抖音和微博
{ "douyin": {"enabled": true, "rank_limit": 20}, "weibo": {"enabled": true, "rank_limit": 15}, "bilibili": {"enabled": false}, "mainstream": {"enabled": false} }

// 快速测试（只测微博5条）
{ "douyin": {"enabled": false}, "weibo": {"enabled": true, "rank_limit": 5}, "bilibili": {"enabled": false}, "mainstream": {"enabled": false} }

// 全开，抖音只抓10条
{ "douyin": {"enabled": true, "rank_limit": 10} }
```

---

## 🚀 安装（其他 Agent 使用）

### 方式一：作为 Hermes Skill 安装

```bash
# 1. 把项目克隆到 Hermes skills 目录
cp -r MKT-Trendy-Seizing ~/.hermes/skills/hot-monitor

# 2. 安装依赖
cd ~/.hermes/skills/hot-monitor
pip install -r requirements.txt
playwright install chromium

# 3. 复制并编辑配置
cp config.example.json config.json
# 编辑 config.json，填入 feishu_user_id 和代理

# 4. 创建定时任务（每小时）
/cron create --name "热点监测 · 每小时" --schedule "0 * * * *" --skills hot-monitor --prompt "运行热点抓取脚本，四路信源并行抓取，结果推送飞书"
```

### 方式二：独立运行

```bash
git clone https://github.com/VictorZS/MKT-Trendy-Seizing.git
cd MKT-Trendy-Seizing
bash install.sh
python scripts/hot_monitor_v1.py
```

---

## 🔔 触发方式

对我说话时使用以下触发词，我会自动执行热点抓取：

- "热点监测"、"每小时热点"、"抓热点"
- "测一下抖音+微博"、"只测微博热搜"
- "热点报告"、"生成今日热点"

---

## 📡 飞书推送说明

推送使用 `lark-cli`，需要填写正确的 `feishu_user_id`（必须是 lark-cli 对应应用的 open_id，不是 openclaw 的 open_id）。

---

## 🔧 依赖环境

- Python 3.8+
- `playwright`（Browser 模拟）
- `urllib3`（HTTP 请求）
- `lark-cli`（飞书消息推送）
- HTTP 代理（微博/抖音 API 需要）
- SOCKS5 代理（Playwright Chromium 浏览器流量）

---

## 🗺️ Roadmap

| 版本 | 功能 |
|------|------|
| v1.0 | 四路信源抓取 + 飞书推送 ✅ |
| v1.1 | 直播间数据跟踪（官方旗舰店）🔄 |
| v1.2 | 抖音达人直播数据抓取（GMV/在线人数） |
| v2.0 | 多维度热度分析 + 趋势预测 |

---

## License

MIT
