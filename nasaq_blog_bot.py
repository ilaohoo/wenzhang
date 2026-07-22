#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
纳斯达克100博客自动写作机器人
功能：获取纳指ETF资金流向 + 七巨头行情 → DeepSeek分析 → 推送微信
作者：你的博客
版本：v1.0
"""

import akshare as ak
import requests
import json
import time
import sys
from datetime import datetime
from typing import Dict, Tuple, Optional, List

# ====================================================================
#  ⚙️  配置区（修改这里即可运行）
# ====================================================================

# ---------- DeepSeek API ----------
# 去 https://platform.deepseek.com 注册获取
DEEPSEEK_API_KEY = "sk-你的DeepSeek密钥"   # 替换成你的

# ---------- PushPlus 推送 ----------
# 关注"PushPlus"公众号获取token（首次需1元）
PUSHPLUS_TOKEN = "你的PushPlus令牌"        # 替换成你的

# ---------- 要追踪的纳指100权重股（俗称"七巨头"） ----------
# 代码使用雅虎格式，可以直接添加或删除
MAGNIFICENT_7: List[str] = [
    "AAPL",   # 苹果
    "MSFT",   # 微软
    "NVDA",   # 英伟达
    "GOOGL",  # 谷歌
    "AMZN",   # 亚马逊
    "META",   # Meta
    "TSLA"    # 特斯拉
]

# ---------- 是否获取完整的纳指100成分股数据（会慢一些，但信息更全） ----------
FETCH_ALL_NASDAQ_100: bool = False   # 默认False，只追踪七巨头

# ---------- 推送开关 ----------
ENABLE_PUSH: bool = True             # 是否推送到微信
ENABLE_PRINT_PREVIEW: bool = True    # 是否在控制台打印文章预览

# ====================================================================
#  工具函数
# ====================================================================

def log(msg: str, level: str = "INFO") -> None:
    """带时间戳的日志输出"""
    color_map = {
        "INFO": "\033[94m",    # 蓝色
        "SUCCESS": "\033[92m", # 绿色
        "WARN": "\033[93m",    # 黄色
        "ERROR": "\033[91m",   # 红色
        "RESET": "\033[0m"     # 重置
    }
    prefix = color_map.get(level, "")
    suffix = color_map.get("RESET", "")
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"{prefix}[{timestamp}] {msg}{suffix}")

def safe_get(data: dict, keys: list, default="N/A") -> str:
    """安全地从嵌套字典中取值"""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key, {})
        else:
            return default
    return data if data is not None and data != {} else default

# ====================================================================
#  第一步：数据获取
# ====================================================================

def fetch_nasdaq_etf_flow() -> Dict:
    """
    获取A股市场纳指ETF的资金流向数据
    返回：包含名称、价格、涨跌幅、主力净流入的DataFrame转字符串
    """
    result = {"status": "success", "data": "无数据", "error": None}
    
    try:
        log("正在获取纳指ETF资金流向...", "INFO")
        etf_list = ak.fund_etf_spot_em()
        
        # 筛选名称包含"纳斯达克"或"纳指"的ETF
        keywords = ['纳斯达克', '纳指']
        mask = etf_list['名称'].str.contains('|'.join(keywords), na=False)
        nasdaq_etfs = etf_list[mask]
        
        if nasdaq_etfs.empty:
            result["data"] = "今日未找到纳指ETF数据，可能休市或数据源无更新。"
            log("未找到纳指ETF数据", "WARN")
            return result
        
        # 保留关键字段，取前5只
        cols = ['名称', '最新价', '涨跌幅', '主力净流入', '成交额']
        available_cols = [c for c in cols if c in nasdaq_etfs.columns]
        summary = nasdaq_etfs[available_cols].head(5)
        
        # 格式化输出
        result["data"] = summary.to_string(index=False)
        log(f"成功获取 {len(summary)} 只纳指ETF数据", "SUCCESS")
        
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        log(f"ETF数据获取失败: {e}", "ERROR")
    
    return result

def fetch_stock_quote(symbol: str) -> Optional[Dict]:
    """
    获取单只美股实时行情
    返回：包含价格、涨跌幅的字典，失败返回None
    """
    try:
        quote = ak.stock_us_quote(symbol=symbol)
        if quote is None or quote.empty:
            return None
        
        row = quote.iloc[0]
        return {
            "symbol": symbol,
            "price": row.get('最新价', 'N/A'),
            "change_pct": row.get('涨跌幅', 'N/A'),
            "volume": row.get('成交量', 'N/A')
        }
    except Exception as e:
        log(f"{symbol} 行情获取失败: {e}", "ERROR")
        return None

def fetch_magnificent_7() -> Dict:
    """
    获取七巨头实时行情
    返回：状态 + 格式化的文本数据
    """
    result = {"status": "success", "data": "", "error": None}
    
    log(f"正在获取 {len(MAGNIFICENT_7)} 只权重股行情...", "INFO")
    
    quotes = []
    failed = []
    
    for symbol in MAGNIFICENT_7:
        quote = fetch_stock_quote(symbol)
        if quote:
            quotes.append(quote)
        else:
            failed.append(symbol)
        time.sleep(0.3)  # 礼貌性停顿，防止被限流
    
    if quotes:
        # 格式化输出：按涨跌幅排序（涨幅大的排前面）
        sorted_quotes = sorted(quotes, key=lambda x: float(x["change_pct"]) if x["change_pct"] != 'N/A' else -999, reverse=True)
        
        lines = []
        for q in sorted_quotes:
            pct = q["change_pct"]
            # 带符号显示
            if isinstance(pct, (int, float)):
                sign = "+" if pct > 0 else ""
                pct_str = f"{sign}{pct:.2f}%"
            else:
                pct_str = str(pct)
            lines.append(f"• {q['symbol']}: ${q['price']}  ({pct_str})")
        
        result["data"] = "\n".join(lines)
        log(f"成功获取 {len(quotes)} 只股票数据", "SUCCESS")
    else:
        result["status"] = "error"
        result["error"] = "所有股票数据获取失败"
        log("七巨头数据全部获取失败", "ERROR")
    
    if failed:
        result["data"] += f"\n\n⚠️ 以下股票数据暂缺：{', '.join(failed)}"
    
    return result

def fetch_all_data() -> Tuple[Dict, Dict]:
    """
    汇总所有数据
    返回：(ETF数据, 七巨头数据)
    """
    log("=" * 50, "INFO")
    log("🚀 开始抓取数据...", "INFO")
    
    etf_data = fetch_nasdaq_etf_flow()
    stock_data = fetch_magnificent_7()
    
    log("✅ 数据抓取完成", "SUCCESS")
    log("=" * 50, "INFO")
    
    return etf_data, stock_data

# ====================================================================
#  第二步：DeepSeek 分析与写作
# ====================================================================

def build_prompt(etf_text: str, stock_text: str) -> Tuple[str, str]:
    """
    构建给DeepSeek的系统提示词和用户输入
    返回：(system_prompt, user_content)
    """
    
    system_prompt = """你是一位拥有10年经验的美股ETF策略分析师，擅长将枯燥的数据转化为投资者爱看的深度洞察。

