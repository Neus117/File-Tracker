import sys
import os
import sqlite3
import time
import subprocess
import warnings
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton, QListWidget, QVBoxLayout, QWidget, QComboBox, \
    QFileDialog, QHBoxLayout, QSizePolicy, QMessageBox, QMenu, QAction, QDialog, QLabel, QWhatsThis, QDialogButtonBox
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QIcon, QFont

# 忽略 DeprecationWarning 警告
warnings.filterwarnings("ignore", category=DeprecationWarning)

# 打包准备
def resource_path(relative_path):
    """获取资源文件的路径，解决打包后的路径问题"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# 获取用户主目录
def get_db_path():
    """获取数据库文件的路径"""
    return os.path.join(os.path.expanduser("~"), "file_access.db")

# 数据库初始化
db_path = get_db_path()  # 使用用户主目录中的数据库路径
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS paths (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE,
    access_count INTEGER DEFAULT 1,
    last_access_time REAL
)
''')
conn.commit()

class CustomFileDialog(QFileDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setOption(QFileDialog.DontUseNativeDialog, True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)  # 移除 "?" 按钮
        self.setFileMode(QFileDialog.Directory)
        self.setOption(QFileDialog.ShowDirsOnly, False)

        # 创建一个新的按钮来选择当前文件夹
        self.selectFolderBtn = QPushButton("选择当前文件夹", self)
        self.selectFolderBtn.clicked.connect(self.selectCurrentFolder)

        # 获取对话框的布局
        layout = self.layout()

        # 找到并移除 "Choose" 按钮
        buttonBox = self.findChild(QDialogButtonBox)
        if buttonBox:
            chooseButton = buttonBox.button(QDialogButtonBox.Open)
            if chooseButton:
                buttonBox.removeButton(chooseButton)

        # 创建一个新的水平布局来容纳新的按钮
        btnLayout = QHBoxLayout()
        btnLayout.addWidget(self.selectFolderBtn)

        # 将新的布局添加到主布局中
        layout.addLayout(btnLayout, layout.rowCount(), 0, 1, layout.columnCount())

    def selectCurrentFolder(self):
        self.done(QFileDialog.Accepted)

# PyQt主窗口类
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # 设置窗口标题和图标
        self.setWindowTitle("快速访问")
        self.setWindowIcon(QIcon(resource_path("images/shell32_star.ico")))  # 打包准备
        self.setGeometry(100, 100, 900, 500)

        # 创建主布局
        self.central_widget = QWidget()
        self.layout = QVBoxLayout(self.central_widget)
        self.setCentralWidget(self.central_widget)

        # 文件夹列表
        self.folder_list = QListWidget(self)
        font = QFont("微软雅黑", 11)  # 稍微放大字体
        self.folder_list.setFont(font)
        self.layout.addWidget(self.folder_list)
        self.folder_list.itemDoubleClicked.connect(self.open_selected_folder)
        self.folder_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folder_list.customContextMenuRequested.connect(self.show_context_menu)

        # 排序选项
        self.sort_option = QComboBox(self)
        self.sort_option.addItems(["频次", "时间"])
        self.sort_option.currentIndexChanged.connect(self.update_folder_list)
        self.sort_option.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.sort_option.setFixedHeight(30)  # 设置固定高度，使其与其他按钮一致
        self.sort_option.setFont(QFont("微软雅黑", 10))  # 设置字体大小

        # 添加“打开”按钮
        self.open_button = QPushButton("打开", self)
        self.open_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.open_button.setFixedHeight(32)  # 设置固定高度
        self.open_button.setFont(QFont("微软雅黑", 10))  # 设置字体大小
        self.open_button.clicked.connect(self.browse_and_record_folder)

        # 添加“清空”按钮
        self.clear_button = QPushButton("清空", self)
        self.clear_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.clear_button.setStyleSheet("color: red;")  # 设置为红色字体
        self.clear_button.setFixedHeight(32)  # 设置固定高度
        self.clear_button.setFont(QFont("微软雅黑", 10))  # 设置字体大小
        self.clear_button.clicked.connect(self.clear_all_records)

        # 置顶开关按钮
        self.top_button = QPushButton(self)
        self.top_button.setIcon(QIcon(resource_path("images/pin_grey.png")))  # 打包准备
        self.top_button.setFixedHeight(32)  # 设置固定高度
        self.top_button.clicked.connect(self.toggle_topmost)

        # 底部布局
        self.bottom_layout = QHBoxLayout()
        self.bottom_layout.addWidget(self.clear_button)  # 清空按钮
        self.bottom_layout.addStretch()
        self.bottom_layout.addWidget(self.open_button)  # 打开按钮
        self.bottom_layout.addStretch()
        self.bottom_layout.addWidget(self.sort_option)  # 排序选择框
        self.bottom_layout.addWidget(self.top_button)  # 置顶开关
        self.layout.addLayout(self.bottom_layout)

        # 初次加载文件夹列表
        self.is_first_time = True  # 标记程序是否第一次运行
        self.update_folder_list()

    def toggle_topmost(self):
        # 切换窗口的置顶状态
        if self.windowFlags() & Qt.WindowStaysOnTopHint:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
            self.top_button.setIcon(QIcon(resource_path("images/pin_grey.png")))  # 置顶关，打包准备
        else:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.top_button.setIcon(QIcon(resource_path("images/pin_red.png")))  # 置顶开，打包准备
        self.show()  # 刷新窗口，应用置顶状态

    def browse_and_record_folder(self):
        file_dialog = CustomFileDialog(self)
        file_dialog.setWindowTitle("选择文件夹或文件")
        
        if file_dialog.exec_() == QFileDialog.Accepted:
            selected = file_dialog.selectedFiles()[0]
            if os.path.isfile(selected):
                folder_selected = os.path.dirname(selected)
            else:
                folder_selected = selected
            folder_selected = os.path.normpath(folder_selected)  # 规范化路径
            self.record_accessed_path(folder_selected)
            self.update_folder_list()
            subprocess.Popen(f'explorer "{folder_selected}"')  # 打开资源管理器

    def record_accessed_path(self, folder_path):
        if folder_path:
            current_time = time.time()
            cursor.execute("SELECT * FROM paths WHERE path=?", (folder_path,))
            result = cursor.fetchone()

            if result:
                cursor.execute("UPDATE paths SET access_count=access_count+1, last_access_time=? WHERE path=?",
                               (current_time, folder_path))
            else:
                cursor.execute("INSERT INTO paths (path, access_count, last_access_time) VALUES (?, 1, ?)",
                               (folder_path, current_time))
            conn.commit()

    def update_folder_list(self):
        # 清空文件夹列表
        self.folder_list.clear()

        # 根据排序选项更新列表
        sort_by = self.sort_option.currentText()
        if sort_by == "频次":
            cursor.execute("SELECT path FROM paths ORDER BY access_count DESC")
        else:
            cursor.execute("SELECT path FROM paths ORDER BY last_access_time DESC")

        folders = cursor.fetchall()
        if folders:
            for folder in folders:
                self.folder_list.addItem(folder[0])
        else:
            if not self.is_first_time:  # 仅在点击清空时显示提示
                pass  # 移除 show_cleared_message 的调用
            self.is_first_time = False  # 重置首次标记

    def open_selected_folder(self, item):
        folder_path = item.text()
        if folder_path:
            folder_path = os.path.normpath(folder_path)  # 规范化路径
            # 检查路径是否存在
            if os.path.exists(folder_path):
                subprocess.Popen(f'explorer "{folder_path}"')
                self.record_accessed_path(folder_path)
                self.update_folder_list()
            else:
                self.delete_selected_path(item)  # 如果路径不存在，删除记录并弹窗提醒
                # 创建自定义 QDialog 对象
                dialog = QDialog(self)
                dialog.setWindowTitle("路径失效")
                dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)  # 移除 "?" 按钮
                # 设置对话框布局
                layout = QVBoxLayout(dialog)
                # 添加文本标签
                label = QLabel(f"该路径已失效并被删除: {folder_path}\n", dialog)
                layout.addWidget(label)
                # 创建水平布局，用于居中按钮
                button_layout = QHBoxLayout()
                # 创建 OK 按钮
                ok_button = QPushButton("OK", dialog)
                ok_button.setFixedWidth(100)  # 设置按钮宽度
                ok_button.clicked.connect(dialog.accept)  # 连接 OK 按钮点击事件
                # 将按钮添加到布局，并设置居中
                button_layout.addStretch()
                button_layout.addWidget(ok_button)
                button_layout.addStretch()
                # 将按钮布局添加到对话框主布局
                layout.addLayout(button_layout)
                # 显示对话框
                dialog.exec_()

    def show_context_menu(self, pos: QPoint):
        # 获取右键点击的项目
        item = self.folder_list.itemAt(pos)

        if item:
            try:
                menu = QMenu(self)

                # 添加“复制”选项
                copy_action = QAction("复制", self)
                menu.addAction(copy_action)

                # 添加一个空白项作为间隔
                spacer_action = QAction("", self)
                spacer_action.setDisabled(True)  # 禁用间隔项
                menu.addAction(spacer_action)

                # 添加“删除”选项
                delete_action = QAction("删除", self)
                menu.addAction(delete_action)

                # 执行菜单，并获取用户选择的操作
                action = menu.exec_(self.folder_list.mapToGlobal(pos))

                if action == copy_action:
                    clipboard = QApplication.clipboard()
                    clipboard.setText(item.text())  # 复制路径到剪贴板
                elif action == delete_action:
                    self.delete_selected_path(item)

            except Exception as e:
                print(f"Error occurred in show_context_menu: {e}")

    def delete_selected_path(self, item):
        # 删除数据库中的记录
        folder_path = item.text()
        cursor.execute("DELETE FROM paths WHERE path=?", (folder_path,))
        conn.commit()
        self.update_folder_list()

    def show_cleared_message(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("提示")
        msg_box.setText(" 已清空")  # 替换为“已清空”
        msg_box.setIcon(QMessageBox.NoIcon)  # 去除默认的蓝色叹号图标
        msg_box.setStyleSheet("QMessageBox QPushButton {min-width: 100px;}")  # 使OK按钮居中
        msg_box.exec_()

    def clear_all_records(self):
        # 清空数据库中的所有记录
        cursor.execute("DELETE FROM paths")
        conn.commit()
        self.is_first_time = False  # 标记不是首次启动
        self.update_folder_list()
        self.show_cleared_message()  # 显示清空提示


# 创建应用程序对象
app = QApplication(sys.argv)

# 创建主窗口
window = MainWindow()

# 显示窗口
window.show()

# 运行应用程序事件循环
sys.exit(app.exec_())
