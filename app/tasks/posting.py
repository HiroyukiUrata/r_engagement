import logging
import os
import sys
import time
import argparse
from playwright.sync_api import sync_playwright, Error as PlaywrightError

# --- プロジェクトルートの定義 ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- ユーティリティのインポート ---
sys.path.insert(0, PROJECT_ROOT)
from app.utils.selector_utils import convert_to_robust_selector

# --- 出力ディレクトリの定義 ---
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")

# --- ロガーの基本設定 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main(profile_page_url: str, comment_text: str):
    """
    指定されたユーザーのプロフィールページで投稿アクションを実行する。
    """
    if not profile_page_url or not profile_page_url.startswith("http"):
        logging.error(f"無効なURLです: {profile_page_url}")
        return

    logging.info(f"投稿アクションを開始します。対象URL: {profile_page_url}")
    with sync_playwright() as p:
        # --- 1. ブラウザの起動 ---
        logging.info("デバッグモードで起動中のChrome (ポート9222) に接続します。")
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.new_page()
            logging.info("Chromeへの接続に成功しました。")
        except PlaywrightError as e:
            logging.error(f"Chromeへの接続に失敗しました。アプリが起動したChromeが実行されているか確認してください。エラー: {e}")
            return
        try:
            # --- 2. 対象ユーザーのURLを開く ---
            logging.info(f"プロフィールページにアクセスします: {profile_page_url}")
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    page.goto(profile_page_url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_load_state("networkidle", timeout=20000)
                    logging.info("ページへのアクセスに成功しました。")
                    break
                except PlaywrightError as e:
                    logging.warning(f"ページへのアクセスに失敗しました (試行 {attempt + 1}/{max_retries}): {e}")
                    if attempt + 1 == max_retries:
                        raise
                    time.sleep(3)
            
            # ウィンドウを前面に表示してユーザーが操作できるようにする
            page.bring_to_front()

            # --- 3. 投稿カードを探す ---
            logging.info("最初の投稿カードを探しています...")
            original_post_selector = 'div.container--a3dH_ a.link-image--15_8Q'
            post_card_image_locator = page.locator(convert_to_robust_selector(original_post_selector)).first
            post_card_image_locator.wait_for(state="visible", timeout=15000)
            logging.info("投稿カードが見つかりました。")

            # --- 4. 投稿カードの画像をクリック ---
            logging.info("投稿カードの画像をクリックします...")
            post_card_image_locator.click()
            page.wait_for_load_state("networkidle", timeout=20000)
            logging.info(f"クリック後のページに遷移しました: {page.url}")

            # --- 5. コメントボタンをクリック ---
            logging.info("コメントボタンを探してクリックします...")
            original_comment_selector = 'div.pointer--3rZ2h:has-text("コメント")'
            comment_button_locator = page.locator(convert_to_robust_selector(original_comment_selector))
            comment_button_locator.wait_for(state="visible", timeout=15000)
            comment_button_locator.click()
            logging.info("コメントボタンをクリックしました。")

            # --- 6. コメントを入力 ---
            logging.info("コメント入力欄にテキストを入力します...")
            comment_textarea_locator = page.locator('textarea[placeholder="コメントを書いてください"]')
            comment_textarea_locator.wait_for(state="visible", timeout=15000)
            comment_textarea_locator.fill(comment_text)

            logging.info("--------------------------------------------------")
            logging.info("コメントを入力しました。ブラウザで内容を確認し、送信してください。")
            logging.info("（操作が完了したら、このブラウザウィンドウは手動で閉じてください）")
            logging.info("--------------------------------------------------")

        except PlaywrightError as e:
            logging.error(f"投稿アクション中にエラーが発生しました: {e}")
            screenshot_path = os.path.join(OUTPUT_DIR, "error_post_action_screenshot.png")
            if 'page' in locals() and not page.is_closed(): page.screenshot(path=screenshot_path)
            logging.info(f"エラー発生時のスクリーンショットを {screenshot_path} に保存しました。")
        finally:
            logging.info("投稿アクションのスクリプトは完了しましたが、ブラウザは開いたままです。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="楽天ROOM 投稿アクションツール")
    parser.add_argument('--url', type=str, required=True, help='投稿アクションの対象となるプロフィールURL')
    parser.add_argument('--comment', type=str, required=True, help='投稿するコメント文')
    args = parser.parse_args()
    main(args.url, args.comment)