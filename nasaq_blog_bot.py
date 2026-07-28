#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
纳斯达克100博客自动写作机器人 v3.3
修复：使用 requests 直接发送 XML-RPC 请求，支持自签名证书
"""

import akshare as ak
import requests
import time
import sys
import os
import feedparser
from datetime import datetime
from typing import Dict, Tuple, List
import socket
import json
import xml.etree.ElementTree as ET

# 禁用 SSL 警告（因为使用了 verify=False）
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

socket.setdefaulttimeout(15)

# ====================================================================
#  配置
# ====================================================================

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_KEY") or ""
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN") or ""
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY") or ""

BLOG_URL = os.environ.get("BLOG_URL", "")
BLOG_USERNAME = os.environ.get("BLOG_USERNAME", "")
BLOG_PASSWORD = os.environ.get("BLOG_PASSWORD", "")

ENABLE_PUSH: bool = True
ENABLE_PRINT_PREVIEW: bool = True
ENABLE_BLOG_PUBLISH: bool = True

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
#  新闻抓取
# ====================================================================

def fetch_rss_news() -> str:
    log("正在抓取RSS新闻...", "INFO")
    feeds = [
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^IXIC",
        "https://www.nasdaq.com/feed/rssoutbound",
        "https://feeds.reuters.com/reuters/businessNews",
        "https://feeds.bloomberg.com/wealth/news.rss",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "https://feeds.wsj.com/wsj/xml/rss/3_7014.xml",
        "https://www.forbes.com/investing/feed/",
    ]
    seen_titles = set()
    all_news = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            if not feed.entries:
                continue
            for entry in feed.entries[:3]:
                title = entry.title.strip()
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                if len(title) > 120:
                    title = title[:117] + "..."
                all_news.append(f"• {title}")
        except Exception:
            continue
    log(f"成功抓取 {len(all_news)} 条RSS新闻", "SUCCESS")
    return "\n".join(all_news[:12])

def fetch_finnhub_news() -> str:
    if not FINNHUB_API_KEY:
        return ""
    log("正在抓取Finnhub个股新闻...", "INFO")
    symbols = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]
    today = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now().replace(day=datetime.now().day - 3)).strftime("%Y-%m-%d")
    all_news = []
    seen_titles = set()
    for sym in symbols:
        try:
            url = f"https://finnhub.io/api/v1/company-news?symbol={sym}&from={from_date}&to={today}&token={FINNHUB_API_KEY}"
            resp = requests.get(url, timeout=10).json()
            for item in resp[:2]:
                headline = item.get('headline', '').strip()
                if headline and headline not in seen_titles:
                    seen_titles.add(headline)
                    if len(headline) > 120:
                        headline = headline[:117] + "..."
                    all_news.append(f"• {sym}: {headline}")
            time.sleep(0.2)
        except Exception:
            continue
    log(f"成功抓取 {len(all_news)} 条个股新闻", "SUCCESS")
    return "\n".join(all_news[:10])

def fetch_all_news() -> str:
    rss = fetch_rss_news()
    finn = fetch_finnhub_news()
    combined = []
    if rss:
        combined.append("【美股宏观新闻】")
        combined.append(rss)
    if finn:
        combined.append("【美股个股新闻】")
        combined.append(finn)
    return "\n\n".join(combined) if combined else "（今日暂无美股新闻）"

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

def fetch_all_data() -> Tuple[Dict, str]:
    log("=" * 50, "INFO")
    log("🚀 开始抓取数据...", "INFO")
    etf_data = fetch_nasdaq_etf_flow()
    news_text = fetch_all_news()
    log("✅ 数据抓取完成", "SUCCESS")
    log("=" * 50, "INFO")
    return etf_data, news_text

# ====================================================================
#  DeepSeek API
# ====================================================================

def build_prompt(etf_text: str, news_text: str) -> Tuple[str, str]:
    system_prompt = """你是一位拥有10年经验的美股ETF策略分析师。

根据纳指ETF资金流向和美股新闻，撰写一篇深度财经短评。

分析要求：
1. 结合ETF资金流向和新闻事件，分析市场逻辑
2. 挖掘数据背后的多空博弈、板块轮动
3. 推演后市逻辑，给出操作启示

格式要求：
- 不要使用任何Markdown符号
- 直接用自然段落输出，段落间用空行分隔
- 文章末尾另起一行，用【标题】标注一个25-35字的钩子标题

文风：专业、犀利、有洞察力。"""

    user_content = f"""请根据以下今日数据和新闻，撰写深度分析文章：

【纳指ETF资金流向】
{etf_text}

