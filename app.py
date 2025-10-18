import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from tkinter.constants import ANCHOR
from collections import defaultdict
import subprocess
import threading
import json
import os
import queue

import webbrowser


class ScraperApp:
    def __init__(self, master):
        self.master = master
        master.title("楽天ROOM エンゲージメント分析ツール")
        master.geometry("950x700") # 横幅を少し広げます

        # --- データ保持用の変数 ---
        self.current_results = []
        self.all_rows_checked = False # ヘッダーチェックボックスの状態
        self.checked_items = {} # チェックボックスの状態を保持
        # プロジェクトのルートディレクトリを取得
        self.project_root = os.path.dirname(os.path.abspath(__file__))
        # 呼び出すスクリプトのパスを app/scraping.py に変更
        self.script_path = os.path.join(self.project_root, "app", "scraping.py")
        self.result_json_path = os.path.join(self.project_root, "output", "scraping_results.json")

        # スタイル設定
        style = ttk.Style()
        style.theme_use('clam')

        # --- フレームの作成 ---
        self.top_frame = ttk.Frame(master, padding="10")
        self.top_frame.pack(fill=tk.X)

        self.middle_frame = ttk.LabelFrame(master, text="ログ出力", padding="10")
        self.middle_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.bottom_frame = ttk.Frame(master, padding="10")
        self.bottom_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # アクションフレームを右側に固定幅で配置
        self.action_frame = ttk.LabelFrame(self.bottom_frame, text="アクション", width=150)
        self.action_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        self.action_frame.pack_propagate(False) # width指定を有効にする

        # 結果表示フレーム（左側）
        self.result_display_frame = ttk.Frame(self.bottom_frame)
        self.result_display_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.filter_frame = ttk.LabelFrame(self.result_display_frame, text="カテゴリフィルター")
        self.filter_frame.pack(fill=tk.X, pady=(0, 5))
        self.result_frame = ttk.LabelFrame(self.result_display_frame, text="スクレイピング結果")
        self.result_frame.pack(fill=tk.BOTH, expand=True)

        # --- ウィジェットの作成 ---
        # トップフレーム
        self.run_button = ttk.Button(self.top_frame, text="スクレイピング実行", command=self.start_scraping_thread)
        self.run_button.pack(side=tk.LEFT, padx=(0, 5))

        self.load_button = ttk.Button(self.top_frame, text="JSONをロード", command=self.load_json_from_file)
        self.load_button.pack(side=tk.LEFT, padx=5)

        self.export_button = ttk.Button(self.top_frame, text="結果をエクスポート", command=self.export_results_to_json, state=tk.DISABLED)
        self.export_button.pack(side=tk.LEFT, padx=5)

        self.status_label = ttk.Label(self.top_frame, text="待機中...")
        self.status_label.pack(side=tk.RIGHT, padx=5)

        # ログ表示用テキストエリア
        self.log_text = scrolledtext.ScrolledText(self.middle_frame, wrap=tk.WORD, height=10)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # フィルター用チェックボックス
        self.category_vars = {}

        # 結果表示用Treeview (テーブル)
        self.tree = ttk.Treeview(self.result_frame, show='headings')
        self.tree.pack(fill=tk.BOTH, expand=True)
        # Treeviewのダブルクリックイベントに関数をバインド
        self.tree.bind("<Double-1>", self.on_tree_double_click)
        # シングルクリックイベントをバインド（ヘッダーとセルの両方に対応）
        self.tree.bind("<Button-1>", self.on_tree_click)

        # アクションフレーム
        self.post_button = ttk.Button(self.action_frame, text="投稿実行", command=self.execute_post_action, state=tk.DISABLED)
        self.post_button.pack(pady=10, padx=10, anchor='n')

        # サブプロセスとキューの初期化
        self.process = None
        self.log_queue = queue.Queue()

        # 定期的なUI更新を開始
        self.master.after(100, self.process_log_queue)
        
        # アプリケーション起動時にデバッグ用Chromeを起動する
        self.launch_debug_chrome()

    def start_scraping_thread(self):
        """スクレイピング処理を別スレッドで開始する"""
        self.run_button.config(state=tk.DISABLED)
        self.load_button.config(state=tk.DISABLED)
        self.export_button.config(state=tk.DISABLED)
        self.post_button.config(state=tk.DISABLED)
        self.status_label.config(text="処理実行中...")
        self.log_text.delete('1.0', tk.END)
        self.tree.delete(*self.tree.get_children()) # テーブルをクリア

        # スレッドを作成して実行
        # モジュールとして実行するようにコマンドを変更
        command = ['python', '-u', '-m', 'app.tasks.analysis']
        self.scraping_thread = threading.Thread(target=self.run_script, args=(command,), daemon=True)
        self.scraping_thread.start()

    def run_script(self, command_args: list):
        """指定されたコマンドをサブプロセスとして実行し、出力をキューに入れる"""
        try:
            # Windowsでコンソールウィンドウを表示しないための設定
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            # サブプロセスの標準入出力エンコーディングをUTF-8に強制
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            self.process = subprocess.Popen(
                command_args,
                cwd=self.project_root, # モジュール実行のためカレントディレクトリを指定
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='ignore',
                startupinfo=startupinfo,
                env=env
            )
            # デッドロックを避けるため、出力読み取りとwaitを分離
            for line in iter(self.process.stdout.readline, ''):
                self.log_queue.put(line)
        except FileNotFoundError:
            self.log_queue.put("エラー: 'python'コマンドが見つかりません。PythonがPATHに設定されているか確認してください。")
        except Exception as e:
            self.log_queue.put(f"スクリプト実行中に予期せぬエラーが発生しました: {e}")
        finally:
            # 処理完了後にGUIに通知
            if self.process:
                self.process.wait() # サブプロセスの終了を待つ
            
            # 実行されたモジュール名からタスクタイプを判別
            if 'app.tasks.analysis' in " ".join(command_args):
                self.log_queue.put(("PROCESS_FINISHED", "analyze"))
            elif 'app.tasks.posting' in " ".join(command_args):
                self.log_queue.put(("PROCESS_FINISHED", "post"))

    def process_log_queue(self):
        """キューからログを取得してUIに表示する"""
        try:
            while True:
                item = self.log_queue.get_nowait()
                if isinstance(item, tuple) and item[0] == "PROCESS_FINISHED":
                    task_type = item[1]
                    if task_type == "analyze":
                        self.on_scraping_complete()
                    else: # postタスクなど、他のタスク完了時
                        self.on_action_complete()
                elif isinstance(item, str):
                    self.log_text.insert(tk.END, item)
                    self.log_text.see(tk.END)
        except queue.Empty:
            pass
        finally:
            self.master.after(100, self.process_log_queue)

    def on_scraping_complete(self):
        """分析スクレイピング完了時の処理"""
        self.status_label.config(text="全処理完了")
        self.run_button.config(state=tk.NORMAL)
        self.load_button.config(state=tk.NORMAL)

        try:
            # 分析とコメント生成が完了した最終結果を読み込む
            with open(self.result_json_path, 'r', encoding='utf-8') as f:
                results = json.load(f)
            self.display_results_in_table(results)
            messagebox.showinfo("成功", "分析が正常に完了しました。")
        except FileNotFoundError:
            messagebox.showwarning("完了", "処理は完了しましたが、結果ファイルが見つかりませんでした。")
        except Exception as e:
            messagebox.showerror("エラー", f"結果ファイルの読み込みに失敗しました:\n{e}")

    def on_action_complete(self):
        """投稿などの個別アクション完了時の処理"""
        self.status_label.config(text="投稿処理完了")
        # 投稿ボタンはテーブルの行が選択されていれば有効化
        if self.tree.selection():
            self.post_button.config(state=tk.NORMAL)

    def load_json_from_file(self):
        """ファイルダイアログを開き、JSONファイルを読み込んでテーブルに表示する"""
        project_root = os.path.dirname(os.path.abspath(__file__))
        file_path = filedialog.askopenfilename(
            initialdir=project_root,
            title="JSONファイルを選択",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*"))
        )
        if not file_path:
            return # ファイルが選択されなかった場合は何もしない

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                results = json.load(f)
            
            if not isinstance(results, list):
                raise ValueError("JSONのルートはリスト形式である必要があります。")

            self.display_results_in_table(results)
            self.status_label.config(text=f"{os.path.basename(file_path)} をロードしました")
            messagebox.showinfo("成功", "JSONファイルを正常にロードしました。")

        except json.JSONDecodeError:
            messagebox.showerror("エラー", "無効なJSONファイルです。ファイルが破損している可能性があります。")
        except Exception as e:
            messagebox.showerror("エラー", f"ファイルの読み込み中にエラーが発生しました:\n{e}")

    def export_results_to_json(self):
        """現在テーブルに表示されているデータをJSONファイルとして保存する"""
        if not self.current_results:
            messagebox.showwarning("エクスポート不可", "エクスポートするデータがありません。")
            return

        file_path = filedialog.asksaveasfilename(
            initialdir=os.path.dirname(os.path.abspath(__file__)),
            title="名前を付けて保存",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
            defaultextension=".json"
        )

        if not file_path:
            return

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.current_results, f, ensure_ascii=False, indent=4)
            messagebox.showinfo("成功", f"結果を {os.path.basename(file_path)} に保存しました。")
        except Exception as e:
            messagebox.showerror("保存エラー", f"ファイルのエクスポート中にエラーが発生しました:\n{e}")

    def setup_category_filters(self, results):
        """結果からカテゴリを抽出し、フィルタ用チェックボックスを作成する"""
        # 既存のウィジェットをクリア
        for widget in self.filter_frame.winfo_children():
            widget.destroy()

        if not results:
            return

        # カテゴリを抽出し、アルファベット順にソート
        categories = sorted(list(set(item.get('category', 'N/A') for item in results)))
        self.category_vars = {}

        # "すべて選択/解除" チェックボックス
        self.all_categories_var = tk.BooleanVar(value=True)
        all_cb = ttk.Checkbutton(self.filter_frame, text="すべて選択/解除", variable=self.all_categories_var, command=self.toggle_all_categories)
        all_cb.pack(side=tk.LEFT, padx=5, pady=2)

        for category in categories:
            var = tk.BooleanVar(value=True)
            cb = ttk.Checkbutton(self.filter_frame, text=category, variable=var, command=self.apply_filter)
            cb.pack(side=tk.LEFT, padx=5, pady=2)
            self.category_vars[category] = var

    def toggle_all_categories(self):
        """すべてのカテゴリチェックボックスの状態を切り替える"""
        is_checked = self.all_categories_var.get()
        for var in self.category_vars.values():
            var.set(is_checked)
        self.apply_filter()

    def display_results_in_table(self, results):
        """受け取ったデータ（辞書のリスト）をTreeviewに表示する"""
        # 既存のデータをクリア
        self.tree.delete(*self.tree.get_children())
        self.current_results = results # データを保持

        if not results:
            # フィルターもクリア
            for widget in self.filter_frame.winfo_children():
                widget.destroy()
            self.export_button.config(state=tk.DISABLED)
            return

        self.export_button.config(state=tk.NORMAL)

        # ヘッダーを定義
        headers = {
            "selection": "☑", "name": "ユーザー名", "post_status": "投稿ステータス", "category": "カテゴリ",
            "comment_text": "生成コメント", "like_count": "いいね", "collect_count": "コレ！", "follow_count": "フォロー", "comment_count": "コメント",
            "latest_action_timestamp": "最終アクション日時",
            "is_following": "フォロー状況", "profile_page_url": "プロフィールURL"
        }
        self.tree["columns"] = list(headers.keys())

        # チェックボックスの状態をリセット
        self.checked_items = {str(i): False for i in range(len(results))}
        self.all_rows_checked = False

        for key, text in headers.items():
            self.tree.heading(key, text=text)
            # デフォルトの幅を設定
            self.tree.column(key, anchor=tk.W, width=100)

        # カラム幅の調整
        self.tree.heading("selection", text="☐") # ヘッダーのチェックボックス
        self.tree.column("selection", width=40, anchor=tk.CENTER, stretch=False)
        self.tree.column("name", width=150)
        self.tree.column("comment_text", width=200)
        self.tree.column("post_status", width=100, anchor=tk.CENTER)
        self.tree.column("profile_page_url", width=200)
        # カウント系は幅を狭くして中央揃え
        self.tree.column("like_count", width=50, anchor=tk.CENTER)
        self.tree.column("collect_count", width=50, anchor=tk.CENTER)
        self.tree.column("follow_count", width=50, anchor=tk.CENTER)
        self.tree.column("comment_count", width=60, anchor=tk.CENTER)
        self.tree.column("is_following", width=80, anchor=tk.CENTER)
        self.tree.column("latest_action_timestamp", width=140, anchor=tk.W)
        self.tree.column("category", width=140)

        # フィルターをセットアップ
        self.setup_category_filters(results)

        # データを挿入
        for i, item in enumerate(results):
            # ブーリアン値を分かりやすい文字列に変換
            is_following_text = "フォロー中" if item.get('is_following', False) else "未フォロー"

            values = (
                "☐", # チェックボックスの初期状態
                item.get('name', ''),
                item.get('post_status', '未処理'), # 投稿ステータスの初期値
                item.get('category', ''),
                item.get('comment_text', ''), # 生成されたコメント
                item.get('like_count', 0),
                item.get('collect_count', 0),
                item.get('follow_count', 0),
                item.get('comment_count', 0),
                item.get('latest_action_timestamp', ''),
                is_following_text,
                item.get('profile_page_url', '')
            )
            # iidで行を識別できるようにする
            self.tree.insert("", tk.END, iid=str(i), values=values)

        self.apply_filter() # 初期表示

    def apply_filter(self):
        """カテゴリフィルターを適用してTreeviewの表示を更新する"""
        # 既存のデータをクリア
        self.tree.delete(*self.tree.get_children())

        selected_categories = {cat for cat, var in self.category_vars.items() if var.get()}

        for i, item in enumerate(self.current_results):
            if item.get('category') in selected_categories:
                is_following_text = "フォロー中" if item.get('is_following', False) else "未フォロー"
                checked_char = "☑" if self.checked_items.get(str(i)) else "☐"
                values = (
                    checked_char,
                    item.get('name', ''), item.get('post_status', '未処理'),
                    item.get('category', ''), item.get('comment_text', ''),
                    item.get('like_count', 0), item.get('collect_count', 0),
                    item.get('follow_count', 0), item.get('comment_count', 0),
                    item.get('latest_action_timestamp', ''), is_following_text,
                    item.get('profile_page_url', '')
                )
                self.tree.insert("", tk.END, iid=str(i), values=values)

    def on_tree_click(self, event):
        """Treeviewのクリックイベントを処理する（ヘッダーまたはセル）"""
        region = self.tree.identify("region", event.x, event.y)

        if region == "heading":
            column_id = self.tree.identify_column(event.x)
            # "selection"列（#1）のヘッダーがクリックされた場合
            if column_id == '#1':
                self.toggle_all_checkboxes()
        
        elif region == "cell":
            column_id = self.tree.identify_column(event.x)
            item_id = self.tree.identify_row(event.y)
            # "selection"列（#1）のセルがクリックされた場合
            if column_id == '#1' and item_id:
                self.toggle_checkbox(item_id)


    def on_tree_double_click(self, event):
        """テーブルの行がダブルクリックされたときの処理"""
        item_id = self.tree.identify_row(event.y)
        if not item_id: return

        item_values = self.tree.item(item_id, "values")
        # ヘッダーのキーと値の辞書を作成
        column_keys = self.tree["columns"]
        item_dict = dict(zip(column_keys, item_values))

        url = item_dict.get("profile_page_url")
        if url and url.startswith("http"):
            webbrowser.open_new_tab(url)
        else:
            messagebox.showinfo("URLなし", "このユーザーのプロフィールURLは利用できません。")

    def toggle_all_checkboxes(self):
        """表示されているすべての行のチェックボックスの状態を切り替える"""
        visible_items = self.tree.get_children()
        if not visible_items:
            return

        # 新しい状態を決定（現在の逆）
        self.all_rows_checked = not self.all_rows_checked
        new_state = self.all_rows_checked

        # ヘッダーの表示を更新
        self.tree.heading("selection", text="☑" if new_state else "☐")

        # 表示されているすべてのアイテムのチェック状態と表示を更新
        for item_id in visible_items:
            self.checked_items[item_id] = new_state
            current_values = list(self.tree.item(item_id, "values"))
            current_values[0] = "☑" if new_state else "☐"
            self.tree.item(item_id, values=tuple(current_values))
        
        self.update_post_button_state()

    def toggle_checkbox(self, item_id):
        """指定された行のチェックボックスの状態を切り替える"""
        current_state = self.checked_items.get(item_id, False)
        new_state = not current_state
        self.checked_items[item_id] = new_state

        # 表示を更新
        current_values = list(self.tree.item(item_id, "values"))
        current_values[0] = "☑" if new_state else "☐"
        self.tree.item(item_id, values=tuple(current_values))

        self.update_post_button_state()

    def update_post_button_state(self):
        """チェック状態に基づいて投稿ボタンの有効/無効を切り替える"""
        # 1つでもチェックがあれば投稿ボタンを有効化
        if any(self.checked_items.values()):
            self.post_button.config(state=tk.NORMAL)
        else:
            self.post_button.config(state=tk.DISABLED)
    def execute_post_action(self):
        """選択された行に対して投稿処理を実行する"""
        checked_ids = [iid for iid, is_checked in self.checked_items.items() if is_checked]

        if not checked_ids:
            messagebox.showwarning("選択エラー", "投稿するユーザーを選択してください。")
            return

        self.post_button.config(state=tk.DISABLED)
        self.status_label.config(text="投稿処理を実行中...")

        for item_id in checked_ids:
            # current_resultsから元のデータを取得
            original_index = int(item_id)
            item_dict = self.current_results[original_index]

            profile_url = item_dict.get("profile_page_url")
            user_name = item_dict.get("name")
            comment_text = item_dict.get("comment_text") # 生成されたコメントを取得

            if not profile_url or not profile_url.startswith("http"):
                messagebox.showwarning("URLエラー", f"「{user_name}」さんのプロフィールURLが無効なため、処理をスキップします。")
                continue

            # 投稿処理を別スレッドで実行
            # モジュールとして実行し、コメントも引数で渡す
            command = ['python', '-u', '-m', 'app.tasks.posting', '--url', profile_url, '--comment', comment_text]
            post_thread = threading.Thread(target=self.run_script, args=(command,), daemon=True)
            post_thread.start()

            # 投稿ステータスを「処理中」に更新 (表示されている行のみ)
            if self.tree.exists(item_id):
                current_values = list(self.tree.item(item_id, 'values'))
                current_values[2] = "⏳ 処理中..." # "投稿ステータス"列を更新
                self.tree.item(item_id, values=tuple(current_values))

            # 処理を開始したアイテムのチェックを内部的に解除
            self.checked_items[item_id] = False

        # 全てのチェックが解除されたので、ヘッダーも更新
        self.all_rows_checked = False
        self.tree.heading("selection", text="☐")

            # 実際の完了はログで確認し、手動で更新する想定

    def launch_debug_chrome(self):
        """start_chrome_debug.bat を実行してデバッグ用Chromeを起動する"""
        bat_path = os.path.join(self.project_root, "start_chrome_debug.bat")
        if os.path.exists(bat_path):
            try:
                # コンソールウィンドウを表示せずにバッチファイルを実行
                subprocess.Popen([bat_path], creationflags=subprocess.CREATE_NO_WINDOW)
                self.log_text.insert(tk.END, "デバッグ用Chromeの起動を試みました。\n")
            except Exception as e:
                self.log_text.insert(tk.END, f"Chromeの起動に失敗しました: {e}\n")
        else:
            self.log_text.insert(tk.END, "start_chrome_debug.bat が見つかりません。\n")


if __name__ == "__main__":
    root = tk.Tk()
    app = ScraperApp(root)
    root.mainloop()
