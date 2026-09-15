from __future__ import annotations

import argparse
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from backup_core import (
    SlotInfo,
    backup_to_slot,
    config_path,
    default_backup_root,
    default_zomboid_saves_root,
    discover_save_directories,
    format_size,
    list_slot_infos,
    load_json,
    restore_from_slot,
    running_game_processes,
    save_json,
    validate_save_directory,
)
from game_integration import (
    CommandPump,
    CommandWatcher,
    GameCommand,
    acquire_single_instance,
    bring_tk_window_to_front,
    launch_project_zomboid,
    release_single_instance,
    resolve_reported_save_directory,
    write_companion_command,
    write_companion_status,
)


APP_VERSION = "1.1.8"
APP_TITLE = f"僵尸毁灭工程存档管理器 {APP_VERSION}"
DEFAULT_CONFIG = {
    "source_path": "",
    "backup_root": str(default_backup_root()),
    "interval_minutes": 10,
    "auto_enabled": True,
    "manual_slots": 5,
    "window_geometry": "980x700",
}


class IntegrationOptions:
    def __init__(self, *, launch_game: bool = False, minimized: bool = False, exit_with_game: bool = False) -> None:
        self.launch_game = launch_game
        self.minimized = minimized
        self.exit_with_game = exit_with_game


class SavePicker(tk.Toplevel):
    def __init__(self, parent: tk.Misc, saves: list[Path]) -> None:
        super().__init__(parent)
        self.title("选择游戏存档")
        self.geometry("760x360")
        self.minsize(560, 280)
        self.transient(parent)
        self.grab_set()
        self.result: str | None = None
        self.saves = saves

        container = ttk.Frame(self, padding=14)
        container.pack(fill="both", expand=True)
        ttk.Label(
            container,
            text="发现了多个世界存档。请选择需要自动备份的一个：",
        ).pack(anchor="w", pady=(0, 8))

        list_frame = ttk.Frame(container)
        list_frame.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(list_frame, activestyle="dotbox", font=("Microsoft YaHei UI", 10))
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        for path in saves:
            self.listbox.insert("end", str(path))
        if saves:
            self.listbox.selection_set(0)
            self.listbox.activate(0)

        buttons = ttk.Frame(container)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="使用此存档", command=self._accept).pack(side="right", padx=(0, 8))
        self.listbox.bind("<Double-Button-1>", lambda _event: self._accept())
        self.bind("<Return>", lambda _event: self._accept())
        self.bind("<Escape>", lambda _event: self.destroy())

    def _accept(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        self.result = str(self.saves[selection[0]])
        self.destroy()


class ZomboidSaveManagerApp:
    def __init__(self, root: tk.Tk, integration: IntegrationOptions | None = None) -> None:
        self.root = root
        self.integration = integration or IntegrationOptions()
        self.root.title(APP_TITLE)
        self.root.minsize(880, 620)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        self.next_auto_at: float | None = None
        self.current_operation = ""
        self.command_watcher = CommandWatcher()
        self.command_pump = CommandPump(
            lambda command: self.events.put(("game_command", command)),
            self.command_watcher,
            on_error=lambda exc: self.events.put(("command_watch_error", exc)),
        )
        self.game_running = False
        self.game_seen = False
        self.launch_started_at: float | None = None
        self.last_process_check = 0.0
        self.exit_backup_due: float | None = None
        self.exit_backup_pending = False

        self.config_file = config_path()
        loaded = load_json(self.config_file, DEFAULT_CONFIG)
        self.config = DEFAULT_CONFIG.copy()
        self.config.update(loaded)
        try:
            self.root.geometry(str(self.config.get("window_geometry") or "980x700"))
        except tk.TclError:
            self.root.geometry("980x700")

        self.source_var = tk.StringVar(value=str(self.config.get("source_path", "")))
        self.backup_root_var = tk.StringVar(value=str(self.config.get("backup_root", default_backup_root())))
        self.interval_var = tk.StringVar(value=str(self.config.get("interval_minutes", 10)))
        self.manual_slots_var = tk.StringVar(value=str(self.config.get("manual_slots", 5)))
        self.auto_enabled_var = tk.BooleanVar(value=bool(self.config.get("auto_enabled", True)))
        self.status_var = tk.StringVar(value="就绪")
        self.countdown_var = tk.StringVar(value="自动备份尚未启动")
        self.progress_var = tk.DoubleVar(value=0.0)

        self._configure_style()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll_events)
        self.root.after(500, self._scheduler_tick)
        self.root.after(250, self._integration_tick)
        self.command_pump.start()
        self._write_companion_status("running", f"pid={os.getpid()}")

        if not self.source_var.get().strip():
            if self.integration.launch_game:
                self._log("等待游戏 Mod 报告当前世界存档")
            else:
                self.root.after(250, self._first_run_discovery)
        else:
            valid, reason = validate_save_directory(self.source_var.get())
            if valid:
                self._log(f"已选择游戏存档：{self.source_var.get()}")
                self._reset_auto_schedule()
            else:
                self._log(f"当前存档路径不可用：{reason}")
        self._refresh_slots()
        if self.integration.minimized:
            self.root.withdraw()
        if self.integration.launch_game:
            self.root.after(450, self._launch_game)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 17, "bold"))
        style.configure("Hint.TLabel", foreground="#59636e")
        style.configure("Status.TLabel", padding=(8, 5))
        style.configure("Treeview", rowheight=29, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text=APP_TITLE, style="Title.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="Mod：F8 唤出窗口，F9 立即备份",
            style="Hint.TLabel",
        ).pack(side="right", anchor="s", pady=(8, 2))

        settings = ttk.LabelFrame(outer, text=" 存档与备份设置 ", padding=10)
        settings.pack(fill="x")
        settings.columnconfigure(1, weight=1)

        ttk.Label(settings, text="游戏存档：").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.source_entry = ttk.Entry(settings, textvariable=self.source_var)
        self.source_entry.grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Button(settings, text="浏览…", command=self._browse_source).grid(row=0, column=2, padx=(8, 0), pady=4)
        ttk.Button(settings, text="自动查找", command=self._discover_saves).grid(row=0, column=3, padx=(8, 0), pady=4)

        ttk.Label(settings, text="备份位置：").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.backup_entry = ttk.Entry(settings, textvariable=self.backup_root_var)
        self.backup_entry.grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(settings, text="浏览…", command=self._browse_backup_root).grid(row=1, column=2, padx=(8, 0), pady=4)
        ttk.Button(settings, text="打开位置", command=self._open_backup_root).grid(row=1, column=3, padx=(8, 0), pady=4)

        options = ttk.Frame(settings)
        options.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 2))
        self.auto_check = ttk.Checkbutton(
            options,
            text="启用定时自动备份",
            variable=self.auto_enabled_var,
            command=self._settings_changed,
        )
        self.auto_check.pack(side="left")
        ttk.Label(options, text="间隔（分钟）：").pack(side="left", padx=(18, 5))
        self.interval_spin = ttk.Spinbox(options, from_=1, to=1440, width=7, textvariable=self.interval_var)
        self.interval_spin.pack(side="left")
        ttk.Label(options, text="手动槽位数：").pack(side="left", padx=(18, 5))
        self.slot_spin = ttk.Spinbox(options, from_=1, to=20, width=6, textvariable=self.manual_slots_var)
        self.slot_spin.pack(side="left")
        ttk.Button(options, text="保存并应用设置", command=self._apply_settings).pack(side="right")

        auto_bar = ttk.Frame(outer)
        auto_bar.pack(fill="x", pady=(10, 8))
        ttk.Label(auto_bar, textvariable=self.countdown_var).pack(side="left")
        self.auto_now_button = ttk.Button(auto_bar, text="立即备份到自动槽", command=lambda: self._start_backup("auto"))
        self.auto_now_button.pack(side="right")
        ttk.Button(auto_bar, text="隐藏到后台", command=self.root.withdraw).pack(side="right", padx=(0, 8))

        slots_frame = ttk.LabelFrame(outer, text=" 存档槽位 ", padding=8)
        slots_frame.pack(fill="both", expand=True)
        slots_frame.rowconfigure(0, weight=1)
        slots_frame.columnconfigure(0, weight=1)
        columns = ("slot", "time", "size", "files", "source")
        self.tree = ttk.Treeview(slots_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("slot", text="槽位")
        self.tree.heading("time", text="备份时间")
        self.tree.heading("size", text="大小")
        self.tree.heading("files", text="文件数")
        self.tree.heading("source", text="原存档")
        self.tree.column("slot", width=130, minwidth=110, stretch=False)
        self.tree.column("time", width=155, minwidth=145, stretch=False)
        self.tree.column("size", width=85, minwidth=75, anchor="e", stretch=False)
        self.tree.column("files", width=70, minwidth=60, anchor="e", stretch=False)
        self.tree.column("source", width=380, minwidth=200)
        tree_scroll = ttk.Scrollbar(slots_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_button_states())

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(9, 8))
        self.backup_button = ttk.Button(actions, text="备份到所选槽位", command=self._backup_selected)
        self.backup_button.pack(side="left")
        self.restore_button = ttk.Button(actions, text="加载所选槽位", command=self._restore_selected)
        self.restore_button.pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="刷新槽位", command=self._refresh_slots).pack(side="left", padx=(8, 0))
        ttk.Label(
            actions,
            text="加载会先生成“恢复前保险槽”，并要求游戏已退出",
            style="Hint.TLabel",
        ).pack(side="right")

        progress_frame = ttk.Frame(outer)
        progress_frame.pack(fill="x")
        self.progress = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress.pack(side="left", fill="x", expand=True)
        ttk.Label(progress_frame, textvariable=self.status_var, style="Status.TLabel", width=32).pack(side="right")

        log_frame = ttk.LabelFrame(outer, text=" 运行记录 ", padding=6)
        log_frame.pack(fill="x", pady=(8, 0))
        self.log_text = tk.Text(
            log_frame,
            height=6,
            wrap="word",
            state="disabled",
            font=("Microsoft YaHei UI", 9),
            background="#fafafa",
            relief="flat",
        )
        self.log_text.pack(fill="both", expand=True)
        self._update_button_states()

    def _manual_slot_count(self) -> int:
        try:
            return min(20, max(1, int(self.manual_slots_var.get())))
        except ValueError:
            return 5

    def _interval_minutes(self) -> int:
        try:
            return min(1440, max(1, int(self.interval_var.get())))
        except ValueError:
            return 10

    def _first_run_discovery(self) -> None:
        saves = discover_save_directories(default_zomboid_saves_root())
        if len(saves) == 1:
            self.source_var.set(str(saves[0]))
            self._log(f"自动发现游戏存档：{saves[0]}")
            self._apply_settings(show_message=False)
        elif len(saves) > 1:
            self._choose_discovered_save(saves)
        else:
            self._log("尚未选择具体世界存档；请点击“自动查找”或“浏览”")

    def _discover_saves(self) -> None:
        root = default_zomboid_saves_root()
        saves = discover_save_directories(root)
        if not saves:
            custom = filedialog.askdirectory(title="未在默认位置找到存档，请选择 Zomboid\\Saves 文件夹")
            if custom:
                saves = discover_save_directories(custom)
        if not saves:
            messagebox.showinfo(APP_TITLE, "没有找到具体的世界存档目录。\n请直接浏览到类似 Builder\\08-11-2024_10-37-57 的目录。")
            return
        self._choose_discovered_save(saves)

    def _choose_discovered_save(self, saves: list[Path]) -> None:
        if len(saves) == 1:
            self.source_var.set(str(saves[0]))
            self._apply_settings(show_message=False)
            return
        picker = SavePicker(self.root, saves)
        self.root.wait_window(picker)
        if picker.result:
            self.source_var.set(picker.result)
            self._apply_settings(show_message=False)

    def _browse_source(self) -> None:
        initial = self.source_var.get().strip() or str(default_zomboid_saves_root())
        chosen = filedialog.askdirectory(title="选择具体的世界存档目录", initialdir=initial)
        if chosen:
            self.source_var.set(chosen)

    def _browse_backup_root(self) -> None:
        initial = self.backup_root_var.get().strip() or str(default_backup_root())
        chosen = filedialog.askdirectory(title="选择备份保存位置", initialdir=initial, mustexist=False)
        if chosen:
            self.backup_root_var.set(chosen)

    def _open_backup_root(self) -> None:
        value = self.backup_root_var.get().strip()
        if not value:
            return
        path = Path(value).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"无法打开备份位置：{exc}")

    def _launch_game(self) -> None:
        try:
            launch_project_zomboid()
            self.launch_started_at = time.monotonic()
            self._log("已通过 Steam 启动《僵尸毁灭工程》")
        except OSError as exc:
            bring_tk_window_to_front(self.root)
            self.integration.exit_with_game = False
            self._log(f"游戏启动失败：{exc}")
            messagebox.showerror(APP_TITLE, f"无法通过 Steam 启动游戏：\n{exc}")

    def _select_reported_save(self, command: GameCommand) -> None:
        active = resolve_reported_save_directory(command.game_mode, command.save_folder)
        if active is None:
            if command.game_mode or command.save_folder:
                self._log(f"Mod 报告了世界 {command.game_mode}/{command.save_folder}，但暂时未找到对应目录")
            return
        current = self.source_var.get().strip()
        if current and os.path.normcase(os.path.normpath(current)) == os.path.normcase(os.path.normpath(str(active))):
            return
        self.source_var.set(str(active))
        self.config["source_path"] = str(active)
        try:
            save_json(self.config_file, self.config)
        except OSError as exc:
            self._log(f"无法保存 Mod 报告的存档路径：{exc}")
        self._log(f"已自动切换到当前世界存档：{active}")
        self._reset_auto_schedule()
        self._refresh_slots()

    def _handle_game_command(self, command: GameCommand) -> None:
        self._write_companion_status("received", f"{command.action}:{command.token}")
        self._select_reported_save(command)
        if command.action == "HELLO":
            self._log("游戏内 Mod 已连接")
        elif command.action == "SHOW":
            bring_tk_window_to_front(self.root)
            self._log("已响应游戏内 F8/图标唤出")
        elif command.action == "BACKUP_AUTO":
            if self.busy:
                self._log("F9 快速备份请求已收到，但当前另一个操作尚未完成")
            else:
                self._start_backup("auto", reason="mod_quick")

    def _integration_tick(self) -> None:
        try:
            now = time.monotonic()
            if now - self.last_process_check >= 1.0:
                self.last_process_check = now
                running = bool(running_game_processes())
                if running:
                    if not self.game_running:
                        self._log("检测到游戏进程，伴生模式已接管")
                    self.game_seen = True
                    self.exit_backup_due = None
                elif self.game_running and self.integration.exit_with_game:
                    # Leave a short grace period: launchers and branch updates can
                    # briefly replace the process without meaning the play session ended.
                    self.exit_backup_due = now + 4.0
                    self._log("检测到游戏退出，准备生成退出快照")
                self.game_running = running

                if self.launch_started_at and not self.game_seen and now - self.launch_started_at > 180:
                    self.launch_started_at = None
                    self.integration.exit_with_game = False
                    bring_tk_window_to_front(self.root)
                    self._log("等待游戏启动超时；伴生程序将继续运行")
                    messagebox.showwarning(
                        APP_TITLE,
                        "等待游戏启动超过 3 分钟。\n程序将保留运行，但不会自动随游戏关闭。",
                    )

            if self.exit_backup_due is not None and now >= self.exit_backup_due and not self.game_running:
                self.exit_backup_due = None
                self._begin_exit_backup()
        except BaseException as exc:
            self._log(f"游戏进程检测异常，指令监听仍将继续：{exc}")
            self._write_companion_status("process_watch_error", str(exc))
        finally:
            try:
                self.root.after(250, self._integration_tick)
            except tk.TclError:
                pass

    def _begin_exit_backup(self) -> None:
        if self.busy:
            self.exit_backup_pending = True
            self._log("当前操作完成后将追加一次退出快照")
            return
        valid, reason = validate_save_directory(self.source_var.get().strip())
        if not valid:
            saves = discover_save_directories(default_zomboid_saves_root())
            if saves:
                self.source_var.set(str(saves[0]))
                self.config["source_path"] = str(saves[0])
                try:
                    save_json(self.config_file, self.config)
                except OSError:
                    pass
                self._log(f"Mod 未能定位当前世界，退出时回退到最近存档：{saves[0]}")
            else:
                self._log(f"无法生成退出快照：{reason}；伴生程序已关闭")
                self.root.destroy()
                return
        self.exit_backup_pending = False
        self._start_backup("auto", reason="game_exit")

    def _settings_changed(self) -> None:
        if self.auto_enabled_var.get():
            self._reset_auto_schedule()
        else:
            self.next_auto_at = None
            self.countdown_var.set("定时自动备份已关闭")

    def _apply_settings(self, *, show_message: bool = True) -> bool:
        source = self.source_var.get().strip()
        backup_root = self.backup_root_var.get().strip()
        valid, reason = validate_save_directory(source) if source else (False, "尚未选择游戏存档")
        if not valid:
            if show_message:
                messagebox.showerror(APP_TITLE, reason)
            return False
        if not backup_root:
            if show_message:
                messagebox.showerror(APP_TITLE, "请选择备份保存位置")
            return False
        try:
            source_path = Path(source).expanduser().resolve()
            backup_path = Path(backup_root).expanduser().resolve()
            backup_path.relative_to(source_path)
        except ValueError:
            pass
        else:
            if show_message:
                messagebox.showerror(APP_TITLE, "备份保存位置不能位于游戏存档目录内部")
            return False

        self.interval_var.set(str(self._interval_minutes()))
        self.manual_slots_var.set(str(self._manual_slot_count()))
        self.config.update(
            {
                "source_path": source,
                "backup_root": backup_root,
                "interval_minutes": self._interval_minutes(),
                "auto_enabled": self.auto_enabled_var.get(),
                "manual_slots": self._manual_slot_count(),
            }
        )
        try:
            save_json(self.config_file, self.config)
        except OSError as exc:
            if show_message:
                messagebox.showerror(APP_TITLE, f"无法保存设置：{exc}")
            return False
        self._reset_auto_schedule()
        self._refresh_slots()
        self._log("设置已保存")
        if show_message:
            self.status_var.set("设置已保存")
        return True

    def _reset_auto_schedule(self) -> None:
        if self.auto_enabled_var.get():
            self.next_auto_at = time.monotonic() + self._interval_minutes() * 60
        else:
            self.next_auto_at = None

    def _scheduler_tick(self) -> None:
        if self.next_auto_at is None:
            if self.auto_enabled_var.get():
                self.countdown_var.set("等待游戏载入或选择世界存档")
            else:
                self.countdown_var.set("定时自动备份已关闭")
        else:
            remaining = max(0, int(self.next_auto_at - time.monotonic()))
            minutes, seconds = divmod(remaining, 60)
            self.countdown_var.set(f"距离下次自动备份：{minutes:02d}:{seconds:02d}")
            if remaining <= 0 and not self.busy:
                self._start_backup("auto", reason="auto_timer")
        self.root.after(1000, self._scheduler_tick)

    def _refresh_slots(self) -> None:
        previous = self._selected_slot_id()
        for item in self.tree.get_children():
            self.tree.delete(item)
        try:
            infos = list_slot_infos(self.backup_root_var.get().strip(), self._manual_slot_count())
        except (OSError, ValueError):
            infos = []
        for info in infos:
            if info.exists:
                timestamp = info.created_at.replace("T", " ")[:19]
                source = info.source_path
                size = format_size(info.total_size)
                count = str(info.file_count)
            else:
                timestamp = "—"
                source = "空"
                size = "—"
                count = "—"
            self.tree.insert(
                "",
                "end",
                iid=info.slot_id,
                values=(info.display_name, timestamp, size, count, source),
            )
        if previous and self.tree.exists(previous):
            self.tree.selection_set(previous)
        elif self.tree.exists("auto"):
            self.tree.selection_set("auto")
        self._update_button_states()

    def _selected_slot_id(self) -> str | None:
        selected = self.tree.selection()
        return selected[0] if selected else None

    def _selected_slot_info(self) -> SlotInfo | None:
        slot_id = self._selected_slot_id()
        if not slot_id:
            return None
        try:
            return next(
                info
                for info in list_slot_infos(self.backup_root_var.get().strip(), self._manual_slot_count())
                if info.slot_id == slot_id
            )
        except (StopIteration, OSError, ValueError):
            return None

    def _update_button_states(self) -> None:
        slot_id = self._selected_slot_id()
        info = self._selected_slot_info() if slot_id else None
        normal = not self.busy
        self.backup_button.configure(state="normal" if normal and slot_id != "recovery" else "disabled")
        self.restore_button.configure(state="normal" if normal and info and info.exists else "disabled")
        self.auto_now_button.configure(state="normal" if normal else "disabled")

    def _set_busy(self, busy: bool, operation: str = "") -> None:
        self.busy = busy
        self.current_operation = operation
        state = "disabled" if busy else "normal"
        for widget in (self.source_entry, self.backup_entry, self.interval_spin, self.slot_spin, self.auto_check):
            widget.configure(state=state)
        self._update_button_states()

    def _backup_selected(self) -> None:
        slot_id = self._selected_slot_id()
        if slot_id:
            self._start_backup(slot_id)

    def _start_backup(self, slot_id: str, *, reason: str = "manual") -> None:
        if self.busy:
            return
        background = reason != "manual"
        if not self._apply_settings(show_message=not background):
            if background:
                self._log("自动备份跳过：游戏存档路径或备份位置无效")
                self._reset_auto_schedule()
            return
        if slot_id == "recovery":
            return
        if not background and slot_id.startswith("manual_"):
            info = self._selected_slot_info()
            if info and info.exists:
                if not messagebox.askyesno(APP_TITLE, f"“{info.display_name}”已有备份，是否覆盖？"):
                    return

        display_name = "自动存档" if slot_id == "auto" else f"手动槽位 {slot_id.split('_')[1]}"
        self._set_busy(True, f"正在备份到{display_name}")
        self.status_var.set(self.current_operation)
        self.progress_var.set(0)
        self._log(f"开始备份到{display_name}")
        self.next_auto_at = None

        source = self.source_var.get().strip()
        backup_root = self.backup_root_var.get().strip()

        def worker() -> None:
            last_update = 0.0

            def progress(done: int, total: int, relative: str) -> None:
                nonlocal last_update
                now = time.monotonic()
                if done == total or now - last_update >= 0.12:
                    last_update = now
                    self.events.put(("progress", (done, total, relative)))

            try:
                info = backup_to_slot(
                    source,
                    backup_root,
                    slot_id,
                    display_name=display_name,
                    progress=progress,
                )
                self.events.put(("backup_done", (info, reason)))
            except BaseException as exc:
                self.events.put(("operation_error", ("备份失败", str(exc), reason)))

        threading.Thread(target=worker, name="zomboid-backup", daemon=True).start()

    def _restore_selected(self) -> None:
        if self.busy:
            return
        info = self._selected_slot_info()
        if not info or not info.exists:
            messagebox.showinfo(APP_TITLE, "所选槽位为空")
            return
        processes = running_game_processes()
        if processes:
            messagebox.showerror(
                APP_TITLE,
                "检测到《僵尸毁灭工程》仍在运行：\n"
                + "、".join(processes)
                + "\n\n请先完全退出游戏，再加载存档。",
            )
            return
        source = self.source_var.get().strip()
        valid, reason = validate_save_directory(source)
        if not valid:
            messagebox.showerror(APP_TITLE, reason)
            return
        mismatch = ""
        if info.source_path and os.path.normcase(os.path.normpath(info.source_path)) != os.path.normcase(os.path.normpath(source)):
            mismatch = "\n\n注意：该槽位来自另一个存档路径，请确认没有选错世界。"
        if info.slot_id == "recovery":
            safety_note = "为保留这份保险备份，本次加载不会先改写保险槽。"
        else:
            safety_note = "覆盖前会把当前存档备份到“恢复前保险槽”。"
        prompt = (
            f"确定加载“{info.display_name}”吗？\n\n"
            f"它将覆盖：\n{source}\n\n"
            + safety_note
            + mismatch
        )
        if not messagebox.askyesno(APP_TITLE, prompt, icon="warning"):
            return

        self._set_busy(True, f"正在加载{info.display_name}")
        self.status_var.set("正在生成保险备份并加载槽位")
        self.progress_var.set(0)
        self._log(f"开始加载{info.display_name}")
        self.next_auto_at = None
        backup_root = self.backup_root_var.get().strip()
        slot_id = info.slot_id

        def worker() -> None:
            last_update = 0.0

            def progress(done: int, total: int, relative: str) -> None:
                nonlocal last_update
                now = time.monotonic()
                if done == total or now - last_update >= 0.12:
                    last_update = now
                    self.events.put(("progress", (done, total, relative)))

            try:
                restored, recovery = restore_from_slot(
                    source,
                    backup_root,
                    slot_id,
                    progress=progress,
                    create_recovery=True,
                )
                self.events.put(("restore_done", (restored, recovery)))
            except BaseException as exc:
                self.events.put(("operation_error", ("加载失败", str(exc), "restore")))

        threading.Thread(target=worker, name="zomboid-restore", daemon=True).start()

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "game_command":
                    self._handle_game_command(payload)  # type: ignore[arg-type]
                elif event == "command_watch_error":
                    self._log(f"Mod 指令监听异常，正在继续重试：{payload}")
                    self._write_companion_status("command_watch_error", str(payload))
                elif event == "progress":
                    done, total, relative = payload  # type: ignore[misc]
                    percent = min(100.0, (done / max(total, 1)) * 100)
                    self.progress_var.set(percent)
                    short = str(relative)
                    if len(short) > 42:
                        short = "…" + short[-41:]
                    self.status_var.set(f"{self.current_operation}  {done}/{total}  {short}")
                elif event == "backup_done":
                    info, reason = payload  # type: ignore[misc]
                    self._set_busy(False)
                    self.progress_var.set(100)
                    self._refresh_slots()
                    warning = f"，{len(info.warnings)} 个文件在复制时发生变化" if info.warnings else ""
                    message = f"备份完成：{info.display_name}，{info.file_count} 个文件，{format_size(info.total_size)}{warning}"
                    self.status_var.set(message)
                    self._log(message)
                    self._reset_auto_schedule()
                    if reason == "manual" and info.warnings:
                        messagebox.showwarning(APP_TITLE, message + "\n建议在游戏暂停或返回主菜单时再手动备份一次。")
                    if reason == "game_exit":
                        self._log("退出快照完成，伴生程序自动关闭")
                        self.root.after(700, self.root.destroy)
                    elif self.exit_backup_pending:
                        self.root.after(100, self._begin_exit_backup)
                elif event == "restore_done":
                    restored, recovery = payload  # type: ignore[misc]
                    self._set_busy(False)
                    self.progress_var.set(100)
                    self._refresh_slots()
                    message = f"加载完成：{restored.display_name} 已覆盖当前游戏存档"
                    self.status_var.set(message)
                    self._log(message)
                    if recovery:
                        self._log("加载前的原存档已保存在“恢复前保险槽”")
                    self._reset_auto_schedule()
                    messagebox.showinfo(APP_TITLE, message + "\n现在可以启动游戏。")
                    if self.exit_backup_pending:
                        self.root.after(100, self._begin_exit_backup)
                elif event == "operation_error":
                    title, details, reason = payload  # type: ignore[misc]
                    self._set_busy(False)
                    self.progress_var.set(0)
                    self.status_var.set(str(title))
                    self._log(f"{title}：{details}")
                    self._reset_auto_schedule()
                    if reason == "game_exit":
                        self.integration.exit_with_game = False
                        bring_tk_window_to_front(self.root)
                        messagebox.showerror(APP_TITLE, f"退出快照失败，程序不会自动关闭：\n{details}")
                    elif reason in {"manual", "restore"}:
                        messagebox.showerror(APP_TITLE, f"{title}：\n{details}")
                    if self.exit_backup_pending and reason != "game_exit":
                        self.root.after(100, self._begin_exit_backup)
        except queue.Empty:
            pass
        except BaseException as exc:
            self._write_companion_status("gui_event_error", str(exc))
            try:
                self._log(f"GUI 事件处理异常，监听将继续：{exc}")
            except BaseException:
                pass
        finally:
            try:
                self.root.after(100, self._poll_events)
            except tk.TclError:
                pass

    def _write_companion_status(self, phase: str, detail: str = "") -> None:
        try:
            write_companion_status(APP_VERSION, phase, detail)
        except OSError:
            pass

    def stop_background_services(self) -> None:
        self.command_pump.stop()

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 300:
            self.log_text.delete("1.0", "80.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_close(self) -> None:
        if self.busy:
            messagebox.showwarning(APP_TITLE, "正在进行备份或加载，请等待操作完成后再关闭程序。")
            return
        if self.integration.exit_with_game and self.game_running:
            self.root.withdraw()
            self._log("窗口已隐藏；游戏退出后程序会完成退出快照并自动关闭")
            return
        try:
            self.config["window_geometry"] = self.root.geometry()
            self.config["auto_enabled"] = self.auto_enabled_var.get()
            save_json(self.config_file, self.config)
        except OSError:
            pass
        self.stop_background_services()
        self._write_companion_status("stopped")
        self.root.destroy()


def _parse_args(argv: list[str] | None = None) -> IntegrationOptions:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--launch-game", action="store_true", help="通过 Steam 启动游戏")
    parser.add_argument("--minimized", action="store_true", help="启动后隐藏窗口")
    parser.add_argument("--exit-with-game", action="store_true", help="游戏退出并备份后关闭程序")
    values = parser.parse_args(argv)
    return IntegrationOptions(
        launch_game=values.launch_game,
        minimized=values.minimized,
        exit_with_game=values.exit_with_game,
    )


def main(argv: list[str] | None = None) -> None:
    options = _parse_args(argv)
    mutex_handle, already_running = acquire_single_instance()
    if already_running:
        try:
            if options.launch_game:
                launch_project_zomboid()
            else:
                write_companion_command("SHOW")
        except OSError:
            pass
        finally:
            release_single_instance(mutex_handle)
        return

    app: ZomboidSaveManagerApp | None = None
    try:
        root = tk.Tk()
        app = ZomboidSaveManagerApp(root, options)
        root.mainloop()
    finally:
        if app is not None:
            app.stop_background_services()
        release_single_instance(mutex_handle)


if __name__ == "__main__":
    main()
