import logging
import os
import re
import sys
import time
import json
import argparse
from playwright.sync_api import sync_playwright, Error as PlaywrightError

# --- プロジェクトルートの定義 ---
# このファイルの親ディレクトリの親ディレクトリがプロジェクトルート
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- ユーティリティのインポート ---
# プロジェクトルートをパスに追加して、appパッケージからインポートできるようにする
sys.path.insert(0, PROJECT_ROOT)
from app.utils.selector_utils import convert_to_robust_selector

# --- 出力ディレクトリの定義 ---
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")

# --- 設定 ---
TARGET_URL = "https://room.rakuten.co.jp/items"
MAX_USERS_TO_SCRAPE = 5  # 取得したいおおよそのユーザー数
OUTPUT_JSON_FILE = "scraping_results.json" # 保存するJSONファイル名

# --- ロガーの基本設定 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_analysis_task():
    """
    楽天ROOMのお知らせページからユーザー情報をスクレイピングするメイン関数
    """
    with sync_playwright() as p:
        # --- 1. ブラウザの起動 ---
        # 既に起動しているデバッグモードのChromeに接続する
        logging.info("デバッグモードで起動中のChrome (ポート9222) に接続します。")
        logging.info("事前に 'start_chrome_debug.bat' を実行してください。")
        browser = None
        for i in range(5): # 5回まで接続を試行
            try:
                browser = p.chromium.connect_over_cdp("http://localhost:9222")
                logging.info("Chromeへの接続に成功しました。")
                break # 接続に成功したらループを抜ける
            except Exception:
                logging.warning(f"接続に失敗しました。3秒後に再試行します... ({i+1}/5)")
                time.sleep(3)

        if not browser:
            logging.error("Chromeへの接続に失敗しました。")
            logging.error("先に 'start_chrome_debug.bat' を実行し、")
            logging.error("表示されたChromeウィンドウを閉じずに、このスクリプトを実行してください。")
            return

        try:
            # 既存のコンテキストに依存せず、新しいクリーンなコンテキストを作成する
            context = browser.contexts[0]
            page = context.new_page()

            # --- 2. ページ遷移 ---
            logging.info(f"{TARGET_URL} にアクセスします。")
            page.goto(TARGET_URL, wait_until="domcontentloaded")

            logging.info("「お知らせ」リンクを探してクリックします。")
            page.get_by_role("link", name="お知らせ").click()

            page.wait_for_load_state("domcontentloaded", timeout=15000)
            logging.info(f"お知らせページに遷移しました: {page.url}")

            # --- 3. 無限スクロールによる情報収集 ---
            logging.info("「アクティビティ」セクションをスクロールして情報を収集します。")
            # ng-show属性を持つアクティビティのタイトル要素を待つ
            activity_title_locator = page.locator("div.title[ng-show='notifications.activityNotifications.length > 0']")
            try:
                # 要素がDOMにアタッチされるのを待つ（表示されていなくても良い）
                activity_title_locator.wait_for(state='attached', timeout=10000)
            except Exception:
                logging.info("「アクティビティ」セクションが見つかりませんでした。処理対象はありません。")
                return

            logging.info("遅延読み込みされるコンテンツを表示するため、ページをスクロールします。")
            last_count = 0
            for attempt in range(4): # 無限ループ防止
           #for attempt in range(15): # 無限ループ防止
                notification_list_items = page.locator("li[ng-repeat='notification in notifications.activityNotifications']")
                current_count = notification_list_items.count()

                # スクロールしてもアクティビティが増えなくなったら終了
                if attempt > 2 and current_count == last_count:
                    logging.info("スクロールしても新しいアクティビティ通知は読み込まれませんでした。")
                    break

                last_count = current_count
                logging.info(f"  スクロール {attempt + 1}回目: {current_count}件のアクティビティ通知を検出。")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                # スクロール後に新しいコンテンツが読み込まれるのを少し待つ
                page.wait_for_timeout(1500) # 1.5秒待機

            # --- 4. データ抽出 ---
            logging.info(f"--- フェーズ1: {notification_list_items.count()}件の通知から基本情報を収集します。 ---")
            all_notifications = []
            for item in notification_list_items.all():
                try: # 個々の通知アイテムの処理
                    user_name_element = item.locator("span.notice-name span.strong").first
                    if not user_name_element.is_visible():
                        continue

                    user_name = user_name_element.inner_text().strip()
                    profile_image_url = item.locator("div.left-img img").get_attribute("src")

                    # プロフィール画像がないユーザーは対象外
                    if "img_noprofile.gif" in profile_image_url:
                        continue

                    if user_name:
                        user_id = "unknown"
                        match = re.search(r'/([^/]+?)(?:\.\w+)?(?:\?.*)?$', profile_image_url)
                        if match: user_id = match.group(1)

                        action_text = item.locator("div.right-text > p").first.inner_text()
                        action_timestamp = item.locator("span.notice-time").get_attribute("title")
                        is_following = not item.locator("span.follow:has-text('未フォロー')").is_visible()

                        all_notifications.append({
                            'id': user_id, 
                            'name': user_name.strip(), 
                            'profile_image_url': profile_image_url,
                            'action_text': action_text,
                            'action_timestamp': action_timestamp,
                            'is_following': is_following
                        })
                except Exception as item_error:
                    logging.warning(f"通知アイテムの取得中にエラー: {item_error}")
            
            # --- フェーズ2: ユーザー単位で情報を集約し、カテゴリを付与 ---
            logging.info(f"--- フェーズ2: {len(all_notifications)}件の通知をユーザー単位で集約します。 ---")
            aggregated_users = {}
            for notification in all_notifications:
                user_id = notification['id']
                if user_id not in aggregated_users:
                    aggregated_users[user_id] = {
                        'id': user_id, 'name': notification['name'],
                        'like_count': 0, 'collect_count': 0, 'is_following': notification['is_following'],
                        'latest_action_timestamp': notification['action_timestamp']
                    }
                
                if "いいねしました" in notification['action_text']:
                    aggregated_users[user_id]['like_count'] += 1
                if "コレ！しました" in notification['action_text']:
                    aggregated_users[user_id]['collect_count'] += 1

                # if notification['action_timestamp'] > aggregated_users[user_id]['latest_action_timestamp']:
                #     aggregated_users[user_id]['is_following'] = notification['is_following']
                #     aggregated_users[user_id]['latest_action_timestamp'] = notification['action_timestamp']
                # 最新の情報を更新
                if notification['action_timestamp'] > aggregated_users[user_id]['latest_action_timestamp']:
                    aggregated_users[user_id].update({
                        'is_following': notification['is_following'],
                        'latest_action_text': notification['action_text'],
                        'latest_action_timestamp': notification['action_timestamp']
                    })
            logging.info(f"  -> {len(aggregated_users)}人のユニークユーザーに集約しました。")
            for user in aggregated_users.values():
                like_count = user['like_count']
                is_following = user['is_following']
                
                if like_count >= 2:
                    user['category'] = "いいね多謝"
                elif like_count > 0 and not is_following:
                    user['category'] = "未フォロー＆いいね感謝"
                elif like_count > 0 and user['collect_count'] > 0:
                    user['category'] = "いいね＆コレ！感謝"
                elif like_count > 0:
                    user['category'] = "いいね感謝"
                else:
                    user['category'] = "その他"

            # --- フェーズ3: 優先度に基づいてソート ---
            logging.info(f"--- フェーズ3: 優先度順にソートし、上位{MAX_USERS_TO_SCRAPE}件を抽出します。 ---")
            sorted_users = sorted(
                aggregated_users.values(), 
                key=lambda u: (
                    -u['like_count'], 
                    u['is_following'], 
                    -(u['like_count'] > 0 and u['collect_count'] > 0)
                )
            )
            
            users_to_process = sorted_users[:MAX_USERS_TO_SCRAPE]

            # --- フェーズ4: URL取得 ---
            logging.info(f"--- フェーズ4: 上位{len(users_to_process)}人のプロフィールURLを取得します。 ---")
            final_user_data = []
            for i, user_info in enumerate(users_to_process):
                logging.debug(f"  {i+1}/{len(users_to_process)}: 「{user_info['name']}」のURLを取得中...")
                try:
                    # 該当ユーザーの最初の通知アイテムを探し、クリックして新しいタブを開く
                    user_li_locator = page.locator(f"li[ng-repeat='notification in notifications.activityNotifications']:has-text(\"{user_info['name']}\")").first
                    image_container_locator = user_li_locator.locator("div.left-img")
                    # --- 要素が表示されるまでスクロールするロジックを追加 ---
                    max_scroll_attempts_find = 15
                    is_found = False
                    for attempt in range(max_scroll_attempts_find):
                        if image_container_locator.is_visible():
                            is_found = True
                            break
                        logging.debug(f"  ユーザー「{user_info['name']}」の画像が見つかりません。スクロールします... ({attempt + 1}/{max_scroll_attempts_find})")
                        page.evaluate("window.scrollBy(0, 500)") # 500pxずつスクロール
                        time.sleep(1)      

                    # 新しいページが開くのを待つ処理
                    image_container_locator.click()
                    
                    profile_page_url = page.url
                    user_info['profile_page_url'] = page.url
                    logging.debug(f"  -> 取得したURL: {profile_page_url}")
                    
                    # お知らせページに戻る
                    page.go_back(wait_until="domcontentloaded")

                except Exception as url_error:
                    logging.warning(f"  ユーザー「{user_info['name']}」のURL取得中にエラー: {url_error}")
                    user_info['profile_page_url'] = "取得失敗"
                
                final_user_data.append(user_info)
                time.sleep(0.5) # サーバーへの負荷を軽減するための短い待機

            logging.info("\n--- 分析完了: 処理対象ユーザー一覧 ---")
            for i, user in enumerate(final_user_data):
                logging.info(f"  {i+1:2d}. {user['name']:<20} (カテゴリ: {user['category']}, URL: {user.get('profile_page_url', 'N/A')})")
            logging.info("------------------------------------")

            # --- フェーズ5: 結果をJSONファイルに保存 ---
            try:
                # outputディレクトリに結果を保存
                os.makedirs(OUTPUT_DIR, exist_ok=True)
                output_path = os.path.join(OUTPUT_DIR, OUTPUT_JSON_FILE)
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(final_user_data, f, ensure_ascii=False, indent=4)
                logging.info(f"結果を {output_path} に保存しました。")
            except Exception as e:
                logging.error(f"JSONファイルへの保存中にエラーが発生しました: {e}")

        except Exception as e:
            logging.error(f"処理中にエラーが発生しました: {e}", exc_info=True)
            # エラー発生時にスクリーンショットを保存
            screenshot_path = os.path.join(OUTPUT_DIR, "error_screenshot.png")
            page.screenshot(path=screenshot_path)
            logging.info(f"エラー発生時のスクリーンショットを {screenshot_path} に保存しました。")
        finally:
            # --- 5. ブラウザを閉じる ---
            logging.info("処理が完了しました。")
            if 'page' in locals() and not page.is_closed():
                page.close() # 接続したブラウザ自体は閉じずに、開いたページだけを閉じる

