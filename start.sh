#!/bin/bash

# OrchestraAI 启动脚本
echo "🎼 启动 OrchestraAI 多AI协作平台..."

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 未安装，请先安装Python3"
    exit 1
fi

# 检查pip
if ! command -v pip &> /dev/null; then
    echo "❌ pip 未安装，请先安装pip"
    exit 1
fi

# 安装依赖
echo "📦 安装Python依赖..."
pip install -r requirements.txt

# 检查Ollama服务
echo "🔍 检查Ollama服务状态..."
if ! curl -s http://localhost:11434/api/tags > /dev/null; then
    echo "⚠️  Ollama服务未运行或未安装"
    echo "请先安装并启动Ollama服务："
    echo "1. 访问 https://ollama.ai 下载安装Ollama"
    echo "2. 运行: ollama pull qwen2.5:7b"
    echo "3. 启动Ollama服务"
    echo ""
    echo "继续启动Web服务，但AI���能将不可用..."
fi

# 创建输出目录
echo "📁 创建输出目录..."
mkdir -p generated_code

# 启动服务
echo "🚀 启动Web服务..."
echo "访问地址: http://localhost:8000"
echo "按 Ctrl+C 停止服务"
echo ""

python3 main.py