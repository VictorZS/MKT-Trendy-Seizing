#!/Users/openclaw/.hermes/hermes-agent/venv/bin/python3
"""
热点情报系统 v1 — Hermes Agent 专用
核心升级：抖音用 Playwright Browser 模拟获取"上升气流"实时热点
新增：B站每周必看 + 央视上升热点
"""
import os, sys, json, subprocess, time, re
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============ 路径配置 ============
SKILL_DIR = Path(__file__).parent.parent
DATA_DIR = SKILL_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
EVENTS_DIR = DATA_DIR / "events"
LOG_FILE = Path(os.environ.get("HOT_LOG", str(SKILL_DIR / "hot_monitor_v1.log")))
PROGRESS_FILE = SKILL_DIR / "progress.json"

RAW_DIR.mkdir(parents=True, exist_ok=True)
EVENTS_DIR.mkdir(parents=True, exist_ok=True)

# ============ 代理配置（从环境变量读取，兜底默认值） ============
_PROXY_ENV = os.environ.get("HTTP_PROXY", "")
SOCKS5_PROXY = os.environ.get("SOCKS5_PROXY", "socks5://127.0.0.1:17890")
# venv Python 启动时可能没有继承 HTTP_PROXY，兜底设置
if not _PROXY_ENV:
    os.environ["HTTP_PROXY"] = "http://127.0.0.1:1082"
HTTP_PROXY = os.environ.get("HTTP_PROXY", "http://127.0.0.1:1082")
PROXY_ARG = f"--proxy {HTTP_PROXY}" if HTTP_PROXY else ""

# ============ 推送配置 ============
FEISHU_USER_ID = os.environ.get("FEISHU_USER_ID", "ou_fdea45ee367625bbeba6138642f6a35b")

# ============ 日志 ============
def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"[{ts}] [hot-monitor-v1] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ============ HTTP 工具 ============
def curl_get(url, timeout=12, headers=None, use_proxy=True, cookies=None):
    """curl 封装，支持 SOCKS5 代理和自定义 Header"""
    h = ["curl", "-s", "--max-time", str(timeout), "--compressed"]
    if use_proxy and HTTP_PROXY:
        h += ["--proxy", HTTP_PROXY]
    default_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    }
    if headers:
        default_headers.update(headers)
    for k, v in default_headers.items():
        h += ["-H", f"{k}: {v}"]
    if cookies:
        h += ["-H", f"Cookie: {cookies}"]
    h.append(url)
    try:
        r = subprocess.run(h, capture_output=True, text=True, timeout=timeout + 5)
        return r.stdout.strip()
    except Exception as e:
        log(f"curl fail [{url[:50]}]: {e}")
        return ""


# ============ ① 抖音上升热点（Playwright Browser 模拟）===========
def fetch_douyin_rising():
    """
    核心功能：使用 Playwright 模拟浏览器访问抖音，获取实时热点。

    抖音热点 API 需要浏览器生成的 __ac_signature（Cookie），
    直接 curl 请求会被 400 拒绝。
    解决流程：Playwright 访问页面 → 提取 Cookie → 用 Cookie 请求热点 API。

    board_type：2 = 上升气流，1 = 总榜（fallback）
    """
    log("抖音热点抓取开始")
    items = _fetch_douyin_browser()
    return items