def execute_post_action(profile_page_url: str):
    """
    指定されたユーザーのプロフィールページで投稿アクション（最初の投稿をクリック）を実行する。
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
            logging.error(f"Chromeへの接続に失敗しました。'start_chrome_debug.bat'が実行されているか確認してください。エラー: {e}")
            return

        try:
            # --- 2. 対象ユーザーのURLを開く ---
            logging.info(f"プロフィールページにアクセスします: {profile_page_url}")
            
            # --- リトライ処理を追加 ---
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    page.goto(profile_page_url, wait_until="domcontentloaded", timeout=30000)
                    # ページがアイドル状態になるまで待機
                    page.wait_for_load_state("networkidle", timeout=20000)
                    logging.info("ページへのアクセスに成功しました。")
                    break # 成功したらループを抜ける
                except PlaywrightError as e:
                    logging.warning(f"ページへのアクセスに失敗しました (試行 {attempt + 1}/{max_retries}): {e}")
                    if attempt + 1 == max_retries:
                        raise # 最大リトライ回数に達したらエラーを再送出
                    time.sleep(3) # 3秒待ってから再試行

            # --- 3. 投稿カードを探す ---
            logging.info("最初の投稿カードを探しています...")
            # AIが生成したセレクタを堅牢な形式に変換して使用
            original_post_selector = 'div.container--a3dH_ a.link-image--15_8Q'
            post_card_image_locator = page.locator(convert_to_robust_selector(original_post_selector)).first

            post_card_image_locator.wait_for(state="visible", timeout=15000)
            logging.info("投稿カードが見つかりました。")

            # --- 4. 投稿カードの画像をクリックしてページ遷移 ---
            logging.info("投稿カードの画像をクリックします...")
            post_card_image_locator.click()

            # ページ遷移が完了するのを待つ
            page.wait_for_load_state("networkidle", timeout=20000)
            logging.info(f"クリック後のページに遷移しました: {page.url}")

            # --- 5. コメントボタンをクリック ---
            logging.info("コメントボタンを探してクリックします...")
            # AIが生成したセレクタを堅牢な形式に変換して使用
            original_comment_selector = 'div.pointer--3rZ2h:has-text("コメント")'
            comment_button_locator = page.locator(convert_to_robust_selector(original_comment_selector))
            comment_button_locator.wait_for(state="visible", timeout=15000)
            comment_button_locator.click()
            logging.info("コメントボタンをクリックしました。")

            # --- 6. コメントを入力 ---
            logging.info("コメント入力欄にテキストを入力します...")
            comment_textarea_locator = page.locator('textarea[placeholder="コメントを書いてください"]')
            comment_textarea_locator.wait_for(state="visible", timeout=15000)
            comment_textarea_locator.fill("こんにちは、よろしくお願いします")

            logging.info("--------------------------------------------------")
            logging.info("コメントを入力しました。ブラウザで内容を確認し、送信してください。")
            logging.info("（操作が完了したら、このブラウザウィンドウは手動で閉じてください）")
            logging.info("--------------------------------------------------")

        except PlaywrightError as e:
            logging.error(f"投稿アクション中にエラーが発生しました: {e}")
            screenshot_path = os.path.join(OUTPUT_DIR, "error_post_action_screenshot.png")
            page.screenshot(path=screenshot_path)
            logging.info(f"エラー発生時のスクリーンショットを {screenshot_path} に保存しました。")
        finally:
            # ページを自動で閉じずに、ユーザーの操作を待つ
            logging.info("投稿アクションのスクリプトは完了しましたが、ブラウザは開いたままです。")
            # if 'page' in locals() and not page.is_closed():
            #     page.close()

def main():
    """
    実行引数を解析し、適切なタスクを実行する。
    """
    parser = argparse.ArgumentParser(description="楽天ROOMスクレイピング・投稿ツール")
    parser.add_argument('--task', type=str, default='analyze', choices=['analyze', 'post'], help='実行するタスク (analyze or post)')
    parser.add_argument('--url', type=str, help='投稿アクションの対象となるプロフィールURL')
    args = parser.parse_args()

    if args.task == 'analyze':
        run_analysis_task()
    elif args.task == 'post':
        execute_post_action(args.url)

if __name__ == "__main__":
    main()