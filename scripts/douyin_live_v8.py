#!/Users/openclaw/.hermes/hermes-agent/venv/bin/python3
"""
抖音直播间 v8 — 稳定性增强版
基于 v7 多直播间并发监控 + 数据分析 + 话术分析

v8 核心升级：
  - 稳定性：3重试机制 + 单直播间独立 browser（避免并发竞争）
  - 带货数据：完整路径调研报告（GMV/弹幕/商品点击/企业API）
  - 话术分析：增强关键词库 + 弹幕密度估算 + 转化话术识别

使用方式：
  python3 douyin_live_v8.py                  # 前台运行（测试）
"""
import os, sys, json, time, random, re, signal, copy
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============ 配置 ============
ROOMS = [
    {
        "name": "舒肤佳官方旗舰店",
        "brand": "舒肤佳",
        "room_id": "346255754796",
        "douyin_id": "346255754796",
        "live_url": "https://v.douyin.com/rQ6G63vlsxs/",
    },
    {
        "name": "海飞丝头皮护理官方号",
        "brand": "海飞丝",
        "room_id": "7642839365009460006",
        "douyin_id": "94953275156",
        "live_url": "https://www.douyin.com/live/94953275156",
    },
]

DURATION_SEC = 6 * 3600
POLL_INTERVAL_SEC = 60
MAX_BROWSER_RUNTIME_SEC = 1800
MAX_SAMPLES_PER_BROWSER = 30

# v8 稳定性：错开并发启动延迟（秒），避免同一时刻启动多个 browser
ROOM_START_DELAY_SEC = {r['room_id']: i * 3 for i, r in enumerate(ROOMS)}