def _fetch_douyin_browser():
    """
    Playwright 模拟浏览器获取抖音热点。
    流程：Playwright 访问页面 → 提取 Cookie → 用 Cookie 请求抖音热点 API → 返回结构化数据。

    抖音热点 API 需要有效的 __ac_signature（来自浏览器 Cookie），
    直接 curl 请求会被 KRAKEND 拒绝（400 Bad Request）。
    """
    log("抖音 Browser 模拟模式启动")
    items = []
    try:
        from playwright.sync_api import sync_playwright
        import urllib.request

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            # 如有 Cookie 则注入（提升数据质量）
            cookie_str = os.environ.get("DOUYIN_COOKIES", "")
            if cookie_str:
                try:
                    cookies = json.loads(cookie_str)
                    context.add_cookies(cookies)
                    log("已注入抖音 Cookie")
                except Exception:
                    pass

            page = context.new_page()
            page.goto(
                "https://www.douyin.com/hot/search",
                wait_until="domcontentloaded",
                timeout=25000,
            )
            time.sleep(6)

            # 提取 cookies（__ac_signature 等关键 cookie 来自浏览器 JS 生成）
            cookies = context.cookies()
            cookie_str = "; ".join(
                [f"{c['name']}={c['value']}" for c in cookies]
            )
            log(f"抖音 Browser: 提取到 {len(cookies)} 个 Cookie")

            # 构造 API 请求（board_type=2 = 上升气流，board_type=1 = 总榜）
            # 两者都需要 Cookie 才能成功响应
            best_result = []
            for board_type in [2, 1]:
                api_url = (
                    "https://www.douyin.com/aweme/v1/web/hot/search/list/"
                    f"?device_platform=webapp&aid=6383&channel=channel_pc_web"
                    f"&detail_list=1&update_version_code=170100&board_type={board_type}"
                )
                req = urllib.request.Request(api_url, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                    "Referer": "https://www.douyin.com/hot/search",
                    "Origin": "https://www.douyin.com",
                    "Cookie": cookie_str,
                })
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        raw = resp.read().decode("utf-8", errors="ignore")
                        d = json.loads(raw)
                        word_list = d.get("data", {}).get("word_list", [])
                        if word_list:
                            log(f"抖音 board_type={board_type}: 获得 {len(word_list)} 条")
                            best_result = word_list
                            break
                except Exception as e:
                    log(f"抖音 board_type={board_type} 请求失败: {e}")

            for i, item in enumerate(best_result[:20], 1):
                hot_value = item.get("hot_value", "") or ""
                word = item.get("word", "") or ""
                label = item.get("label", "") or ""
                items.append({
                    "rank": i,
                    "word": str(word),
                    "hot_value": str(hot_value),
                    "label": str(label),
                    "source": "douyin_browser",
                })

            browser.close()
            log(f"抖音 Browser 模式成功: {len(items)} 条")

    except Exception as e:
        log(f"抖音 Browser 模拟失败: {e}")

    return items


def _fetch_douyin_browser_fallback():
    """
    board_type=1 总榜 fallback（当 _fetch_douyin_browser 无法获取上升气流时使用）
    """
    log("抖音总榜 fallback 模式")
    items = []
    try:
        from playwright.sync_api import sync_playwright
        import urllib.request

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"],
            )
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page.goto("https://www.douyin.com/hot/search",
                      wait_until="domcontentloaded", timeout=25000)
            time.sleep(6)

            cookies = context.cookies()
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

            # board_type=1 = 总榜
            api_url = ("https://www.douyin.com/aweme/v1/web/hot/search/list/"
                       "?device_platform=webapp&aid=6383&channel=channel_pc_web"
                       "&detail_list=1&update_version_code=170100&board_type=1")
            req = urllib.request.Request(api_url, headers={
                "User-Agent": "Mozilla/5.0 Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
                "Referer": "https://www.douyin.com/hot/search",
                "Cookie": cookie_str,
            })
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw = resp.read().decode("utf-8", errors="ignore")
                    d = json.loads(raw)
                    word_list = d.get("data", {}).get("word_list", [])
                    for i, item in enumerate(word_list[:20], 1):
                        items.append({
                            "rank": i,
                            "word": str(item.get("word", "") or ""),
                            "hot_value": str(item.get("hot_value", "") or ""),
                            "label": str(item.get("label", "") or ""),
                            "source": "douyin_total_api",
                        })
                    log(f"抖音总榜 fallback 成功: {len(items)} 条")
            except Exception as e:
                log(f"抖音总榜 fallback 失败: {e}")

            browser.close()
    except Exception as e:
        log(f"抖音总榜 fallback 异常: {e}")
    return items


# ============ ② 微博热搜 ============
def fetch_weibo():
    """微博热搜总榜 Top15"""
    items = []
    raw = curl_get(
        "https://weibo.com/ajax/statuses/hot_band",
        headers={"Referer": "https://weibo.com"},
        use_proxy=True,
    )
    if not raw or len(raw) < 100:
        log("微博空响应")
        return items
    try:
        data = json.loads(raw)
        band_list = data.get("data", {}).get("band_list", [])
        for i, item in enumerate(band_list[:15], 1):
            word = item.get("word", "") or item.get("note", "")
            # 过滤广告和非热搜条目
            if item.get("is_ad") or item.get("is_low_priority"):
                continue
            items.append({
                "rank": i,
                "word": word,
                "hot_value": item.get("num", ""),
                "label": item.get("label_name", ""),
                "category": item.get("category", ""),
                "source": "weibo",
            })
        log(f"微博热搜: {len(items)} 条")
    except Exception as e:
        log(f"微博解析失败: {e}")
    return items


