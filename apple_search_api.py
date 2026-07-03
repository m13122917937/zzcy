import requests
import re
import base64
import os
import io
import sys
import time
import asyncio
import aiohttp
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
import pandas as pd
from typing import List, Dict, Optional, Union
import json
import threading
from dataclasses import dataclass
from pathlib import Path
import logging

# 尝试导入 curl_cffi，如果失败则使用备用方案
try:
    from curl_cffi import requests as curl_requests
    from curl_cffi.requests.errors import RequestsError as CurlRequestsError
    CURL_CFFI_AVAILABLE = True
except ImportError as e:
    # 如果 curl_cffi 不可用，使用普通 requests 作为备用
    CURL_CFFI_AVAILABLE = False
    import requests as curl_requests
    # 创建一个虚拟的异常类
    class CurlRequestsError(Exception):
        pass
    print(f"[警告] curl_cffi 导入失败: {e}，将使用普通 requests")

# 尝试导入 PIL，如果失败则提供备用方案
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError as e:
    PIL_AVAILABLE = False
    print(f"[警告] PIL 导入失败: {e}")


# =========================================最终响应处理函数=========================================

"""
Apple Coverage HTML Parser  v2.0
==================================
从 Apple 保障查询页面 (checkcoverage.apple.com) 的 HTML 文件中
提取与序列号 (serialNumber) 强相关的所有字段，并输出标准化 JSON 对象。

支持的数据来源：
  · Next.js SSR payload（__next_f.push，双层 JSON 转义）
  · 页面内嵌 API JSON 块（如存在）

用法：
    python apple_coverage_parser.py <input.html> [output.json]

若不指定输出文件，结果将打印到标准输出。
"""

import json
import re
import sys
import os
from datetime import datetime
from urllib.parse import urlparse, parse_qs


# ────────────────────────────────────────────
# 工具函数
# ────────────────────────────────────────────

def _safe_get(d, *keys, default=""):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur if cur is not None else default


def _extract_snkey(url: str) -> str:
    try:
        return parse_qs(urlparse(url).query).get("snKey", [""])[0]
    except Exception:
        return ""


def _parse_date_to_iso(text: str) -> str:
    """将 '2025年6月22日' / '2026年6月21 日' 等转为 YYYY-MM-DD。"""
    if not text:
        return ""
    m = re.search(r'(\d{4})\D+?(\d{1,2})\D+?(\d{1,2})', text)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
    return text


def _coverage_type_label(ct: str) -> str:
    return {
        "LIMITED_WARRANTY": "Apple 有限保修",
        "ACPLUS":           "AppleCare+ 服务计划",
        "ACPLUS_MONTHLY":   "AppleCare+（月付）",
        "EXPIRED":          "已过保",
        "OUT_OF_WARRANTY":  "超出保修范围",
    }.get(ct, ct)


# ────────────────────────────────────────────
# 阶段 1：提取 Next.js SSR 原始文本
# ────────────────────────────────────────────

def _decode_nextf_chunks(html: str) -> str:
    """
    HTML 文件中的 __next_f.push 内容经过双重 JSON 字符串转义，
    需要两次 json.loads 解包后拼接成可供正则搜索的纯文本。
    """
    chunks = re.findall(
        r'self\.__next_f\.push\(\[1,\s*\\+"(.*?)\\+"\]\)',
        html,
        re.DOTALL,
    )
    combined = ""
    for raw in chunks:
        decoded = raw
        for _ in range(3):
            try:
                decoded = json.loads('"' + decoded + '"')
            except Exception:
                break
        combined += decoded
    return combined


# ────────────────────────────────────────────
# 阶段 2：从解码文本中提取各字段
# ────────────────────────────────────────────

def _extract_json_block(text: str, key: str) -> dict:
    """从文本中找 "key":{...} 并解析，支持嵌套对象。"""
    pattern = re.compile(rf'"{re.escape(key)}":\s*(\{{)')
    m = pattern.search(text)
    if not m:
        return {}
    start = m.start(1)
    depth, i = 0, start
    while i < len(text):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                fragment = text[start:i + 1]
                fragment = fragment.replace('"$undefined"', 'null')
                try:
                    return json.loads(fragment)
                except Exception:
                    return {}
        i += 1
    return {}


def _re_str(text: str, key: str, default: str = "") -> str:
    m = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]*)"', text)
    return m.group(1) if m else default


# ────────────────────────────────────────────
# 阶段 3：组装标准化对象
# ────────────────────────────────────────────

def build_standard_object(decoded_text: str, raw_api: dict) -> dict:
    """
    以 decoded_text（Next.js payload 纯文本）为主数据源，
    raw_api 为补充，输出以 serialNumber 为中心的标准化对象。
    """

    # ── A. 产品基础信息 ─────────────────────────────
    pi        = _extract_json_block(decoded_text, "productInfo")
    hierarchy = _safe_get(pi, "productHierarchy", default={})
    pm_raw    = _safe_get(raw_api, "data", "productInfo", "productMeta", default={})

    serial_number = _safe_get(pi, "serialNumber") or _re_str(decoded_text, "serialNumber")
    sn_key        = _safe_get(pi, "serialNumberKey")
    dop_raw       = _safe_get(pi, "dop")

    product_info = {
        "serialNumber":    serial_number,
        "snKey":           sn_key,
        "productType":     _safe_get(pi, "modelName"),
        "productName":     _safe_get(pi, "productName"),
        "productNickname": _safe_get(pi, "productNickname"),
        "imageUrl":        _safe_get(pi, "imgUrl"),
        "dop":             dop_raw,
        "dopISO":          _parse_date_to_iso(dop_raw),
        "countryOfPurchase": _safe_get(raw_api, "data", "productInfo", "countryOfPurchase"),
        "openRepair":      _safe_get(pi, "openRepair", default=False),
        "productMeta": {
            "groupFamily":     _safe_get(hierarchy, "productGroupFamily") or _safe_get(pm_raw, "groupFamily"),
            "superGroup":      _safe_get(hierarchy, "superGroup")         or _safe_get(pm_raw, "superGroup"),
            "prodFamilyClass": _safe_get(hierarchy, "productFamilyClass") or _safe_get(pm_raw, "prodFamilyClass"),
            "name":            _safe_get(pm_raw, "name"),
        },
    }

    # ── B. 保障 / 协议信息 ──────────────────────────
    ag            = _extract_json_block(decoded_text, "agreement")
    bs            = _safe_get(ag, "benefitsSection", default={})
    ci_np         = _extract_json_block(decoded_text, "coverageInfo")
    coverage_type = _safe_get(ag, "coverageType") or _safe_get(ci_np, "coverageType")
    validity_label = _safe_get(ag, "validityLabel")

    warranty_info = {
        "coverageType":      coverage_type,
        "coverageTypeLabel": _coverage_type_label(coverage_type),
        "agreementTitle":    _safe_get(ag, "title"),
        "validityLabel":     validity_label,
        "warrantyExpiry":    _parse_date_to_iso(validity_label),
        "agreementCode":     _safe_get(ag, "agreementCode") or _safe_get(ci_np, "agreementCode"),
        "agreementNumber":   _safe_get(ag, "agreementNumber") or _safe_get(ci_np, "agreementNumber"),
        "temporaryCoverage": _safe_get(ag, "temporaryCoverage", default=False),
        "benefitsSummary":   _safe_get(bs, "benefits", default=[]),
        "agreements":        _safe_get(raw_api, "data", "agreements", default=[]),
        "isOwner":           _safe_get(raw_api, "data", "isOwner", default=False),
    }

    # ── C. 国家 / 地区（与 SN 绑定的销售区域）────────
    ci = _extract_json_block(decoded_text, "countryInfo")
    country_info = {
        "locale":        _safe_get(ci, "locale"),
        "countryCode":   _safe_get(ci, "countryCode"),
        "countryCode3L": _safe_get(ci, "countryCode3L"),
        "countryName":   _safe_get(ci, "countryName"),
        "languageCode":  _safe_get(ci, "languageCode"),
    } if ci else {}

    # ── D. 激活 / 注册状态 ──────────────────────────
    notifications = raw_api.get("coverageNotification", [])
    if not notifications and "激活你的设备" in decoded_text:
        notifications = [{
            "type": 0,
            "title": "激活你的设备",
            "description": "由于你还没有注册设备，我们无法显示详细的保障信息。",
            "links": [{
                "caption": "查看你的服务选项",
                "url": f"https://getsupport.apple.com?snKey={sn_key}&cn=CHN",
            }],
        }]
    activation_status = _build_activation_status(notifications, sn_key)

    # ── E. 支持入口（含 snKey 的专属链接）────────────
    support_entries = _build_support_entries(
        raw_api.get("supportOptions", []), sn_key
    )
    if not support_entries and sn_key:
        support_entries = [{
            "title":    "获取支持",
            "subTitle": "你可以通过电话、在线聊天、电子邮件等方式联系我们。",
            "links": [{
                "caption":      "立即开始",
                "url":          f"https://getsupport.apple.com?locale=zh_CN&snKey={sn_key}&caller=ccweb",
                "snKey":        sn_key,
                "isSNSpecific": True,
            }],
        }]

    return {
        "serialNumber":     serial_number,
        "snKey":            sn_key,
        "productInfo":      product_info,
        "warrantyInfo":     warranty_info,
        "activationStatus": activation_status,
        "countryInfo":      country_info,
        "supportEntries":   support_entries,
        "_meta": {
            "parsedAt":      datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "parserVersion": "2.0.0",
            "sourceType":    "apple_coverage_html",
        },
    }