【美股新闻】
{news_text}"""
    return system_prompt, user_content

def call_deepseek(system_prompt: str, user_content: str, etf_text: str = "", news_text: str = "") -> Tuple[bool, str, str]:
    if not DEEPSEEK_API_KEY:
        log("API Key 未配置，使用备用内容", "WARN")
        return True, ("📊 纳指每日简报（备用）", "DeepSeek API Key 未配置，请检查 Secrets。")

    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    if len(user_content) > 10000:
        user_content = user_content[:10000]
        log("内容过长已截断", "WARN")

    payload = {
        "model": "deepseek-v4-pro",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.7,
        "max_tokens": 2500
    }

    for attempt in range(1, 4):
        try:
            log(f"正在调用DeepSeek API... (第{attempt}次)", "INFO")
            response = requests.post(url, headers=headers, json=payload, timeout=60)

            log(f"HTTP状态码: {response.status_code}", "INFO")

            if response.status_code == 200:
                result = response.json()
                full_text = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                if full_text:
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
                else:
                    log("API返回内容为空", "WARN")
            else:
                log(f"API返回错误: {response.text[:500]}", "WARN")

        except Exception as e:
            log(f"API调用异常: {e}", "WARN")

        if attempt < 3:
            time.sleep(2)

    log("所有API尝试失败，使用备用内容", "WARN")
    fallback_title = "📊 纳指每日简报（备用）"
    fallback_content = f"""纳指ETF今日资金流向观察

今日纳指相关ETF表现出现明显分化。在跟踪的几只主要纳指ETF中，各品种涨跌幅差异较大，成交额也呈现不同特征。

从资金流向来看，部分ETF成交额显著放大，显示多空双方博弈激烈。结合近期美股市场表现，纳指100指数整体处于高位震荡格局。

（DeepSeek API暂时不可用，此内容由系统自动生成）

【标题：纳指ETF分化加剧，资金博弈进入关键期】"""
    return True, fallback_title, fallback_content

# ====================================================================
#  PushPlus 微信推送
# ====================================================================

def push_to_wechat(title: str, content: str) -> bool:
    if not ENABLE_PUSH:
        return True
    if not PUSHPLUS_TOKEN:
        log("PUSHPLUS_TOKEN 未配置，跳过推送", "WARN")
        return False

    url = "https://www.pushplus.plus/send"
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": title[:100],
        "content": content,
        "template": "txt"
    }

    try:
        log("正在推送至微信...", "INFO")
        response = requests.post(url, data=data, timeout=15)

        if response.status_code != 200:
            log(f"推送失败，HTTP状态码: {response.status_code}", "ERROR")
            return False

        resp_json = response.json()
        if resp_json.get('code') == 200:
            log("✅ 微信推送成功！", "SUCCESS")
            return True
        else:
            log(f"推送失败: {resp_json.get('msg', resp_json)}", "ERROR")
            return False

    except Exception as e:
        log(f"推送异常: {e}", "ERROR")
        return False

# ====================================================================
#  博客发布（使用 requests 直接发送 XML-RPC）
# ====================================================================

def publish_to_blog(title: str, content: str) -> bool:
    if not ENABLE_BLOG_PUBLISH:
        log("博客自动发布已禁用", "WARN")
        return True

    if not BLOG_URL or not BLOG_USERNAME or not BLOG_PASSWORD:
        log("博客配置不完整（BLOG_URL/BLOG_USERNAME/BLOG_PASSWORD），跳过发布", "WARN")
        return False

    log("正在发布文章到博客...", "INFO")

    try:
        # 清理标题
        clean_title = title.replace("📊", "").strip()
        if not clean_title:
            clean_title = f"纳指每日简报 {datetime.now().strftime('%Y-%m-%d')}"

        # 将纯文本内容转换为 HTML
        paragraphs = content.split("\n\n")
        html_content = ""
        for p in paragraphs:
            p = p.strip()
            if p:
                if p.startswith("【标题】"):
                    html_content += f"<p><strong>{p}</strong></p>"
                else:
                    html_content += f"<p>{p}</p>"

        # 构造 XML-RPC 请求体
        method_call = ET.Element("methodCall")

        method_name = ET.SubElement(method_call, "methodName")
        method_name.text = "metaWeblog.newPost"

        params = ET.SubElement(method_call, "params")

        # blogid
        p1 = ET.SubElement(params, "param")
        v1 = ET.SubElement(p1, "value")
        s1 = ET.SubElement(v1, "string")
        s1.text = "1"

        # username
        p2 = ET.SubElement(params, "param")
        v2 = ET.SubElement(p2, "value")
        s2 = ET.SubElement(v2, "string")
        s2.text = BLOG_USERNAME

        # password
        p3 = ET.SubElement(params, "param")
        v3 = ET.SubElement(p3, "value")
        s3 = ET.SubElement(v3, "string")
        s3.text = BLOG_PASSWORD

        # struct (post data)
        p4 = ET.SubElement(params, "param")
        v4 = ET.SubElement(p4, "value")
        struct = ET.SubElement(v4, "struct")

        # title
        m1 = ET.SubElement(struct, "member")
        n1 = ET.SubElement(m1, "name")
        n1.text = "title"
        v1_1 = ET.SubElement(m1, "value")
        s1_1 = ET.SubElement(v1_1, "string")
        s1_1.text = clean_title

        # description
        m2 = ET.SubElement(struct, "member")
        n2 = ET.SubElement(m2, "name")
        n2.text = "description"
        v2_1 = ET.SubElement(m2, "value")
        s2_1 = ET.SubElement(v2_1, "string")
        s2_1.text = html_content

        # categories
        m3 = ET.SubElement(struct, "member")
        n3 = ET.SubElement(m3, "name")
        n3.text = "categories"
        v3_1 = ET.SubElement(m3, "value")
        arr = ET.SubElement(v3_1, "array")
        data = ET.SubElement(arr, "data")
        val = ET.SubElement(data, "value")
        s3_1 = ET.SubElement(val, "string")
        s3_1.text = "纳指简报"

        # publish (true)
        m4 = ET.SubElement(struct, "member")
        n4 = ET.SubElement(m4, "name")
        n4.text = "publish"
        v4_1 = ET.SubElement(m4, "value")
        b1 = ET.SubElement(v4_1, "boolean")
        b1.text = "1"

        xml_str = ET.tostring(method_call, encoding='unicode')

        # 发送请求
        log("发送 XML-RPC 请求...", "INFO")
        response = requests.post(
            BLOG_URL,
            data=xml_str,
            headers={"Content-Type": "text/xml"},
            verify=False,
            timeout=30
        )

        if response.status_code != 200:
            log(f"❌ HTTP 错误: {response.status_code}", "ERROR")
            return False

        # 解析响应
        try:
            resp_xml = ET.fromstring(response.text)
            # 查找 value/string 节点中的文章 ID
            string_nodes = resp_xml.findall(".//value/string")
            if string_nodes:
                post_id = string_nodes[0].text
                if post_id and post_id.isdigit():
                    log(f"✅ 文章发布成功！ID: {post_id}", "SUCCESS")
                    return True

            # 检查是否是 fault 响应
            fault_node = resp_xml.find(".//fault")
            if fault_node is not None:
                # 提取错误信息
                for member in fault_node.findall(".//member"):
                    name_node = member.find("name")
                    if name_node is not None and name_node.text == "faultString":
                        value_node = member.find("value/string")
                        if value_node is not None:
                            log(f"❌ XML-RPC 错误: {value_node.text}", "ERROR")
                            return False
                log(f"❌ XML-RPC 错误: {response.text[:300]}", "ERROR")
                return False

            log(f"❌ 无法解析响应: {response.text[:200]}", "ERROR")
            return False

        except ET.ParseError as e:
            log(f"❌ XML 解析错误: {e}", "ERROR")
            log(f"响应内容: {response.text[:300]}", "ERROR")
            return False

    except requests.exceptions.SSLError as e:
        log(f"❌ SSL 错误: {e}", "ERROR")
        log("  提示：如果博客使用自签名证书，请检查 verify=False 是否生效", "WARN")
        return False
    except Exception as e:
        log(f"❌ 发布异常: {e}", "ERROR")
        return False

# ====================================================================
#  数据来源声明
# ====================================================================

def build_data_source() -> str:
    today = datetime.now().strftime("%Y年%m月%d日")
    return f"""

