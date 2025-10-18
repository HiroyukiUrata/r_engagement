import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Optional

from playwright.sync_api import sync_playwright, BrowserContext, Page

PROFILE_DIR = "db/playwright_profile"

class BaseTask(ABC):
    """
    Playwrightを使用する自動化タスクの基底クラス。
    ブラウザのセットアップ、実行、ティアダウンの共通処理を管理する。
    """
    def __init__(self, count: Optional[int] = None, max_duration_seconds: int = 600):
        self.target_count = count
        self.max_duration_seconds = max_duration_seconds
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.action_name = "アクション" # サブクラスで上書きする
        self.needs_browser = True # デフォルトではブラウザを必要とする
        self.use_auth_profile = True # デフォルトでは認証プロファイルを使用する

    def _setup_browser(self):
        """ブラウザコンテキストをセットアップする"""
        from .config_manager import is_headless
        headless_mode = is_headless()
        logging.info(f"Playwright ヘッドレスモード: {headless_mode}")

        if self.use_auth_profile:
            logging.info(f"認証プロファイル ({PROFILE_DIR}) を使用してブラウザを起動します。")
            if not os.path.exists(PROFILE_DIR):
                raise FileNotFoundError(f"認証プロファイル {PROFILE_DIR} が見つかりません。")

            lockfile_path = os.path.join(PROFILE_DIR, "SingletonLock")
            if os.path.exists(lockfile_path):
                logging.warning(f"古いロックファイル {lockfile_path} が見つかったため、削除します。")
                os.remove(lockfile_path)

            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                headless=headless_mode,
                slow_mo=500 if not headless_mode else 0,
                env={"DISPLAY": ":0"},
                args=["--disable-blink-features=AutomationControlled"] # 自動化検知を回避する引数を追加
            )
        else:
            logging.info("新しいブラウザセッション（認証プロファイルなし）で起動します。")
            browser = self.playwright.chromium.launch(
                headless=headless_mode,
                slow_mo=500 if not headless_mode else 0,
                env={"DISPLAY": ":0"},
                args=["--disable-blink-features=AutomationControlled"] # 自動化検知を回避する引数を追加
            )
            self.context = browser.new_context(locale="ja-JP")

        self.page = self.context.new_page()

    def _teardown_browser(self):
        """ブラウザコンテキストを閉じる"""
        if self.context:
            logging.info("処理が完了しました。5秒後にブラウザを閉じます...")
            time.sleep(5)
            self.context.close()
            logging.info("ブラウザコンテキストを閉じました。")

    def run(self):
        """タスクの実行フローを管理する"""
        result = False # 失敗時のデフォルト値
        if self.target_count is not None:
            logging.info(f"「{self.action_name}」アクションを開始します。目標件数: {self.target_count}")
        else:
            logging.info(f"「{self.action_name}」アクションを開始します。")

        if self.needs_browser:
            with sync_playwright() as p:
                self.playwright = p
                try:
                    self._setup_browser()
                    # _execute_main_logic の戻り値を result 変数に格納する
                    result = self._execute_main_logic()
                except FileNotFoundError as e:
                    logging.error(f"ファイルが見つかりません: {e}")
                except Exception as e:
                    logging.error(f"「{self.action_name}」アクション中に予期せぬエラーが発生しました: {e}", exc_info=True)
                    self._take_screenshot_on_error()
                    result = False # 例外発生時は明確に False とする
                finally:
                    self._teardown_browser()
        else:
            # ブラウザ不要のタスク
            try:
                result = self._execute_main_logic()
            except Exception as e:
                logging.error(f"「{self.action_name}」アクション中にエラーが発生しました: {e}", exc_info=True)
                result = False

        logging.info(f"「{self.action_name}」アクションを終了します。")
        return result

    def _take_screenshot_on_error(self, prefix: str = "error"):
        """エラー発生時にスクリーンショットを保存する"""
        if self.page:
            from .config_manager import SCREENSHOT_DIR
            try:
                os.makedirs(SCREENSHOT_DIR, exist_ok=True)
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                safe_action_name = "".join(c for c in self.action_name if c.isalnum() or c in (' ', '_')).rstrip()
                screenshot_path = os.path.join(SCREENSHOT_DIR, f"{prefix}_{safe_action_name}_{timestamp}.png")
                self.page.screenshot(path=screenshot_path)
                logging.info(f"エラー発生時のスクリーンショットを {screenshot_path} に保存しました。")
            except Exception as ss_e:
                logging.error(f"スクリーンショットの保存に失敗しました: {ss_e}")

    @abstractmethod
    def _execute_main_logic(self):
        """
        タスク固有のメインロジック。
        サブクラスで必ず実装する必要がある。
        """
        pass