def _build_activation_status(notifications: list, sn_key: str) -> dict:
    if not notifications:
        return {
            "isActivated": True, "isRegistered": True,
            "notificationType": -1, "notificationTitle": "",
            "notificationDescription": "", "actionLinks": [],
        }
    notif = notifications[0]
    notif_type   = notif.get("type", -1)
    is_activated = notif_type != 0
    action_links = []
    for link in notif.get("links", []):
        url = link.get("url", "")
        action_links.append({
            "caption": link.get("caption", ""),
            "url":     url,
            "snKey":   _extract_snkey(url) or sn_key,
        })
    return {
        "isActivated":            is_activated,
        "isRegistered":           is_activated,
        "notificationType":       notif_type,
        "notificationTitle":      notif.get("title", ""),
        "notificationDescription": notif.get("description", ""),
        "actionLinks":            action_links,
    }


def _build_support_entries(support_options: list, sn_key: str) -> list:
    entries = []
    for opt in support_options:
        links_out = []
        for link in opt.get("link", []):
            url = link.get("url", "")
            extracted_key = _extract_snkey(url)
            links_out.append({
                "caption":      link.get("caption", ""),
                "url":          url,
                "snKey":        extracted_key,
                "isSNSpecific": bool(extracted_key),
            })
        entries.append({
            "title":    opt.get("title", ""),
            "subTitle": opt.get("subTitle", ""),
            "links":    links_out,
        })
    return entries


# ────────────────────────────────────────────
# 阶段 4：尝试提取页面内嵌 API JSON（可选）
# ────────────────────────────────────────────