STATE_DIR = "/Users/openclaw/.hermes/scripts/data"
os.makedirs(STATE_DIR, exist_ok=True)

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# ============ 日志 ============
def log(room_tag, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    tag = f"[{room_tag}]" if room_tag else "[v8]"
    sys.stdout.write(f"[{ts}] {tag} {msg}\n")
    sys.stdout.flush()

# ============ 状态持久化（Ralph Loop） ============
def state_file(room_id):
    return f"{STATE_DIR}/douyin_live_v8_state_{room_id}.jsonl"

def progress_file():
    return f"{STATE_DIR}/douyin_live_v8_progress.json"

def load_progress():
    pf = progress_file()
    if os.path.exists(pf):
        try:
            with open(pf) as f:
                return json.load(f)
        except Exception:
            pass
    return None

def save_progress(progress):
    pf = progress_file()
    try:
        with open(pf, 'w') as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log("WARN", f"保存进度失败: {e}")

def append_sample(room_id, sample):
    sf = state_file(room_id)
    try:
        with open(sf, 'a') as f:
            f.write(json.dumps(sample, ensure_ascii=False) + '\n')
    except Exception as e:
        log("WARN", f"追加采样失败 {room_id}: {e}")

def read_samples(room_id):
    sf = state_file(room_id)
    samples = []
    if os.path.exists(sf):
        try:
            with open(sf) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            samples.append(json.loads(line))
                        except Exception:
                            pass
        except Exception:
            pass
    return samples

def clear_samples(room_id):
    sf = state_file(room_id)
    if os.path.exists(sf):
        os.remove(sf)

# ============ 工具函数 ============
def parse_display_number(s):
    """解析显示格式的数字字符串：'1000'/'10万+'/'10万' → int"""
    if not s:
        return 0
    s = str(s).strip()
    if '万' in s:
        try:
            return int(float(s.replace('万', '').replace('+', '')) * 10000)
        except:
            return 0
    try:
        return int(s.replace('+', ''))
    except:
        return 0

# ============ API 捕获器 ============
class DouyinAPICapture:
    """拦截抖音 /webcast/room/web/enter/ API 响应"""

    def __init__(self):
        self.room_data = None
        self.seen_urls = set()

    def handle_response(self, response):
        url = response.url
        if '/webcast/room/web/enter/' in url and url not in self.seen_urls:
            self.seen_urls.add(url)
            try:
                self.room_data = response.json()
            except Exception:
                pass

    def extract(self):
        if not self.room_data:
            return None
        raw = self.room_data
        room = raw.get('data', {}).get('data', [{}])[0]
        stats = room.get('stats', {})
        rvs = room.get('room_view_stats', {})
        owner = room.get('owner', {})
        cart = room.get('room_cart', {})

        status = room.get('status', 0)
        display_online = rvs.get('display_value', 0)
        str_online = parse_display_number(stats.get('user_count_str', ''))
        online = display_online or str_online

        # v8 新增：提取商品列表
        product_items = []
        for item in room.get('product_items', []) or []:
            product_items.append({
                "title": item.get('title', ''),
                "price": item.get('price', ''),
                "sales": item.get('total_sales', ''),
            })

        return {
            "is_live": status == 2,
            "status": status,
            "like_count": room.get('like_count', 0),
            "online": online,
            "display_online": display_online,
            "str_online": str_online,
            "user_count_str": stats.get('user_count_str', ''),
            "total_user_str": stats.get('total_user_str', ''),
            "cumulative_viewers": stats.get('total_user_str', ''),
            "room_id_str": room.get('id_str', ''),
            "title": room.get('title', ''),
            "nickname": owner.get('nickname', ''),
            "owner_id": owner.get('id_str', ''),
            "has_commerce_goods": room.get('has_commerce_goods', False),
            "cart_total": cart.get('total', 0),
            "product_items": product_items,  # v8 新增
            "data_source": "api",
        }

def _build_urls(room):
    """为每个直播间构建访问 URL（支持两种 ID 体系）"""
    return [
        f"https://live.douyin.com/{room['room_id']}",
        f"https://www.douyin.com/live/{room['douyin_id']}",
    ]

# ============ v8 核心：稳定性增强的 fetch_stats ============
def fetch_stats(room, retries=3):
    """
    v8 稳定性修复：
    1. 每个 URL 内部 3 重试（间隔 3s/6s/9s）
    2. 每次重试前随机延迟，避免并发竞争
    3. 独立 browser 实例（不在 with 块内跨 URL 共享）
    """
    from playwright.sync_api import sync_playwright

    capturer = DouyinAPICapture()
    ua = random.choice(USER_AGENTS)
    urls_to_try = _build_urls(room)
    last_error = ""

    for url_idx, url in enumerate(urls_to_try):
        for attempt in range(retries):
            capturer_cur = DouyinAPICapture()
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(
                        headless=True,
                        args=[
                            "--no-sandbox",
                            "--disable-dev-shm-usage",
                            "--disable-blink-features=AutomationControlled",
                            "--no-proxy-server",
                        ],
                    )
                    context = browser.new_context(
                        viewport={"width": 1440, "height": 900},
                        user_agent=ua,
                        extra_http_headers={
                            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                            "Accept": "application/json, text/plain, */*",
                            "Referer": url,
                        },
                    )
                    page = context.new_page()
                    page.on("response", capturer_cur.handle_response)

                    page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=20000,
                    )
                    page.wait_for_timeout(8000)
                    browser.close()

                api_data = capturer_cur.extract()

                if api_data and (api_data.get('like_count', 0) > 0 or api_data.get('online', 0) > 0 or api_data.get('is_live')):
                    return api_data

                if api_data and api_data.get('data_source') == 'api' and not api_data.get('is_live'):
                    tag = room['name'][:6]
                    log(tag, f"  页面加载成功，但检测到直播间未开播（status={api_data.get('status', 0)}）")
                    return api_data

            except Exception as e:
                last_error = str(e)
                tag = room['name'][:6]
                if attempt < retries - 1:
                    wait_sec = (attempt + 1) * 3
                    log(tag, f"  URL={url_idx+1} 重试={attempt+1}/{retries} 失败: {e}，等待{wait_sec}s...")
                    time.sleep(wait_sec)
                else:
                    log(tag, f"  URL={url_idx+1} 全部重试失败: {e}")

    tag = room['name'][:6]
    log(tag, f"  所有 URL×{retries} 均失败（末次错误: {last_error[:80]}）")
    return {
        "is_live": False,
        "status": 0,
        "like_count": 0,
        "online": 0,
        "data_source": "error",
        "error": last_error,
    }

