#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
纳斯达克100博客自动写作机器人 v2.0
增加美股新闻抓取（RSS + Finnhub）
"""

import akshare as ak
import requests
import time
import sys
import os
import feedparser
from datetime import datetime
from typing import Dict, Tuple, List

# ====================================================================
#  配置
# ====================================================================

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_KEY") or ""
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN") or ""
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY") or ""  # 新增：Finnhub API Key

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
#  新闻抓取模块（新增）
# ====================================================================

def fetch_rss_news() -> str:
    """从RSS源抓取美股新闻"""
    log("正在抓取RSS新闻...", "INFO")
    
    feeds = [
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^IXIC",
        "https://www.nasdaq.com/feed/rssoutbound",
        "https://www.marketwatch.com/rss/headline?type=stock&source=nasdaq"
    ]
    
    all_news = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                title = entry.title
                # 去重
                if title not in all_news:
                    all_news.append(f"• {title}")
        except Exception as e:
            log(f"RSS源 {url} 抓取失败: {e}", "WARN")
            continue
    
    log(f"成功抓取 {len(all_news)} 条RSS新闻", "SUCCESS")
    return "\n".join(all_news[:8])

def fetch_finnhub_news() -> str:
    """从Finnhub抓取美股个股新闻（需要API Key）"""
    if not FINNHUB_API_KEY:
        log("FINNHUB_API_KEY 未配置，跳过个股新闻", "WARN")
        return "（未配置Finnhub API Key，无法获取美股个股新闻）"
    
    log("正在抓取Finnhub个股新闻...", "INFO")
    
    symbols = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]
    today = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now().replace(day=datetime.now().day - 7)).strftime("%Y-%m-%d")
    
    all_news = []
    for sym in symbols:
        url = f"https://finnhub.io/api/v1/company-news?symbol={sym}&from={from_date}&to={today}&token={FINNHUB_API_KEY}"
        try:
            resp = requests.get(url, timeout=10).json()
            for item in resp[:2]:
                headline = item.get('headline', '')
                if headline:
                    all_news.append(f"• {sym}: {headline}")
            time.sleep(0.3)
        except Exception as e:
            log(f"{sym} 新闻抓取失败: {e}", "WARN")
            continue
    
    log(f"成功抓取 {len(all_news)} 条个股新闻", "SUCCESS")
    return "\n".join(all_news[:10])

def fetch_all_news() -> str:
    """汇总所有新闻"""
    rss_news = fetch_rss_news()
    finnhub_news = fetch_finnhub_news()
    
    combined = []
    if rss_news:
        combined.append("【RSS美股宏观新闻】")
        combined.append(rss_news)
    if finnhub_news and "未配置" not in finnhub_news:
        combined.append("【Finnhub个股新闻】")
        combined.append(finnhub_news)
    
    return "\n\n".join(combined) if combined else "（今日暂无美股新闻）"

# ====================================================================
#  数据获取（ETF资金流向）
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

def fetch_all_data() -> Tuple[Dict, str]:
    log("=" * 50, "INFO")
    log("🚀 开始抓取数据...", "INFO")
    
    etf_data = fetch_nasdaq_etf_flow()
    news_text = fetch_all_news()
    
    log("✅ 数据抓取完成", "SUCCESS")
    log("=" * 50, "INFO")
    return etf_data, news_text

# ====================================================================
#  DeepSeek 分析（升级版：加入新闻）
# ====================================================================

def build_prompt(etf_text: str, news_text: str) -> Tuple[str, str]:
    system_prompt = """你是一位拥有10年经验的美股ETF策略分析师，擅长深度解读市场信号。

## 任务
根据纳指ETF资金流向数据 和 美股新闻，撰写一篇有深度的财经短评。

## 分析要求
1. 结合ETF资金流向和新闻事件，分析市场逻辑
2. 挖掘数据背后的多空博弈、板块轮动
3. 引入历史对比和估值视角
4. 推演后市逻辑，给出操作启示

## 格式要求
- 不要使用 ## ** > - 等任何Markdown符号
- 直接用自然段落输出，段落间用空行分隔
- 文章末尾另起一行，用 【标题】 标注一个25-35字的钩子标题

## 文风
专业、犀利、有洞察力。"""

    user_content = f"""请根据以下今日数据和新闻，撰写深度分析文章：

【纳指ETF资金流向】
{etf_text}

【美股新闻】
{news_text}

【数据说明】
ETF数据来自东方财富网公开数据。新闻来自Yahoo Finance、Nasdaq.com、MarketWatch等公开RSS源，以及Finnhub API。"""
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
        "max_tokens": 3000
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
#  数据来源声明
# ====================================================================

def build_data_source() -> str:
    today = datetime.now().strftime("%Y年%m月%d日")
    return f"""

---
【数据来源声明】
本文数据来源包括：
1. ETF资金流向数据：东方财富网（https://www.eastmoney.com）
2. 美股新闻：Yahoo Finance、Nasdaq.com、MarketWatch 公开RSS源，以及 Finnhub API

数据日期：{today}
本文由AI辅助生成，内容仅供参考，不构成投资建议。投资有风险，入市需谨慎。
"""

# ====================================================================
#  主程序
# ====================================================================

def main():
    print("\n" + "=" * 60)
    print("  📈 纳斯达克100 博客自动写作机器人 v2.0")
    print("  ⏰ 运行时间: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60 + "\n")

    if not DEEPSEEK_API_KEY:
        log("⚠️ DEEPSEEK_API_KEY 未设置！", "ERROR")
        sys.exit(1)

    etf_data, news_text = fetch_all_data()
    etf_text = etf_data["data"] or "（纳指ETF数据暂缺）"

    system_prompt, user_content = build_prompt(etf_text, news_text)
    success, title, article = call_deepseek(system_prompt, user_content)

    if not success:
        article = f"""今日简报生成失败

数据情况：
纳指ETF：{etf_text[:200]}

请检查 DeepSeek API 配置。"""
        title = "简报生成异常"

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
