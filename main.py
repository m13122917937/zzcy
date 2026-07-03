import base64
import json
import logging
import os
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime

import pandas as pd
import psutil
import requests
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPropertyAnimation, QEasingCurve, QRect
from PyQt6.QtGui import QFont, QIcon, QColor, QPixmap, QAction
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QTableWidget, QTableWidgetItem, QPushButton,
                             QLabel, QLineEdit, QFileDialog, QCheckBox,
                             QProgressBar, QComboBox, QGroupBox,
                             QRadioButton, QButtonGroup, QStatusBar, QSplitter,
                             QDialog, QFrame,
                             QSizePolicy, QMenu)

# Apple查询版本控制开关
# 1 = 使用 apple_code.py (原版本：模拟浏览器)
# 2 = 使用 apple_search_api.py (新版本：走api接口)
APPLE_QUERY_VERSION = 2

# Apple查询代理配置
APPLE_USE_PROXY = True
APPLE_PROXY_KEY = "0LM61IPB"  # 青果代理密钥（使用青果代理时需要）
# 代理服务商选择: "kuaidaili"(快代理，默认) / "qingguo"(青果代理)
APPLE_PROXY_PROVIDER = "qingguo"

# 根据版本导入Apple查询功能
if APPLE_QUERY_VERSION == 1:
    from apple_code import AppleWarrantyChecker
    print(f"[Apple查询] 使用版本 {APPLE_QUERY_VERSION}: apple_code.py")
elif APPLE_QUERY_VERSION == 2:
    from apple_search_api import ConcurrentAppleCoverageChecker, AppleDataExtractor
    print(f"[Apple查询] 使用版本 {APPLE_QUERY_VERSION}: apple_search_api.py")
else:
    from apple_search_api import ConcurrentAppleCoverageChecker, AppleDataExtractor
    print(f"[Apple查询] 版本配置错误，默认使用版本 2: apple_search_api.py")

# 超级管理员配置
SUPER_ADMIN_USERNAME = base64.b64decode("c3VwZXJtYXhhZG1pbjEwMjQ=").decode()
SUPER_ADMIN_PASSWORD = base64.b64decode("c3VwZXJtYXhhZG1pbjEwMjQ=").decode()

# 日志配置开关
ENABLE_FILE_LOGGING = False

# 导入环境检测配置
try:
    from environment_config import (
        ENABLE_ENVIRONMENT_CHECK,
        ENVIRONMENT_CHECK_URL,
        ENVIRONMENT_CHECK_TIMEOUT,
        ENVIRONMENT_CHECK_HEADERS
    )
    logger_temp = logging.getLogger(__name__)
    logger_temp.info("[环境检测] 已从配置文件加载环境检测设置")
except ImportError:
    ENABLE_ENVIRONMENT_CHECK = True
    ENVIRONMENT_CHECK_URL = " "
    ENVIRONMENT_CHECK_TIMEOUT = 10
    ENVIRONMENT_CHECK_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    logger_temp = logging.getLogger(__name__)
    logger_temp.warning("[环境检测] 配置文件不存在，使用默认环境检测设置")


def setup_logging():
    """设置日志系统"""
    log_format = "%(asctime)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    handlers = [logging.StreamHandler(sys.stdout)]

    if ENABLE_FILE_LOGGING:
        logs_dir = "logs"
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir)
        current_date = datetime.now().strftime("%Y-%m-%d")
        log_filename = os.path.join(logs_dir, f"apple_warranty_app_{current_date}.log")
        handlers.append(logging.FileHandler(log_filename, encoding='utf-8'))

    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        handlers=handlers
    )

    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("Apple设备保修查询工具启动")
    if ENABLE_FILE_LOGGING:
        logger.info("日志文件输出: 已启用")
    else:
        logger.info("日志文件输出: 已禁用")
    logger.info("=" * 60)

    return logger


logger = setup_logging()