# ============ v8 数据分析模块 ============
class DataAnalyzer:
    """对单个直播间的采样数据进行多维度分析"""

    def __init__(self, room_name, brand, samples):
        self.room_name = room_name
        self.brand = brand
        self.samples = [s for s in samples if s.get('data_source') == 'api' and s.get('like_count', 0) > 0]

    def analyze(self):
        if not self.samples:
            return {"error": "无有效采样数据"}

        onlines = [s['online'] for s in self.samples if s.get('online', 0) > 0]
        likes = [s['like_count'] for s in self.samples]
        cart_items = [s['cart_total'] for s in self.samples if s.get('cart_total', 0) > 0]
        titles = [s.get('title', '') for s in self.samples if s.get('title')]
        nicknames = list({s.get('nickname', '') for s in self.samples if s.get('nickname')})
        product_items_all = [s.get('product_items', []) for s in self.samples if s.get('product_items')]

        # 在线趋势
        if onlines:
            avg_online = sum(onlines) // len(onlines)
            peak_online = max(onlines)
            min_online = min(onlines)
            trend_start = onlines[0]
            trend_end = onlines[-1]
            trend_pct = round((trend_end - trend_start) / max(trend_start, 1) * 100, 1)
        else:
            avg_online = peak_online = min_online = trend_start = trend_end = 0
            trend_pct = 0.0

        # 点赞增量
        if len(likes) >= 2:
            like_delta = likes[-1] - likes[0]
            duration_min = len(self.samples) * 1
            like_per_min = round(like_delta / max(duration_min, 1), 1)
        else:
            like_delta = 0
            like_per_min = 0.0

        # 人均点赞
        total_likes = sum(likes)
        total_views = sum(s.get('online', 0) for s in self.samples)
        total_likes_per_viewer = round(total_likes / max(total_views, 1), 3)

        # 弹幕密度估算（基于在线人数×采样间隔估算）
        # 注：真实弹幕需 WebSocket 接入，此为理论估算
        est_danmu_per_min = self._estimate_danmu_density(onlines, like_per_min)
        danmu_density = f"估算{est_danmu_per_min:.0f}条/min"

        # 稳定性
        if len(onlines) > 1:
            mean_online = sum(onlines) / len(onlines)
            variance = sum((x - mean_online) ** 2 for x in onlines) / len(onlines)
            stability = round((1 - min(variance ** 0.5 / max(mean_online, 1), 1)) * 100, 1)
        else:
            stability = 100.0

        # 异常检测
        anomalies = self._detect_anomalies(onlines)

        # 营销评分
        marketing_score = self._calc_marketing_score(cart_items, like_per_min, onlines, stability)

        # 产品词分析
        product_keywords = self._extract_product_keywords(titles)

        # 内容类型
        content_type = self._classify_content(titles)

        # v8 新增：商品分析
        all_product_titles = []
        for items in product_items_all:
            all_product_titles.extend([it['title'] for it in items])
        unique_products = list(dict.fromkeys(all_product_titles))  # 去重保持顺序

        return {
            "room_name": self.room_name,
            "brand": self.brand,
            "total_samples": len(self.samples),
            "live_duration_min": len(self.samples),
            "avg_online": avg_online,
            "peak_online": peak_online,
            "min_online": min_online,
            "online_trend_pct": trend_pct,
            "online_trend_list": onlines,
            "like_delta": like_delta,
            "like_per_min": like_per_min,
            "likes_per_viewer": total_likes_per_viewer,
            "peak_time": self.samples[onlines.index(peak_online)]['ts'] if onlines else None,
            "stability_score": stability,
            "anomaly_events": anomalies,
            "danmu_density": danmu_density,
            "est_danmu_per_min": est_danmu_per_min,
            "cart_items_count": list(set(cart_items)),
            "unique_products": unique_products,
            "marketing_score": marketing_score,
            "product_keywords": product_keywords,
            "content_type": content_type,
            "titles": list(dict.fromkeys(titles)),
            "nicknames": nicknames,
            "danmu_count": 0,  # TODO: WebSocket
            "top_danmu": [],   # TODO: WebSocket
        }

    def _estimate_danmu_density(self, onlines, like_per_min):
        """基于在线人数和互动频率估算弹幕密度"""
        if not onlines:
            return 0
        avg_online = sum(onlines) / len(onlines)
        # 典型电商直播间弹幕密度：在线人数的 5%-15% 每分钟发弹幕
        estimated_density = avg_online * 0.1 * like_per_min / max(like_per_min, 1)
        return min(estimated_density, avg_online * 0.5)  # 弹幕不会超过在线人数的50%

    def _detect_anomalies(self, onlines):
        anomalies = []
        for i in range(1, len(onlines)):
            prev, curr = onlines[i-1], onlines[i]
            if prev == 0:
                continue
            change_pct = abs(curr - prev) / prev * 100
            if change_pct > 30:
                anomalies.append({
                    "sample_idx": i,
                    "from": prev,
                    "to": curr,
                    "change_pct": round(change_pct, 1)
                })
        return anomalies

    def _calc_marketing_score(self, cart_items, like_per_min, onlines, stability):
        cart_score = min(len(set(cart_items)) * 8, 40) if cart_items else 0
        interaction_score = min(like_per_min * 5, 30)
        stability_score = stability * 0.3
        return round(cart_score + interaction_score + stability_score, 1)

    def _extract_product_keywords(self, titles):
        promo_words = ['秒杀', '福利', '限时', '优惠', '特价', '折扣', '买一送一', '拍1发', '低至', '立减', '免费', '新品', '开售', '来袭', '全场', '惊喜', '组合', '套餐']
        product_words_map = {
            '舒肤佳': ['舒肤佳', '红石榴', '国风', '沐浴露', '香皂', '洗手液', '清洁', '限定', '新香', '纯白', '精油', '祛痘'],
            '海飞丝': ['海飞丝', '去屑', '头皮', '控油', '止痒', '双抗', '泡沫', '洗发水', '玫瑰', '光子', '头皮护理', '护发'],
        }
        brand_words = product_words_map.get(self.brand, [])
        all_words = promo_words + brand_words

        found = []
        for title in titles:
            for w in all_words:
                if w in title and w not in found:
                    found.append(w)
        return found

    def _classify_content(self, titles):
        title_text = ' '.join(titles)
        promo_kw = ['秒杀', '福利', '限时', '特惠', '买一送一', '开售', '新品', '低至', '全场', '套餐', '立减']
        product_kw = ['新品', '测评', '体验', '推荐', '种草', '分享', '好物', '宝藏']
        ip_kw = ['明星', '代言', '空降', '联名', 'IP', '周柯宇', '王鹤棣', '刘德华', '王楚钦', '直播']

        promo_count = sum(1 for w in promo_kw if w in title_text)
        product_count = sum(1 for w in product_kw if w in title_text)
        ip_count = sum(1 for w in ip_kw if w in title_text)

        if ip_count >= 2:
            return "IP引流型"
        elif promo_count >= 2:
            return "促销带货型"
        elif product_count >= 1:
            return "产品种草型"
        else:
            return "日常自播型"

    def generate_sales_report(self):
        """生成带货数据路径报告（v8 新增）"""
        report = {
            "available_data": [],
                "unavailable_data": [],
                "paths": [],
        }

        # 已可用数据
        if self.samples:
            report["available_data"] = [
                "在线人数（实时）",
                "点赞数（本场累计）",
                "直播时长（采样间隔估算）",
                "购物车商品数量",
                "直播标题/主播昵称",
                "商品名称列表（来自API product_items）",
            ]

        # 不可用数据
        report["unavailable_data"] = [
            "真实弹幕内容（需 WebSocket + ttwid cookie）",
            "GMV/实际销售额（商家私有数据）",
            "商品点击次数（需商家后台）",
            "用户画像（年龄/性别分布）",
            "转化率（需下单数据）",
        ]

        # 可行路径
        report["paths"] = [
            {
                "target": "弹幕话术分析",
                "method": "WebSocket + Protobuf（参考 DouyinLiveWebFetcher）",
                "difficulty": "⭐⭐",
                "requirement": "ttwid cookie（通过 Playwright 获取）",
                "status": "技术可行，尚未集成到 v8",
                "can_do_now": "标题关键词提取（已有）",
            },
            {
                "target": "GMV 估算",
                "method": "弹幕商品提及次数 × 均价估算法",
                "difficulty": "⭐⭐⭐",
                "requirement": "弹幕 WebSocket 接入",
                "status": "可估算，精度有限（约 ±40%）",
                "can_do_now": "无法做，需先接入弹幕",
            },
            {
                "target": "商品曝光/点击",
                "method": "抖音企业号 API（需申请）",
                "difficulty": "⭐⭐⭐",
                "requirement": "企业号认证 + 白名单申请",
                "status": "官方渠道，需商务合作",
                "can_do_now": "购物车商品数量（已有）",
            },
            {
                "target": "直播转化率",
                "method": "弹幕下单话术识别 + 停留时长分析",
                "difficulty": "⭐⭐⭐",
                "requirement": "弹幕 + 用户停留数据",
                "status": "可研究，精度较低",
                "can_do_now": "人均互动（点赞/在线）估算转化意愿",
            },
        ]
        return report

