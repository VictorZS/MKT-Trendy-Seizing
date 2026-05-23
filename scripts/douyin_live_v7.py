#!/Users/openclaw/.hermes/hermes-agent/venv/bin/python3
"""
抖音直播间 v7 — 多直播间并发监控 + 数据分析 + 话术分析
功能：
  - 双直播间并发（舒肤佳官方旗舰店 + 海飞丝头皮护理官方号）
  - 每 60s 采样一次，在播则持续监控
  - 数据分析：趋势、对比、峰值、异常检测
  - 话术分析：标题关键词提取 + 产品词频 + 互动指数 + 营销力度评分

使用方式：
  python3 douyin_live_v7.py                  # 前台运行（测试）
  python3 -c "import subprocess; ..."          # 后台运行（正式）
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
        # room_id: 用于 live.douyin.com/{room_id}
        "room_id": "346255754796",
        # douyin_id: 抖音号，用于 www.douyin.com/live/{douyin_id}
        "douyin_id": "346255754796",
        "live_url": "https://v.douyin.com/rQ6G63vlsxs/",
    },
    {
        "name": "海飞丝头皮护理官方号",
        "brand": "海飞丝",
        # 海飞丝的 room_id（7642839365009460006）只适用于 www.douyin.com/live/{douyin_id}
        # live.douyin.com/{room_id} 对海飞丝无效（已实测验证）
        "room_id": "7642839365009460006",
        "douyin_id": "94953275156",
        "live_url": "https://www.douyin.com/live/94953275156",
    },
]

DURATION_SEC = 6 * 3600   # 6 小时（如所有直播间均下播则提前结束）
POLL_INTERVAL_SEC = 60    # 1 分钟采样一次
MAX_BROWSER_RUNTIME_SEC = 1800  # 30 分钟强制重启
MAX_SAMPLES_PER_BROWSER = 30

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
    tag = f"[{room_tag}]" if room_tag else "[v7]"
    sys.stdout.write(f"[{ts}] {tag} {msg}\n")
    sys.stdout.flush()

# ============ 状态持久化（Ralph Loop） ============
def state_file(room_id):
    return f"{STATE_DIR}/douyin_live_v7_state_{room_id}.jsonl"

def progress_file():
    return f"{STATE_DIR}/douyin_live_v7_progress.json"

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
    with open(pf, "w") as f:
        json.dump(progress, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())

def append_sample(room_id, sample):
    sf = state_file(room_id)
    with open(sf, "a") as f:
        f.write(json.dumps(sample, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())

def read_samples(room_id):
    sf = state_file(room_id)
    samples = []
    if os.path.exists(sf):
        with open(sf) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        samples.append(json.loads(line))
                    except Exception:
                        pass
    return samples

# ============ 数据提取（API 拦截） ============
def parse_display_number(s):
    if not s:
        return 0
    m = re.search(r'^(\d+)', str(s).strip())
    return int(m.group(1)) if m else 0

class DouyinAPICapture:
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
            "data_source": "api",
        }

def _build_urls(room):
    """为每个直播间构建访问 URL（支持两种 ID 体系）"""
    # live.douyin.com/{room_id}  ← 大多数直播间适用
    # www.douyin.com/live/{douyin_id} ← 海飞丝等部分直播间适用
    return [
        f"https://live.douyin.com/{room['room_id']}",
        f"https://www.douyin.com/live/{room['douyin_id']}",
    ]

def fetch_stats(room):
    from playwright.sync_api import sync_playwright

    capturer = DouyinAPICapture()
    ua = random.choice(USER_AGENTS)
    urls_to_try = _build_urls(room)

    last_error = ""

    for url in urls_to_try:
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
                page.on("response", capturer.handle_response)

                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=20000,
                )
                page.wait_for_timeout(8000)
                browser.close()

            api_data = capturer.extract()

            if api_data and (api_data.get('like_count', 0) > 0 or api_data.get('online', 0) > 0 or api_data.get('is_live')):
                return api_data

            # API 捕获到了但数据为空，说明页面加载了但直播未开播
            if api_data and api_data.get('data_source') == 'api' and not api_data.get('is_live'):
                tag = room['name'][:6]
                log(tag, f"  页面加载成功，但检测到直播间未开播（status={api_data.get('status', 0)}）")
                return api_data

        except Exception as e:
            last_error = str(e)
            tag = room['name'][:6]
            log(tag, f"  URL {url} 失败: {e}")
            capturer = DouyinAPICapture()  # 重置捕获器

    tag = room['name'][:6]
    log(tag, f"  所有 URL 均失败（末次错误: {last_error[:60]}）")
    return {
        "is_live": False,
        "status": 0,
        "like_count": 0,
        "online": 0,
        "data_source": "error",
        "error": last_error,
    }

# ============ 数据分析模块 ============
class DataAnalyzer:
    """
    对单个直播间的采样数据进行多维度分析。
    """

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

        # 在线趋势分析
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

        # 点赞增量分析
        if len(likes) >= 2:
            like_delta = likes[-1] - likes[0]
            duration_min = len(self.samples) * 1  # 每采样间隔约1分钟
            like_per_min = round(like_delta / max(duration_min, 1), 1)
            total_likes_per_viewer = round(like_delta / max(sum(onlines) // max(len(onlines), 1), 1), 3)
        else:
            like_delta = 0
            like_per_min = 0.0
            total_likes_per_viewer = 0.0

        # 弹幕密度估算（目前无弹幕数据，预留接口）
        danmu_density = 0  # TODO: 接入 WebSocket 后计算

        # 峰值时段检测
        peak_sample = max(self.samples, key=lambda s: s.get('online', 0)) if onlines else None
        peak_time = peak_sample['ts'] if peak_sample else None

        # 稳定性分析（在线人数标准差）
        if len(onlines) > 1:
            mean_online = sum(onlines) / len(onlines)
            variance = sum((x - mean_online) ** 2 for x in onlines) / len(onlines)
            stability = round((1 - min(variance ** 0.5 / max(mean_online, 1), 1)) * 100, 1)
        else:
            stability = 100.0

        # 异常检测（在线人数突降/突增）
        anomalies = self._detect_anomalies(onlines)

        # 营销力度评分（基于购物车商品数和互动指数）
        marketing_score = self._calc_marketing_score(cart_items, like_per_min, onlines, stability)

        # 产品词分析（从标题提取产品/促销关键词）
        product_keywords = self._extract_product_keywords(titles)

        # 内容类型判断
        content_type = self._classify_content(titles)

        return {
            "room_name": self.room_name,
            "brand": self.brand,
            "total_samples": len(self.samples),
            "live_duration_min": len(self.samples),
            # 核心指标
            "avg_online": avg_online,
            "peak_online": peak_online,
            "min_online": min_online,
            "online_trend_pct": trend_pct,
            "online_trend_list": onlines,
            "like_delta": like_delta,
            "like_per_min": like_per_min,
            "likes_per_viewer": total_likes_per_viewer,
            "peak_time": peak_time,
            # 互动质量
            "stability_score": stability,
            "anomaly_events": anomalies,
            "danmu_density": danmu_density,  # TODO: WebSocket
            # 营销
            "cart_items_count": list(set(cart_items)),
            "marketing_score": marketing_score,
            "product_keywords": product_keywords,
            # 内容
            "content_type": content_type,
            "titles": list(set(titles)),
            "nicknames": nicknames,
            # 弹幕（预留）
            "danmu_count": 0,  # TODO
            "top_danmu": [],   # TODO
        }

    def _detect_anomalies(self, onlines):
        """检测在线人数突降/突增（>30%变化）"""
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
        """营销力度综合评分（0-100）"""
        # 购物车商品越多，营销越积极
        cart_score = min(len(set(cart_items)) * 8, 40) if cart_items else 0
        # 互动频率
        interaction_score = min(like_per_min * 5, 30)
        # 在线稳定性
        stability_score = stability * 0.3
        return round(cart_score + interaction_score + stability_score, 1)

    def _extract_product_keywords(self, titles):
        """从标题提取产品/促销关键词"""
        # 常见促销词
        promo_words = ['秒杀', '福利', '限时', '优惠', '特价', '折扣', '买一送一', '拍1发', '低至', '立减', '免费', '新品', '开售', '来袭']
        # 产品词（按品牌）
        product_words_map = {
            '舒肤佳': ['舒肤佳', '红石榴', '国风', '沐浴露', '香皂', '洗手液', '清洁', '限定', '新香'],
            '海飞丝': ['海飞丝', '去屑', '头皮', '控油', '止痒', '双抗', '泡沫', '洗发水', '玫瑰'],
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
        """内容类型判断"""
        title_text = ' '.join(titles)
        # 促销导向
        promo_kw = ['秒杀', '福利', '限时', '特惠', '买一送一', '开售', '新品', '低至']
        # 产品/品牌导向
        product_kw = ['新品', '测评', '体验', '推荐', '种草', '分享']
        # IP/明星
        ip_kw = ['明星', '代言', '空降', '联名', 'IP', '周柯宇', '王鹤棣', '刘德华', '王楚钦']

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

# ============ 双直播间并发采样 ============
def sample_all_rooms(room_states, browser_restart_counters):
    """
    并发采样所有直播间。
    room_states: {room_id: {"name": ..., "brand": ..., ...}}
    返回: {room_id: sample_dict}
    """
    results = {}
    samples_this_run = {rid: browser_restart_counters.get(rid, 0) for rid in room_states}

    def sample_one(room_id, room_info, samples_this_browser):
        tag = room_info['name'][:6]
        log(tag, f"采样 (browser_run={samples_this_browser})")

        # 每 N 次重启一次 browser（防泄漏）
        stats = fetch_stats(room_info)
        return room_id, stats

    with ThreadPoolExecutor(max_workers=len(ROOMS)) as executor:
        futures = {}
        for room in ROOMS:
            rid = room['room_id']
            futures[executor.submit(sample_one, rid, room, samples_this_run[rid])] = rid

        for future in as_completed(futures):
            rid = futures[future]
            try:
                _, stats = future.result()
                results[rid] = stats
            except Exception as e:
                log("?", f"采样失败 {rid}: {e}")
                results[rid] = {"is_live": False, "data_source": "error"}

    return results

# ============ 主循环 ============
def run():
    log("", "=" * 65)
    log("", "抖音直播间 v7 — 多直播间并发监控 + 数据分析 + 话术分析")
    log("", f"监控目标: {[r['name'] for r in ROOMS]}")
    log("", f"采样间隔: {POLL_INTERVAL_SEC}s | 目标时长: {DURATION_SEC}s")
    log("", "=" * 65)

    # 断点续跑
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

    # 预热：同时探测所有直播间状态
    log("", "=== 预热：探测所有直播间 ===")
    warmup_results = {}
    with ThreadPoolExecutor(max_workers=len(ROOMS)) as executor:
        future_to_room = {
            executor.submit(fetch_stats, room): room
            for room in ROOMS
        }
        for future in as_completed(future_to_room):
            room = future_to_room[future]
            try:
                stats = future.result()
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

        # 并发采样
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

            log(tag, f"  {live_tag} 在线={online} | 点赞={likes:,} | 购物车={cart}件 [{source}]")
            log(tag, f"  标题: {title}")

            # 追加采样
            sample = {
                "ts": datetime.now().isoformat(),
                "elapsed_s": elapsed,
                "sample_no": sample_no,
                **stats,
            }
            append_sample(rid, sample)

            if stats.get('is_live'):
                any_live = True

            # 提前下播判定
            if elapsed > 120 and stats.get('data_source') == 'api' and not stats.get('is_live'):
                log(tag, f"  API确认已下播 (status={stats.get('status', 0)})")

            room_summaries[rid] = {
                "name": room['name'],
                "brand": room['brand'],
                "stats": stats,
                "samples_count": samples_this_browser_run[rid],
            }

        # Browser 重启判定（每个房间独立）
        for rid, count in samples_this_browser_run.items():
            if count >= MAX_SAMPLES_PER_BROWSER:
                room_name = next((r['name'] for r in ROOMS if r['room_id'] == rid), rid)
                log(room_name[:6], f"[Browser Restart] 采样达上限，重置计数器")
                samples_this_browser_run[rid] = 0
                browser_restart_counters[rid] = browser_restart_counters.get(rid, 0) + 1

        # 保存进度
        progress = {
            "total_samples": sample_no,
            "elapsed_sec": elapsed,
            "any_confirmed_down": any_confirmed_down,
            "browser_restart_counters": browser_restart_counters,
            "rooms": room_summaries,
            "last_ts": datetime.now().isoformat(),
        }
        save_progress(progress)

        # 所有直播间均下播且运行超过2分钟 → 停止
        if elapsed > 120 and not any_live:
            log("", "所有直播间均已下播（API确认），停止监控")
            break

        # 精确等待
        next_sample_ts = start_ts + (sample_no - total_samples) * POLL_INTERVAL_SEC
        sleep_time = max(next_sample_ts - time.time(), 1)
        if sleep_time > 0:
            log("", f"  等待 {sleep_time:.0f}s 至下一个采样点...")
            time.sleep(sleep_time)

    # ============ 最终报告 ============
    log("", "\n" + "=" * 65)
    log("", "📊 抖音直播间 v7 — 最终分析报告")
    log("", "=" * 65)

    all_room_reports = {}
    all_online_data = {}
    all_like_data = {}

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

        # 打印结构化报告
        log("", f"  📈 核心指标:")
        log("", f"     在线人数: 平均={report['avg_online']} 峰值={report['peak_online']} 趋势={report['online_trend_pct']:+.1f}%")
        log("", f"     点赞增量: +{report['like_delta']:,} (≈{report['like_per_min']}/min)")
        log("", f"     互动指数: 人均点赞={report['likes_per_viewer']} 稳定性={report['stability_score']}%")
        if report['anomaly_events']:
            log("", f"     异常事件: {len(report['anomaly_events'])}次（{'↑突增' if report['anomaly_events'][0]['to'] > report['anomaly_events'][0]['from'] else '↓突降'}）")

        log("", f"  🛒 营销分析:")
        log("", f"     购物车: {len(report['cart_items_count'])}个商品 {report['cart_items_count']}")
        log("", f"     营销力度评分: {report['marketing_score']}/100")
        log("", f"     内容类型: {report['content_type']}")

        log("", f"  💬 话术分析:")
        log("", f"     产品关键词: {report['product_keywords']}")
        log("", f"     直播标题: {report['titles']}")
        log("", f"     弹幕密度: {report['danmu_density']}（WebSocket接入后可见）")

        if report['peak_time']:
            log("", f"  ⏰ 峰值时间: {report['peak_time']}")

        all_online_data[rid] = report.get('online_trend_list', [])
        all_like_data[rid] = report.get('like_delta', 0)

    # ============ 双品牌横向对比 ============
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
        log("", f"  峰值时间: {r1.get('peak_time','N/A')} vs {r2.get('peak_time','N/A')}")

        # 综合表现判断
        r1_wins = sum([
            r1['avg_online'] > r2['avg_online'],
            r1['peak_online'] > r2['peak_online'],
            r1['like_delta'] > r2['like_delta'],
            r1['marketing_score'] > r2['marketing_score'],
            r1['stability_score'] > r2['stability_score'],
        ])
        log("", f"\n  综合表现: {r1['room_name']} 赢{r1_wins}项 / {r2['room_name']} 赢{5-r1_wins}项")

    # 保存最终报告
    final_report = {
        "version": "v7-multi-room",
        "generated_at": datetime.now().isoformat(),
        "duration_sec": DURATION_SEC,
        "total_samples": sample_no,
        "rooms": {rid: {**r, "samples_count": len(valid_samples)} for rid, (r, valid_samples) in [
            (rid, (all_room_reports.get(rid, {}), read_samples(rid))) for rid in [r['room_id'] for r in ROOMS]
        ]},
        "comparison": {
            rid: {
                "avg_online": r.get('avg_online', 0),
                "peak_online": r.get('peak_online', 0),
                "like_delta": r.get('like_delta', 0),
                "marketing_score": r.get('marketing_score', 0),
                "content_type": r.get('content_type', 'N/A'),
            } for rid, r in all_room_reports.items() if 'error' not in r
        }
    }

    out_path = f"{STATE_DIR}/douyin_live_v7_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(final_report, f, ensure_ascii=False, indent=2)

    log("", f"\n📁 报告已保存: {out_path}")

    # JSON 输出（供 cron final response 使用）
    print("\n" + "=" * 60)
    print("📊 抖音直播间 v7 多直播间监控报告")
    print(json.dumps(final_report, ensure_ascii=False, indent=2))

    return final_report

if __name__ == "__main__":
    def signal_handler(signum, frame):
        log("", f"收到信号 {signum}，保存状态后退出...")
        sys.exit(0)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    run()
