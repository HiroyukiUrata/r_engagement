import tkinter as tk
from tkinter import ttk
from tkinter import scrolledtext
from tkinter import messagebox
import threading
import queue
import sys
import os
import subprocess
import webbrowser
from tkinter.font import Font
import json

# プロジェクトのルートディレクトリをPythonのパスに追加します。
# これにより、'app'パッケージ内のモジュールが正しく解決されます。
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

def run_script_in_thread(log_queue: queue.Queue):
    """
    run_scraping.pyを別プロセスで実行し、その出力をキューに流す関数
    """
    try:
        # run_scraping.pyへのパスを構築
        script_path = os.path.join(project_root, "run_scraping.py")
        
        # サブプロセスの環境変数を設定
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        # 新しいプロセスとしてスクリプトを実行
        process = subprocess.Popen(
            [sys.executable, script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            # encodingはサブプロセスの出力に合わせるが、環境変数でutf-8に強制
            encoding='utf-8', 
            # Windowsで発生する可能性のあるデコードエラーを無視する
            errors='ignore',
            bufsize=1,
            env=env,
        )

        # プロセスの標準出力を一行ずつ読み取り、キューに入れる
        for line in iter(process.stdout.readline, ''):
            log_queue.put(line.strip())
        
        process.stdout.close()
        return_code = process.wait()
        if return_code != 0:
            log_queue.put(f"--- スクリプトがエラーコード {return_code} で終了しました ---")

    except Exception as e:
        log_queue.put(f"--- スクリプトの実行中にエラーが発生しました: {e} ---")
    finally:
        # 処理が完了したことをGUIに通知
        log_queue.put("---TASK_DONE---")

def create_results_window(results_data):
    """
    スクレイピング結果をテーブル形式で表示する新しいウィンドウを作成する
    """
    if not results_data:
        messagebox.showinfo("結果", "表示するデータがありません。")
        return

    win = tk.Toplevel()
    win.title("スクレイピング結果")
    win.geometry("800x400")

    # Treeviewウィジェット（テーブル）の作成
    columns = ('id', 'name', 'category', 'likes', 'url')
    tree = ttk.Treeview(win, columns=columns, show='headings')

    # 各列の設定
    tree.heading('id', text='ID')
    tree.column('id', width=100, anchor='center')
    tree.heading('name', text='ユーザー名')
    tree.column('name', width=150)
    tree.heading('category', text='カテゴリ')
    tree.column('category', width=150)
    tree.heading('likes', text='いいね数')
    tree.column('likes', width=60, anchor='center')
    tree.heading('url', text='プロフィールURL')
    tree.column('url', width=300)

    # データをテーブルに挿入
    for user in results_data:
        url = user.get('profile_page_url', 'N/A')
        tree.insert('', tk.END, values=(user['id'], user['name'], user['category'], user['like_count'], url))

    # URLクリック用のイベントハンドラ
    def on_tree_click(event):
        item_id = tree.identify_row(event.y)
        column_id = tree.identify_column(event.x)
        if item_id and column_id == '#5': # 5番目の列 (URL)
            item = tree.item(item_id)
            url = item['values'][4]
            if url and url.startswith('http'):
                webbrowser.open_new_tab(url)

    # 下線付きフォントを作成
    link_font = Font()
    link_font.configure(underline=True)
    tree.tag_configure('link', foreground='blue', font=link_font)
    tree.bind("<Button-1>", on_tree_click)

    tree.pack(fill="both", expand=True, padx=10, pady=10)


def main():
    """GUIアプリケーションのメイン関数"""
    log_queue = queue.Queue()

    # --- GUIアプリケーションクラス ---
    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("楽天ROOM ユーザー分析ツール")
            self.geometry("750x550")

            # --- ウィジェットの作成 ---
            button_frame = ttk.Frame(self)
            button_frame.pack(padx=10, pady=5, fill="x")

            self.run_button = ttk.Button(button_frame, text="スクレイピング実行", command=self.start_task)
            self.run_button.pack(side="left", padx=5)
            ttk.Button(button_frame, text="ログをクリア", command=self.clear_log).pack(side="left", padx=5)

            log_frame = ttk.Frame(self)
            log_frame.pack(padx=10, pady=5, fill="both", expand=True)
            ttk.Label(log_frame, text="スクリプト実行ログ:").pack(anchor="w")
            self.log_text = scrolledtext.ScrolledText(log_frame, state="disabled", height=10)
            self.log_text.pack(fill="both", expand=True)

            self.status_var = tk.StringVar(value="準備完了")
            ttk.Label(self, textvariable=self.status_var, anchor="w").pack(side="bottom", fill="x", padx=10, pady=2)

            self.process_log_queue()

        def start_task(self):
            self.run_button.config(state="disabled")
            self.status_var.set("スクリプト実行中...")
            self.clear_log()
            threading.Thread(target=run_script_in_thread, args=(log_queue,), daemon=True).start()

        def process_log_queue(self):
            try:
                message = log_queue.get_nowait()
                if message == "---TASK_DONE---":
                    self.run_button.config(state="normal")
                    self.status_var.set("スクリプトの実行が完了しました。")
                    # 最後の行からJSONデータを取得しようと試みる
                    all_logs = self.log_text.get(1.0, tk.END).strip()
                    json_data = None
                    for line in reversed(all_logs.split('\n')):
                        if line.strip().startswith('[') and line.strip().endswith(']'):
                            try:
                                json_data = json.loads(line.strip())
                                break
                            except json.JSONDecodeError:
                                continue
                    if json_data:
                        create_results_window(json_data)
                    else:
                        messagebox.showinfo("完了", "スクリプトは完了しましたが、表示する結果データが見つかりませんでした。")
                else:
                    self.log_text.config(state="normal")
                    self.log_text.insert(tk.END, message + "\n")
                    self.log_text.config(state="disabled")
                    self.log_text.see(tk.END) # 自動スクロール
            except queue.Empty:
                pass
            finally:
                self.after(100, self.process_log_queue)

        def clear_log(self):
            self.log_text.config(state="normal")
            self.log_text.delete(1.0, tk.END)
            self.log_text.config(state="disabled")

    app = App()
    app.mainloop()

if __name__ == '__main__':
    main()