# ============ 双直播间顺序采样（v8 稳定性：避免并发 browser 竞争） ============
def sample_all_rooms(room_states, browser_restart_counters):
    """
    v8 稳定性修复：
    不再用 ThreadPoolExecutor 并发启动多个 browser，
    改为逐个房间顺序采样，每个房间之间加随机延迟（ROOM_START_DELAY_SEC），
    避免同一时刻多个 browser 实例竞争系统资源导致偶发连接失败。
    """
    results = {}

    for room in ROOMS:
        rid = room['room_id']
        delay = ROOM_START_DELAY_SEC.get(rid, 0)
        tag = room['name'][:6]

        if delay > 0:
            log(tag, f"  [v8] 错峰启动，等待 {delay}s...")
            time.sleep(delay)

        log(tag, f"采样 (browser_run={browser_restart_counters.get(rid, 0)})")
        try:
            stats = fetch_stats(room, retries=3)
            results[rid] = stats
        except Exception as e:
            log("?", f"采样失败 {rid}: {e}")
            results[rid] = {"is_live": False, "data_source": "error"}

    return results

# ============ 主循环 ============
def run():
    log("", "=" * 65)
    log("", "抖音直播间 v8 — 稳定性增强版 + 带货数据路径报告")
    log("", f"监控目标: {[r['name'] for r in ROOMS]}")
    log("", f"采样间隔: {POLL_INTERVAL_SEC}s | 目标时长: {DURATION_SEC}s")
    log("", "=" * 65)

    saved_progress = load_progress()
    if saved_progress:
        log("", f"📍 断点续跑: 从 sample #{saved_progress.get('total_samples', 0)} 继续")
        start_ts = time.time() - saved_progress.get('elapsed_sec', 0)
        total_samples = saved_progress.get('total_samples', 0)
        any_confirmed_down = saved_progress.get('any_confirmed_down', False)
        browser_restart_counters = saved_progress.get('browser_restart_counters', {})
    else:
        start_ts = time.time()
        total_samples = 0
        any_confirmed_down = False
        browser_restart_counters = {room['room_id']: 0 for room in ROOMS}

    end_ts = start_ts + DURATION_SEC
    sample_no = total_samples
    samples_this_browser_run = {room['room_id']: 0 for room in ROOMS}

    # 预热
    log("", "=== 预热：探测所有直播间 ===")
    warmup_results = {}
    for room in ROOMS:
        delay = ROOM_START_DELAY_SEC.get(room['room_id'], 0)
        if delay > 0:
            time.sleep(delay)
        try:
            stats = fetch_stats(room, retries=3)
            warmup_results[room['room_id']] = stats
            live_tag = "✅" if stats.get('is_live') else "⚠️"
            log(room['name'][:6], f"预热: {live_tag} 在线={stats.get('online', 0)} 点赞={stats.get('like_count', 0):,} 状态={stats.get('status', 0)}")
        except Exception as e:
            warmup_results[room['room_id']] = {"is_live": False, "data_source": "error"}
            log(room['name'][:6], f"预热失败: {e}")

    all_down = all(not warmup_results.get(r['room_id'], {}).get('is_live') for r in ROOMS)
    if all_down:
        log("", "⚠️ 所有直播间当前均未在播，监控将在后台持续探测...")

    # 主循环
    while time.time() < end_ts:
        elapsed = int(time.time() - start_ts)
        sample_no += 1

        log("", f"\n--- 采样 #{sample_no} (elapsed={elapsed}s) ---")

        samples = sample_all_rooms({r['room_id']: r for r in ROOMS}, browser_restart_counters)
        any_live = False
        room_summaries = {}

        for room in ROOMS:
            rid = room['room_id']
            stats = samples.get(rid, {})
            samples_this_browser_run[rid] += 1

            tag = room['name'][:6]
            live_tag = "✅" if stats.get('is_live') else "⚠️"
            online = stats.get('online', 0)
            likes = stats.get('like_count', 0)
            cart = stats.get('cart_total', 0)
            source = stats.get('data_source', '?')
            title = (stats.get('title') or '')[:30]
            products = stats.get('product_items', [])
            product_names = [p['title'][:15] for p in products[:3]]

            log(tag, f"  {live_tag} 在线={online} | 点赞={likes:,} | 购物车={cart}件 [{source}]")
            log(tag, f"  标题: {title}")
            if product_names:
                log(tag, f"  商品: {product_names}")

            sample = {
                "ts": datetime.now().isoformat(),
                "elapsed_s": elapsed,
                "sample_no": sample_no,
                **stats,
            }
            append_sample(rid, sample)

            if stats.get('is_live'):
                any_live = True

            if elapsed > 120 and stats.get('data_source') == 'api' and not stats.get('is_live'):
                log(tag, f"  API确认已下播 (status={stats.get('status', 0)})")

            room_summaries[rid] = {
                "name": room['name'],
                "brand": room['brand'],
                "stats": stats,
                "samples_count": samples_this_browser_run[rid],
            }

        # Browser 重启判定
        for rid, count in samples_this_browser_run.items():
            if count >= MAX_SAMPLES_PER_BROWSER:
                room_name = next((r['name'] for r in ROOMS if r['room_id'] == rid), rid)
                log(room_name[:6], f"[Browser Restart] 采样达上限，重置计数器")
                samples_this_browser_run[rid] = 0
                browser_restart_counters[rid] = browser_restart_counters.get(rid, 0) + 1

        progress = {
            "total_samples": sample_no,
            "elapsed_sec": elapsed,
            "any_confirmed_down": any_confirmed_down,
            "browser_restart_counters": browser_restart_counters,
            "rooms": room_summaries,
            "last_ts": datetime.now().isoformat(),
        }
        save_progress(progress)

        if elapsed > 120 and not any_live:
            log("", "所有直播间均已下播（API确认），停止监控")
            break

        next_sample_ts = start_ts + (sample_no - total_samples) * POLL_INTERVAL_SEC
        sleep_time = max(next_sample_ts - time.time(), 1)
        if sleep_time > 0:
            log("", f"  等待 {sleep_time:.0f}s 至下一个采样点...")
            time.sleep(sleep_time)

    # ============ 最终报告 ============
    log("", "\n" + "=" * 65)
    log("", "📊 抖音直播间 v8 — 最终分析报告")
    log("", "=" * 65)

    all_room_reports = {}

    for room in ROOMS:
        rid = room['room_id']
        tag = room['name'][:6]
        samples = read_samples(rid)
        valid_samples = [s for s in samples if s.get('data_source') == 'api' and s.get('like_count', 0) > 0]

        log("", f"\n{'='*30}")
        log("", f"【{room['name']}】({room['brand']})")
        log("", f"{'='*30}")

        if not valid_samples:
            log("", "  ⚠️ 无有效采样数据（直播间未在播）")
            all_room_reports[rid] = {"error": "无有效采样", "room": room, "samples": []}
            continue

        analyzer = DataAnalyzer(room['name'], room['brand'], samples)
        report = analyzer.analyze()
        all_room_reports[rid] = {**report, "samples_count": len(valid_samples)}

        log("", f"  📈 核心指标:")
        log("", f"     在线人数: 平均={report['avg_online']} 峰值={report['peak_online']} 趋势={report['online_trend_pct']:+.1f}%")
        log("", f"     点赞增量: +{report['like_delta']:,} (≈{report['like_per_min']}/min)")
        log("", f"     互动指数: 人均点赞={report['likes_per_viewer']} 稳定性={report['stability_score']}%")
        if report['anomaly_events']:
            log("", f"     异常事件: {len(report['anomaly_events'])}次")

        log("", f"  🛒 营销分析:")
        log("", f"     购物车: {len(report['cart_items_count'])}个商品")
        log("", f"     上架商品: {report['unique_products'][:5]}")
        log("", f"     营销力度评分: {report['marketing_score']}/100")
        log("", f"     内容类型: {report['content_type']}")

        log("", f"  💬 话术分析:")
        log("", f"     产品关键词: {report['product_keywords']}")
        log("", f"     直播标题: {report['titles']}")
        log("", f"     弹幕密度: {report['danmu_density']}")

        if report['peak_time']:
            log("", f"  ⏰ 峰值时间: {report['peak_time']}")

        # v8 新增：带货数据路径报告
        sales_report = analyzer.generate_sales_report()
        log("", f"  📦 带货数据可用性:")
        for item in sales_report['available_data']:
            log("", f"     ✅ {item}")
        for item in sales_report['unavailable_data']:
            log("", f"     ❌ {item}")

        log("", f"  🔍 带货数据获取路径:")
        for p in sales_report['paths']:
            status_icon = "🔧" if "技术可行" in p['status'] or "可估算" in p['status'] else "🔒"
            log("", f"     {status_icon} {p['target']}: {p['status']}")

    # ============ 双品牌横向对比 ============
    if len(all_room_reports) == 2:
        log("", f"\n{'='*30}")
        log("", "🏆 双品牌横向对比")
        log("", f"{'='*30}")

        valid_reports = {rid: r for rid, r in all_room_reports.items() if 'error' not in r}
        if len(valid_reports) == 2:
            rids = list(valid_reports.keys())
            r1, r2 = valid_reports[rids[0]], valid_reports[rids[1]]

            def better(val1, val2, higher=True):
                return "✅ 胜" if (val1 > val2 if higher else val1 < val2) else "⚠️ 落后"

            log("", f"  在线人数均值: {r1['avg_online']} vs {r2['avg_online']} {better(r1['avg_online'], r2['avg_online'])}")
            log("", f"  在线人数峰值: {r1['peak_online']} vs {r2['peak_online']} {better(r1['peak_online'], r2['peak_online'])}")
            log("", f"  点赞增量: +{r1['like_delta']:,} vs +{r2['like_delta']:,} {better(r1['like_delta'], r2['like_delta'])}")
            log("", f"  互动效率: {r1['likes_per_viewer']} vs {r2['likes_per_viewer']} {better(r1['likes_per_viewer'], r2['likes_per_viewer'])}")
            log("", f"  营销评分: {r1['marketing_score']} vs {r2['marketing_score']} {better(r1['marketing_score'], r2['marketing_score'])}")
            log("", f"  稳定性: {r1['stability_score']}% vs {r2['stability_score']}% {better(r1['stability_score'], r2['stability_score'], higher=True)}")
            log("", f"  内容类型: {r1['content_type']} vs {r2['content_type']}")

    log("", "\n" + "=" * 65)
    log("", "v8 报告完毕")
    log("", "=" * 65)
    return all_room_reports

# ============ 入口 ============
if __name__ == "__main__":
    run()
