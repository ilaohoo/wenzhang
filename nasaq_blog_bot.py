#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
纳斯达克100博客自动写作机器人 v1.6
优化：美股数据获取加超时控制，防止卡死
"""

import akshare as ak
import requests
import time
import sys
import os
from datetime import datetime
from typing import Dict, Tuple, List
import concurrent.futures

# ====================================================================
#  配置
# ====================================================================

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_KEY") or ""
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN") or ""

MAGNIFICENT_7: List[str] = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]

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

def fetch_us_stocks_with_timeout(symbols: List[str], timeout: int = 60) -> Dict:
    """
    带超时控制的美股行情获取
    如果60秒内没完成，返回错误信息并继续
    """
    result = {"status": "success", "data": "", "error": None}

    def _fetch():
        try:
            log(f"正在获取美股行情（超时限制 {timeout} 秒）...", "INFO")
            all_stocks = ak.stock_us_spot()
            matched = []
            for symbol in symbols:
                mask = all_stocks['代码'].str.upper() == symbol.upper()
                stock = all_stocks[mask]
                if not stock.empty:
                    row = stock.iloc[0]
                    price = row.get('最新价', 'N/A')
                    change_pct = row.get('涨跌幅', 'N/A')
                    matched.append({"symbol": symbol.upper(), "price": price, "change_pct": change_pct})
                else:
                    matched.append({"symbol": symbol.upper(), "price": "N/A", "change_pct": "N/A"})
            return matched
        except Exception as e:
            raise e

    try:
        # 使用线程池执行，带超时
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_fetch)
            matched = future.result(timeout=timeout)

        lines = []
        for m in matched:
            if m["price"] != "N/A":
                pct = m["change_pct"]
                if isinstance(pct, (int, float)):
                    sign = "+" if pct > 0 else ""
                    pct_str = f"{sign}{pct:.2f}%"
                else:
                    pct_str = str(pct)
                lines.append(f"• {m['symbol']}: ${m['price']}  ({pct_str})")
            else:
                lines.append(f"• {m['symbol']}: 数据暂缺")
        result["data"] = "\n".join(lines)
        log("成功获取美股行情数据", "SUCCESS")

    except concurrent.futures.TimeoutError:
        result["status"] = "error"
        result["error"] = "美股数据获取超时"
        result["data"] = "• 美股行情获取超时，请稍后重试\n• 建议：可在非交易时段运行"
        log("美股行情获取超时（超过60秒）", "WARN")
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        result["data"] = f"• 美股行情获取失败: {str(e)[:50]}"
        log(f"美股行情获取失败: {e}", "ERROR")

    return result

def fetch_all_data() -> Tuple[Dict, Dict]:
    log("=" * 50, "INFO")
    log("🚀 开始抓取数据...", "INFO")

    etf_data = fetch_nasdaq_etf_flow()
    stock_data = fetch_us_stocks_with_timeout(MAGNIFICENT_7, timeout=60)

    log("✅ 数据抓取完成", "SUCCESS")
    log("=" * 50, "INFO")
    return etf_data, stock_data

# ====================================================================
#  DeepSeek 分析与写作
# ====================================================================

def build_prompt(etf_text: str, stock_text: str) -> Tuple[str, str]:
    system_prompt = """你是一位拥有10年经验的美股ETF策略分析师。

## 任务
根据纳指ETF资金流向和七巨头行情数据，撰写一篇财经短评。

## 文章结构
1. **聪明钱动向**：分析主力资金流向和信号强度。
2. **巨头轮动分析**：对比七只权重股表现，指出领涨领跌及轮动逻辑。
3. **核心结论**：总结交易逻辑，给出操作启示。

## 文风
专业但不晦涩，数据说话，适当使用比喻。最后用 **【标题】** 标注一个25-35字的钩子标题。"""

    user_content = f"""请根据以下今日数据撰写分析文章：

---
【纳指ETF资金流向】
{etf_text}

【七巨头实时行情】
{stock_text}
---
"""
    return system_prompt, user_content

def call_deepseek(system_prompt: str, user_content: str, max_retries: int = 3) -> Tuple[bool, str, str]:
    if not DEEPSEEK_API_KEY:
        return False, "配置错误", "DEEPSEEK_API_KEY 未设置"
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
        "temperature": 0.6,
        "max_tokens": 2000
    }
    for attempt in range(1, max_retries + 1):
        try:
            log(f"正在调用DeepSeek API... (第{attempt}次)", "INFO")
            response = requests.post(url, headers=headers, json=payload, timeout=45)
            response.raise_for_status()
            result = response.json()
            full_text = result['choices'][0]['message']['content']
            title = "📊 纳指每日简报"
            if "【标题】" in full_text:
                parts = full_text.split("【标题】")
                if len(parts) > 1:
                    raw_title = parts[-1].strip()
                    title = raw_title.split("\n")[0].strip().replace("】", "")
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
        "template": "markdown"
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
#  主程序
# ====================================================================

def main():
    print("\n" + "=" * 60)
    print("  📈 纳斯达克100 博客自动写作机器人 v1.6")
    print("  ⏰ 运行时间: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60 + "\n")

    if not DEEPSEEK_API_KEY:
        log("⚠️ DEEPSEEK_API_KEY 未设置！", "ERROR")
        sys.exit(1)

    etf_data, stock_data = fetch_all_data()
    etf_text = etf_data["data"] or "（纳指ETF数据暂缺）"
    stock_text = stock_data["data"] or "（七巨头行情数据暂缺）"

    system_prompt, user_content = build_prompt(etf_text, stock_text)
    success, title, article = call_deepseek(system_prompt, user_content)

    if not success:
        article = f"""# ⚠️ 今日简报生成失败

**数据情况**：
- 纳指ETF：{etf_text[:200]}
- 七巨头：{stock_text[:200]}

请检查 DeepSeek API 配置。
"""
        title = "⚠️ 简报生成异常"

    if ENABLE_PRINT_PREVIEW:
        print("\n" + "=" * 60)
        print(f"📌 标题：{title}")
        print("=" * 60)
        print(article)
        print("=" * 60 + "\n")

    # 保存文章
    with open("briefing.md", "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{article}")

    push_success = push_to_wechat(title, article)

    print("\n" + "=" * 60)
    if push_success:
        print("  🎉 任务执行完毕！请查看微信消息。")
    else:
        print("  ⚠️ 任务执行完毕，但微信推送未成功。")
        print("  📄 文章已保存到 briefing.md")
    print("=" * 60 + "\n")

    sys.exit(0 if push_success else 1)

if __name__ == "__main__":
    main()
