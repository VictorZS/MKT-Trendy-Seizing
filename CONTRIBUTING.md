# 👋 欢迎参与 MKT-Trendy-Seizing

MKT-Trendy-Seizing 是一个开源热点情报监测系统，欢迎任何形式的贡献。

---

## 🎯 项目定位

帮助市场/运营/数据分析人员第一时间抓牢热点红利：

- **即时性**：每小时自动抓取，不错过任何热点
- **跨平台**：抖音、微博、B站、主流媒体，一套系统全覆盖
- **可扩展**：支持直播间跟踪、达人数据等未来扩展方向

---

## 📌 v1.0 当前能力

### 已实现
- ✅ 抖音实时上升热点（Top 20，Playwright Browser 模拟）
- ✅ 微博热搜（Top 15，API 直连）
- ✅ B站全站热榜（Top 15，API 直连 + 代理 Fallback）
- ✅ 主流媒体 RSS（36kr + 网易，Top 5）
- ✅ 飞书定时推送
- ✅ 原始数据本地存储（JSON）

### 正在开发
- 🔄 直播间数据跟踪（淘宝/抖音/京东官方旗舰店）
- 🔄 抖音达人直播数据抓取

---

## ⚙️ 配置项说明

### 信源开关

在 `config.json` 的 `sources` 中：

```json
"sources": {
  "douyin":     { "enabled": true,  "rank_limit": 20 },
  "weibo":      { "enabled": true,  "rank_limit": 15 },
  "bilibili":   { "enabled": true,  "rank_limit": 15 },
  "mainstream": { "enabled": true,  "rank_limit": 5  }
}
```

| 配置项 | 说明 | 可选值 |
|--------|------|--------|
| `enabled` | 是否启用该信源 | `true` / `false` |
| `rank_limit` | 抓取条目数量 | 整数，建议 5-30 |

**常用配置示例：**

```json
// 只测抖音和微博
{ "douyin": {"enabled": true, "rank_limit": 20}, "weibo": {"enabled": true, "rank_limit": 15}, "bilibili": {"enabled": false}, "mainstream": {"enabled": false} }

// 只测微博（快速测试）
{ "douyin": {"enabled": false}, "weibo": {"enabled": true, "rank_limit": 5}, "bilibili": {"enabled": false}, "mainstream": {"enabled": false} }

// 减少B站条目
{ "bilibili": {"enabled": true, "rank_limit": 5} }
```

### 代理配置

```json
"http_proxy": "http://127.0.0.1:1082",    // 微博/抖音 API 用
"socks5_proxy": "socks5://127.0.0.1:17890" // Playwright Chromium 浏览器流量用
```

### 飞书配置

```json
"feishu_user_id": "ou_xxxxxxxxxxxx"  // 飞书 open_id
```

---

## 🔌 作为 Hermes Skill 使用

### 安装
```bash
cp -r MKT-Trendy-Seizing ~/.hermes/skills/
```

### 创建定时任务
```
/cron create --name "热点监测" --schedule "0 * * * *" --skills hot-monitor
```

### 手动触发
```
热点监测
```

---

## 🐛 报告问题

请提供：
1. 操作系统和 Python 版本
2. 脚本完整报错日志
3. `config.json`（脱敏后）的代理和 open_id 配置
4. 如果是抖音问题，说明是否手动注入了 Cookie

---

## 💡 贡献方向

- 新的信源（如小红书、知乎热榜）
- 数据分析模块（热度趋势、话题生命周期）
- 可视化仪表盘
- Docker 部署优化
- 直播间数据抓取（进行中）
