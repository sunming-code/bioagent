#!/bin/bash
# 实验状态检查脚本
# 使用方法: bash evaluation/check_experiment_status.sh

cd /Users/vinorica/CodeBuddy/grad/GDgpt

echo "================================================"
echo "🧪 GDgpt 实验状态检查"
echo "================================================"
echo ""

# 检查进程
echo "📊 运行中的实验进程:"
echo "------------------------------------------------"
ps aux | grep run_batch_eval | grep -v grep
if [ $? -ne 0 ]; then
    echo "  (无运行中的实验进程)"
fi
echo ""

# 检查 Exp-0 (Full KG)
echo "📁 Exp-0 (Full Task KG) 状态:"
echo "------------------------------------------------"
if [ -f "evaluation/results/quick_exp0_full.jsonl" ]; then
    count=$(wc -l < evaluation/results/quick_exp0_full.jsonl)
    echo "  已完成: $count / 30 题"
else
    echo "  结果文件不存在"
fi

if [ -f "evaluation/results/quick_exp0_full.log" ]; then
    echo "  最新日志:"
    tail -5 evaluation/results/quick_exp0_full.log | sed 's/^/    /'
else
    echo "  日志文件不存在"
fi
echo ""

# 检查 Exp-1 (LLM only)
echo "📁 Exp-1 (LLM only) 状态:"
echo "------------------------------------------------"
if [ -f "evaluation/results/quick_exp1_llm_only.jsonl" ]; then
    count=$(wc -l < evaluation/results/quick_exp1_llm_only.jsonl)
    echo "  已完成: $count / 30 题"
else
    echo "  结果文件不存在 (可能尚未开始)"
fi

if [ -f "evaluation/results/quick_exp1_llm_only.log" ]; then
    echo "  最新日志:"
    tail -5 evaluation/results/quick_exp1_llm_only.log | sed 's/^/    /'
fi
echo ""

echo "================================================"
echo "💡 提示: 再次运行此脚本检查进度"
echo "   bash evaluation/check_experiment_status.sh"
echo "================================================"