def _try_extract_inline_api(html: str) -> dict:
    patterns = [
        r'window\.__(?:COVERAGE|APP)_DATA__\s*=\s*(\{.*?\});',
        r'<script[^>]*>\s*(\{"data":\s*\{.*?"supportOptions".*?\})\s*</script>',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
    return {}


# ────────────────────────────────────────────
# 主解析入口
# ────────────────────────────────────────────

def parse_html_file(html: str) -> dict:
    print("[1/3] 提取并解码 Next.js SSR payload ...", file=sys.stderr)
    decoded_text = _decode_nextf_chunks(html)
    if not decoded_text:
        raise ValueError("未能提取 Next.js payload，请确认 HTML 文件来源正确。")

    print("[2/3] 尝试提取内联 API JSON ...", file=sys.stderr)
    raw_api = _try_extract_inline_api(html)
    status  = "✓ 找到内联 API JSON" if raw_api else "ℹ 未找到内联 JSON，完全依赖 Next.js payload"
    print(f"      {status}", file=sys.stderr)

    print("[3/3] 构建标准化对象 ...", file=sys.stderr)
    return build_standard_object(decoded_text, raw_api)


"""
apple_coverage_parser.py
========================
将 checkcoverage.apple.com 返回的原始 HTML 字符串（origin_str）解析为
与序列号（serialNumber）相关的标准结构化对象。

依赖：
    pip install beautifulsoup4 lxml

解析层次：
    Layer 1 — BeautifulSoup DOM 解析（设备基础信息、协议卡片、页脚、支持链接）
    Layer 2 — Next.js RSC Payload 解析（self.__next_f.push 脚本中的结构化 JSON）
              包含：productInfo、agreement、countryInfo、benefitDetails 等
"""

import re
import json
import sys
from bs4 import BeautifulSoup


# ─────────────────────────────────────────────────────────────────────────────
# 内部工具
# ─────────────────────────────────────────────────────────────────────────────

def _decode_origin_str(origin_str: str) -> str:
    s = origin_str.strip()
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    s = s.replace('\\"', '"').replace('\\/', '/').replace('\\n', '\n')
    return s


def _extract_rsc_payloads(soup: BeautifulSoup) -> str:
    segments = []
    for tag in soup.find_all("script"):
        raw = tag.string or ""
        if "self.__next_f.push" not in raw:
            continue
        for m in re.finditer(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', raw, re.DOTALL):
            segments.append(m.group(1))
    combined = "\n".join(segments)
    combined = combined.replace('\\"', '"').replace('\\\\', '\\')
    return combined


def _json_block(text: str, key: str):
    pattern = rf'"{re.escape(key)}"\s*:\s*(\{{|\[)'
    m = re.search(pattern, text)
    if not m:
        return None
    start = m.start(1)
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start: i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 各层解析函数
# ─────────────────────────────────────────────────────────────────────────────

def _parse_dom_basics(soup: BeautifulSoup) -> dict:
    result = {
        "serialNumber": "",
        "productName":  "",
        "dop":          "",
        "imageUrl":     "",
    }

    h1 = soup.find("h1", class_="device-header-title")
    if h1:
        result["productName"] = h1.get_text(strip=True)

    sn_p = soup.find("p", class_="device-header-serial-number")
    if sn_p:
        text = sn_p.get_text().replace(" ", "")
        m = re.search(r"[A-Z0-9]{10,14}", text)
        result["serialNumber"] = m.group(0) if m else text.split("：")[-1].strip()

    dop_p = soup.find("p", class_="device-header-purchase")
    if dop_p:
        result["dop"] = dop_p.get_text(strip=True).replace("已购买", "").strip()

    img = soup.find("img", class_="device-header-image")
    if img:
        result["imageUrl"] = img.get("src", "")

    return result


def _parse_dom_agreements(soup: BeautifulSoup) -> list:
    agreements = []
    for card in soup.find_all("li", class_="agreement-card"):
        icon   = card.find("img", class_="card-image-wrapper")
        title  = card.find("h3", class_="header-title")
        date   = card.find("div", class_="header-sub-title")
        bfts   = [s.get_text(strip=True) for s in card.find_all("span", class_="benefits-description")]
        agreements.append({
            "title":         title.get_text(strip=True) if title else "",
            "iconUrl":       icon.get("src", "") if icon else "",
            "validityLabel": date.get_text(strip=True) if date else "",
            "benefits":      bfts,
        })
    return agreements


def _parse_dom_footers(soup: BeautifulSoup) -> list:
    footers = []
    for section in soup.find_all("div", class_="coverage-middle-section"):
        span = section.find("span")
        if not span:
            continue
        a_el = span.find("a")
        link_text = link_url = aria = ""
        if a_el:
            link_text = a_el.get_text(strip=True)
            link_url  = a_el.get("href", "")
            aria      = a_el.get("aria-label", "")
            a_el.decompose()
        footer_text = re.sub(r'\s+', ' ', span.get_text()).strip()
        if link_text:
            footer_text += "%@"
        footers.append({
            "footerText":  footer_text,
            "linkText":    link_text,
            "linkTextUrl": link_url,
            "ariaLabel":   aria,
        })
    return footers


def _parse_dom_support_links(soup: BeautifulSoup) -> list:
    links = []
    wrapper = soup.find("div", class_="link-section-link-wrapper")
    if not wrapper:
        return links
    for idx, a in enumerate(wrapper.find_all("a")):
        links.append({
            "caption":    a.get_text(strip=True),
            "url":        a.get("href", ""),
            "a11yCta":    a.get("aria-label", ""),
            "method":     0,
            "formData":   {},
            "openNewTab": a.get("target") == "_blank",
            "iconType":   1,
            "order":      idx,
        })
    return links


def _parse_rsc_product_info(rsc_text: str) -> dict:
    pi = _json_block(rsc_text, "productInfo")
    if not pi:
        return {}

    hierarchy = pi.get("productHierarchy", {})
    cov_info  = pi.get("coverageInfo", {})

    return {
        "serialNumber":    pi.get("serialNumber", ""),
        "serialNumberKey": pi.get("serialNumberKey", ""),
        "productName":     pi.get("productName", ""),
        "modelName":       pi.get("modelName", ""),
        "imageUrl":        pi.get("imgUrl", ""),
        "dop":             pi.get("dop", ""),
        "openRepair":      pi.get("openRepair", False),
        "productMeta": {
            "superGroup":      hierarchy.get("superGroup", "").lower(),
            "groupFamily":     hierarchy.get("productGroupFamily", "").lower(),
            "prodFamilyClass": hierarchy.get("productFamilyClass", "").lower(),
            "name":            pi.get("productName", "").lower(),
        },
        "coverageType":    cov_info.get("coverageType", ""),
        "agreementNumber": cov_info.get("agreementNumber", ""),
        "agreementCode":   cov_info.get("agreementCode", ""),
        "temporaryCoverage": cov_info.get("temporaryCoverage", False),
    }


def _parse_rsc_agreement(rsc_text: str) -> dict:
    ag = _json_block(rsc_text, "agreement")
    if not ag:
        return {}

    bs    = ag.get("benefitsSection", {})
    modal = bs.get("modalData", {})
    benefit_details = []
    for bd in modal.get("benefitData", []):
        benefit_details.append({
            "imageUrl":    bd.get("imageUrl", "").strip(),
            "summary":     bd.get("summary", ""),
            "description": bd.get("description", "").strip(),
        })

    return {
        "title":           ag.get("title", ""),
        "validityLabel":   ag.get("validityLabel", "").strip(),
        "validity":        ag.get("validity", ""),
        "agreementCode":   ag.get("agreementCode", ""),
        "agreementNumber": ag.get("agreementNumber", ""),
        "iconUrl":         ag.get("appleCareIconUrl", ""),
        "coverageType":    ag.get("coverageType", ""),
        "temporaryCoverage": ag.get("temporaryCoverage", False),
        "benefits":        bs.get("benefits", []),
        "benefitSectionTitle": bs.get("title", ""),
        "benefitDetails":  benefit_details,
        "modalTitle":      modal.get("title", ""),
        "modalSubTitle":   modal.get("subTitle", ""),
        "modalFooter":     modal.get("footer", ""),
        "linkData":        ag.get("linkData", []),
        "additionalInfo":  ag.get("additionalInfo", []),
    }


def _parse_rsc_country_info(rsc_text: str) -> dict:
    ci = _json_block(rsc_text, "countryInfo")
    if not ci:
        return {}
    return {
        "locale":       ci.get("locale", ""),
        "countryName":  ci.get("countryName", ""),
        "countryCode":  ci.get("countryCode", ""),
        "countryCode3L": ci.get("countryCode3L", ""),
        "languageCode": ci.get("languageCode", ""),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────────────────────

def parse_coverage_page(origin_str: str) -> dict:
    """
    解析 Apple checkcoverage.apple.com 页面原始字符串。
    """
    html = _decode_origin_str(origin_str)
    soup = BeautifulSoup(html, "lxml")
    rsc  = _extract_rsc_payloads(soup)

    # ── Layer 1: DOM ──────────────────────────────────────────────────────────
    basics         = _parse_dom_basics(soup)
    dom_agreements = _parse_dom_agreements(soup)
    footers        = _parse_dom_footers(soup)
    support_links  = _parse_dom_support_links(soup)

    # ── Layer 2: RSC Payload ──────────────────────────────────────────────────
    rsc_pi = _parse_rsc_product_info(rsc)
    rsc_ag = _parse_rsc_agreement(rsc)
    rsc_ci = _parse_rsc_country_info(rsc)

    # ── 合并，RSC 优先（信息更完整），DOM 兜底 ────────────────────────────────
    serial_number = rsc_pi.get("serialNumber") or basics["serialNumber"]
    sn_key        = rsc_pi.get("serialNumberKey", "")
    product_name  = rsc_pi.get("productName") or basics["productName"]
    dop           = rsc_pi.get("dop") or basics["dop"]
    image_url     = rsc_pi.get("imageUrl") or basics["imageUrl"]
    product_meta  = rsc_pi.get("productMeta", {})
    coverage_type = rsc_pi.get("coverageType", "")

    country_info = rsc_ci if rsc_ci else {}
    locale = country_info.get("locale", "zh_CN")

    # 协议合并：DOM 卡片列表 + RSC 详细数据
    merged_agreements = []
    for i, dom_ag in enumerate(dom_agreements):
        ag = dict(dom_ag)
        if rsc_ag:
            ag.update({
                "coverageType":       rsc_ag.get("coverageType", coverage_type),
                "agreementNumber":    rsc_ag.get("agreementNumber", ""),
                "agreementCode":      rsc_ag.get("agreementCode", ""),
                "validity":           rsc_ag.get("validity", ""),
                "temporaryCoverage":  rsc_ag.get("temporaryCoverage", False),
                "benefits":           rsc_ag.get("benefits") or ag.get("benefits", []),
                "benefitSectionTitle": rsc_ag.get("benefitSectionTitle", ""),
                "benefitDetails":     rsc_ag.get("benefitDetails", []),
                "modalTitle":         rsc_ag.get("modalTitle", ""),
                "modalSubTitle":      rsc_ag.get("modalSubTitle", ""),
                "modalFooter":        rsc_ag.get("modalFooter", ""),
                "linkData":           rsc_ag.get("linkData", []),
                "additionalInfo":     rsc_ag.get("additionalInfo", []),
            })
        merged_agreements.append(ag)

    # 若 DOM 没有卡片但 RSC 有协议数据，单独生成
    if not merged_agreements and rsc_ag:
        merged_agreements.append({
            "title":              rsc_ag.get("title", ""),
            "iconUrl":            rsc_ag.get("iconUrl", ""),
            "validityLabel":      rsc_ag.get("validityLabel", ""),
            "coverageType":       rsc_ag.get("coverageType", coverage_type),
            "agreementNumber":    rsc_ag.get("agreementNumber", ""),
            "agreementCode":      rsc_ag.get("agreementCode", ""),
            "validity":           rsc_ag.get("validity", ""),
            "temporaryCoverage":  rsc_ag.get("temporaryCoverage", False),
            "benefits":           rsc_ag.get("benefits", []),
            "benefitSectionTitle": rsc_ag.get("benefitSectionTitle", ""),
            "benefitDetails":     rsc_ag.get("benefitDetails", []),
            "modalTitle":         rsc_ag.get("modalTitle", ""),
            "modalSubTitle":      rsc_ag.get("modalSubTitle", ""),
            "modalFooter":        rsc_ag.get("modalFooter", ""),
            "linkData":           rsc_ag.get("linkData", []),
            "additionalInfo":     rsc_ag.get("additionalInfo", []),
        })

    # ── 组装最终结果 ──────────────────────────────────────────────────────────
    return {
        "data": {
            "redirectParam": (
                f"https://getsupport.apple.com?locale={locale}&snKey={sn_key}&caller=ccweb"
                if sn_key else ""
            ),
            "productInfo": {
                "imageUrl":        image_url,
                "productName":     product_name,
                "productType":     product_name,
                "serialNumber":    serial_number,
                "serialNumberKey": sn_key,
                "dop":             dop,
                "countryOfPurchase": country_info.get("countryName", ""),
                "countryInfo":     country_info,
                "productMeta":     product_meta,
            },
            "agreements":       merged_agreements,
            "coverageType":     coverage_type,
            "showActivity":     False,
            "showSupportOptions": bool(support_links),
            "isOwner":          False,
            "pageFooters":      footers,
        },
        "supportLinks": support_links,
    }


# =========================================最终响应处理函数=========================================


class AppleProxyManager:
    """Apple查询代理管理器"""
    def __init__(self, api_url: str, max_usage_per_ip: int = 4, proxy_key: str = "YOUR_PROXY_KEY",
                 proxy_protocol: str = "http", username: Optional[str] = None, password: Optional[str] = None,
                 bypass: Optional[List[str]] = None):
        self.api_url_template = api_url
        self.proxy_key = proxy_key
        self.max_usage_per_ip = max_usage_per_ip
        self.proxy_protocol = proxy_protocol
        self.username = username
        self.password = password
        self.bypass = bypass or []
        self.current_proxy_server: Optional[str] = None
        self.current_proxy_usage: int = 0
        self._lock = threading.Lock()
        self.session: Optional[requests.Session] = None

    def _get_session(self) -> requests.Session:
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36'
            })
        return self.session

    def _fetch_new_proxy(self) -> Optional[str]:
        request_url = f"https://share.proxy.qg.net/get?key={self.proxy_key}&pwd=0F20CE0391AB&distinct=true"
        print(f"[Apple代理] 正在从 {request_url} 获取新的代理IP...")

        session = self._get_session()
        try:
            response = session.get(request_url, timeout=15)
            response.raise_for_status()
            response_text = response.text
            print(f"[Apple代理] 代理API响应: {response_text}")

            try:
                response_data = json.loads(response_text)

                if response_data.get("code") == "SUCCESS":
                    data_list = response_data.get("data", [])
                    if data_list and len(data_list) > 0:
                        proxy_server = data_list[0].get("server")
                        if proxy_server and ":" in proxy_server:
                            print(f"[Apple代理] 获取到新的代理IP: {proxy_server}")
                            proxy_info = data_list[0]
                            area = proxy_info.get("area", "未知地区")
                            isp = proxy_info.get("isp", "未知运营商")
                            deadline = proxy_info.get("deadline", "未知到期时间")
                            print(f"[Apple代理] 代理详情 - 地区: {area}, 运营商: {isp}, 到期时间: {deadline}")

                            proxy_ip = proxy_info.get("proxy_ip")
                            if proxy_ip:
                                print(f"[Apple代理] 代理认证IP: {proxy_ip}")
                                self.username = self.proxy_key
                                self.password = "0F20CE0391AB"

                            return proxy_server
                        else:
                            print(f"[Apple代理] 代理服务器格式无效: {proxy_server}")
                    else:
                        print("[Apple代理] 代理API返回的数据列表为空")
                else:
                    error_msg = response_data.get("msg", "未知错误")
                    print(f"[Apple代理] 代理API返回错误: {error_msg}")

            except json.JSONDecodeError as e:
                print(f"[Apple代理] 解析代理API响应JSON失败: {e}")
                print(f"[Apple代理] 原始响应: {response_text}")

        except requests.RequestException as e:
            print(f"[Apple代理] 获取代理IP时发生网络错误: {e}")

        return None

    def get_proxy_config(self) -> Optional[Dict[str, str]]:
        with self._lock:
            max_concurrent_usage = min(self.max_usage_per_ip, 2)

            if self.current_proxy_server and self.current_proxy_usage < max_concurrent_usage:
                self.current_proxy_usage += 1
                print(f"[Apple代理] 复用代理: {self.current_proxy_server} (使用次数: {self.current_proxy_usage}/{max_concurrent_usage})")
                return self._build_proxy_config(self.current_proxy_server)

            new_proxy_server = self._fetch_new_proxy()
            if new_proxy_server:
                self.current_proxy_server = new_proxy_server
                self.current_proxy_usage = 1
                print(f"[Apple代理] 切换到新代理: {self.current_proxy_server} (协议: {self.proxy_protocol})")
                return self._build_proxy_config(self.current_proxy_server)
            else:
                self.current_proxy_server = None
                self.current_proxy_usage = 0
                print("[Apple代理] 无法获取新的有效代理IP，将使用无代理模式")
                return None

    def _build_proxy_config(self, proxy_server: str) -> Dict[str, str]:
        proxy_url = f"{self.proxy_protocol}://{proxy_server}"

        if hasattr(self, 'username') and hasattr(self, 'password') and self.username and self.password:
            proxy_url = f"{self.proxy_protocol}://{self.username}:{self.password}@{proxy_server}"
            print(f"[Apple代理] 代理认证配置: 用户名={self.username}")

        return {
            "http": proxy_url,
            "https": proxy_url
        }

    def mark_proxy_failed(self, proxy_server_used: str):
        with self._lock:
            normalized_proxy_used = proxy_server_used.replace("http://", "").replace("https://", "")
            if "@" in normalized_proxy_used:
                normalized_proxy_used = normalized_proxy_used.split("@")[1]

            if self.current_proxy_server == normalized_proxy_used:
                print(f"[Apple代理] 标记代理失败: {self.current_proxy_server}，将强制获取新代理")
                self.current_proxy_server = None
                self.current_proxy_usage = 0

    def close(self):
        if self.session:
            self.session.close()
            self.session = None


class KuaiDaiLiProxyManager:
    """快代理(kuaidaili)代理管理器"""
    def __init__(self, max_usage_per_ip: int = 2):
        self.api_url = "https://dps.kdlapi.com/api/getdps/?secret_id=oo9bi96g37h2hv7egobc&signature=vdzw9fn42fg1la4gufa4izjse2eeprzr&num=1&sep=1"
        self.username = "d4904677932"
        self.password = "kbs2zsan"
        self.max_usage_per_ip = max_usage_per_ip
        self.current_proxy_server: Optional[str] = None
        self.current_proxy_usage: int = 0
        self._lock = threading.Lock()
        self.session: Optional[requests.Session] = None

    def _get_session(self) -> requests.Session:
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36'
            })
        return self.session

    def _fetch_new_proxy(self) -> Optional[str]:
        print(f"[快代理] 正在获取新的代理IP...")
        session = self._get_session()
        try:
            response = session.get(self.api_url, timeout=15)
            response.raise_for_status()
            proxy_ip = response.text.strip()
            if proxy_ip and ":" in proxy_ip:
                print(f"[快代理] 获取到新的代理IP: {proxy_ip}")
                return proxy_ip
            else:
                print(f"[快代理] 代理API返回格式无效: {proxy_ip}")
        except requests.RequestException as e:
            print(f"[快代理] 获取代理IP时发生网络错误: {e}")
        return None

    def get_proxy_config(self) -> Optional[Dict[str, str]]:
        with self._lock:
            if self.current_proxy_server and self.current_proxy_usage < self.max_usage_per_ip:
                self.current_proxy_usage += 1
                print(f"[快代理] 复用代理: {self.current_proxy_server} (使用次数: {self.current_proxy_usage}/{self.max_usage_per_ip})")
                return self._build_proxy_config(self.current_proxy_server)

            new_proxy_server = self._fetch_new_proxy()
            if new_proxy_server:
                self.current_proxy_server = new_proxy_server
                self.current_proxy_usage = 1
                print(f"[快代理] 切换到新代理: {self.current_proxy_server}")
                return self._build_proxy_config(self.current_proxy_server)
            else:
                self.current_proxy_server = None
                self.current_proxy_usage = 0
                print("[快代理] 无法获取新的有效代理IP，将使用无代理模式")
                return None

    def _build_proxy_config(self, proxy_server: str) -> Dict[str, str]:
        proxy_url = f"http://{self.username}:{self.password}@{proxy_server}"
        return {
            "http": proxy_url,
            "https": proxy_url
        }

    def mark_proxy_failed(self, proxy_server_used: str):
        with self._lock:
            normalized = proxy_server_used.replace("http://", "").replace("https://", "")
            if "@" in normalized:
                normalized = normalized.split("@")[1]
            if self.current_proxy_server == normalized:
                print(f"[快代理] 标记代理失败: {self.current_proxy_server}，将强制获取新代理")
                self.current_proxy_server = None
                self.current_proxy_usage = 0

    def close(self):
        if self.session:
            self.session.close()
            self.session = None


