#!/bin/bash
# hot-monitor 快捷安装脚本
set -e

echo "🔥 hot-monitor 安装中..."

# 检测 Python
if ! command -v python3 &>/dev/null; then
    echo "❌ python3 未安装"
    exit 1
fi

# 创建 venv（如果不存在）
if [ ! -d ".venv" ]; then
    echo "📦 创建 Python 虚拟环境..."
    python3 -m venv .venv
fi

# 激活 venv
source .venv/bin/activate

# 安装依赖
echo "📦 安装 Python 依赖..."
pip install --upgrade pip -q
pip install playwright -q
playwright install chromium --with-deps -q 2>/dev/null || playwright install chromium -q

# 生成配置文件
if [ ! -f "config.json" ]; then
    echo "📝 生成配置文件..."
    cp config.example.json config.json
    echo "⚠️  请编辑 config.json 填入飞书 user_id 和代理地址"
fi

echo ""
echo "✅ 安装完成！"
echo ""
echo "下一步："
echo "  1. 编辑 config.json 填入配置"
echo "  2. 运行: source .venv/bin/activate && python scripts/hot_monitor_v1.py"
echo ""