---
【数据来源声明】
本文数据来源：
1. ETF资金流向：东方财富网（https://www.eastmoney.com）
2. 宏观新闻：Yahoo Finance、Nasdaq.com、Reuters、Bloomberg、CNBC、WSJ、Forbes 公开RSS
3. 个股新闻：Finnhub API（如已配置）

数据日期：{today}
本文由AI辅助生成，仅供参考，不构成投资建议。
"""

# ====================================================================
#  主程序
# ====================================================================

def main():
    print("\n" + "=" * 60)
    print("  📈 纳斯达克100 博客自动写作机器人 v3.3")
    print("  ⏰ 运行时间: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60 + "\n")

    etf_data, news_text = fetch_all_data()
    etf_text = etf_data["data"] or "（纳指ETF数据暂缺）"

    system_prompt, user_content = build_prompt(etf_text, news_text)
    success, title, article = call_deepseek(system_prompt, user_content, etf_text, news_text)

    full_article = article + build_data_source()

    if ENABLE_PRINT_PREVIEW:
        print("\n" + "=" * 60)
        print(f"标题：{title}")
        print("=" * 60)
        print(full_article)
        print("=" * 60 + "\n")

    with open("briefing.md", "w", encoding="utf-8") as f:
        f.write(f"{title}\n\n{full_article}")

    # 推送到微信
    push_success = push_to_wechat(title, full_article)

    # 自动发布到博客
    blog_success = publish_to_blog(title, full_article)

    print("\n" + "=" * 60)
    print("  任务执行结果：")
    print(f"  微信推送: {'✅ 成功' if push_success else '⚠️ 失败'}")
    print(f"  博客发布: {'✅ 成功' if blog_success else '⚠️ 失败'}")
    print("=" * 60 + "\n")

    sys.exit(0 if push_success or blog_success else 1)

if __name__ == "__main__":
    main()