## 你的任务
根据用户提供的纳指ETF资金流向和七巨头行情数据，撰写一篇专业的财经短评。

## 文章结构要求
1. **聪明钱动向**：分析主力资金在流入还是流出纳指ETF，结合成交额和涨跌幅判断信号强度。
2. **巨头轮动分析**：对比七只权重股的表现，指出领涨和领跌的股票，分析资金在板块间的轮动逻辑（例如：资金从AI芯片转向消费电子，或从成长股转向防御性龙头）。
3. **核心结论**：用一两句话总结当前市场最核心的交易逻辑，并给散户一个明确的操作启示（观点鲜明，不模棱两可）。

## 文风要求
- 专业但不晦涩，像跟朋友聊市场一样通透。
- 多用数据说话，但要翻译成"这对你意味着什么"。
- 可以适当使用比喻，增强可读性。

## 输出格式
- 使用Markdown格式，分三个板块（加粗标题）。
- 文章结尾另起一行，用 **【标题】** 标注一个25-35字的钩子标题。
- 标题要求：包含核心关键词（如"纳指""资金""巨头"），有吸引力但不标题党。"""

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
    """
    调用DeepSeek API生成文章
    返回：(是否成功, 标题, 文章内容)
    """
    
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY.startswith("sk-你的"):
        return False, "配置错误", "请先在代码顶部配置 DEEPSEEK_API_KEY"
    
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.6,
        "max_tokens": 2000
    }
    
    for attempt in range(1, max_retries + 1):
        try:
            log(f"正在调用DeepSeek API... (第{attempt}次尝试)", "INFO")
            response = requests.post(url, headers=headers, json=payload, timeout=45)
            response.raise_for_status()
            
            result = response.json()
            full_text = result['choices'][0]['message']['content']
            
            # 提取标题
            title = "📊 纳指每日简报"
            if "【标题】" in full_text:
                parts = full_text.split("【标题】")
                if len(parts) > 1:
                    raw_title = parts[-1].strip()
                    # 取第一行
                    title = raw_title.split("\n")[0].strip()
                    # 移除可能残留的符号
                    title = title.replace("】", "").strip()
                    if not title:
                        title = "📊 纳指每日简报"
            
            log("✅ DeepSeek分析完成", "SUCCESS")
            return True, title, full_text
            
        except requests.exceptions.Timeout:
            log(f"API调用超时 (第{attempt}次)", "WARN")
        except requests.exceptions.RequestException as e:
            log(f"API请求失败: {e} (第{attempt}次)", "WARN")
        except Exception as e:
            log(f"未知错误: {e} (第{attempt}次)", "WARN")
        
        if attempt < max_retries:
            time.sleep(3)  # 重试前等待3秒
    
    return False, "API调用失败", "DeepSeek API 多次重试后仍失败，请检查网络和密钥。"

# ====================================================================
#  第三步：PushPlus 微信推送
# ====================================================================

def push_to_wechat(title: str, content: str) -> bool:
    """
    通过PushPlus推送到微信
    返回：是否成功
    """
    
    if not ENABLE_PUSH:
        log("推送已禁用 (ENABLE_PUSH=False)", "WARN")
        return True
    
    if not PUSHPLUS_TOKEN or PUSHPLUS_TOKEN.startswith("你的PushPlus"):
        log("未配置PUSHPLUS_TOKEN，跳过推送", "WARN")
        return False
    
    url = "https://www.pushplus.plus/send"
    params = {
        "token": PUSHPLUS_TOKEN,
        "title": title[:100],  # 标题限制100字
        "content": content,
        "template": "markdown"
    }
    
    try:
        log("正在推送至微信...", "INFO")
        resp = requests.get(url, params=params, timeout=15)
        resp_json = resp.json()
        
        if resp_json.get('code') == 200:
            log("✅ 微信推送成功！", "SUCCESS")
            return True
        else:
            log(f"❌ 推送失败: {resp_json.get('msg', resp.text)}", "ERROR")
            return False
    except Exception as e:
        log(f"❌ 推送异常: {e}", "ERROR")
        return False

# ====================================================================
#  主程序
# ====================================================================

def main():
    """主程序入口"""
    print("\n" + "=" * 60)
    print("  📈 纳斯达克100 博客自动写作机器人 v1.0")
    print("  ⏰ 运行时间: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60 + "\n")
    
    # ----- 第一步：抓取数据 -----
    etf_data, stock_data = fetch_all_data()
    
    # 检查数据是否有效
    if etf_data["status"] == "error" and stock_data["status"] == "error":
        log("所有数据源均获取失败，程序终止", "ERROR")
        sys.exit(1)
    
    # 准备文本
    etf_text = etf_data["data"] or "（纳指ETF数据暂缺）"
    stock_text = stock_data["data"] or "（七巨头行情数据暂缺）"
    
    # ----- 第二步：AI生成文章 -----
    system_prompt, user_content = build_prompt(etf_text, stock_text)
    success, title, article = call_deepseek(system_prompt, user_content)
    
    if not success:
        # 如果AI调用失败，使用默认内容
        article = f"""# ⚠️ 今日简报生成失败

**数据情况**：
- 纳指ETF：{etf_text[:200]}
- 七巨头：{stock_text[:200]}

请检查 DeepSeek API 配置或稍后重试。
"""
        title = "⚠️ 简报生成异常"
    
    # ----- 第三步：控制台预览 -----
    if ENABLE_PRINT_PREVIEW:
        print("\n" + "=" * 60)
        print(f"📌 标题：{title}")
        print("=" * 60)
        print(article)
        print("=" * 60 + "\n")
    
    # ----- 第四步：推送到微信 -----
    push_success = push_to_wechat(title, article)
    
    # ----- 完成 -----
    print("\n" + "=" * 60)
    if push_success:
        print("  🎉 任务执行完毕！请查看微信消息。")
    else:
        print("  ⚠️ 任务执行完毕，但微信推送未成功。")
    print("=" * 60 + "\n")
    
    # 返回状态码（方便GitHub Actions判断）
    sys.exit(0 if push_success else 1)

# ====================================================================
#  入口
# ====================================================================

if __name__ == "__main__":
    main()