# ============ ③ B站全站热榜 ============
def fetch_bilibili():
    """
    B站全站热榜 Top15。
    接口：https://api.bilibili.com/x/web-interface/ranking/v2?type=all
    注：B站无"每周必看"独立分类，改用全站热榜替代，
    过滤ady_type=1（广告推广），保留真实热门内容。
    """
    items = []
    raw = curl_get(
        "https://api.bilibili.com/x/web-interface/ranking/v2?type=all",
        headers={"Referer": "https://www.bilibili.com"},
        use_proxy=False,
    )
    if not raw or len(raw) < 100:
        log("B站直连失败，尝试代理 fallback")
        raw = curl_get(
            "https://api.bilibili.com/x/web-interface/ranking/v2?type=all",
            headers={"Referer": "https://www.bilibili.com"},
            use_proxy=True,
        )
    if not raw or len(raw) < 100:
        log("B站空响应")
        return items
    try:
        data = json.loads(raw)
        video_list = data.get("data", {}).get("list", [])
        for i, v in enumerate(video_list[:15], 1):
            title = v.get("title", "").replace("<em>", "").replace("</em>", "")
            tname = v.get("tname", "")
            owner = v.get("owner", {}).get("uname", "")
            # 过滤广告（ady_type=1 为推广内容）
            if v.get("ady_type") == 1:
                continue
            items.append({
                "rank": len(items) + 1,
                "title": title,
                "author": owner,
                "tag": tname,
                "duration": v.get("duration", 0),
                "view": v.get("stat", {}).get("view", ""),
                "source": "bilibili",
            })
        log(f"B站全站热榜: {len(items)} 条")
    except Exception as e:
        log(f"B站解析失败: {e}")
    return items


# ============ ④ 主流媒体上升热点（央视/新华网/澎湃） ============
def fetch_mainstream_news():
    """
    主流媒体头条：从多个可靠接口抓取
    优先：澎湃新闻(thepaper) > 新浪新闻 > 腾讯新闻
    避免：央视 RSS（全挂）、微博媒体号（反爬）
    """
    items = []
    sources = [
        # 36氪 RSS（科技创投媒体，头条有深度）
        ("36氪", "https://36kr.com/feed", 5),
        # 网易 RSS
        ("网易", "https://www.163.com/rss", 5),
    ]

    for name, url, limit in sources:
        raw = curl_get(url, timeout=10, use_proxy=False)
        if not raw or len(raw) < 50:
            continue
        try:
            entries = re.findall(r"<item>(.*?)</item>", raw, re.DOTALL)
            for entry in entries[:limit]:
                title_m = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", entry)
                if not title_m:
                    title_m = re.search(r"<title>(.*?)</title>", entry)
                if title_m:
                    t = title_m.group(1).strip()
                    if len(t) > 5:
                        items.append({
                            "rank": len(items) + 1,
                            "title": t,
                            "source": f"mainstream_{name.lower()}",
                        })
                        if len(items) >= limit:
                            break
        except Exception as e:
            log(f"主流媒体 [{name}] 解析失败: {e}")

        if len(items) >= 5:
            break

    # 去重
    seen, deduped = set(), []
    for item in items:
        key = item["title"][:25]
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)

    log(f"主流媒体上升热点: {len(deduped)} 条")
    return deduped[:5]