class CopyableTableWidget(QTableWidget):
    """支持右键复制功能的表格控件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def show_context_menu(self, position):
        item = self.itemAt(position)
        if item is None:
            return

        context_menu = QMenu(self)

        copy_cell_action = QAction("复制单元格", self)
        copy_cell_action.triggered.connect(lambda: self.copy_cell_data(item))
        context_menu.addAction(copy_cell_action)

        copy_row_action = QAction("复制整行", self)
        copy_row_action.triggered.connect(lambda: self.copy_row_data(item.row()))
        context_menu.addAction(copy_row_action)

        selected_rows = self.get_selected_rows()
        if len(selected_rows) > 1:
            context_menu.addSeparator()
            copy_selected_action = QAction(f"复制选中的{len(selected_rows)}行", self)
            copy_selected_action.triggered.connect(lambda: self.copy_selected_rows())
            context_menu.addAction(copy_selected_action)

        context_menu.exec(self.mapToGlobal(position))

    def copy_cell_data(self, item):
        if item is not None:
            clipboard = QApplication.clipboard()
            clipboard.setText(item.text())

    def copy_row_data(self, row):
        if 0 <= row < self.rowCount():
            row_data = []
            for col in range(self.columnCount()):
                item = self.item(row, col)
                row_data.append(item.text() if item else "")
            clipboard = QApplication.clipboard()
            clipboard.setText("\t".join(row_data))

    def get_selected_rows(self):
        selected_rows = set()
        for item in self.selectedItems():
            selected_rows.add(item.row())
        return sorted(list(selected_rows))

    def copy_selected_rows(self):
        selected_rows = self.get_selected_rows()
        if not selected_rows:
            return

        all_rows_data = []

        headers = []
        for col in range(self.columnCount()):
            header_item = self.horizontalHeaderItem(col)
            headers.append(header_item.text() if header_item else f"列{col+1}")
        all_rows_data.append("\t".join(headers))

        for row in selected_rows:
            row_data = []
            for col in range(self.columnCount()):
                item = self.item(row, col)
                row_data.append(item.text() if item else "")
            all_rows_data.append("\t".join(row_data))

        clipboard = QApplication.clipboard()
        clipboard.setText("\n".join(all_rows_data))


def get_auto_concurrent_count():
    """根据CPU数量自动计算推荐的并发查询数量"""
    try:
        logical_cores = psutil.cpu_count(logical=True)
        physical_cores = psutil.cpu_count(logical=False)

        if logical_cores is None:
            logical_cores = 4
        if physical_cores is None:
            physical_cores = 2

        if logical_cores >= 16:
            recommended = 8
        elif logical_cores >= 8:
            recommended = 4
        elif logical_cores >= 4:
            recommended = 2
        else:
            recommended = 1

        desc = f"auto ({recommended}个，基于{logical_cores}逻辑核心)"
        logger.info(f"[CPU检测] 检测到 {logical_cores} 个逻辑核心，推荐并发数: {recommended}")
        return recommended, desc

    except Exception as e:
        logger.warning(f"[CPU检测] 无法检测CPU信息: {e}，使用默认并发数")
        return 2, "auto (2个，检测失败)"


def parse_concurrent_count(concurrent_text):
    """解析并发数量文本，支持auto选项"""
    try:
        if concurrent_text.startswith("auto"):
            auto_count, _ = get_auto_concurrent_count()
            return auto_count
        else:
            return int(concurrent_text.split()[0])
    except (ValueError, IndexError) as e:
        logger.warning(f"[并发解析] 无法解析并发数量 '{concurrent_text}': {e}，使用默认值2")
        return 2


class ModernDialog(QDialog):
    """现代化统一对话框基类"""
    def __init__(self, parent=None, title="提示", width=400, height=280):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedSize(width, height)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        icon_path = resource_path("honor_logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

    def setup_base_ui(self, icon_text, icon_color, title_text, subtitle_text, message_text, buttons):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.main_container = QFrame()
        self.main_container.setStyleSheet("""
            QFrame {
                background-color: #f7f7f4;
                border-radius: 12px;
                border: 1px solid rgba(38, 37, 30, 0.1);
            }
        """)
        main_layout.addWidget(self.main_container)

        container_layout = QVBoxLayout(self.main_container)
        container_layout.setContentsMargins(30, 25, 30, 25)
        container_layout.setSpacing(20)

        icon_layout = QHBoxLayout()
        icon_layout.addStretch()

        icon_label = QLabel()
        icon_label.setFixedSize(48, 48)
        icon_label.setStyleSheet(f"""
            QLabel {{
                background-color: {icon_color};
                border-radius: 24px;
                color: #f7f7f4;
                font-size: 24px;
                font-weight: 400;
                border: none;
            }}
        """)
        icon_label.setText(icon_text)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(icon_label)
        icon_layout.addStretch()
        container_layout.addLayout(icon_layout)

        title_label = QLabel(title_text)
        title_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: 400;
                color: #26251e;
                margin: 0;
                padding: 0;
                border: none;
                background: transparent;
            }
        """)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(title_label)

        if subtitle_text:
            subtitle_label = QLabel(subtitle_text)
            subtitle_label.setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    color: rgba(38, 37, 30, 0.55);
                    margin: 0;
                    padding: 0;
                    border: none;
                    background: transparent;
                }
            """)
            subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            subtitle_label.setWordWrap(True)
            container_layout.addWidget(subtitle_label)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("""
            QFrame {
                color: rgba(38, 37, 30, 0.08);
                background-color: rgba(38, 37, 30, 0.08);
                border: none;
                height: 1px;
            }
        """)
        container_layout.addWidget(separator)

        message_label = QLabel(message_text)
        message_label.setStyleSheet("""
            QLabel {
                font-size: 13px;
                color: #26251e;
                line-height: 1.4;
                padding: 10px 0;
                border: none;
                background: transparent;
            }
        """)
        message_label.setWordWrap(True)
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(message_label)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        button_layout.addStretch()

        for button_text, button_role in buttons:
            button = QPushButton(button_text)
            button.setFixedSize(100, 36)

            if button_role == "accept":
                button.setStyleSheet("""
                    QPushButton {
                        background-color: #26251e;
                        color: #f7f7f4;
                        border: none;
                        border-radius: 8px;
                        font-size: 14px;
                        font-weight: 400;
                        padding: 8px 16px;
                    }
                    QPushButton:hover { background-color: #3d3c33; }
                    QPushButton:pressed { background-color: #1a1914; }
                """)
                button.clicked.connect(self.accept)
                button.setDefault(True)
                button.setFocus()
            elif button_role == "reject":
                button.setStyleSheet("""
                    QPushButton {
                        background-color: #e6e5e0;
                        color: rgba(38, 37, 30, 0.6);
                        border: 1px solid rgba(38, 37, 30, 0.1);
                        border-radius: 8px;
                        font-size: 14px;
                        font-weight: 400;
                        padding: 8px 16px;
                    }
                    QPushButton:hover { color: #cf2d56; border-color: rgba(38, 37, 30, 0.2); }
                    QPushButton:pressed { background-color: #e1e0db; }
                """)
                button.clicked.connect(self.reject)

            button_layout.addWidget(button)

        button_layout.addStretch()
        container_layout.addLayout(button_layout)


class EnvironmentErrorDialog(ModernDialog):
    def __init__(self, parent=None):
        super().__init__(parent, "环境检测", 400, 280)
        self.setup_ui()

    def setup_ui(self):
        self.setup_base_ui(
            icon_text="!",
            icon_color="#cf2d56",
            title_text="环境检测异常",
            subtitle_text="当前运行环境检测异常，请重试！",
            message_text="程序无法在当前环境下正常运行。\n请检查网络连接或稍后重试。",
            buttons=[("确定", "accept")]
        )


class ModernInfoDialog(ModernDialog):
    def __init__(self, parent=None, title="提示", message="", width=400, height=280):
        super().__init__(parent, title, width, height)
        self.message = message
        self.setup_ui()

    def setup_ui(self):
        self.setup_base_ui(
            icon_text="i",
            icon_color="#26251e",
            title_text=self.windowTitle(),
            subtitle_text=None,
            message_text=self.message,
            buttons=[("确定", "accept")]
        )


class ModernWarningDialog(ModernDialog):
    def __init__(self, parent=None, title="警告", message="", width=400, height=280):
        super().__init__(parent, title, width, height)
        self.message = message
        self.setup_ui()

    def setup_ui(self):
        self.setup_base_ui(
            icon_text="!",
            icon_color="#c08532",
            title_text=self.windowTitle(),
            subtitle_text=None,
            message_text=self.message,
            buttons=[("确定", "accept")]
        )


class ModernQuestionDialog(ModernDialog):
    def __init__(self, parent=None, title="确认", message="", width=400, height=280):
        super().__init__(parent, title, width, height)
        self.message = message
        self.setup_ui()

    def setup_ui(self):
        self.setup_base_ui(
            icon_text="?",
            icon_color="rgba(38, 37, 30, 0.6)",
            title_text=self.windowTitle(),
            subtitle_text=None,
            message_text=self.message,
            buttons=[("是", "accept"), ("否", "reject")]
        )


def show_modern_info(parent, title, message, width=400, height=280):
    dialog = ModernInfoDialog(parent, title, message, width, height)
    return dialog.exec()


def show_modern_warning(parent, title, message, width=400, height=280):
    dialog = ModernWarningDialog(parent, title, message, width, height)
    return dialog.exec()


def show_modern_question(parent, title, message, width=400, height=280):
    dialog = ModernQuestionDialog(parent, title, message, width, height)
    return dialog.exec()


def check_environment():
    """检查启动环境"""
    if not ENABLE_ENVIRONMENT_CHECK:
        logger.info("[环境检测] 环境检测功能已禁用，跳过检查")
        return True, ""

    logger.info("[环境检测] 正在进行启动环境检测...")

    try:
        response = requests.get(
            ENVIRONMENT_CHECK_URL,
            timeout=ENVIRONMENT_CHECK_TIMEOUT,
            headers=ENVIRONMENT_CHECK_HEADERS
        )

        if response.status_code != 200:
            error_msg = f"服务器返回状态码: {response.status_code}"
            logger.error(f"[环境检测] 检测失败: {error_msg}")
            return False, error_msg

        try:
            data = response.json()
            signal = data.get('signal', False)

            if signal is True:
                logger.info("[环境检测] 环境检测通过，程序正常启动")
                return True, ""
            else:
                error_msg = "环境检测信号为false"
                logger.error(f"[环境检测] 检测失败: {error_msg}")
                return False, error_msg

        except json.JSONDecodeError as e:
            error_msg = f"JSON解析失败: {str(e)}"
            logger.error(f"[环境检测] 检测失败: {error_msg}")
            return False, error_msg

    except requests.exceptions.Timeout:
        error_msg = f"请求超时（{ENVIRONMENT_CHECK_TIMEOUT}秒）"
        logger.error(f"[环境检测] 检测失败: {error_msg}")
        return False, error_msg
    except requests.exceptions.ConnectionError:
        error_msg = "网络连接失败"
        logger.error(f"[环境检测] 检测失败: {error_msg}")
        return False, error_msg
    except requests.exceptions.RequestException as e:
        error_msg = f"请求异常: {str(e)}"
        logger.error(f"[环境检测] 检测失败: {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"未知错误: {str(e)}"
        logger.error(f"[环境检测] 检测失败: {error_msg}")
        return False, error_msg


class AppleWarrantyQueryWorker(QThread):
    """Worker thread to handle Apple warranty queries without blocking the UI"""
    progress_updated = pyqtSignal(int, str)
    query_completed = pyqtSignal(int, dict)
    all_completed = pyqtSignal()

    def __init__(self, serial_numbers, use_proxy=False, proxy_key="", proxy_provider="kuaidaili"):
        super().__init__()
        self.serial_numbers = serial_numbers
        self.use_proxy = use_proxy
        self.proxy_key = proxy_key
        self.proxy_provider = proxy_provider
        self.is_running = True
        if APPLE_QUERY_VERSION == 1:
            self.max_concurrent_queries = 1
        else:
            self.max_concurrent_queries = 3

    def stop(self):
        self.is_running = False

    def _convert_result_format(self, api_result, serial_number):
        try:
            if APPLE_QUERY_VERSION == 1:
                return self._convert_apple_code_result(api_result, serial_number)
            else:
                return self._convert_apple_search_api_result(api_result, serial_number)
        except Exception as e:
            print(f"[Apple查询] 转换结果格式时发生错误: {e}")
            return {
                "serial_number": serial_number,
                "status": "数据转换失败",
                "data": None,
                "duration_seconds": 0.0,
                "proxy_used": "代理异常" if self.use_proxy and self.proxy_key else "未启用",
                "error_message": str(e)
            }

    def _convert_apple_code_result(self, result, serial_number):
        try:
            status = result.get("status", "")
            success_statuses = ["查询成功", "设备需要激活"]

            if status in success_statuses and result.get("data"):
                data = result["data"]
                product_info = {
                    "产品名称": data.get("产品信息", {}).get("产品名称", "未知"),
                    "适用范围": data.get("产品信息", {}).get("适用范围", "中国"),
                    "是否激活": data.get("产品信息", {}).get("是否激活", "否"),
                    "AC+": data.get("产品信息", {}).get("AC+", "否"),
                    "激活时间": data.get("产品信息", {}).get("激活时间", "未知"),
                    "查询时间": data.get("产品信息", {}).get("查询时间", "未知")  # 原来的到期时间
                }
                return {
                    "serial_number": serial_number,
                    "status": "成功",
                    "data": {"产品信息": product_info},
                    "duration_seconds": result.get("duration_seconds", 0.0),
                    "proxy_used": result.get("proxy_used", "未启用"),
                    "error_message": ""
                }
            else:
                return {
                    "serial_number": serial_number,
                    "status": result.get("error_message", "查询失败"),
                    "data": None,
                    "duration_seconds": result.get("duration_seconds", 0.0),
                    "proxy_used": result.get("proxy_used", "未启用"),
                    "error_message": result.get("error_message", "未知错误")
                }
        except Exception as e:
            return {
                "serial_number": serial_number,
                "status": "数据转换失败",
                "data": None,
                "duration_seconds": 0.0,
                "proxy_used": "未启用",
                "error_message": str(e)
            }

    def _convert_apple_search_api_result(self, api_result, serial_number):
        try:
            if api_result.success and api_result.data:
                if APPLE_QUERY_VERSION == 2:
                    extracted_data = AppleDataExtractor.extract_data(api_result.data)
                    product_info = {
                        "产品名称": extracted_data.product_type,
                        "适用范围": "中国",
                        "是否激活": extracted_data.is_pre_activated,
                        "AC+": extracted_data.ac_plus,
                        "激活时间": extracted_data.activation_time,
                        "查询时间": extracted_data.expiry_time  # 原来的到期时间
                    }
                else:
                    product_info = {
                        "产品名称": "未知",
                        "适用范围": "中国",
                        "是否激活": "否",
                        "AC+": "否",
                        "激活时间": "未知",
                        "查询时间": "未知"  # 原来的到期时间
                    }

                proxy_status = api_result.proxy_used or "未启用"
                return {
                    "serial_number": serial_number,
                    "status": "成功",
                    "data": {"产品信息": product_info},
                    "duration_seconds": api_result.processing_time,
                    "proxy_used": proxy_status,
                    "error_message": ""
                }
            else:
                proxy_status = api_result.proxy_used or "未启用"
                return {
                    "serial_number": serial_number,
                    "status": api_result.error or "查询失败",
                    "data": None,
                    "duration_seconds": api_result.processing_time,
                    "proxy_used": proxy_status,
                    "error_message": api_result.error or "未知错误"
                }

        except Exception as e:
            proxy_status = "未启用"
            if hasattr(api_result, 'proxy_used') and api_result.proxy_used:
                proxy_status = api_result.proxy_used
            elif self.use_proxy and self.proxy_key:
                proxy_status = "代理异常"

            return {
                "serial_number": serial_number,
                "status": "数据转换失败",
                "data": None,
                "duration_seconds": 0.0,
                "proxy_used": proxy_status,
                "error_message": str(e)
            }

    def _query_with_apple_code(self, serial_number):
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                if APPLE_QUERY_VERSION == 1:
                    checker = AppleWarrantyChecker(
                        use_proxy=self.use_proxy,
                        proxy_key=self.proxy_key,
                        reuse_browser=False
                    )
                    result = loop.run_until_complete(checker.check_warranty(serial_number))
                    loop.run_until_complete(checker.cleanup_browser())
                    return result
                else:
                    raise ValueError("版本配置错误")
            finally:
                loop.close()
        except Exception as e:
            return {
                "serial_number": serial_number,
                "status": "查询失败",
                "error_message": str(e),
                "data": None,
                "duration_seconds": 0.0,
                "proxy_used": "未启用"
            }

    def _query_with_apple_search_api(self, serial_number):
        try:
            if APPLE_QUERY_VERSION == 2:
                checker = ConcurrentAppleCoverageChecker(
                    max_workers=1,
                    max_retries=10,
                    use_proxy=self.use_proxy,
                    proxy_key=self.proxy_key,
                    proxy_provider=self.proxy_provider
                )
                result = checker.check_single_serial(serial_number)
                return result
            else:
                raise ValueError("版本配置错误")
        except Exception as e:
            class ErrorResult:
                def __init__(self, error_msg):
                    self.success = False
                    self.error = error_msg
                    self.data = None
                    self.processing_time = 0.0
                    self.proxy_used = "未启用"
            return ErrorResult(str(e))

    def run(self):
        print("[Apple查询] 查询工作线程启动")
        try:
            if self.use_proxy:
                print(f"[Apple查询] 代理模式已启用，服务商: {self.proxy_provider}")
            else:
                print("[Apple查询] 直连模式")

            if self.max_concurrent_queries <= 1:
                print("[Apple查询] 使用顺序查询模式")
                self._run_sequential_queries()
            else:
                print(f"[Apple查询] 使用并发查询模式，并发数: {self.max_concurrent_queries}")
                self._run_concurrent_queries()

            print("[Apple查询] 查询任务执行完成")
        except Exception as e:
            print(f"[Apple查询] 查询工作线程发生错误: {e}")
            traceback.print_exc()
        finally:
            self.all_completed.emit()
            print("[Apple查询] 查询工作线程结束")

    def _run_sequential_queries(self):
        for i, serial_number in enumerate(self.serial_numbers):
            if not self.is_running:
                break

            print(f"[Apple查询] 正在查询第 {i+1}/{len(self.serial_numbers)} 个序列号: {serial_number}")
            self.progress_updated.emit(i, "正在查询...")

            try:
                if APPLE_QUERY_VERSION == 1:
                    result = self._query_with_apple_code(serial_number)
                else:
                    result = self._query_with_apple_search_api(serial_number)

                converted_result = self._convert_result_format(result, serial_number)
                self.query_completed.emit(i, converted_result)

                if APPLE_QUERY_VERSION == 1:
                    success_statuses = ["查询成功", "设备需要激活"]
                    result_status = result.get("status", "") if isinstance(result, dict) else ""
                    status = "成功" if result_status in success_statuses else "失败"
                else:
                    status = "成功" if (hasattr(result, 'success') and result.success) else "失败"
                print(f"[Apple查询] 序列号 {serial_number} 查询完成: {status}")

            except Exception as e:
                print(f"[Apple查询] 处理序列号 {serial_number} 时发生错误: {e}")
                error_result = {
                    "serial_number": serial_number,
                    "status": "查询失败",
                    "error_message": str(e),
                    "data": None,
                    "duration_seconds": 0.0,
                    "proxy_used": "无代理"
                }
                self.query_completed.emit(i, error_result)

    def _run_concurrent_queries(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed

        for i in range(len(self.serial_numbers)):
            self.progress_updated.emit(i, "正在查询...")

        with ThreadPoolExecutor(max_workers=self.max_concurrent_queries) as executor:
            future_to_index = {}
            for i, serial_number in enumerate(self.serial_numbers):
                if not self.is_running:
                    break
                future = executor.submit(self._query_single_serial, serial_number)
                future_to_index[future] = i

            for future in as_completed(future_to_index):
                if not self.is_running:
                    break

                index = future_to_index[future]
                try:
                    result = future.result()
                    self.query_completed.emit(index, result)
                    serial_number = self.serial_numbers[index]
                    status = "成功" if result.get('status') == '成功' else "失败"
                    print(f"[Apple查询] [{index+1}] 序列号 {serial_number} 查询完成: {status}")
                except Exception as e:
                    serial_number = self.serial_numbers[index]
                    error_result = {
                        "serial_number": serial_number,
                        "status": "查询失败",
                        "error_message": str(e),
                        "data": None,
                        "duration_seconds": 0.0,
                        "proxy_used": "无代理"
                    }
                    self.query_completed.emit(index, error_result)

    def _query_single_serial(self, serial_number):
        try:
            if APPLE_QUERY_VERSION == 1:
                result = self._query_with_apple_code(serial_number)
            else:
                result = self._query_with_apple_search_api(serial_number)
            return self._convert_result_format(result, serial_number)
        except Exception as e:
            return {
                "serial_number": serial_number,
                "status": "查询失败",
                "error_message": str(e),
                "data": None,
                "duration_seconds": 0.0,
                "proxy_used": "无代理"
            }


class AnimatedExitDialog(ModernDialog):
    def __init__(self, parent=None, has_running_tasks=False):
        self.has_running_tasks = has_running_tasks
        if has_running_tasks:
            width, height = 420, 320
        else:
            width, height = 400, 280

        super().__init__(parent, "确认退出", width, height)
        self.setup_ui()
        self.setup_animations()

    def setup_ui(self):
        if self.has_running_tasks:
            message_text = "检测到有查询任务正在运行！\n\n强制退出可能导致数据丢失。\n建议等待任务完成后再退出。\n\n确定要立即退出吗？"
            icon_color = "#cf2d56"
        else:
            message_text = "确定要退出程序吗？"
            icon_color = "rgba(38, 37, 30, 0.4)"

        self.setup_base_ui(
            icon_text="!",
            icon_color=icon_color,
            title_text="确认退出",
            subtitle_text=None,
            message_text=message_text,
            buttons=[("取消", "reject"), ("退出", "accept")]
        )

    def setup_animations(self):
        self.scale_animation = QPropertyAnimation(self.main_container, b"geometry")
        self.scale_animation.setDuration(200)
        self.scale_animation.setEasingCurve(QEasingCurve.Type.OutBack)

        self.opacity_animation = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_animation.setDuration(150)
        self.opacity_animation.setEasingCurve(QEasingCurve.Type.OutQuad)

    def showEvent(self, a0):
        super().showEvent(a0)
        self.setWindowOpacity(0)

        final_geometry = self.main_container.geometry()
        start_geometry = QRect(
            final_geometry.x() + final_geometry.width() // 4,
            final_geometry.y() + final_geometry.height() // 4,
            final_geometry.width() // 2,
            final_geometry.height() // 2
        )
        self.main_container.setGeometry(start_geometry)

        self.scale_animation.setStartValue(start_geometry)
        self.scale_animation.setEndValue(final_geometry)
        self.opacity_animation.setStartValue(0)
        self.opacity_animation.setEndValue(1)

        self.scale_animation.start()
        self.opacity_animation.start()




class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("用户认证")
        self.setFixedSize(450, 500)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        icon_path = resource_path("honor_logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.user_info = None
        self.is_register_mode = False
        self.device_registration_manager = DeviceRegistrationManager()
        self.remember_config_file = self._get_remember_config_path()
        self.setup_ui()
        self._load_saved_credentials()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.main_container = QFrame()
        self.main_container.setStyleSheet("""
            QFrame {
                background-color: #f7f7f4;
                border-radius: 12px;
                border: 1px solid rgba(38, 37, 30, 0.1);
            }
        """)
        main_layout.addWidget(self.main_container)

        container_layout = QVBoxLayout(self.main_container)
        container_layout.setContentsMargins(35, 30, 35, 30)
        container_layout.setSpacing(25)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(15)

        logo_layout = QHBoxLayout()
        logo_layout.addStretch()

        logo_label = QLabel()
        logo_pixmap = QPixmap(resource_path("honor_logo.png"))
        if not logo_pixmap.isNull():
            scaled_pixmap = logo_pixmap.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(scaled_pixmap)
        else:
            logo_label.setText("A")
            logo_label.setStyleSheet("""
                QLabel {
                    background-color: #26251e;
                    color: #f7f7f4;
                    border-radius: 28px;
                    font-size: 24px;
                    font-weight: 400;
                    text-align: center;
                }
            """)
        logo_label.setFixedSize(56, 56)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_layout.addWidget(logo_label)
        logo_layout.addStretch()
        title_layout.addLayout(logo_layout)

        self.title_label = QLabel("用户登录")
        self.title_label.setStyleSheet("""
            QLabel {
                font-size: 20px;
                font-weight: 400;
                color: #26251e;
                margin: 0px;
            }
        """)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(self.title_label)
        container_layout.addLayout(title_layout)

        form_layout = QVBoxLayout()
        form_layout.setSpacing(18)

        username_container = QVBoxLayout()
        username_container.setSpacing(8)
        username_container.setContentsMargins(0, 0, 0, 0)

        username_label = QLabel("用户名")
        username_label.setStyleSheet("QLabel { font-weight: 400; color: rgba(38, 37, 30, 0.6); font-size: 14px; border: none; background: transparent; padding: 0px; margin: 0px; }")
        username_container.addWidget(username_label)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("请输入用户名")
        self.username_input.setMinimumHeight(42)
        self.username_input.setStyleSheet("""
            QLineEdit { border: 1px solid rgba(38, 37, 30, 0.1); border-radius: 8px; padding: 10px 14px; font-size: 14px; background-color: #f7f7f4; color: #26251e; }
            QLineEdit:focus { border: 1px solid rgba(38, 37, 30, 0.2); }
            QLineEdit:hover { border: 1px solid rgba(38, 37, 30, 0.15); }
        """)
        username_container.addWidget(self.username_input)
        form_layout.addLayout(username_container)

        password_container = QVBoxLayout()
        password_container.setSpacing(8)
        password_container.setContentsMargins(0, 0, 0, 0)

        password_label = QLabel("密码")
        password_label.setStyleSheet("QLabel { font-weight: 400; color: rgba(38, 37, 30, 0.6); font-size: 14px; border: none; background: transparent; padding: 0px; margin: 0px; }")
        password_container.addWidget(password_label)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("请输入密码")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setMinimumHeight(42)
        self.password_input.setStyleSheet("""
            QLineEdit { border: 1px solid rgba(38, 37, 30, 0.1); border-radius: 8px; padding: 10px 14px; font-size: 14px; background-color: #f7f7f4; color: #26251e; }
            QLineEdit:focus { border: 1px solid rgba(38, 37, 30, 0.2); }
            QLineEdit:hover { border: 1px solid rgba(38, 37, 30, 0.15); }
        """)
        password_container.addWidget(self.password_input)
        form_layout.addLayout(password_container)

        # 记住我复选框
        self.remember_me_checkbox = QCheckBox("记住我")
        self.remember_me_checkbox.setStyleSheet("""
            QCheckBox { font-size: 13px; color: rgba(38, 37, 30, 0.6); spacing: 8px; border: none; background: transparent; }
            QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid rgba(38, 37, 30, 0.2); background-color: #f7f7f4; }
            QCheckBox::indicator:checked { background-color: #26251e; border-color: #26251e; }
            QCheckBox::indicator:hover { border-color: rgba(38, 37, 30, 0.35); }
        """)
        form_layout.addWidget(self.remember_me_checkbox)

        confirm_password_container = QVBoxLayout()
        confirm_password_container.setSpacing(8)

        self.confirm_password_label = QLabel("确认密码")
        self.confirm_password_label.setStyleSheet("QLabel { font-weight: 400; color: rgba(38, 37, 30, 0.6); font-size: 14px; border: none; background: transparent; padding: 0px; margin: 0px; }")
        confirm_password_container.addWidget(self.confirm_password_label)

        self.confirm_password_input = QLineEdit()
        self.confirm_password_input.setPlaceholderText("请再次输入密码")
        self.confirm_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_password_input.setMinimumHeight(42)
        self.confirm_password_input.setStyleSheet("""
            QLineEdit { border: 1px solid rgba(38, 37, 30, 0.1); border-radius: 8px; padding: 10px 14px; font-size: 14px; background-color: #f7f7f4; color: #26251e; }
            QLineEdit:focus { border: 1px solid rgba(38, 37, 30, 0.2); }
            QLineEdit:hover { border: 1px solid rgba(38, 37, 30, 0.15); }
        """)
        confirm_password_container.addWidget(self.confirm_password_input)

        self.confirm_password_widget = QWidget()
        self.confirm_password_widget.setLayout(confirm_password_container)
        self.confirm_password_widget.setVisible(False)
        self.confirm_password_widget.setContentsMargins(0, 0, 0, 0)
        confirm_password_container.setContentsMargins(0, 0, 0, 0)
        form_layout.addWidget(self.confirm_password_widget)

        container_layout.addLayout(form_layout)

        button_layout = QVBoxLayout()
        button_layout.setSpacing(12)

        self.main_action_button = QPushButton("登录")
        self.main_action_button.setMinimumHeight(45)
        self.main_action_button.setStyleSheet("""
            QPushButton { background-color: #26251e; color: #f7f7f4; border: none; border-radius: 8px; padding: 12px; font-size: 14px; font-weight: 400; }
            QPushButton:hover { background-color: #3d3c33; }
            QPushButton:pressed { background-color: #1a1914; }
            QPushButton:disabled { background-color: #e6e5e0; color: rgba(38, 37, 30, 0.35); }
        """)
        button_layout.addWidget(self.main_action_button)

        bottom_button_layout = QHBoxLayout()
        bottom_button_layout.setSpacing(10)

        self.switch_mode_button = QPushButton("注册账号")
        self.switch_mode_button.setMinimumHeight(38)
        self.switch_mode_button.setStyleSheet("""
            QPushButton { background-color: transparent; color: rgba(38, 37, 30, 0.6); border: 1px solid rgba(38, 37, 30, 0.15); border-radius: 8px; padding: 8px 16px; font-size: 14px; font-weight: 400; }
            QPushButton:hover { color: #cf2d56; border-color: rgba(38, 37, 30, 0.2); }
        """)

        self.cancel_button = QPushButton("取消")
        self.cancel_button.setMinimumHeight(38)
        self.cancel_button.setStyleSheet("""
            QPushButton { background-color: #e6e5e0; color: rgba(38, 37, 30, 0.6); border: 1px solid rgba(38, 37, 30, 0.1); border-radius: 8px; padding: 8px 16px; font-size: 14px; }
            QPushButton:hover { color: #cf2d56; border-color: rgba(38, 37, 30, 0.2); }
        """)

        bottom_button_layout.addWidget(self.switch_mode_button)
        bottom_button_layout.addWidget(self.cancel_button)
        button_layout.addLayout(bottom_button_layout)

        container_layout.addLayout(button_layout)

        self.main_action_button.clicked.connect(self.handle_main_action)
        self.switch_mode_button.clicked.connect(self.toggle_mode)
        self.cancel_button.clicked.connect(self.reject)
        self.username_input.returnPressed.connect(self.handle_main_action)
        self.password_input.returnPressed.connect(self.handle_main_action)
        self.confirm_password_input.returnPressed.connect(self.handle_main_action)

    # ── 记住我：凭据持久化 ──

    def _get_remember_config_path(self):
        try:
            appdata_local = os.path.expandvars(r'%LOCALAPPDATA%')
            app_dir = os.path.join(appdata_local, 'Microsoft', 'Windows', 'HonorApp')
            os.makedirs(app_dir, exist_ok=True)
            return os.path.join(app_dir, 'user_credentials.dat')
        except Exception:
            return "user_credentials.json"

    @staticmethod
    def _encrypt_password(password: str) -> str:
        import hashlib
        machine_id = get_unique_id()
        key = hashlib.sha256(machine_id.encode()).digest()
        pwd_bytes = password.encode('utf-8')
        encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(pwd_bytes))
        return base64.b64encode(encrypted).decode('utf-8')

    @staticmethod
    def _decrypt_password(encrypted: str) -> str:
        import hashlib
        machine_id = get_unique_id()
        key = hashlib.sha256(machine_id.encode()).digest()
        encrypted_bytes = base64.b64decode(encrypted)
        decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(encrypted_bytes))
        return decrypted.decode('utf-8')

    def _save_credentials(self, username: str, password: str):
        try:
            data = {
                'username': username,
                'password': self._encrypt_password(password)
            }
            encoded = base64.b64encode(json.dumps(data, ensure_ascii=False).encode('utf-8')).decode('utf-8')
            # 写入前先解除隐藏和只读属性，避免权限问题
            if os.name == 'nt' and os.path.exists(self.remember_config_file):
                try:
                    subprocess.run(['attrib', '-H', '-R', self.remember_config_file], capture_output=True, check=False)
                except Exception:
                    pass
            with open(self.remember_config_file, 'w', encoding='utf-8') as f:
                f.write(encoded)
            if os.name == 'nt':
                try:
                    subprocess.run(['attrib', '+H', self.remember_config_file], capture_output=True, check=False)
                except Exception:
                    pass
        except Exception as e:
            print(f"[记住我] 保存凭据失败: {e}")

    def _clear_credentials(self):
        try:
            if os.path.exists(self.remember_config_file):
                if os.name == 'nt':
                    try:
                        subprocess.run(['attrib', '-H', '-R', self.remember_config_file], capture_output=True, check=False)
                    except Exception:
                        pass
                os.remove(self.remember_config_file)
        except Exception as e:
            print(f"[记住我] 清除凭据失败: {e}")

    def _load_saved_credentials(self):
        try:
            if not os.path.exists(self.remember_config_file):
                return
            with open(self.remember_config_file, 'r', encoding='utf-8') as f:
                encoded = f.read().strip()
            if not encoded:
                return
            decoded = json.loads(base64.b64decode(encoded).decode('utf-8'))
            username = decoded.get('username', '')
            encrypted_pwd = decoded.get('password', '')
            if username and encrypted_pwd:
                self.username_input.setText(username)
                self.password_input.setText(self._decrypt_password(encrypted_pwd))
                self.remember_me_checkbox.setChecked(True)
        except Exception as e:
            print(f"[记住我] 加载凭据失败: {e}")

    def toggle_mode(self):
        self.is_register_mode = not self.is_register_mode

        if self.is_register_mode:
            self.title_label.setText("用户注册")
            self.main_action_button.setText("注册")
            self.switch_mode_button.setText("已有账号？登录")
            self.confirm_password_widget.setVisible(True)
            self.remember_me_checkbox.setVisible(False)
            self.setFixedSize(450, 580)
        else:
            self.title_label.setText("用户登录")
            self.main_action_button.setText("登录")
            self.switch_mode_button.setText("注册账号")
            self.confirm_password_widget.setVisible(False)
            self.remember_me_checkbox.setVisible(True)
            self.setFixedSize(450, 500)

        self.username_input.clear()
        self.password_input.clear()
        self.confirm_password_input.clear()
        self.username_input.setFocus()

    def handle_main_action(self):
        if self.is_register_mode:
            self.handle_register()
        else:
            self.handle_login()

    def handle_login(self):
        if not self.main_action_button.isEnabled():
            return

        username = self.username_input.text().strip()
        password = self.password_input.text().strip()

        if not username or not password:
            show_modern_warning(self, "输入错误", "请输入用户名和密码")
            return

        self.main_action_button.setEnabled(False)
        self.main_action_button.setText("登录中...")

        self.login_thread = LoginThread(username, password)
        self.login_thread.login_result.connect(self.on_login_result)
        self.login_thread.start()

    def handle_register(self):
        if not self.main_action_button.isEnabled():
            return

        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        confirm_password = self.confirm_password_input.text().strip()

        if not username or not password or not confirm_password:
            show_modern_warning(self, "输入错误", "请填写所有字段")
            return

        if password != confirm_password:
            show_modern_warning(self, "密码错误", "两次输入的密码不一致")
            return

        if len(password) < 6:
            show_modern_warning(self, "密码错误", "密码长度至少6位")
            return

        if self.check_device_registration_limit():
            return

        self.main_action_button.setEnabled(False)
        self.main_action_button.setText("注册中...")

        self.register_thread = RegisterThread(username, password)
        self.register_thread.register_result.connect(self.on_register_result)
        self.register_thread.start()

    def check_device_registration_limit(self):
        try:
            username = self.username_input.text().strip()
            if username == SUPER_ADMIN_USERNAME:
                return False

            current_mac_id = get_unique_id()

            if hasattr(self, 'device_registration_manager'):
                if self.device_registration_manager.is_device_registered(current_mac_id):
                    registered_username = self.device_registration_manager.get_registered_username(current_mac_id)
                    message = (f"此设备已经注册过账号！\n\n"
                              f"已注册的账号：{registered_username}\n"
                              f"设备标识：{current_mac_id[:20]}...\n\n"
                              f"为了防止滥用，每台设备只能注册一个账号。\n"
                              f"如果您忘记了密码，请联系管理员重置。")
                    dialog = ModernWarningDialog(self, "设备注册限制", message, 450, 320)
                    dialog.setModal(True)
                    dialog.exec()
                    return True

            return False

        except Exception as e:
            print(f"[设备限制] 检查设备注册限制时发生错误: {e}")
            return False

    def on_login_result(self, success, message, user_info):
        self.main_action_button.setEnabled(True)
        self.main_action_button.setText("登录")

        if success:
            # 记住我：登录成功后根据复选框状态保存或清除凭据
            if self.remember_me_checkbox.isChecked():
                self._save_credentials(self.username_input.text().strip(), self.password_input.text().strip())
            else:
                self._clear_credentials()

            self.user_info = user_info
            username = user_info.get('loginName', '用户')
            self.accept()
        else:
            dialog = ModernWarningDialog(self, "登录失败", message)
            dialog.exec()

    def on_register_result(self, success, message):
        self.main_action_button.setEnabled(True)
        self.main_action_button.setText("注册")

        if success:
            username = self.username_input.text().strip()
            if username != SUPER_ADMIN_USERNAME:
                try:
                    current_mac_id = get_unique_id()
                    self.device_registration_manager.register_device(current_mac_id, username)
                except Exception as e:
                    print(f"[设备注册] 保存设备注册记录失败: {e}")

            dialog = ModernInfoDialog(self, "注册成功", "账号注册成功！请使用新账号登录。")
            dialog.exec()
            self.is_register_mode = True
            self.toggle_mode()
            self.username_input.setText(username)
            self.password_input.setFocus()
        else:
            dialog = ModernWarningDialog(self, "注册失败", message)
            dialog.exec()


class LoginThread(QThread):
    login_result = pyqtSignal(bool, str, dict)

    def __init__(self, username, password):
        super().__init__()
        self.username = username
        self.password = password

    def run(self):
        logger.info("开始执行登录请求")
        try:
            if self.username == SUPER_ADMIN_USERNAME and self.password == SUPER_ADMIN_PASSWORD:
                super_admin_info = {
                    "loginName": self.username,
                    "type": 999,
                    "is_super_admin": True,
                    "userId": "super_admin_001"
                }
                logger.info("管理员登录成功")
                self.login_result.emit(True, "登录成功！", super_admin_info)
                return

            mac_id = get_unique_id()
            data = {
                "loginName": self.username,
                "pwd": self.password,
                "macId": mac_id
            }

            response = requests.post(
                "http://infra.freeme.xin/company/auth/login",
                json=data,
                timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                code = result.get("code")
                msg = result.get("msg", "未知错误")

                if code == 200:
                    user_info = result.get("data", {})
                    user_info["loginName"] = self.username
                    user_info["type"] = user_info.get("type", 1)
                    self.login_result.emit(True, msg, user_info)
                else:
                    display_msg = "请联系管理员" if "认证失败" in msg or "无法访问系统资源" in msg else msg
                    self.login_result.emit(False, display_msg, {})
            else:
                self.login_result.emit(False, f"服务器HTTP错误: {response.status_code}", {})

        except requests.exceptions.Timeout:
            self.login_result.emit(False, "请求超时，请检查网络连接", {})
        except requests.exceptions.ConnectionError:
            self.login_result.emit(False, "网络连接失败，请检查网络设置", {})
        except Exception as e:
            self.login_result.emit(False, f"登录失败: {str(e)}", {})
        finally:
            logger.info("登录请求处理完成")


class RegisterThread(QThread):
    register_result = pyqtSignal(bool, str)

    def __init__(self, username, password):
        super().__init__()
        self.username = username
        self.password = password

    def run(self):
        logger.info("开始执行注册请求")
        try:
            mac_id = get_unique_id()
            data = {
                "loginName": self.username,
                "pwd": self.password,
                "macId": mac_id
            }

            response = requests.post(
                "http://infra.freeme.xin/company/auth/register",
                json=data,
                timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                code = result.get("code")
                msg = result.get("msg", "未知错误")

                if code == 200:
                    self.register_result.emit(True, msg)
                else:
                    display_msg = "请联系管理员" if "认证失败" in msg or "无法访问系统资源" in msg else msg
                    self.register_result.emit(False, display_msg)
            else:
                self.register_result.emit(False, f"服务器HTTP错误: {response.status_code}")

        except requests.exceptions.Timeout:
            self.register_result.emit(False, "请求超时，请检查网络连接")
        except requests.exceptions.ConnectionError:
            self.register_result.emit(False, "网络连接失败，请检查网络设置")
        except Exception as e:
            self.register_result.emit(False, f"注册失败: {str(e)}")
        finally:
            logger.info("注册请求处理完成")


class AppleWarrantyApp(QMainWindow):
    """Main application window for Apple Warranty Query Tool"""

    def __init__(self):
        super().__init__()
        logger.info("应用程序启动中...")

        self.setWindowTitle("设备查询工具(Apple)")
        self.setMinimumSize(1400, 800)
        self.resize(1400, 800)

        icon_path = resource_path("honor_logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.setup_style()

        self.user_info = self.show_login_dialog()
        if not self.user_info:
            logger.info("用户取消登录，应用程序退出")
            sys.exit(0)

        username = self.user_info.get('loginName', '未知用户')
        logger.info(f"用户登录成功: {username}")

        self.query_count_manager = QueryCountManager()
        type_value = self.user_info.get('type', 1)
        if username and type_value:
            if hasattr(self.query_count_manager, 'user_data') and username in self.query_count_manager.user_data:
                stored_type = self.query_count_manager.user_data[username].get('type_value', 1)
                if type_value != stored_type:
                    self.query_count_manager.handle_paid_user_login(username, type_value)
                else:
                    self.query_count_manager.check_and_reset_daily_count(username, type_value)
            else:
                self.query_count_manager.init_user_count(username, type_value)

        self.init_ui()

        self.apple_serial_numbers = []
        self.apple_results = []
        self.apple_query_worker = None
        logger.info("应用程序初始化完成")

    def show_login_dialog(self):
        login_dialog = LoginDialog(self)
        result = login_dialog.exec()
        if result != QDialog.DialogCode.Accepted:
            return None
        return login_dialog.user_info

    def setup_style(self):
        app_font = QFont("Microsoft YaHei", 10)
        QApplication.setFont(app_font)

        self.setStyleSheet("""
            QMainWindow { background-color: #f2f1ed; }
            QWidget { font-family: 'Microsoft YaHei'; color: #26251e; }
            QGroupBox {
                border: 1px solid rgba(38, 37, 30, 0.1);
                border-radius: 8px;
                margin-top: 12px;
                font-weight: 400;
                background-color: #ebeae5;
                color: rgba(38, 37, 30, 0.6);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                background-color: #ebeae5;
                color: rgba(38, 37, 30, 0.6);
            }
            QPushButton {
                background-color: #ebeae5;
                color: #26251e;
                border: 1px solid rgba(38, 37, 30, 0.1);
                border-radius: 8px;
                padding: 8px 14px;
                font-weight: 400;
                font-size: 14px;
            }
            QPushButton:hover { color: #cf2d56; border-color: rgba(38, 37, 30, 0.2); }
            QPushButton:pressed { background-color: #e1e0db; color: #26251e; }
            QPushButton:disabled { background-color: #e6e5e0; color: rgba(38, 37, 30, 0.35); border-color: rgba(38, 37, 30, 0.05); }
            QLineEdit, QComboBox {
                border: 1px solid rgba(38, 37, 30, 0.1);
                border-radius: 8px;
                padding: 6px 10px;
                background-color: #f7f7f4;
                color: #26251e;
            }
            QLineEdit:focus, QComboBox:focus { border: 1px solid rgba(38, 37, 30, 0.2); }
            QTableWidget {
                border: 1px solid rgba(38, 37, 30, 0.1);
                border-radius: 8px;
                background-color: #f7f7f4;
                gridline-color: rgba(38, 37, 30, 0.06);
                selection-background-color: #ebeae5;
                selection-color: #26251e;
                color: #26251e;
            }
            QTableWidget::item { text-align: center; alignment: center; }
            QHeaderView::section {
                background-color: #ebeae5;
                border: 1px solid rgba(38, 37, 30, 0.1);
                padding: 6px 4px;
                font-weight: 400;
                text-align: center;
                color: rgba(38, 37, 30, 0.6);
                font-size: 13px;
            }
            QProgressBar {
                border: 1px solid rgba(38, 37, 30, 0.1);
                border-radius: 8px;
                text-align: center;
                background-color: #ebeae5;
                color: #26251e;
                font-size: 12px;
            }
            QProgressBar::chunk { background-color: #f54e00; border-radius: 7px; }
            QCheckBox, QRadioButton { spacing: 8px; color: #26251e; }
            QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
            QSplitter::handle { background-color: rgba(38, 37, 30, 0.1); }
            QStatusBar {
                background-color: #f2f1ed;
                color: rgba(38, 37, 30, 0.55);
                border-top: 1px solid rgba(38, 37, 30, 0.1);
                font-size: 12px;
            }
            QScrollBar:vertical {
                background: #f2f1ed;
                width: 8px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: rgba(38, 37, 30, 0.15);
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover { background: rgba(38, 37, 30, 0.25); }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
        """)

    def init_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(8, 6, 8, 6)
        main_layout.setSpacing(6)

        # ── Header Bar ──
        header_frame = QFrame()
        header_frame.setFixedHeight(42)
        header_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header_frame.setStyleSheet("""
            QFrame {
                background-color: #ebeae5;
                border: 1px solid rgba(38, 37, 30, 0.08);
                border-radius: 8px;
            }
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(16, 0, 16, 0)
        header_layout.setSpacing(12)

        app_title = QLabel("设备查询工具(Apple)")
        app_title.setStyleSheet("""
            font-size: 14px; font-weight: 400; color: #26251e;
            letter-spacing: -0.11px; border: none; background: transparent;
        """)
        header_layout.addWidget(app_title)
        header_layout.addStretch()

        # 右侧元信息区
        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(8)
        meta_layout.setContentsMargins(0, 0, 0, 0)

        username = self.user_info.get('loginName', '未知用户') if self.user_info else '未知用户'
        user_info_label = QLabel(f"当前用户: {username}")
        user_info_label.setStyleSheet("""
            font-size: 12px;
            color: rgba(38, 37, 30, 0.55);
            background-color: transparent;
            border: none;
            padding: 0;
        """)
        meta_layout.addWidget(user_info_label)

        # 分隔竖线
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFixedSize(1, 16)
        divider.setStyleSheet("""
            QFrame {
                color: rgba(38, 37, 30, 0.15);
                background-color: rgba(38, 37, 30, 0.15);
                border: none;
            }
        """)
        meta_layout.addWidget(divider)

        self.query_count_label = QLabel("剩余查询次数: 计算中...")
        self.query_count_label.setFixedHeight(24)
        self.query_count_label.setStyleSheet("""
            font-size: 12px;
            color: #26251e;
            background-color: #f7f7f4;
            border: 1px solid rgba(38, 37, 30, 0.1);
            border-radius: 12px;
            padding: 2px 12px;
            font-weight: 400;
        """)
        meta_layout.addWidget(self.query_count_label)

        header_layout.addLayout(meta_layout)
        self.update_query_count_display()

        main_layout.addWidget(header_frame)

        # Apple查询直接作为主内容（不用TabWidget，单功能更简洁）
        apple_splitter = QSplitter(Qt.Orientation.Horizontal)
        apple_splitter.setHandleWidth(2)
        apple_splitter.setChildrenCollapsible(False)
        apple_splitter.setStretchFactor(0, 0)
        apple_splitter.setStretchFactor(1, 1)

        self.apple_query_panel = QWidget()
        self.create_apple_query_panel()

        self.apple_results_panel = QWidget()
        self.create_apple_results_panel()

        apple_splitter.addWidget(self.apple_query_panel)
        apple_splitter.addWidget(self.apple_results_panel)
        apple_splitter.setSizes([350, 1050])

        self.apple_query_panel.setMinimumWidth(320)
        self.apple_query_panel.setMaximumWidth(450)

        main_layout.addWidget(apple_splitter)

        self.status_bar = QStatusBar()
        self.status_bar.setFixedHeight(25)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

        self.setCentralWidget(main_widget)

    def update_query_count_display(self):
        try:
            if hasattr(self, 'query_count_manager') and self.user_info:
                username = self.user_info.get('loginName')
                is_super_admin = self.user_info.get('is_super_admin', False)

                if username:
                    if is_super_admin:
                        self.query_count_label.setText("查询次数: 无限制 (超级管理员)")
                        self.query_count_label.setStyleSheet("""
                            font-size: 12px; color: #1f8a65; background-color: rgba(31, 138, 101, 0.08);
                            border: 1px solid rgba(31, 138, 101, 0.15); border-radius: 12px;
                            padding: 2px 12px; font-weight: 400;
                        """)
                    else:
                        remaining = self.query_count_manager.get_remaining_count(username)
                        self.query_count_label.setText(f"剩余查询次数: {remaining}")

                        if remaining <= 0:
                            self.query_count_label.setStyleSheet("""
                                font-size: 12px; color: #cf2d56; background-color: rgba(207, 45, 86, 0.06);
                                border: 1px solid rgba(207, 45, 86, 0.15); border-radius: 12px;
                                padding: 2px 12px; font-weight: 400;
                            """)
                        elif remaining <= 5:
                            self.query_count_label.setStyleSheet("""
                                font-size: 12px; color: #c08532; background-color: rgba(192, 133, 50, 0.06);
                                border: 1px solid rgba(192, 133, 50, 0.15); border-radius: 12px;
                                padding: 2px 12px; font-weight: 400;
                            """)
                        else:
                            self.query_count_label.setStyleSheet("""
                                font-size: 12px; color: #26251e; background-color: #f7f7f4;
                                border: 1px solid rgba(38, 37, 30, 0.1); border-radius: 12px;
                                padding: 2px 12px; font-weight: 400;
                            """)
        except Exception as e:
            print(f"[UI] 更新查询次数显示失败: {e}")
            self.query_count_label.setText("剩余查询次数: 错误")

    def create_apple_query_panel(self):
        layout = QVBoxLayout(self.apple_query_panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(14)

        title_label = QLabel("Apple设备查询设置")
        title_label.setStyleSheet("""
            font-size: 15px; font-weight: 400; color: #26251e;
            padding-bottom: 2px; letter-spacing: -0.11px;
        """)
        layout.addWidget(title_label)

        input_group = QGroupBox("序列号输入方式")
        input_layout = QVBoxLayout(input_group)
        input_layout.setContentsMargins(16, 24, 16, 16)
        input_layout.setSpacing(12)

        self.apple_input_method_group = QButtonGroup(self)
        self.apple_manual_input_radio = QRadioButton("手动输入")
        self.apple_excel_input_radio = QRadioButton("从Excel文件读取")
        self.apple_manual_input_radio.setChecked(True)

        self.apple_input_method_group.addButton(self.apple_manual_input_radio, 1)
        self.apple_input_method_group.addButton(self.apple_excel_input_radio, 2)

        radio_layout = QHBoxLayout()
        radio_layout.setSpacing(16)
        radio_layout.addWidget(self.apple_manual_input_radio)
        radio_layout.addWidget(self.apple_excel_input_radio)
        radio_layout.addStretch()
        input_layout.addLayout(radio_layout)

        self.apple_manual_input_widget = QWidget()
        manual_layout = QVBoxLayout(self.apple_manual_input_widget)
        manual_layout.setContentsMargins(0, 4, 0, 0)
        manual_layout.setSpacing(6)

        sn_label = QLabel("序列号:")
        sn_label.setStyleSheet("font-weight: 400; color: rgba(38, 37, 30, 0.6); font-size: 13px;")
        manual_layout.addWidget(sn_label)

        self.apple_sn_input = QLineEdit()
        self.apple_sn_input.setPlaceholderText("输入设备序列号，多个请用英文逗号或空格分隔")
        self.apple_sn_input.setMinimumHeight(34)
        self.apple_sn_input.setMinimumWidth(250)
        manual_layout.addWidget(self.apple_sn_input)
        input_layout.addWidget(self.apple_manual_input_widget)

        self.apple_excel_input_widget = QWidget()
        excel_layout = QVBoxLayout(self.apple_excel_input_widget)
        excel_layout.setContentsMargins(0, 4, 0, 0)
        excel_layout.setSpacing(6)

        file_label = QLabel("Excel文件:")
        file_label.setStyleSheet("font-weight: 400; color: rgba(38, 37, 30, 0.6); font-size: 13px;")
        excel_layout.addWidget(file_label)

        file_select_layout = QHBoxLayout()
        file_select_layout.setSpacing(8)

        self.apple_excel_path_input = QLineEdit()
        self.apple_excel_path_input.setReadOnly(True)
        self.apple_excel_path_input.setMinimumHeight(34)
        self.apple_excel_path_input.setMinimumWidth(200)
        file_select_layout.addWidget(self.apple_excel_path_input, 1)

        self.apple_browse_button = QPushButton("浏览...")
        self.apple_browse_button.setFixedSize(80, 34)
        self.apple_browse_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        file_select_layout.addWidget(self.apple_browse_button, 0)
        excel_layout.addLayout(file_select_layout)

        column_label = QLabel("序列号列:")
        column_label.setStyleSheet("font-weight: 400; color: rgba(38, 37, 30, 0.6); font-size: 13px;")
        excel_layout.addWidget(column_label)

        self.apple_excel_column_input = QComboBox()
        self.apple_excel_column_input.setMinimumHeight(34)
        excel_layout.addWidget(self.apple_excel_column_input)

        input_layout.addWidget(self.apple_excel_input_widget)
        layout.addWidget(input_group)

        # 并发设置
        query_group = QGroupBox("查询设置")
        query_layout = QVBoxLayout(query_group)
        query_layout.setContentsMargins(16, 24, 16, 16)
        query_layout.setSpacing(12)

        concurrent_label = QLabel("并发查询数:")
        concurrent_label.setStyleSheet("font-weight: 400; color: rgba(38, 37, 30, 0.6); font-size: 13px;")
        query_layout.addWidget(concurrent_label)

        self.apple_concurrent_input = QComboBox()
        auto_count, auto_desc = get_auto_concurrent_count()
        self.apple_concurrent_input.addItems([
            auto_desc,
            "2 (推荐，稳定性最佳)",
            "4 (平衡性能和稳定性)",
            "8 (较高性能)",
            "16 (高性能)",
            "32 (最高性能，可能不稳定)"
        ])
        self.apple_concurrent_input.setCurrentIndex(0)
        self.apple_concurrent_input.setMinimumHeight(34)
        query_layout.addWidget(self.apple_concurrent_input)

        self.apple_concurrent_tip_label = QLabel(f"提示: 当前使用自动模式（{auto_count}个并发），根据CPU核数自动优化")
        self.apple_concurrent_tip_label.setStyleSheet("font-size: 10px; color: rgba(38, 37, 30, 0.4); font-style: italic;")
        self.apple_concurrent_tip_label.setWordWrap(True)
        query_layout.addWidget(self.apple_concurrent_tip_label)

        layout.addWidget(query_group)
        query_group.setVisible(False)

        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("QFrame { color: rgba(38, 37, 30, 0.08); background-color: rgba(38, 37, 30, 0.08); border: none; height: 1px; }")
        layout.addWidget(separator)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        self.apple_start_button = QPushButton("开始查询")
        self.apple_start_button.setMinimumHeight(42)
        self.apple_start_button.setStyleSheet("""
            QPushButton {
                background-color: #26251e; color: #f7f7f4; border: none;
                border-radius: 8px; padding: 10px 16px; font-weight: 400; font-size: 14px;
            }
            QPushButton:hover { background-color: #3d3c33; }
            QPushButton:pressed { background-color: #1a1914; }
            QPushButton:disabled { background-color: #e6e5e0; color: rgba(38, 37, 30, 0.35); }
        """)

        self.apple_stop_button = QPushButton("停止查询")
        self.apple_stop_button.setMinimumHeight(42)
        self.apple_stop_button.setEnabled(False)

        button_layout.addWidget(self.apple_start_button)
        button_layout.addWidget(self.apple_stop_button)
        layout.addLayout(button_layout)

        self.apple_browse_button.clicked.connect(self.apple_browse_excel_file)
        self.apple_start_button.clicked.connect(self.apple_start_query)
        self.apple_stop_button.clicked.connect(self.apple_stop_query)
        self.apple_manual_input_radio.toggled.connect(self.apple_toggle_input_method)
        self.apple_excel_input_radio.toggled.connect(self.apple_toggle_input_method)
        self.apple_concurrent_input.currentTextChanged.connect(self.apple_update_concurrent_tip)

        self.apple_toggle_input_method()
        layout.addStretch()

    def create_apple_results_panel(self):
        layout = QVBoxLayout(self.apple_results_panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        header_layout = QHBoxLayout()

        title_label = QLabel("Apple设备查询结果")
        title_label.setStyleSheet("font-size: 16px; font-weight: 400; color: #26251e; padding-bottom: 5px; letter-spacing: -0.11px;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        self.apple_retry_all_button = QPushButton("一键重试")
        self.apple_retry_all_button.setEnabled(False)
        self.apple_retry_all_button.setStyleSheet("""
            QPushButton {
                background-color: #ebeae5; color: #26251e; border: 1px solid rgba(38, 37, 30, 0.1);
                padding: 8px 16px; border-radius: 8px; font-weight: 400; font-size: 14px;
            }
            QPushButton:hover { color: #cf2d56; border-color: rgba(38, 37, 30, 0.2); }
            QPushButton:disabled { background-color: #e6e5e0; color: rgba(38, 37, 30, 0.35); }
        """)
        header_layout.addWidget(self.apple_retry_all_button)

        self.apple_export_button = QPushButton("导出结果")
        self.apple_export_button.setEnabled(False)
        header_layout.addWidget(self.apple_export_button)

        layout.addLayout(header_layout)

        table_container = QGroupBox()
        table_container.setStyleSheet("QGroupBox { border: 1px solid rgba(38, 37, 30, 0.1); border-radius: 8px; background-color: #f7f7f4; }")
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(5, 5, 5, 5)

        self.apple_results_table = CopyableTableWidget()
        self.apple_results_table.setColumnCount(13)
        self.apple_results_table.setHorizontalHeaderLabels([
            "序号", "序列号", "状态", "产品名称",
            "适用范围", "是否激活", "AC+", "激活时间", "查询时间", "查询耗时", "耗时(秒)", "代理状态", "操作"
        ])

        self.apple_results_table.setAlternatingRowColors(True)
        self.apple_results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.apple_results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        vertical_header = self.apple_results_table.verticalHeader()
        if vertical_header:
            vertical_header.hide()

        self.apple_results_table.setShowGrid(True)

        self.apple_results_table.setColumnWidth(0, 50)
        self.apple_results_table.setColumnWidth(1, 120)
        self.apple_results_table.setColumnWidth(2, 120)
        self.apple_results_table.setColumnWidth(3, 180)
        self.apple_results_table.setColumnWidth(4, 120)
        self.apple_results_table.setColumnWidth(5, 100)
        self.apple_results_table.setColumnWidth(6, 70)
        self.apple_results_table.setColumnWidth(7, 100)
        self.apple_results_table.setColumnWidth(8, 100)
        self.apple_results_table.setColumnWidth(9, 150)
        self.apple_results_table.setColumnWidth(10, 70)
        self.apple_results_table.setColumnWidth(11, 100)
        self.apple_results_table.setColumnWidth(12, 70)

        self.apple_results_table.setColumnHidden(4, True)
        self.apple_results_table.setColumnHidden(10, True)
        self.apple_results_table.setColumnHidden(11, True)
        self.apple_results_table.setColumnHidden(12, True)

        table_layout.addWidget(self.apple_results_table)
        layout.addWidget(table_container, 1)

        progress_container = QGroupBox("查询进度")
        progress_container.setStyleSheet("""
            QGroupBox {
                border: 1px solid rgba(38, 37, 30, 0.1); border-radius: 8px;
                margin-top: 12px; font-weight: 400; background-color: #ebeae5;
                color: rgba(38, 37, 30, 0.6);
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px;
                padding: 0 5px; background-color: #ebeae5;
                color: rgba(38, 37, 30, 0.6);
            }
        """)
        progress_layout = QVBoxLayout(progress_container)
        progress_layout.setContentsMargins(15, 20, 15, 15)

        self.apple_progress_bar = QProgressBar()
        self.apple_progress_bar.setMinimumHeight(25)
        self.apple_progress_bar.setTextVisible(True)
        self.apple_progress_bar.setFormat("%v/%m (%p%)")
        self.apple_progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress_layout.addWidget(self.apple_progress_bar)

        stats_layout = QHBoxLayout()
        stats_layout.addWidget(QLabel("总数: "))
        self.apple_total_count_label = QLabel("0")
        self.apple_total_count_label.setStyleSheet("font-weight: 400; color: #26251e;")
        stats_layout.addWidget(self.apple_total_count_label)

        stats_layout.addSpacing(20)
        stats_layout.addWidget(QLabel("成功: "))
        self.apple_success_count_label = QLabel("0")
        self.apple_success_count_label.setStyleSheet("font-weight: 400; color: #1f8a65;")
        stats_layout.addWidget(self.apple_success_count_label)

        stats_layout.addSpacing(20)
        stats_layout.addWidget(QLabel("失败: "))
        self.apple_failed_count_label = QLabel("0")
        self.apple_failed_count_label.setStyleSheet("font-weight: 400; color: #cf2d56;")
        stats_layout.addWidget(self.apple_failed_count_label)

        stats_layout.addStretch()
        progress_layout.addLayout(stats_layout)

        layout.addWidget(progress_container)

        self.apple_export_button.clicked.connect(self.apple_export_results)
        self.apple_retry_all_button.clicked.connect(self.apple_retry_all_failed)

    def apple_toggle_input_method(self):
        if self.apple_manual_input_radio.isChecked():
            self.apple_manual_input_widget.setEnabled(True)
            self.apple_excel_input_widget.setEnabled(False)
            self.apple_excel_column_input.setEnabled(False)
        else:
            self.apple_manual_input_widget.setEnabled(False)
            self.apple_excel_input_widget.setEnabled(True)
            self.apple_excel_column_input.setEnabled(True)

    def apple_browse_excel_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择Excel文件", "", "Excel Files (*.xlsx *.xls)"
        )
        if file_path:
            self.apple_excel_path_input.setText(file_path)
            self.apple_load_excel_columns(file_path)

    def apple_load_excel_columns(self, file_path):
        try:
            df = pd.read_excel(file_path, engine='openpyxl', header=0)
            self.apple_excel_column_input.clear()
            for column in df.columns:
                self.apple_excel_column_input.addItem(str(column))
            if not df.empty and len(df.columns) > 0:
                self.apple_excel_column_input.setCurrentIndex(0)
        except Exception as e:
            show_modern_warning(self, "Excel读取错误", f"无法读取Excel文件: {str(e)}")

    def apple_get_serial_numbers(self):
        if self.apple_manual_input_radio.isChecked():
            sn_text = self.apple_sn_input.text().strip()
            if not sn_text:
                show_modern_warning(self, "输入错误", "请输入至少一个Apple设备序列号")
                return []
            return [sn.strip() for sn in sn_text.replace(',', ' ').split() if sn.strip()]
        else:
            file_path = self.apple_excel_path_input.text()
            if not file_path:
                show_modern_warning(self, "输入错误", "请选择Excel文件")
                return []
            try:
                df = pd.read_excel(file_path, engine='openpyxl', header=0)
                column = self.apple_excel_column_input.currentText()
                if column not in df.columns:
                    show_modern_warning(self, "列错误", f"找不到列 '{column}'")
                    return []
                serial_numbers = df[column].astype(str).dropna().tolist()
                return [sn.strip() for sn in serial_numbers if sn.strip()]
            except Exception as e:
                show_modern_warning(self, "Excel读取错误", f"无法从Excel读取序列号: {str(e)}")
                return []

    def apple_update_concurrent_tip(self):
        concurrent_text = self.apple_concurrent_input.currentText()
        concurrent_num = parse_concurrent_count(concurrent_text)

        if concurrent_text.startswith("auto"):
            tip_text = f"提示: 当前使用自动模式（{concurrent_num}个并发），根据CPU核数自动优化"
        elif concurrent_num <= 2:
            tip_text = "提示: 当前使用低并发模式，查询速度较慢但稳定性最佳"
        elif concurrent_num <= 8:
            tip_text = "提示: 当前使用中等并发模式，平衡查询速度和稳定性"
        else:
            tip_text = "提示: 当前使用高并发模式，查询速度快但可能不稳定"

        self.apple_concurrent_tip_label.setText(tip_text)

    def apple_start_query(self):
        self.apple_start_button.setEnabled(False)
        self.apple_start_button.setText("准备中...")
        self.status_bar.showMessage("正在准备查询...")
        QApplication.processEvents()

        self.apple_serial_numbers = self.apple_get_serial_numbers()
        if not self.apple_serial_numbers:
            self.apple_start_button.setEnabled(True)
            self.apple_start_button.setText("开始查询")
            self.status_bar.showMessage("就绪")
            return

        username = self.user_info.get('loginName') if self.user_info else None
        is_super_admin = self.user_info.get('is_super_admin', False) if self.user_info else False
        required_count = len(self.apple_serial_numbers)

        if username and hasattr(self, 'query_count_manager') and not is_super_admin:
            remaining_count = self.query_count_manager.get_remaining_count(username)

            if remaining_count < required_count:
                self.apple_start_button.setEnabled(True)
                self.apple_start_button.setText("开始查询")
                self.status_bar.showMessage("就绪")
                message = (f"查询次数不足！\n\n"
                          f"本次查询需要：{required_count} 次\n"
                          f"您的剩余次数：{remaining_count} 次\n\n"
                          f"请减少查询的设备数量或等待次日重置。")
                show_modern_warning(self, "查询次数不足", message, 420, 300)
                return

            if not self.query_count_manager.consume_count(username, required_count):
                self.apple_start_button.setEnabled(True)
                self.apple_start_button.setText("开始查询")
                self.status_bar.showMessage("就绪")
                show_modern_warning(self, "查询次数不足", "查询次数消耗失败，请稍后重试！")
                return

            self.update_query_count_display()

        self.apple_start_button.setText("查询中...")
        self.apple_stop_button.setEnabled(True)

        self.apple_results_table.setRowCount(0)
        self.apple_results_table.setRowCount(len(self.apple_serial_numbers))
        self.apple_progress_bar.setMaximum(len(self.apple_serial_numbers))
        self.apple_progress_bar.setValue(0)

        self.apple_total_count_label.setText(str(len(self.apple_serial_numbers)))
        self.apple_success_count_label.setText("0")
        self.apple_failed_count_label.setText("0")
        self.apple_success_count = 0
        self.apple_failed_count = 0

        for i, sn in enumerate(self.apple_serial_numbers):
            index_item = QTableWidgetItem(str(i+1))
            index_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.apple_results_table.setItem(i, 0, index_item)

            sn_item = QTableWidgetItem(sn)
            sn_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.apple_results_table.setItem(i, 1, sn_item)

            status_item = QTableWidgetItem("等待查询")
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setForeground(QColor("rgba(38, 37, 30, 0.35)"))
            self.apple_results_table.setItem(i, 2, status_item)

        concurrent_text = self.apple_concurrent_input.currentText()
        concurrent_queries = parse_concurrent_count(concurrent_text)

        self.apple_query_worker = AppleWarrantyQueryWorker(self.apple_serial_numbers, APPLE_USE_PROXY, APPLE_PROXY_KEY, APPLE_PROXY_PROVIDER)
        self.apple_query_worker.max_concurrent_queries = concurrent_queries

        self.apple_query_worker.progress_updated.connect(self.apple_update_progress)
        self.apple_query_worker.query_completed.connect(self.apple_update_result)
        self.apple_query_worker.all_completed.connect(self.apple_queries_completed)
        self.apple_query_worker.start()

        self.status_bar.showMessage(f"正在查询 {len(self.apple_serial_numbers)} 个Apple设备序列号...")

    def apple_stop_query(self):
        if self.apple_query_worker and self.apple_query_worker.isRunning():
            self.apple_query_worker.stop()
            self.status_bar.showMessage("正在停止Apple设备查询...")
            self.apple_start_button.setEnabled(True)
            self.apple_start_button.setText("开始查询")
            self.apple_stop_button.setEnabled(False)
            self.apple_query_worker = None

    def apple_update_progress(self, row_index, status):
        if row_index < self.apple_results_table.rowCount():
            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if status == "正在查询...":
                status_item.setForeground(QColor("rgba(38, 37, 30, 0.4)"))
            elif status == "查询完成":
                status_item.setForeground(QColor("#1f8a65"))
            elif status == "查询失败":
                status_item.setForeground(QColor("#cf2d56"))
            else:
                status_item.setForeground(QColor("rgba(38, 37, 30, 0.4)"))
            self.apple_results_table.setItem(row_index, 2, status_item)

    def apple_update_result(self, row_index, result_data):
        if row_index >= self.apple_results_table.rowCount():
            return

        current_progress = self.apple_progress_bar.value()
        self.apple_progress_bar.setValue(current_progress + 1)

        serial_number = result_data.get('serial_number', '')
        status = result_data.get('status', '未知')
        data = result_data.get('data', {})
        duration = result_data.get('duration_seconds', 0.0)

        failed_statuses = [
            "查询失败", "序列号错误", "网络错误", "验证码识别失败", "表单提交失败",
            "设备序列号无效", "请求异常", "验证码错误", "网络异常", "查询超时"
        ]
        is_success = data and status not in failed_statuses

        if is_success:
            self.apple_success_count += 1
            self.apple_success_count_label.setText(str(self.apple_success_count))

            status_item = QTableWidgetItem("成功")
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setForeground(QColor("#1f8a65"))
            self.apple_results_table.setItem(row_index, 2, status_item)

            if data.get("产品信息"):
                product_info = data["产品信息"]

                for col, key, default in [
                    (3, "产品名称", "未知"),
                    (4, "适用范围", "中国"),
                    (5, "是否激活", "否"),
                    (6, "AC+", "否"),
                    (7, "激活时间", "未知"),
                    (8, "查询时间", "未知"),  # 原来的到期时间现在是查询时间
                ]:
                    item = QTableWidgetItem(product_info.get(key, default))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.apple_results_table.setItem(row_index, col, item)
            else:
                device_name = data.get('device_title', '未知设备')
                for col, val in [
                    (3, device_name), (4, "中国"),
                    (5, "否"), (6, "否"), (7, "未知"), (8, "未知")
                ]:
                    item = QTableWidgetItem(val)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.apple_results_table.setItem(row_index, col, item)
        else:
            self.apple_failed_count += 1
            self.apple_failed_count_label.setText(str(self.apple_failed_count))

            display_status = status if status in failed_statuses else "失败"
            status_item = QTableWidgetItem(display_status)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setForeground(QColor("#cf2d56"))
            self.apple_results_table.setItem(row_index, 2, status_item)

            for col in range(3, 8):
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.apple_results_table.setItem(row_index, col, item)

        # 原来的查询时间现在是查询耗时（显示查询时长）
        duration_item = QTableWidgetItem(f"{duration:.1f}秒")
        duration_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.apple_results_table.setItem(row_index, 9, duration_item)

        proxy_status = result_data.get("proxy_used", "未启用")
        if not proxy_status or proxy_status == "None":
            proxy_status = "未启用"
        proxy_item = QTableWidgetItem(proxy_status)
        proxy_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.apple_results_table.setItem(row_index, 10, proxy_item)

        if is_success:
            action_button = QPushButton("已完成")
            action_button.setStyleSheet("""
                QPushButton {
                    font-size: 12px; padding: 2px 8px;
                    background-color: #ebeae5; color: rgba(38, 37, 30, 0.35);
                    border: 1px solid rgba(38, 37, 30, 0.05); border-radius: 8px;
                }
            """)
            action_button.setEnabled(False)
            self.apple_results_table.setCellWidget(row_index, 11, action_button)
        else:
            retry_button = QPushButton("重试")
            retry_button.setStyleSheet("""
                QPushButton {
                    font-size: 12px; padding: 2px 8px;
                    background-color: #ebeae5; color: #cf2d56;
                    border: 1px solid rgba(207, 45, 86, 0.2); border-radius: 8px;
                }
                QPushButton:hover { background-color: rgba(207, 45, 86, 0.06); }
            """)
            retry_button.clicked.connect(lambda: self.apple_retry_single(row_index))
            self.apple_results_table.setCellWidget(row_index, 11, retry_button)

        if not hasattr(self, 'apple_results'):
            self.apple_results = []
        while len(self.apple_results) <= row_index:
            self.apple_results.append(None)
        self.apple_results[row_index] = result_data

    def _update_retry_button_style(self, has_failures):
        """根据是否存在失败项来更新一键重试按钮的样式"""
        if has_failures:
            self.apple_retry_all_button.setStyleSheet("""
                QPushButton {
                    background-color: rgba(207, 45, 86, 0.1); color: #cf2d56;
                    border: 1px solid rgba(207, 45, 86, 0.3);
                    padding: 8px 16px; border-radius: 8px; font-weight: 400; font-size: 14px;
                }
                QPushButton:hover { background-color: rgba(207, 45, 86, 0.18); border-color: rgba(207, 45, 86, 0.45); }
                QPushButton:pressed { background-color: rgba(207, 45, 86, 0.25); }
                QPushButton:disabled { background-color: #e6e5e0; color: rgba(38, 37, 30, 0.35); border-color: rgba(38, 37, 30, 0.05); }
            """)
        else:
            self.apple_retry_all_button.setStyleSheet("""
                QPushButton {
                    background-color: #ebeae5; color: #26251e; border: 1px solid rgba(38, 37, 30, 0.1);
                    padding: 8px 16px; border-radius: 8px; font-weight: 400; font-size: 14px;
                }
                QPushButton:hover { color: #cf2d56; border-color: rgba(38, 37, 30, 0.2); }
                QPushButton:disabled { background-color: #e6e5e0; color: rgba(38, 37, 30, 0.35); border-color: rgba(38, 37, 30, 0.05); }
            """)

    def apple_update_retry_button_status(self):
        if not hasattr(self, 'apple_results') or not self.apple_results:
            self.apple_retry_all_button.setEnabled(False)
            self._update_retry_button_style(False)
            return

        failed_statuses = [
            "查询失败", "序列号错误", "网络错误", "验证码识别失败", "表单提交失败",
            "设备序列号无效", "请求异常", "验证码错误", "网络异常", "查询超时"
        ]

        current_failed_count = 0
        for result in self.apple_results:
            if result:
                status = result.get('status', '未知')
                data = result.get('data', {})
                is_success = data and status not in failed_statuses
                if not is_success:
                    current_failed_count += 1

        self.apple_failed_count = current_failed_count
        self.apple_failed_count_label.setText(str(current_failed_count))

        total_count = len([r for r in self.apple_results if r is not None])
        success_count = total_count - current_failed_count
        self.apple_success_count = success_count
        self.apple_success_count_label.setText(str(success_count))

        self.apple_retry_all_button.setEnabled(current_failed_count > 0)
        self._update_retry_button_style(current_failed_count > 0)

    def apple_queries_completed(self):
        self.apple_start_button.setEnabled(True)
        self.apple_start_button.setText("开始查询")
        self.apple_stop_button.setEnabled(False)
        self.apple_export_button.setEnabled(True)

        if self.apple_failed_count > 0:
            self.apple_retry_all_button.setEnabled(True)
            self._update_retry_button_style(True)

        self.apple_query_worker = None

        success_count = self.apple_success_count
        failed_count = self.apple_failed_count
        total_count = len(self.apple_serial_numbers)

        self.status_bar.showMessage(
            f"Apple设备查询完成 - 成功: {success_count}, 失败: {failed_count}, 总计: {total_count}"
        )

        message = (f"Apple设备查询已完成！\n\n"
                  f"查询总数：{total_count}\n"
                  f"成功：{success_count}\n"
                  f"失败：{failed_count}\n\n"
                  f"您可以导出结果或重试失败的查询。")
        show_modern_info(self, "查询完成", message, 420, 320)

    def apple_retry_single(self, row_index):
        if row_index >= len(self.apple_serial_numbers):
            return

        if hasattr(self, 'apple_single_retry_worker') and self.apple_single_retry_worker and self.apple_single_retry_worker.isRunning():
            return

        serial_number = self.apple_serial_numbers[row_index]

        status_item = QTableWidgetItem("正在重试...")
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        status_item.setForeground(QColor("rgba(38, 37, 30, 0.4)"))
        self.apple_results_table.setItem(row_index, 2, status_item)

        retry_button = self.apple_results_table.cellWidget(row_index, 12)
        if retry_button:
            retry_button.setEnabled(False)

        self.apple_single_retry_worker = AppleWarrantyQueryWorker([serial_number], APPLE_USE_PROXY, APPLE_PROXY_KEY, APPLE_PROXY_PROVIDER)
        self.apple_single_retry_worker.query_completed.connect(
            lambda _, result: self.apple_handle_single_retry_result(row_index, result)
        )
        self.apple_single_retry_worker.all_completed.connect(
            lambda: self.apple_single_retry_completed(row_index)
        )
        self.apple_single_retry_worker.start()

    def apple_handle_single_retry_result(self, original_row_index, result_data):
        self.apple_update_result(original_row_index, result_data)

        status = result_data.get('status', '未知')
        data = result_data.get('data', {})
        failed_statuses = [
            "查询失败", "序列号错误", "网络错误", "验证码识别失败", "表单提交失败",
            "设备序列号无效", "请求异常", "验证码错误", "网络异常", "查询超时"
        ]
        is_success = data and status not in failed_statuses

        if not is_success:
            retry_button = self.apple_results_table.cellWidget(original_row_index, 12)
            if retry_button:
                retry_button.setEnabled(True)

        self.apple_update_retry_button_status()

    def apple_single_retry_completed(self, row_index):
        if hasattr(self, 'apple_single_retry_worker'):
            self.apple_single_retry_worker = None

    def apple_retry_all_failed(self):
        if not hasattr(self, 'apple_results') or not self.apple_results:
            show_modern_warning(self, "重试错误", "没有找到失败的查询结果")
            return

        # 检查是否有正在运行的查询任务
        running_workers = []
        if hasattr(self, 'apple_query_worker') and self.apple_query_worker and self.apple_query_worker.isRunning():
            running_workers.append("主查询")
        if hasattr(self, 'apple_retry_worker') and self.apple_retry_worker and self.apple_retry_worker.isRunning():
            running_workers.append("批量重试")
        if hasattr(self, 'apple_single_retry_worker') and self.apple_single_retry_worker and self.apple_single_retry_worker.isRunning():
            running_workers.append("单条重试")
        if running_workers:
            show_modern_warning(self, "重试错误", f"当前有正在运行的任务（{', '.join(running_workers)}），请等待完成后再试。")
            return

        failed_indices = []
        failed_serial_numbers = []
        failed_statuses = [
            "查询失败", "序列号错误", "网络错误", "验证码识别失败", "表单提交失败",
            "设备序列号无效", "请求异常", "验证码错误", "网络异常", "查询超时"
        ]

        for i, result in enumerate(self.apple_results):
            if result:
                status = result.get('status', '未知')
                data = result.get('data', {})
                is_success = data and status not in failed_statuses
                if not is_success:
                    failed_indices.append(i)
                    failed_serial_numbers.append(self.apple_serial_numbers[i])

        if not failed_serial_numbers:
            show_modern_info(self, "重试提示", "没有失败的查询需要重试")
            return

        reply = show_modern_question(
            self, "确认重试",
            f"确定要重试 {len(failed_serial_numbers)} 个失败的Apple设备查询吗？"
        )
        if reply != QDialog.DialogCode.Accepted:
            return

        self.apple_retry_all_button.setEnabled(False)
        self._update_retry_button_style(False)

        # 禁用所有行的重试按钮，防止批量重试期间触发单条重试
        for row in range(self.apple_results_table.rowCount()):
            btn = self.apple_results_table.cellWidget(row, 12)
            if btn and btn.isEnabled():
                btn.setEnabled(False)

        for idx in failed_indices:
            status_item = QTableWidgetItem("等待重试...")
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setForeground(QColor("rgba(38, 37, 30, 0.4)"))
            self.apple_results_table.setItem(idx, 2, status_item)

        concurrent_text = self.apple_concurrent_input.currentText()
        concurrent_queries = parse_concurrent_count(concurrent_text)

        self.apple_retry_row_mapping = {i: failed_indices[i] for i in range(len(failed_indices))}

        self.apple_retry_worker = AppleWarrantyQueryWorker(failed_serial_numbers, APPLE_USE_PROXY, APPLE_PROXY_KEY, APPLE_PROXY_PROVIDER)
        self.apple_retry_worker.max_concurrent_queries = concurrent_queries

        self.apple_retry_worker.progress_updated.connect(self.apple_retry_update_progress)
        self.apple_retry_worker.query_completed.connect(
            lambda idx, result: self.apple_handle_batch_retry_result(failed_indices[idx], result)
        )
        self.apple_retry_worker.all_completed.connect(self.apple_batch_retry_completed)
        self.apple_retry_worker.start()

    def apple_retry_update_progress(self, worker_row_index, status):
        if hasattr(self, 'apple_retry_row_mapping') and worker_row_index in self.apple_retry_row_mapping:
            actual_row_index = self.apple_retry_row_mapping[worker_row_index]
            if 0 <= actual_row_index < self.apple_results_table.rowCount():
                status_item = QTableWidgetItem(status)
                status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                status_item.setForeground(QColor("rgba(38, 37, 30, 0.4)"))
                self.apple_results_table.setItem(actual_row_index, 2, status_item)

    def apple_handle_batch_retry_result(self, original_row_index, result_data):
        self.apple_update_result(original_row_index, result_data)

    def apple_batch_retry_completed(self):
        self.apple_update_retry_button_status()
        self.apple_retry_worker = None
        if hasattr(self, 'apple_retry_row_mapping'):
            delattr(self, 'apple_retry_row_mapping')
        show_modern_info(self, "重试完成", "Apple设备批量重试已完成！")

    def apple_export_results(self):
        if self.apple_results_table.rowCount() == 0:
            show_modern_info(self, "导出提示", "没有可导出的结果")
            return

        default_filename = f"apple_query_results_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出结果", default_filename, "Excel Files (*.xlsx)"
        )
        if not file_path:
            return

        try:
            excluded_columns = {10, 11, 12}
            data = []
            for row in range(self.apple_results_table.rowCount()):
                row_data = {}
                for col in range(self.apple_results_table.columnCount()):
                    if col in excluded_columns:
                        continue
                    header_item = self.apple_results_table.horizontalHeaderItem(col)
                    header = header_item.text() if header_item else f"列{col}"
                    item = self.apple_results_table.item(row, col)
                    row_data[header] = item.text() if item else ""
                data.append(row_data)

            df = pd.DataFrame(data)
            df.to_excel(file_path, index=False)
            show_modern_info(self, "导出成功", "结果已成功导出")
        except Exception as e:
            show_modern_warning(self, "导出错误", f"导出结果时出错: {str(e)}")

    def closeEvent(self, a0):
        if a0 is None:
            return

        has_running_tasks = bool(
            (hasattr(self, 'apple_query_worker') and self.apple_query_worker and self.apple_query_worker.isRunning()) or
            (hasattr(self, 'apple_retry_worker') and self.apple_retry_worker and self.apple_retry_worker.isRunning()) or
            (hasattr(self, 'apple_single_retry_worker') and self.apple_single_retry_worker and self.apple_single_retry_worker.isRunning())
        )

        exit_dialog = AnimatedExitDialog(self, has_running_tasks)
        exit_dialog.move(
            self.x() + (self.width() - exit_dialog.width()) // 2,
            self.y() + (self.height() - exit_dialog.height()) // 2
        )

        result = exit_dialog.exec()

        if result == QDialog.DialogCode.Accepted:
            if hasattr(self, 'apple_query_worker') and self.apple_query_worker and self.apple_query_worker.isRunning():
                self.apple_query_worker.stop()
            if hasattr(self, 'apple_retry_worker') and self.apple_retry_worker and self.apple_retry_worker.isRunning():
                self.apple_retry_worker.stop()
            if hasattr(self, 'apple_single_retry_worker') and self.apple_single_retry_worker and self.apple_single_retry_worker.isRunning():
                self.apple_single_retry_worker.stop()
            a0.accept()
        else:
            a0.ignore()


def resource_path(relative_path):
    """获取资源文件的绝对路径，支持 PyInstaller 和 Nuitka"""
    # 检查是否为 Nuitka 打包 (onefile 模式)
    if getattr(sys, 'nuitka_onefile', False):
        # Nuitka onefile 模式
        base_path = os.path.dirname(sys.executable)
    elif getattr(sys, 'nuitka', False):
        # Nuitka 打包但非 onefile
        base_path = os.path.dirname(sys.executable)
    elif getattr(sys, '_MEIPASS', None):
        # PyInstaller
        base_path = getattr(sys, '_MEIPASS')
    elif getattr(sys, 'frozen', False):
        # 其他打包方式
        base_path = os.path.dirname(sys.executable)
    else:
        # 开发模式
        base_path = os.path.abspath(".")

    # 对于 Nuitka onefile，也需要检查临时解压目录
    # Nuitka 会将资源解压到临时目录
    nuitka_temp = os.environ.get('NUITKA_ONEFILE_TEMP_DIR')
    if nuitka_temp and os.path.exists(os.path.join(nuitka_temp, relative_path)):
        return os.path.join(nuitka_temp, relative_path)

    full_path = os.path.join(base_path, relative_path)

    # 如果文件不存在，尝试查找其他可能的位置
    if not os.path.exists(full_path):
        # 尝试在 exe 同级目录查找
        exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else base_path
        alt_path = os.path.join(exe_dir, relative_path)
        if os.path.exists(alt_path):
            return alt_path

        # 尝试在工作目录查找
        cwd_path = os.path.join(os.getcwd(), relative_path)
        if os.path.exists(cwd_path):
            return cwd_path

    return full_path


class DeviceRegistrationManager:
    def __init__(self):
        self.config_file = self._get_secure_config_path()
        self.device_data = {}
        self.load_data()

    def _get_secure_config_path(self):
        try:
            appdata_local = os.path.expandvars(r'%LOCALAPPDATA%')
            app_dir = os.path.join(appdata_local, 'Microsoft', 'Windows', 'HonorApp')
            os.makedirs(app_dir, exist_ok=True)
            return os.path.join(app_dir, 'device_registry.dat')
        except Exception:
            return "device_registry.json"

    def _encode_data(self, data):
        try:
            import base64
            json_str = json.dumps(data, ensure_ascii=False)
            return base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
        except Exception as e:
            return json.dumps(data, ensure_ascii=False)

    def _decode_data(self, encoded_data):
        try:
            import base64
            decoded_bytes = base64.b64decode(encoded_data.encode('utf-8'))
            return json.loads(decoded_bytes.decode('utf-8'))
        except Exception:
            try:
                return json.loads(encoded_data)
            except:
                return {}

    def load_data(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    file_content = f.read().strip()
                self.device_data = self._decode_data(file_content) if file_content else {}
            else:
                self.device_data = {}
        except Exception as e:
            self.device_data = {}

    def save_data(self):
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            if os.path.exists(self.config_file) and os.name == 'nt':
                try:
                    import subprocess
                    # 安全地设置 creationflags
                    kwargs = {}
                    if hasattr(subprocess, 'CREATE_NO_WINDOW'):
                        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
                    subprocess.run(['attrib', '-H', self.config_file], capture_output=True, check=False, **kwargs)
                except Exception:
                    pass

            encoded_data = self._encode_data(self.device_data)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                f.write(encoded_data)

            if os.name == 'nt':
                try:
                    import subprocess
                    # 安全地设置 creationflags
                    kwargs = {}
                    if hasattr(subprocess, 'CREATE_NO_WINDOW'):
                        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
                    subprocess.run(['attrib', '+H', self.config_file], capture_output=True, check=False, **kwargs)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"保存设备数据失败: {e}")

    def is_device_registered(self, mac_id):
        return mac_id in self.device_data

    def get_registered_username(self, mac_id):
        if mac_id in self.device_data:
            return self.device_data[mac_id].get('username', '未知')
        return None

    def register_device(self, mac_id, username):
        import time
        self.device_data[mac_id] = {
            'username': username,
            'register_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'register_timestamp': time.time()
        }
        self.save_data()


class QueryCountManager:
    def __init__(self):
        self.config_file = self._get_secure_config_path()
        self.user_data = {}
        self.load_data()

        try:
            from pytz import timezone
            self.china_tz = timezone('Asia/Shanghai')
        except ImportError:
            self.china_tz = None

    def _get_current_china_time(self):
        from datetime import datetime
        if self.china_tz:
            return datetime.now(self.china_tz)
        return datetime.now()

    def _get_current_date_str(self):
        return self._get_current_china_time().strftime('%Y-%m-%d')

    def _get_current_datetime_str(self):
        return self._get_current_china_time().strftime('%Y-%m-%d %H:%M:%S')

    def _get_secure_config_path(self):
        try:
            appdata_local = os.path.expandvars(r'%LOCALAPPDATA%')
            app_dir = os.path.join(appdata_local, 'Microsoft', 'Windows', 'HonorApp')
            os.makedirs(app_dir, exist_ok=True)
            return os.path.join(app_dir, 'app_config.dat')
        except Exception:
            return "query_count.json"

    def _encode_data(self, data):
        try:
            import base64
            json_str = json.dumps(data, ensure_ascii=False)
            return base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
        except Exception as e:
            return json.dumps(data, ensure_ascii=False)

    def _decode_data(self, encoded_data):
        try:
            import base64
            decoded_bytes = base64.b64decode(encoded_data.encode('utf-8'))
            return json.loads(decoded_bytes.decode('utf-8'))
        except Exception:
            try:
                return json.loads(encoded_data)
            except:
                return {}

    def load_data(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    file_content = f.read().strip()
                self.user_data = self._decode_data(file_content) if file_content else {}
            else:
                self.user_data = {}
            self._migrate_old_config()
        except Exception as e:
            self.user_data = {}

    def _migrate_old_config(self):
        old_config_file = "query_count.json"
        try:
            if os.path.exists(old_config_file) and not self.user_data:
                with open(old_config_file, 'r', encoding='utf-8') as f:
                    old_data = json.load(f)
                if old_data:
                    self.user_data = old_data
                    self.save_data()
                    try:
                        os.remove(old_config_file)
                    except Exception:
                        pass
        except Exception:
            pass

    def save_data(self):
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            if os.path.exists(self.config_file) and os.name == 'nt':
                try:
                    import subprocess
                    subprocess.run(['attrib', '-H', self.config_file], capture_output=True, check=False)
                except Exception:
                    pass

            encoded_data = self._encode_data(self.user_data)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                f.write(encoded_data)

            if os.name == 'nt':
                try:
                    import subprocess
                    subprocess.run(['attrib', '+H', self.config_file], capture_output=True, check=False)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"保存数据失败: {e}")

    def check_and_reset_daily_count(self, username, type_value):
        if username == SUPER_ADMIN_USERNAME:
            return 999999

        current_date = self._get_current_date_str()

        if username in self.user_data:
            user_info = self.user_data[username]
            last_reset_date = user_info.get('last_reset_date', '')

            if last_reset_date != current_date:
                total_count = type_value * 10
                self.user_data[username].update({
                    'type_value': type_value,
                    'total_count': total_count,
                    'remaining_count': total_count,
                    'last_reset_date': current_date,
                    'last_reset_time': self._get_current_datetime_str()
                })
                self.save_data()
                return total_count
            else:
                return user_info.get('total_count', type_value * 10)
        else:
            total_count = type_value * 10
            self.user_data[username] = {
                'type_value': type_value,
                'total_count': total_count,
                'remaining_count': total_count,
                'last_reset_date': current_date,
                'last_reset_time': self._get_current_datetime_str(),
                'created_time': self._get_current_datetime_str()
            }
            self.save_data()
            return total_count

    def handle_paid_user_login(self, username, new_type_value):
        if username == SUPER_ADMIN_USERNAME:
            return 999999

        current_date = self._get_current_date_str()

        if username in self.user_data:
            user_info = self.user_data[username]
            old_type_value = user_info.get('type_value', 1)

            if new_type_value != old_type_value:
                current_remaining = user_info.get('remaining_count', 0)

                if new_type_value > old_type_value:
                    new_total_count = new_type_value * 10
                    old_total_count = old_type_value * 10
                    remaining_count = (new_total_count - old_total_count) + current_remaining
                else:
                    new_total_count = new_type_value * 10
                    remaining_count = new_total_count

                self.user_data[username].update({
                    'type_value': new_type_value,
                    'total_count': new_total_count,
                    'remaining_count': remaining_count,
                    'last_reset_date': current_date,
                    'last_reset_time': self._get_current_datetime_str(),
                    'type_change_time': self._get_current_datetime_str(),
                    'old_type_value': old_type_value,
                    'preserved_remaining': current_remaining if new_type_value > old_type_value else 0
                })
                self.save_data()
                return new_total_count
            else:
                return self.check_and_reset_daily_count(username, new_type_value)
        else:
            return self.check_and_reset_daily_count(username, new_type_value)

    def init_user_count(self, username, type_value):
        return self.check_and_reset_daily_count(username, type_value)

    def get_remaining_count(self, username):
        if username == SUPER_ADMIN_USERNAME:
            return 999999

        if username not in self.user_data:
            return 0

        user_info = self.user_data[username]
        current_date = self._get_current_date_str()
        last_reset_date = user_info.get('last_reset_date', '')

        if last_reset_date != current_date:
            type_value = user_info.get('type_value', 1)
            self.check_and_reset_daily_count(username, type_value)
            user_info = self.user_data[username]

        return user_info.get('remaining_count', 0)

    def consume_count(self, username, count=1):
        if username == SUPER_ADMIN_USERNAME:
            return True

        if username not in self.user_data:
            return False

        remaining = self.get_remaining_count(username)
        if remaining < count:
            return False

        self.user_data[username]['remaining_count'] = remaining - count
        self.save_data()
        return True

    def can_query(self, username):
        if username == SUPER_ADMIN_USERNAME:
            return True
        return self.get_remaining_count(username) > 0


def get_unique_id():
    """
    生成一个在同一台电脑上稳定不变的唯一ID。
    策略：
    1. 首先尝试从缓存文件读取ID
    2. 如果没有缓存，则收集多个硬件信息生成新ID并缓存
    3. 使用多种硬件信息组合，即使部分信息变化仍能保持稳定
    """
    import hashlib

    # 定义缓存文件路径
    cache_dir = os.path.join(os.path.expanduser("~"), ".apple_warranty")
    cache_file = os.path.join(cache_dir, "machine_id")

    # 尝试从缓存读取
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                cached_id = f.read().strip()
                if cached_id:
                    return cached_id
        except Exception as e:
            logger.warning(f"[唯一ID] 读取缓存文件失败: {e}")

    # 如果没有缓存，生成新ID
    hardware_info = []

    # 1. 获取MAC地址（多个网卡）
    try:
        mac_addresses = set()
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == psutil.AF_LINK and addr.address:
                    mac = addr.address.upper()
                    if mac != '00:00:00:00:00:00' and not mac.startswith('00:50:56'):  # 过滤VMware等虚拟网卡
                        mac_addresses.add(mac)
        if mac_addresses:
            hardware_info.append("|".join(sorted(mac_addresses)))
    except Exception as e:
        logger.warning(f"[唯一ID] 获取MAC地址失败: {e}")

    # 2. 获取CPU信息
    try:
        cpu_info = []
        cpu_info.append(f"cores:{psutil.cpu_count(logical=True)}")
        cpu_info.append(f"freq:{psutil.cpu_freq().max if psutil.cpu_freq() else 0}")
        # 尝试获取更具体的CPU标识
        if sys.platform == "win32":
            try:
                # 安全地设置 creationflags
                kwargs = {}
                if hasattr(subprocess, 'CREATE_NO_WINDOW'):
                    kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

                result = subprocess.check_output(
                    ["wmic", "cpu", "get", "ProcessorId"],
                    text=True,
                    **kwargs
                )
                processor_id = result.split('\n')[1].strip()
                if processor_id:
                    cpu_info.append(f"pid:{processor_id}")
            except Exception as e:
                logger.warning(f"[唯一ID] wmic cpu 失败: {e}")
                pass
        hardware_info.append("CPU:" + "|".join(cpu_info))
    except Exception as e:
        logger.warning(f"[唯一ID] 获取CPU信息失败: {e}")

    # 3. 获取内存信息
    try:
        mem_total = psutil.virtual_memory().total
        hardware_info.append(f"MEM:{mem_total}")
    except Exception as e:
        logger.warning(f"[唯一ID] 获取内存信息失败: {e}")

    # 4. 获取磁盘信息（使用序列号）
    try:
        disk_info = []
        if sys.platform == "win32":
            try:
                # 安全地设置 creationflags
                kwargs = {}
                if hasattr(subprocess, 'CREATE_NO_WINDOW'):
                    kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

                result = subprocess.check_output(
                    ["wmic", "diskdrive", "get", "SerialNumber"],
                    text=True,
                    **kwargs
                )
                lines = [line.strip() for line in result.split('\n') if line.strip()]
                if len(lines) > 1:
                    disk_info.extend(lines[1:])
            except Exception as e:
                logger.warning(f"[唯一ID] wmic diskdrive 失败: {e}")
                pass
        elif sys.platform == "darwin":  # macOS
            try:
                result = subprocess.check_output(
                    ["system_profiler", "SPSerialATADataType"],
                    text=True
                )
                if "Serial Number" in result:
                    disk_info.append("mac_disk")
            except:
                pass
        elif sys.platform.startswith("linux"):  # Linux
            try:
                if os.path.exists("/sys/block/sda/device/vendor"):
                    vendor = open("/sys/block/sda/device/vendor").read().strip()
                    model = open("/sys/block/sda/device/model").read().strip()
                    disk_info.append(f"{vendor}_{model}")
            except:
                pass
        if disk_info:
            hardware_info.append("DISK:" + "|".join(disk_info))
    except Exception as e:
        logger.warning(f"[唯一ID] 获取磁盘信息失败: {e}")

    # 5. 获取主板信息（如果可能）
    try:
        if sys.platform == "win32":
            try:
                # 安全地设置 creationflags
                kwargs = {}
                if hasattr(subprocess, 'CREATE_NO_WINDOW'):
                    kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

                result = subprocess.check_output(
                    ["wmic", "baseboard", "get", "SerialNumber"],
                    text=True,
                    **kwargs
                )
                lines = [line.strip() for line in result.split('\n') if line.strip()]
                if len(lines) > 1 and lines[1] and lines[1] != "To be filled by O.E.M.":
                    hardware_info.append(f"BOARD:{lines[1]}")
            except Exception as e:
                logger.warning(f"[唯一ID] wmic baseboard 失败: {e}")
                pass
    except Exception as e:
        logger.warning(f"[唯一ID] 获取主板信息失败: {e}")

    # 6. 备用方案：使用uuid.getnode()和机器名
    if not hardware_info:
        hardware_info.append(f"NODE:{uuid.getnode()}")
        # 安全地获取主机名
        try:
            hostname = os.uname().nodename
        except (AttributeError, Exception):
            # Windows 上 os.uname 可能不存在，使用 platform.node()
            import platform
            hostname = platform.node()
        hardware_info.append(f"HOST:{hostname}")

    # 生成哈希ID
    combined_info = "||".join(hardware_info).encode('utf-8')
    machine_id = hashlib.sha256(combined_info).hexdigest()[:32]

    # 尝试缓存ID
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, 'w') as f:
            f.write(machine_id)
        logger.info(f"[唯一ID] 已缓存机器ID: {machine_id[:16]}...")
    except Exception as e:
        logger.warning(f"[唯一ID] 缓存机器ID失败: {e}")

    return machine_id


def global_exception_handler(exc_type, exc_value, exc_traceback):
    """全局异常处理函数"""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    logger.critical("发生未捕获的异常:\n%s", error_msg)

    try:
        from PyQt6.QtWidgets import QMessageBox
        error_box = QMessageBox()
        error_box.setIcon(QMessageBox.Icon.Critical)
        error_box.setWindowTitle("程序错误")
        error_box.setText("程序发生了严重错误，即将退出。")
        error_box.setInformativeText(str(exc_value))
        error_box.setDetailedText(error_msg)
        error_box.exec()
    except:
        pass

    sys.__excepthook__(exc_type, exc_value, exc_traceback)


def main():
    try:
        app = QApplication(sys.argv)

        sys.excepthook = global_exception_handler

        check_passed, error_message = check_environment()

        if not check_passed:
            error_dialog = EnvironmentErrorDialog()
            error_dialog.exec()
            logger.info("[环境检测] 程序因环境检测失败而退出")
            sys.exit(1)

        window = AppleWarrantyApp()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        logger.critical("程序启动失败: %s", str(e))
        traceback.print_exc()
        try:
            from PyQt6.QtWidgets import QMessageBox
            error_box = QMessageBox()
            error_box.setIcon(QMessageBox.Icon.Critical)
            error_box.setWindowTitle("启动失败")
            error_box.setText("程序启动失败！")
            error_box.setInformativeText(str(e))
            error_box.setDetailedText(traceback.format_exc())
            error_box.exec()
        except:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()