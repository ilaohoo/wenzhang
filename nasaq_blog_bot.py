#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
纳斯达克100博客自动写作机器人 v1.9
深度分析版：引入估值、历史对比、逻辑推演，自动标注数据来源
"""

import akshare as ak
import requests
import time
import sys
import os
from datetime import datetime
from typing import Dict, Tuple, List

# ====================================================================
#  配置
# ====================================================================

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_KEY") or ""
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN") or ""

ENABLE_PUSH: bool = True
ENABLE_PRINT_PREVIEW: bool = True

# ====================================================================
#  工具函数
# ====================================================================

def log(msg: str, level: str = "INFO") -> None:
    color_map = {
        "INFO": "\033[94m",
        "SUCCESS": "\033[92m",
        "WARN": "\033[93m",
        "ERROR": "\033[91m",
        "RESET": "\033[0m"
    }
    prefix = color_map.get(level, "")
    suffix = color_map.get("RESET", "")
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"{prefix}[{timestamp}] {msg}{suffix}")

# ====================================================================
#  数据获取
# ====================================================================

def fetch_nasdaq_etf_flow() -> Dict:
    result = {"status": "success", "data": "无数据", "error": None}
    try:
        log("正在获取纳指ETF资金流向...", "INFO")
        etf_list = ak.fund_etf_spot_em()
        keywords = ['纳斯达克', '纳指']
        mask = etf_list['名称'].str.contains('|'.join(keywords), na=False)
        nasdaq_etfs = etf_list[mask]
        if nasdaq_etfs.empty:
            result["data"] = "今日未找到纳指ETF数据"
            return result
        cols = ['名称', '最新价', '涨跌幅', '成交额']
        available_cols = [c for c in cols if c in nasdaq_etfs.columns]
        summary = nasdaq_etfs[available_cols].head(5)
        result["data"] = summary.to_string(index=False)
        log(f"成功获取 {len(summary)} 只纳指ETF数据", "SUCCESS")
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        log(f"ETF数据获取失败: {e}", "ERROR")
    return result

def fetch_all_data() -> Dict:
    log("=" * 50, "INFO")
    log("🚀 开始抓取数据...", "INFO")
    etf_data = fetch_nasdaq_etf_flow()
    log("✅ 数据抓取完成", "SUCCESS")
    log("=" * 50, "INFO")
    return etf_data

# ====================================================================
#  DeepSeek 深度分析（升级版提示词）
# ====================================================================

def build_prompt(etf_text: str) -> Tuple[str, str]:
    system_prompt = """你是一位拥有10年经验的美股ETF策略分析师，擅长深度解读市场信号。

## 任务
根据纳指ETF资金流向数据，撰写一篇有深度的财经短评。

## 深度分析要求（重要）
1. 不只是描述数据，要挖掘数据背后的逻辑。例如：
   - 某只ETF成交额异常放大但价格微跌 → 多空分歧加剧，谁在买、谁在卖？
   - 资金从传统纳指ETF流向生物科技ETF → 板块轮动开始，驱动力是什么？
2. 引入历史对比。例如：当前成交额/资金流向与过去一周、一个月相比处于什么水平？
3. 引入估值视角。例如：纳指当前估值分位数如何？资金流向与估值是否匹配？
4. 推演后市逻辑。例如：如果某类资金持续流入/流出，未来1-2周可能出现什么局面？
5. 给出明确的操作逻辑，而非模糊建议。

## 文章结构（纯文本，不要用## **等符号）
第一段：今日资金流向核心信号（最关键的1-2个数据点）
第二段：深度解读——数据背后的多空逻辑与板块轮动
第三段：历史视角与估值参考
第四段：后市推演与操作启示

## 格式要求
- 不要使用任何 Markdown 符号（如 ## ** > - 等）
- 不要使用编号列表
- 直接用自然段落输出，段落间用空行分隔
- 文章末尾另起一行，用 【标题】 标注一个25-35字的钩子标题

## 文风
专业、犀利、有洞察力，像跟资深投资者聊天。"""

    user_content = f"""请根据以下今日数据撰写深度分析文章：

【纳指ETF资金流向】
{etf_text}