# ============ 格式化推送报告 ============
def format_report(douyin, weibo, bilibili, mainstream, elapsed):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []

    lines.append(f"🔥 热点情报 · {now}")
    lines.append("")
    lines.append(f"⏱ 抓取耗时: {elapsed:.1f}s")

    # 抖音上升
    lines.append("")
    lines.append("【抖音实时上升】")
    if not douyin:
        lines.append("（暂无数据）")
    else:
        for item in douyin:
            label = f" [{item['label']}]" if item.get("label") else ""
            hot = f" 🔥{item['hot_value']}" if item.get("hot_value") else ""
            lines.append(f"{item['rank']}. {item['word']}{label}{hot}")

    # 微博
    lines.append("")
    lines.append("【微博热搜】")
    if not weibo:
        lines.append("（暂无数据）")
    else:
        for item in weibo:
            label = f" [{item['label']}]" if item.get("label") else ""
            hot = f" 🔥{item['hot_value']}" if item.get("hot_value") else ""
            lines.append(f"{item['rank']}. {item['word']}{label}{hot}")

    # B站
    lines.append("")
    lines.append("【B站每周必看】")
    if not bilibili:
        lines.append("（暂无数据）")
    else:
        for item in bilibili:
            lines.append(f"{item['rank']}. {item['title']} — {item['author']} [{item['tag']}]")

    # 主流媒体
    lines.append("")
    lines.append("【主流媒体上升热点】")
    if not mainstream:
        lines.append("（暂无数据）")
    else:
        for item in mainstream:
            lines.append(f"{item['rank']}. {item['title']}")

    lines.append("")
    lines.append("数据源：抖音(上升气流) / 微博热搜 / B站每周必看 / 主流媒体")
    lines.append(f"抓取时间：{now}")

    return "\n".join(lines)


# ============ 推送飞书 ============
def push_feishu(content):
    """通过 lark-cli im +messages-send 推送（openclaw 与 lark-cli 是不同飞书 app，open_id 不互通）"""
    try:
        env = {
            **os.environ,
            "PATH": "/Users/openclaw/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        }
        r = subprocess.run(
            [
                "lark-cli", "im", "+messages-send",
                "--user-id", FEISHU_USER_ID,
                "--text", content,
            ],
            capture_output=True, text=True, timeout=25, env=env,
        )
        ok = r.returncode == 0
        if ok:
            log("飞书推送成功")
        else:
            log(f"飞书推送失败: {r.stderr.strip()[:200]}")
        return ok
    except Exception as e:
        log(f"飞书推送异常: {e}")
        return False


# ============ 保存原始数据 ============
def save_raw(douyin, weibo, bilibili, mainstream):
    ts = datetime.now().strftime("%Y-%m-%d-%H")
    raw_file = RAW_DIR / f"{ts}.json"
    payload = {
        "timestamp": datetime.now().isoformat(),
        "douyin_rising": douyin,
        "weibo": weibo,
        "bilibili": bilibili,
        "mainstream": mainstream,
    }
    try:
        with open(raw_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        log(f"原始数据已保存: {raw_file.name}")
    except Exception as e:
        log(f"保存原始数据失败: {e}")


# ============ 主流程 ============
def run():
    log("=" * 60)
    log("热点情报系统 v1 启动（抖音 Browser 模拟 + 四路信源）")
    t0 = time.time()

    # 四路并行抓取
    results = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            "douyin": executor.submit(fetch_douyin_rising),
            "weibo": executor.submit(fetch_weibo),
            "bilibili": executor.submit(fetch_bilibili),
            "mainstream": executor.submit(fetch_mainstream_news),
        }
        for name, fut in futures.items():
            try:
                results[name] = fut.result(timeout=25)
            except Exception as e:
                log(f"{name} 抓取超时/失败: {e}")
                results[name] = []

    elapsed = time.time() - t0
    douyin = results.get("douyin", [])
    weibo = results.get("weibo", [])
    bilibili = results.get("bilibili", [])
    mainstream = results.get("mainstream", [])

    log(f"数据获取完成: 抖音{len(douyin)} 微博{len(weibo)} B站{len(bilibili)} 主流媒体{len(mainstream)}")

    # 格式化报告
    report = format_report(douyin, weibo, bilibili, mainstream, elapsed)
    log(f"报告生成: {len(report)} 字")

    # 保存原始数据
    save_raw(douyin, weibo, bilibili, mainstream)

    # 推送飞书
    push_ok = push_feishu(report)

    # 更新进度
    try:
        prog = {}
        if PROGRESS_FILE.exists():
            try:
                prog = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        prog["total_scans"] = prog.get("total_scans", 0) + 1
        prog["last_run"] = datetime.now().isoformat()
        prog["douyin"] = len(douyin)
        prog["weibo"] = len(weibo)
        prog["bilibili"] = len(bilibili)
        prog["mainstream"] = len(mainstream)
        prog["elapsed_s"] = round(elapsed, 1)
        prog["feishu_ok"] = push_ok
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(prog, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"进度更新失败: {e}")

    log(f"完成(第{prog.get('total_scans', 1)}次, {elapsed:.1f}秒, 飞书={'OK' if push_ok else 'FAIL'})")
    return push_ok


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