# 配置日志 - 禁用文件日志记录，只保留控制台输出
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """查询结果数据类"""
    serial_number: str
    success: bool
    data: Optional[Dict] = None
    error: Optional[str] = None
    attempts: int = 0
    processing_time: float = 0.0
    proxy_used: Optional[str] = None


@dataclass
class ExtractedData:
    """提取的结构化数据类"""
    product_type: str = ""
    serial_number: str = ""
    validity: str = ""
    activation_time: str = ""
    expiry_time: str = ""
    coverage_notification_title: str = ""
    is_activation_required: bool = False
    is_pre_activated: str = ""
    ac_plus: str = "否"


class AppleCoverageChecker:
    BASE_URL = "https://checkcoverage.apple.com"

    def __init__(self, serial_number: str, max_retries: int = 10, use_proxy: bool = False, proxy_key: str = "",
                 proxy_provider: str = "qingguo",
                 jfbym_token: str = "6MGaV8UJsgCV-pGpCrjOsr1HYOkqgT7ypAar3dhbMqQ",
                 jfbym_type: str = "10110"):
        # 序列号预处理：如果是11位且首字母是S，则去掉S
        processed_serial = serial_number.strip().upper()
        if len(processed_serial) == 11 and processed_serial.startswith('S'):
            processed_serial = processed_serial[1:]
            logger.info(f"序列号预处理：{serial_number} -> {processed_serial}")

        self.serial_number = processed_serial
        self.max_retries = max_retries
        self.session = None
        self.jwt_token = None

        # 第三方打码平台(jfbym)配置
        self.jfbym_token = jfbym_token
        self.jfbym_type = jfbym_type

        # 代理配置
        self.use_proxy = use_proxy
        self.proxy_key = proxy_key
        self.proxy_provider = proxy_provider
        self.proxy_manager: Optional[Union[AppleProxyManager, KuaiDaiLiProxyManager]] = None
        self.current_proxy_config: Optional[Dict[str, str]] = None
        self.proxy_server_used: Optional[str] = None

        # 初始化代理管理器
        if self.use_proxy:
            if self.proxy_provider == "kuaidaili":
                print(f"[Apple代理] 启用快代理模式")
                self.proxy_manager = KuaiDaiLiProxyManager(max_usage_per_ip=2)
                print(f"[Apple代理] 快代理管理器初始化成功")
            elif self.proxy_provider == "qingguo" and self.proxy_key:
                print(f"[Apple代理] 启用青果代理模式，密钥: {self.proxy_key[:10]}...")
                self.proxy_manager = AppleProxyManager(
                    api_url="https://share.proxy.qg.net/get",
                    max_usage_per_ip=4,
                    proxy_key=self.proxy_key
                )
                print(f"[Apple代理] 青果代理管理器初始化成功")
            else:
                print("[Apple代理] 代理配置无效，代理功能未启用")
        else:
            print("[Apple代理] 代理功能未启用")

    # 可用的浏览器指纹模拟目标（随机选择以实现动态指纹）
    _BROWSER_TARGETS = ["chrome136", "chrome133a", "edge101"]

    def _create_session(self):
        if self.session is None:
            import random
            browser = random.choice(self._BROWSER_TARGETS)
            logger.info(f"[{self.serial_number}] 浏览器指纹模拟: {browser}")

            # 先获取代理配置
            proxy_url = None
            if self.use_proxy and self.proxy_manager:
                proxy_config = self.proxy_manager.get_proxy_config()
                if proxy_config:
                    proxy_url = proxy_config.get("http") or proxy_config.get("https") or ""
                    self.current_proxy_config = proxy_config

                    if "://" in proxy_url:
                        proxy_ip = proxy_url.split("://")[1]
                        if "@" in proxy_ip:
                            proxy_ip = proxy_ip.split("@")[1]
                        if ":" in proxy_ip:
                            proxy_ip = proxy_ip.split(":")[0]
                        self.proxy_server_used = proxy_ip
                        print(f"[Apple代理] 使用代理: {proxy_ip}")
                    else:
                        self.proxy_server_used = proxy_url or "未知"
                        print(f"[Apple代理] 使用代理: {self.proxy_server_used}")
                else:
                    self.proxy_server_used = "代理获取失败"
                    print("[Apple代理] 无法获取代理配置，使用直连模式")
            else:
                self.proxy_server_used = "未启用"
                print("[Apple代理] 未启用代理，使用直连模式")

            # 尝试使用 curl_cffi，如果失败则使用普通 requests
            try:
                if CURL_CFFI_AVAILABLE:
                    # 使用curl_cffi + impersonate模拟真实浏览器
                    self.session = curl_requests.Session(impersonate=browser, proxy=proxy_url)  # type: ignore[arg-type]
                else:
                    raise ImportError("curl_cffi not available")
            except Exception as e:
                logger.warning(f"[{self.serial_number}] curl_cffi 初始化失败: {e}，使用普通 requests")
                # 回退到普通 requests
                self.session = requests.Session()
                if proxy_url:
                    self.session.proxies = {
                        'http': proxy_url,
                        'https': proxy_url
                    }
                # 设置默认 User-Agent
                self.session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36'
                })

    def _get_common_api_headers(self):
        if not self.jwt_token:
            raise ValueError("JWT token is not set. Call get_jwt_token first.")
        return {
            'Origin': self.BASE_URL,
            'Referer': f'{self.BASE_URL}/',
            'accept': 'application/json',
            'x-apple-csrf-token': self.jwt_token,
        }

    def get_jwt_token(self) -> bool:
        self._create_session()
        logger.info(f"[{self.serial_number}] 开始抓取Token...")
        try:
            params = {'locale': 'zh_CN'}

            response = self.session.get('https://checkcoverage.apple.com/', params=params)

            location = response.headers.get("Location")
            if location:
                response = self.session.get("https://checkcoverage.apple.com/user-consent?locale=zh_CN")

            html_content = response.text
            jwt_pattern = r'<meta name="csrf-token" content="([^"]+)"'
            jwt_match = re.search(jwt_pattern, html_content)
            if jwt_match:
                self.jwt_token = jwt_match.group(1)
                logger.info(f"[{self.serial_number}] Token获取成功-{self.jwt_token[:15]}")
                return True
            else:
                logger.error(f"[{self.serial_number}] 获取 Token 失败")
                return False
        except CurlRequestsError as e:
            logger.error(f"[{self.serial_number}] 获取JWT Token时发生网络错误: {e}")
            return False

    def _get_page_init(self):
        check_coverage_response = self.session.get(
            'https://checkcoverage.apple.com/?locale=zh_CN',
        )
        check_coverage_response.raise_for_status()

    def submit_user_consent(self) -> bool:
        if not self.jwt_token:
            return False

        headers_user_consent = {
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'Origin': 'https://checkcoverage.apple.com',
            'X-Apple-Csrf-Token': self.jwt_token,
            'Referer': 'https://checkcoverage.apple.com/'
        }

        data = {
            'locale': "zh_CN",
        }

        try:
            user_consent_resp = self.session.post(
                'https://checkcoverage.apple.com/api/v1/consent?locale=zh_CN ',
                headers=headers_user_consent,
                data=data,
            )
            user_consent_resp.raise_for_status()
            resp_data = user_consent_resp.json()
            userConsented = resp_data.get("data").get("userConsented")
            meta = resp_data.get("meta")
            logger.info(f"返回成功响应字段:-{userConsented}- 提交状态: - {meta.get('status')}")
            logger.info(f"[{self.serial_number}] 提交用户同意成功")
            return True
        except CurlRequestsError as e:
            logger.error(f"[{self.serial_number}] 提交用户同意失败: {e}")
            return False

    def get_captcha_data(self) -> Optional[str]:
        img_headers = {
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': 'https://checkcoverage.apple.com/',
            'accept': 'application/json',
            'x-apple-csrf-token': self.jwt_token,
        }
        img_params = {
            'type': 'image',
            'locale': 'zh_CN'
        }

        try:
            img_response = self.session.get(
                'https://checkcoverage.apple.com/api/v1/captcha',
                params=img_params,
                headers=img_headers
            )
            img_response.raise_for_status()
            resp_data = img_response.json()
            base64_captcha = resp_data.get("data").get("binary")
            logger.info(f"[{self.serial_number}] 获取到验证码base64编码")
            return base64_captcha
        except Exception as e:
            logger.error(f"[{self.serial_number}] 获取验证码数据失败: {e}")
            return None

    def recognize_captcha(self, base64_data: str) -> Optional[str]:
        """使用第三方打码平台(jfbym.com)识别验证码"""
        if not base64_data or not self.jfbym_token:
            return None

        try:
            url = "http://api.jfbym.com/api/YmServer/customApi"
            data = {
                "token": self.jfbym_token,
                "type": self.jfbym_type,
                "image": base64_data,
            }
            headers = {"Content-Type": "application/json"}

            resp = requests.post(url, headers=headers, json=data, timeout=30)
            resp_data = resp.json()

            # 响应: {"code": 10000, "msg": "识别成功", "data": {"code": 0, "data": "6jh1u", ...}}
            if resp_data.get("code") == 10000:
                captcha_text = resp_data.get("data", {}).get("data", "")
                captcha_text = re.sub(r'[^A-Za-z0-9]', '', captcha_text).upper()
                if captcha_text and len(captcha_text) >= 3:
                    logger.info(f"[{self.serial_number}] 第三方打码识别成功: {captcha_text}")
                    return captcha_text
                else:
                    logger.warning(f"[{self.serial_number}] 第三方打码结果无效: raw='{resp_data}'")
            else:
                logger.error(f"[{self.serial_number}] 第三方打码失败: {resp_data}")

        except Exception as e:
            logger.error(f"[{self.serial_number}] 第三方打码请求异常: {e}")

        return None

    def submit_coverage_data(self, captcha_answer: str) -> Optional[Dict]:
        if not self.jwt_token or not captcha_answer:
            return None

        headers = self._get_common_api_headers()
        headers['content-type'] = 'application/json'

        payload = {
            'serialInput': self.serial_number,
            'answer': captcha_answer,
            'captchaType': 'image',
        }

        try:
            resp = self.session.post(
                f'{self.BASE_URL}/api/v1/captchaValidate?locale=zh_CN',
                headers=headers,
                json=payload,
                timeout=15
            )
            resp.raise_for_status()
            return resp.json()
        except CurlRequestsError as e:
            if e.response is not None:
                try:
                    return e.response.json()
                except:
                    pass
            logger.error(f"[{self.serial_number}] 提交数据失败: {e}")
            return None

    def final_coverage_data(self):
        coverage_headers = {
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://checkcoverage.apple.com/',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        }
        coverage_params = {
            'locale': 'zh_CN'
        }

        coverage_response = self.session.get(
            'https://checkcoverage.apple.com/coverage',
            params=coverage_params,
            headers=coverage_headers
        )
        coverage_response.raise_for_status()
        return coverage_response.text

    def format_coverage_response(self, coverage_response):
        result = parse_coverage_page(coverage_response)
        return result

    def check_coverage(self) -> CheckResult:
        """执行完整的保修检查流程"""
        start_time = time.time()
        result = CheckResult(serial_number=self.serial_number, success=False)

        try:
            for attempt in range(self.max_retries):
                result.attempts = attempt + 1
                logger.info(f"[{self.serial_number}] 第 {attempt + 1}/{self.max_retries} 次尝试")

                # 每次重试重建 session（新代理 + 新指纹）
                if attempt > 0:
                    if self.session:
                        self.session.close()
                    self.session = None
                    self.jwt_token = None
                    self._create_session()

                # 第一步：获取JWT Token
                if not self.get_jwt_token():
                    if attempt < self.max_retries - 1:
                        logger.warning(f"[{self.serial_number}] 获取Token失败，重试中...")
                        time.sleep(2)
                        continue
                    result.error = "Failed to get JWT token"
                    break

                # 第二步：提交用户同意
                if not self.submit_user_consent():
                    if attempt < self.max_retries - 1:
                        logger.warning(f"[{self.serial_number}] 提交用户同意失败，重试中...")
                        time.sleep(2)
                        continue
                    result.error = "Failed to submit user consent"
                    break

                # 第三步：页面初始化
                self._get_page_init()

                # 第四步：获取验证码并提交查询
                base64_captcha = self.get_captcha_data()
                if not base64_captcha:
                    if attempt < self.max_retries - 1:
                        time.sleep(2)
                        continue
                    result.error = "Failed to get captcha data"
                    break

                captcha_code = self.recognize_captcha(base64_captcha)
                if not captcha_code:
                    if attempt < self.max_retries - 1:
                        time.sleep(2)
                        continue
                    result.error = "Failed to recognize captcha"
                    break

                final_response = self.submit_coverage_data(captcha_code)
                if not final_response:
                    if attempt < self.max_retries - 1:
                        time.sleep(3)
                        continue
                    result.error = "Failed to submit coverage data"
                    break

                validate_result = final_response.get("meta").get("status")
                logger.info(f"验证码提交验证结果——{validate_result}")

                if validate_result == "FAILURE":
                    if attempt < self.max_retries - 1:
                        logger.warning(f"[{self.serial_number}] 验证码错误，重试中...")
                        time.sleep(2)
                        continue
                else:
                    final_response = self.final_coverage_data()
                    final_response = self.format_coverage_response(final_response)
                    result.success = True
                    result.data = final_response
                    logger.info(f"[{self.serial_number}] 查询成功！")
                    break

        except Exception as e:
            result.error = f"Unexpected error: {str(e)}"
            logger.error(f"[{self.serial_number}] 意外错误: {e}")

            if self.use_proxy and self.proxy_manager and self.current_proxy_config:
                if "Connection" in str(e) or "Timeout" in str(e) or "ProxyError" in str(e):
                    proxy_url = self.current_proxy_config.get("http", "")
                    if proxy_url:
                        self.proxy_manager.mark_proxy_failed(proxy_url)
                        print(f"[Apple代理] 网络错误，标记代理失败: {proxy_url}")
        finally:
            if self.session:
                self.session.close()
            if self.proxy_manager:
                self.proxy_manager.close()
            result.processing_time = time.time() - start_time
            result.proxy_used = self.proxy_server_used or "未启用"

        return result


class AppleDataExtractor:
    """苹果保修数据提取器"""

    CHINESE_MONTHS = {
        '一月': 1, '二月': 2, '三月': 3, '四月': 4, '五月': 5, '六月': 6,
        '七月': 7, '八月': 8, '九月': 9, '十月': 10, '十一月': 11, '十二月': 12
    }

    @staticmethod
    def parse_chinese_date_fuzzy(date_str: str) -> Optional[datetime]:
        """解析中文日期格式，如 '五月 21 2026'"""
        try:
            date_part = re.search(r'([一二三四五六七八九十十一十二]+月)\s+(\d+)\s+(\d{4})', date_str)
            if not date_part:
                return None

            month_chinese, day, year = date_part.groups()
            month_num = AppleDataExtractor.CHINESE_MONTHS.get(month_chinese)

            if month_num:
                return datetime(int(year), month_num, int(day))
        except Exception as e:
            logger.error(f"解析中文日期失败: {date_str}, 错误: {e}")
        return None

    def extract_dop(self, data: dict) -> str:
        """从 data.productInfo.dop 提取激活时间，返回 YYYY-MM-DD 格式"""
        dop_str = data["data"]["productInfo"]["dop"]
        return self.parse_date(dop_str)

    def extract_validity_label(self, data: dict) -> str:
        """从 data.agreements[0].validityLabel 提取到期时间，返回 YYYY-MM-DD 格式"""
        label = data["data"]["agreements"][0]["validityLabel"]
        match = re.search(r"\d{4}年\d{1,2}月\d{1,2}日", label)
        if not match:
            raise ValueError(f"无法从 validityLabel 中提取日期：{label}")
        return self.parse_date(match.group())

    def parse_date(self, date_str: str) -> str:
        """将 'YYYY年M月D日' 解析为 'YYYY-MM-DD'"""
        return datetime.strptime(date_str, "%Y年%m月%d日").strftime("%Y-%m-%d")

    @staticmethod
    def extract_data(api_response: Dict) -> ExtractedData:
        """从API响应中提取结构化数据"""
        extracted = ExtractedData()

        try:
            data = api_response.get('data', {})
            product_info = data.get('productInfo', {})

            extracted.product_type = product_info.get('productType', '')
            extracted.serial_number = product_info.get('serialNumber', '')

            # 检查是否有AppleCare+
            coverage_type = data.get('coverageType', '')
            if coverage_type:
                extracted.ac_plus = "是"
            else:
                extracted.ac_plus = "否"

            agreements = data.get('agreements', [])
            if agreements:
                first_agreement = agreements[0]
                validity = first_agreement.get('validity', '')
                extracted.validity = validity

            activation_time = AppleDataExtractor().extract_dop(api_response)
            expiry_time = AppleDataExtractor().extract_validity_label(api_response)

            extracted.activation_time = activation_time if activation_time else "未知"
            extracted.expiry_time = expiry_time if expiry_time else "未知"

            coverage_notifications = api_response.get('coverageNotification', [])
            if coverage_notifications:
                first_notification = coverage_notifications[0]
                title = first_notification.get('title', '')
                extracted.coverage_notification_title = title

                if title == "激活你的设备":
                    extracted.is_activation_required = True
                    extracted.activation_time = "未激活"

            if extracted.is_activation_required and not extracted.activation_time:
                extracted.activation_time = "未激活"
            elif not extracted.activation_time and not extracted.is_activation_required:
                extracted.activation_time = "未知"

            dop = product_info.get('dop', '')
            has_validity = bool(agreements and agreements[0].get('validity', ''))

            if dop and dop.strip() and not has_validity:
                extracted.is_pre_activated = "是"
            else:
                extracted.is_pre_activated = "否"

        except Exception as e:
            logger.error(f"数据提取失败: {e}")
            extracted.is_pre_activated = "未激活"

        return extracted

    @staticmethod
    def format_extracted_data(extracted: ExtractedData) -> Dict[str, str]:
        return {
            "产品名称": extracted.product_type,
            "序列号": extracted.serial_number,
            "保修时间": extracted.validity,
            "激活时间": extracted.activation_time,
            "到期时间": extracted.expiry_time,
            "通知标题": extracted.coverage_notification_title,
            "需要激活": "是" if extracted.is_activation_required else "否",
            "是否激活": extracted.is_pre_activated,
            "AC+": extracted.ac_plus
        }


class ConcurrentAppleCoverageChecker:
    """高并发苹果保修查询器"""

    def __init__(self, max_workers: Optional[int] = None, max_retries: int = 10, use_proxy: bool = False, proxy_key: str = "0LM61IPB",
                 proxy_provider: str = "qingguo",
                 jfbym_token: str = "6MGaV8UJsgCV-pGpCrjOsr1HYOkqgT7ypAar3dhbMqQ",
                 jfbym_type: str = "10110"):
        self.max_workers = max_workers or min(32, (cpu_count() or 1) + 4)
        self.max_retries = max_retries
        self.results = []

        self.use_proxy = use_proxy
        self.proxy_key = proxy_key
        self.proxy_provider = proxy_provider
        self.jfbym_token = jfbym_token
        self.jfbym_type = jfbym_type

    def check_single_serial(self, serial_number: str) -> CheckResult:
        checker = AppleCoverageChecker(
            serial_number,
            self.max_retries,
            use_proxy=self.use_proxy,
            proxy_key=self.proxy_key,
            proxy_provider=self.proxy_provider,
            jfbym_token=self.jfbym_token,
            jfbym_type=self.jfbym_type
        )
        return checker.check_coverage()

    def check_multiple_serials_threaded(self, serial_numbers: List[str]) -> List[CheckResult]:
        results = []
        logger.info(f"开始检查 {len(serial_numbers)} 个序列号，使用 {self.max_workers} 个线程")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_serial = {
                executor.submit(self.check_single_serial, serial): serial
                for serial in serial_numbers
            }

            for future in as_completed(future_to_serial):
                serial = future_to_serial[future]
                try:
                    result = future.result()
                    results.append(result)
                    status = "成功" if result.success else f"失败: {result.error}"
                    logger.info(f"[{serial}] 完成 - {status} (用时: {result.processing_time:.2f}s)")
                except Exception as e:
                    error_result = CheckResult(
                        serial_number=serial,
                        success=False,
                        error=f"Processing error: {str(e)}"
                    )
                    results.append(error_result)
                    logger.error(f"[{serial}] 处理异常: {e}")

        return results

    def check_multiple_serials_process(self, serial_numbers: List[str]) -> List[CheckResult]:
        results = []
        logger.info(f"开始检查 {len(serial_numbers)} 个序列号，使用 {self.max_workers} 个进程")

        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_serial = {
                executor.submit(self._process_single_serial, serial): serial
                for serial in serial_numbers
            }

            for future in as_completed(future_to_serial):
                serial = future_to_serial[future]
                try:
                    result = future.result()
                    results.append(result)
                    status = "成功" if result.success else f"失败: {result.error}"
                    logger.info(f"[{serial}] 完成 - {status} (用时: {result.processing_time:.2f}s)")
                except Exception as e:
                    error_result = CheckResult(
                        serial_number=serial,
                        success=False,
                        error=f"Processing error: {str(e)}"
                    )
                    results.append(error_result)
                    logger.error(f"[{serial}] 处理异常: {e}")

        return results

    @staticmethod
    def _process_single_serial(serial_number: str, max_retries: int = 3) -> CheckResult:
        checker = AppleCoverageChecker(serial_number, max_retries)
        return checker.check_coverage()

    def load_serials_from_excel(self, file_path: str, column_name: str = "序列号") -> List[str]:
        try:
            df = pd.read_excel(file_path)
            if column_name not in df.columns:
                possible_columns = ["序列号", "serial_number", "Serial Number", "SN", "sn"]
                for col in possible_columns:
                    if col in df.columns:
                        column_name = col
                        break
                else:
                    column_name = df.columns[0]
                    logger.warning(f"未找到指定列名，使用第一列: {column_name}")

            serials = df[column_name].dropna().astype(str).str.strip().str.upper().tolist()
            serials = list(set(serials))
            logger.info(f"从Excel文件加载了 {len(serials)} 个唯一序列号")
            return serials
        except Exception as e:
            logger.error(f"加载Excel文件失败: {e}")
            return []

    def save_results_to_excel(self, results: List[CheckResult], output_path: Optional[str] = None):
        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"apple_coverage_results_{timestamp}.xlsx"

        data = []
        for result in results:
            row = {
                "序列号": result.serial_number,
                "查询状态": "成功" if result.success else "失败",
                "错误信息": result.error or "",
                "尝试次数": result.attempts,
                "处理时间(秒)": round(result.processing_time, 2)
            }

            if result.success and result.data:
                try:
                    extracted_data = AppleDataExtractor.extract_data(result.data)
                    formatted_data = AppleDataExtractor.format_extracted_data(extracted_data)

                    row.update({
                        "产品名称": formatted_data.get("产品名称", ""),
                        "保修时间": formatted_data.get("保修时间", ""),
                        "激活时间": formatted_data.get("激活时间", ""),
                        "到期时间": formatted_data.get("到期时间", ""),
                        "通知标题": formatted_data.get("通知标题", ""),
                        "需要激活": formatted_data.get("需要激活", ""),
                        "是否激活": formatted_data.get("是否激活", "")
                    })
                except Exception as e:
                    logger.error(f"提取数据失败: {e}")
                    row.update({
                        "产品名称": "",
                        "保修时间": "",
                        "激活时间": "未知",
                        "到期时间": "未知",
                        "通知标题": "",
                        "需要激活": "",
                        "是否激活": ""
                    })
            else:
                row.update({
                    "产品名称": "",
                    "保修时间": "",
                    "激活时间": "",
                    "到期时间": "",
                    "通知标题": "",
                    "需要激活": "",
                    "是否激活": ""
                })

            data.append(row)

        df = pd.DataFrame(data)
        df.to_excel(output_path, index=False)
        logger.info(f"结果已保存到: {output_path}")
        return output_path


def main():
    """主函数"""
    print("=== 高并发苹果保修查询工具 ===")
    print("1. 单个序列号查询")
    print("2. 多个序列号查询（手动输入）")
    print("3. 从Excel文件批量查询")

    choice = input("请选择模式 (1/2/3): ").strip()

    checker = ConcurrentAppleCoverageChecker(max_retries=10, use_proxy=True)

    if choice == "1":
        serial = input("请输入苹果设备序列号: ").strip()
        if serial:
            result = checker.check_single_serial(serial)
            print(f"\n查询结果:")
            print(f"序列号: {result.serial_number}")
            print(f"状态: {'成功' if result.success else '失败'}")
            if result.success and result.data:
                try:
                    extracted_data = AppleDataExtractor.extract_data(result.data)
                    formatted_data = AppleDataExtractor.format_extracted_data(extracted_data)

                    print("\n=== 提取的结构化数据 ===")
                    for key, value in formatted_data.items():
                        print(f"{key}: {value}")

                    print(f"\n=== 原始数据 ===")
                    print(f"{json.dumps(result.data, indent=2, ensure_ascii=False)}")
                except Exception as e:
                    print(f"数据提取失败: {e}")
                    print(f"原始数据: {json.dumps(result.data, indent=2, ensure_ascii=False)}")
            else:
                print(f"错误: {result.error}")
            print(f"处理时间: {result.processing_time:.2f}秒")

    elif choice == "2":
        print("请输入多个序列号，每行一个，输入空行结束:")
        serials = []
        while True:
            serial = input().strip()
            if not serial:
                break
            serials.append(serial)

        if serials:
            print(f"\n开始查询 {len(serials)} 个序列号...")
            results = checker.check_multiple_serials_threaded(serials)

            success_count = sum(1 for r in results if r.success)
            print(f"\n=== 查询完成 ===")
            print(f"总计: {len(results)} 个")
            print(f"成功: {success_count} 个")
            print(f"失败: {len(results) - success_count} 个")

            output_file = checker.save_results_to_excel(results)
            print(f"详细结果已保存到: {output_file}")

    elif choice == "3":
        excel_path = input("请输入Excel文件路径: ").strip().strip('"')
        if os.path.exists(excel_path):
            column_name = input("请输入序列号列名 (直接回车使用默认'序列号'): ").strip()
            if not column_name:
                column_name = "序列号"

            serials = checker.load_serials_from_excel(excel_path, column_name)
            if serials:
                print(f"\n开始查询 {len(serials)} 个序列号...")

                mode = input("选择并发模式 (1=线程池, 2=进程池): ").strip()
                if mode == "2":
                    results = checker.check_multiple_serials_process(serials)
                else:
                    results = checker.check_multiple_serials_threaded(serials)

                success_count = sum(1 for r in results if r.success)
                total_time = sum(r.processing_time for r in results)
                print(f"\n=== 查询完成 ===")
                print(f"总计: {len(results)} 个")
                print(f"成功: {success_count} 个")
                print(f"失败: {len(results) - success_count} 个")
                print(f"总耗时: {total_time:.2f}秒")
                print(f"平均耗时: {total_time/len(results):.2f}秒/个")

                output_file = checker.save_results_to_excel(results)
                print(f"详细结果已保存到: {output_file}")
            else:
                print("未能从Excel文件中加载到序列号")
        else:
            print("Excel文件不存在")

    else:
        print("无效选择")


if __name__ == "__main__":
    main()