【数据说明】
以上数据来自东方财富公开数据，包含今日纳指相关ETF的成交额、涨跌幅等信息。请结合这些数据，运用你的专业知识进行深度解读。"""
    return system_prompt, user_content

def call_deepseek(system_prompt: str, user_content: str, max_retries: int = 3) -> Tuple[bool, str, str]:
    if not DEEPSEEK_API_KEY:
        return False, "配置错误", "DEEPSEEK_API_KEY 未设置"
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
        "temperature": 0.7,
        "max_tokens": 2500
    }
    for attempt in range(1, max_retries + 1):
        try:
            log(f"正在调用DeepSeek API... (第{attempt}次)", "INFO")
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()
            full_text = result['choices'][0]['message']['content']
            title = "📊 纳指每日简报"
            if "【标题】" in full_text:
                parts = full_text.split("【标题】")
                if len(parts) > 1:
                    raw_title = parts[-1].strip()
                    title = raw_title.split("\n")[0].strip()
                    if not title:
                        title = "📊 纳指每日简报"
            log("✅ DeepSeek分析完成", "SUCCESS")
            return True, title, full_text
        except Exception as e:
            log(f"API调用失败 (第{attempt}次): {e}", "WARN")
            if attempt < max_retries:
                time.sleep(3)
    return False, "API调用失败", "DeepSeek API 多次重试后失败。"

# ====================================================================
#  PushPlus 微信推送
# ====================================================================

def push_to_wechat(title: str, content: str) -> bool:
    if not ENABLE_PUSH:
        log("推送已禁用", "WARN")
        return True

    if not PUSHPLUS_TOKEN:
        log("PUSHPLUS_TOKEN 未配置，跳过推送", "WARN")
        return False

    url = "https://www.pushplus.plus/send"
    params = {
        "token": PUSHPLUS_TOKEN,
        "title": title[:100],
        "content": content,
        "template": "txt"
    }

    try:
        log("正在推送至微信...", "INFO")
        response = requests.get(url, params=params, timeout=15)

        if response.status_code != 200:
            log(f"❌ 推送失败，HTTP状态码: {response.status_code}", "ERROR")
            return False

        try:
            resp_json = response.json()
            if resp_json.get('code') == 200:
                log("✅ 微信推送成功！", "SUCCESS")
                return True
            else:
                log(f"❌ 推送失败: {resp_json.get('msg', resp_json)}", "ERROR")
                return False
        except ValueError:
            log(f"❌ 响应异常: {response.text[:200]}", "ERROR")
            return False

    except requests.exceptions.Timeout:
        log("❌ 推送超时", "ERROR")
        return False
    except Exception as e:
        log(f"❌ 推送异常: {e}", "ERROR")
        return False

# ====================================================================
#  生成数据来源声明
# ====================================================================

def build_data_source() -> str:
    """生成数据来源和法律声明"""
    today = datetime.now().strftime("%Y年%m月%d日")
    return f"""

---
【数据来源声明】
本文数据来源于东方财富网（https://www.eastmoney.com）公开披露的ETF行情数据，数据日期为{today}。
本文由AI辅助生成，内容仅供参考，不构成投资建议。投资有风险，入市需谨慎。
如需引用本文数据，请注明数据来源为东方财富网。
"""

# ====================================================================
#  主程序
# ====================================================================

def main():
    print("\n" + "=" * 60)
    print("  📈 纳斯达克100 博客自动写作机器人 v1.9")
    print("  ⏰ 运行时间: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60 + "\n")

    if not DEEPSEEK_API_KEY:
        log("⚠️ DEEPSEEK_API_KEY 未设置！", "ERROR")
        sys.exit(1)

    etf_data = fetch_all_data()
    etf_text = etf_data["data"] or "（纳指ETF数据暂缺）"

    system_prompt, user_content = build_prompt(etf_text)
    success, title, article = call_deepseek(system_prompt, user_content)

    if not success:
        article = f"""今日简报生成失败

数据情况：
纳指ETF：{etf_text[:200]}

请检查 DeepSeek API 配置。"""
        title = "简报生成异常"

    # 添加数据来源声明
    full_article = article + build_data_source()

    if ENABLE_PRINT_PREVIEW:
        print("\n" + "=" * 60)
        print(f"标题：{title}")
        print("=" * 60)
        print(full_article)
        print("=" * 60 + "\n")

    with open("briefing.md", "w", encoding="utf-8") as f:
        f.write(f"{title}\n\n{full_article}")

    push_success = push_to_wechat(title, full_article)

    print("\n" + "=" * 60)
    if push_success:
        print("  任务执行完毕！请查看微信消息。")
    else:
        print("  任务执行完毕，但微信推送未成功。")
        print("  文章已保存到 briefing.md")
    print("=" * 60 + "\n")

    sys.exit(0 if push_success else 1)

if __name__ == "__main__":
    main()
