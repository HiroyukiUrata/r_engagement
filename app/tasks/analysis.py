import logging
import os
import re
import sys
import time
import json
import unicodedata
import random
from playwright.sync_api import sync_playwright, Error as PlaywrightError

# --- プロジェクトルートの定義 ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- ユーティリティのインポート ---
sys.path.insert(0, PROJECT_ROOT)
from app.utils.selector_utils import convert_to_robust_selector

# --- 出力ディレクトリの定義 ---
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")

# --- 設定 ---
TARGET_URL = "https://room.rakuten.co.jp/items"
MAX_USERS_TO_SCRAPE = 50
OUTPUT_JSON_FILE = "scraping_results.json"
COMMENT_TEMPLATES_FILE = os.path.join(PROJECT_ROOT, "comment_templates.json")

# --- ロガーの基本設定 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def extract_natural_name(full_name: str) -> str:
    """
    絵文字や装飾が含まれる可能性のあるフルネームから、自然な名前の部分を抽出する。
    例: '春🌷身長が3cm伸びました😳' -> '春'
    例: '𝐬𝐚𝐲𝐮¹²²⁵𝓡' -> 'sayu'
    例: '❁mizuki❁' -> 'mizuki'
    """
    if not full_name:
        return ""

    # Unicodeの絵文字や特定の記号を区切り文字として定義
    separators = re.compile(
        r'['
        u'\u2600-\u27BF'          # Miscellaneous Symbols
        u'\U0001F300-\U0001F5FF'  # Miscellaneous Symbols and Pictographs
        u'\U0001F600-\U0001F64F'  # Emoticons
        u'\U0001F680-\U0001F6FF'  # Transport & Map Symbols
        u'\U0001F1E0-\U0001F1FF'  # Flags (iOS)
        u'\U0001F900-\U0001F9FF'  # Supplemental Symbols and Pictographs
        u'|│￤＠@/｜*＊※☆★♪#＃♭🎀' # 全角・半角の記号類
        u'|│￤＠@/｜*＊※☆★♪#＃♭🎀' # 全角・半角の記号類（♡は意図的に除外）
        u']+' # 連続する区切り文字を一つとして扱う
    )

    # 区切り文字で文字列を分割
    parts = separators.split(full_name)

    # 分割されたパーツから、空でない最初の要素を探す
    # 分割されたパーツから、空でない最初の要素を候補とする
    name_candidate = ""
    for part in parts:
        cleaned_part = part.strip()
        if cleaned_part:
            return cleaned_part
            name_candidate = cleaned_part
            break
    
    if not name_candidate:
        return full_name.strip() # 候補が見つからなければ元の名前を返す

    # 適切なパーツが見つからなかった場合（名前全体が記号だった場合など）、元の名前をフォールバックとして返す
    return full_name.strip()
    # 候補の文字列を正規化 (例: 𝐬𝐚𝐲𝐮¹²²⁵𝓡 -> sayu1225R)
    normalized_name = unicodedata.normalize('NFKC', name_candidate)

    # 正規化された名前から、最初の数字や特定の記号までの部分を抽出
    match = re.search(r'[\d_‐-]', normalized_name)
    if match:
        return normalized_name[:match.start()]
    
    return normalized_name

def main():
    """
    楽天ROOMのお知らせページからユーザー情報をスクレイピングするメイン関数
    """
    with sync_playwright() as p:
        # --- 1. ブラウザの起動 ---
        logging.info("デバッグモードで起動中のChrome (ポート9222) に接続します。")
        browser = None
        for i in range(5):
            try:
                browser = p.chromium.connect_over_cdp("http://localhost:9222")
                logging.info("Chromeへの接続に成功しました。")
                break
            except Exception:
                logging.warning(f"接続に失敗しました。3秒後に再試行します... ({i+1}/5)")
                time.sleep(3)

        if not browser:
            logging.error("Chromeへの接続に失敗しました。")
            logging.error("アプリが起動したChromeウィンドウを閉じずに、このスクリプトを実行してください。")
            return

        try:
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
            activity_title_locator = page.locator("div.title[ng-show='notifications.activityNotifications.length > 0']")
            try:
                activity_title_locator.wait_for(state='attached', timeout=10000)
            except Exception:
                logging.info("「アクティビティ」セクションが見つかりませんでした。処理対象はありません。")
                return

            logging.info("遅延読み込みされるコンテンツを表示するため、ページをスクロールします。")
            last_count = 0
            for attempt in range(4):
                notification_list_items = page.locator("li[ng-repeat='notification in notifications.activityNotifications']")
                current_count = notification_list_items.count()

                if attempt > 2 and current_count == last_count:
                    logging.info("スクロールしても新しいアクティビティ通知は読み込まれませんでした。")
                    break

                last_count = current_count
                logging.info(f"  スクロール {attempt + 1}回目: {current_count}件のアクティビティ通知を検出。")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1500)

            # --- 4. データ抽出 ---
            logging.info(f"--- フェーズ1: {notification_list_items.count()}件の通知から基本情報を収集します。 ---")
            all_notifications = []
            for item in notification_list_items.all():
                try:
                    user_name_element = item.locator("span.notice-name span.strong").first
                    if not user_name_element.is_visible():
                        continue

                    user_name = user_name_element.inner_text().strip()
                    profile_image_url = item.locator("div.left-img img").get_attribute("src")

                    if "img_noprofile.gif" in profile_image_url:
                        continue

                    if user_name:
                        user_id = "unknown"
                        match = re.search(r'/([^/]+?)(?:\.\w+)?(?:\?.*)?$', profile_image_url)
                        if match: user_id = match.group(1)

                        action_text = item.locator("div.right-text > p").first.inner_text()
                        action_timestamp = item.locator("span.notice-time").first.get_attribute("title")
                        is_following = not item.locator("span.follow:has-text('未フォロー')").is_visible()

                        all_notifications.append({
                            'id': user_id, 'name': user_name.strip(),
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
                        'like_count': 0, 'collect_count': 0,
                        'follow_count': 0, 'comment_count': 0, # フォローとコメントのカウンターを追加
                        'is_following': notification['is_following'],
                        'latest_action_timestamp': notification['action_timestamp']
                    }
                
                if "いいねしました" in notification['action_text']:
                    aggregated_users[user_id]['like_count'] += 1
                if "コレ！しました" in notification['action_text']:
                    aggregated_users[user_id]['collect_count'] += 1
                if "あなたをフォローしました" in notification['action_text']:
                    aggregated_users[user_id]['follow_count'] += 1
                if "あなたの商品にコメントしました" in notification['action_text']:
                    aggregated_users[user_id]['comment_count'] += 1

                if notification['action_timestamp'] > aggregated_users[user_id]['latest_action_timestamp']:
                    aggregated_users[user_id].update({
                        'is_following': notification['is_following'],
                        'latest_action_text': notification['action_text'],
                        'latest_action_timestamp': notification['action_timestamp']
                    })
            logging.info(f"  -> {len(aggregated_users)}人のユニークユーザーに集約しました。")
            
            categorized_users = []
            for user in aggregated_users.values():
                like_count = user['like_count']
                is_following = user['is_following']
                follow_count = user['follow_count']
                collect_count = user['collect_count']
                
                if like_count >= 3:
                    user['category'] = "いいね多謝"
                elif follow_count > 0 and like_count > 0:
                    user['category'] = "新規フォロー＆いいね感謝"
                elif like_count > 0 and not is_following: 
                    user['category'] = "未フォロー＆いいね感謝"
                elif like_count > 0 and collect_count > 0:
                    user['category'] = "いいね＆コレ！感謝"
                elif follow_count > 0 and like_count == 0:
                    user['category'] = "新規フォロー"
                elif like_count > 0:
                    user['category'] = "いいね感謝"
                else:
                    user['category'] = "その他"
                
                # 「その他」カテゴリは処理対象から除外
                if user['category'] != "その他":
                    categorized_users.append(user)

            # --- フェーズ3: 優先度に基づいてソート ---
            logging.info(f"--- フェーズ3: 優先度順にソートし、上位{MAX_USERS_TO_SCRAPE}件を抽出します。 ---")
            sorted_users = sorted(
                categorized_users,
                key=lambda u: (
                    -u['like_count'], # 1. いいねの数が多い（最優先）
                    -(u['follow_count'] > 0 and u['like_count'] > 0), # 2. 新規フォロー＆いいねがある
                    -(u['follow_count'] > 0 and u['like_count'] == 0), # 3. 新規フォローのみ
                    u['is_following'], # 4. フォロー状況
                    -(u['collect_count'] > 0) # 5. コレ！がある
                )
            )
            
            users_to_process = sorted_users[:MAX_USERS_TO_SCRAPE]

            # --- フェーズ4: URL取得 ---
            logging.info(f"--- フェーズ4: 上位{len(users_to_process)}人のプロフィールURLを取得します。 ---")
            final_user_data = []
            last_scroll_position = 0  # スクロール位置を記憶する変数を初期化

            for i, user_info in enumerate(users_to_process):
                logging.debug(f"  {i+1}/{len(users_to_process)}: 「{user_info['name']}」のURLを取得中...")
                try:
                    # 前回のスクロール位置に戻す
                    if last_scroll_position > 0:
                        page.evaluate(f"window.scrollTo(0, {last_scroll_position})")
                        logging.debug(f"  スクロール位置を {last_scroll_position}px に復元しました。")

                    user_li_locator = page.locator(f"li[ng-repeat='notification in notifications.activityNotifications']:has-text(\"{user_info['name']}\")").first
                    image_container_locator = user_li_locator.locator("div.left-img")
                    
                    max_scroll_attempts_find = 15
                    is_found = False
                    for attempt in range(max_scroll_attempts_find):
                        if image_container_locator.count() > 0 and image_container_locator.is_visible():
                            is_found = True
                            break
                        logging.debug(f"  ユーザー「{user_info['name']}」の画像が見つかりません。スクロールします... ({attempt + 1}/{max_scroll_attempts_find})")
                        page.evaluate("window.scrollBy(0, 500)")
                        time.sleep(1)      

                    if not is_found:
                        raise PlaywrightError(f"スクロールしてもユーザー「{user_info['name']}」の要素が見つかりませんでした。")

                    # ページ遷移の直前に現在のスクロール位置を記憶
                    last_scroll_position = page.evaluate("window.scrollY")
                    image_container_locator.click()
                    
                    user_info['profile_page_url'] = page.url
                    logging.debug(f"  -> 取得したURL: {page.url}")
                    
                    page.go_back(wait_until="domcontentloaded")
                except Exception as url_error:
                    logging.warning(f"  ユーザー「{user_info['name']}」のURL取得中にエラー: {url_error}")
                    user_info['profile_page_url'] = "取得失敗"
                
                final_user_data.append(user_info)
                time.sleep(0.5)

            logging.info("\n--- 分析完了: 処理対象ユーザー一覧 ---")
            for i, user in enumerate(final_user_data):
                logging.info(f"  {i+1:2d}. {user['name']:<20} (カテゴリ: {user['category']}, URL: {user.get('profile_page_url', 'N/A')})")
            logging.info("------------------------------------")

            # --- フェーズ5: コメント生成 ---
            logging.info(f"--- フェーズ5: {len(final_user_data)}人のユーザーにコメントを紐付けます。 ---")
            try:
                with open(COMMENT_TEMPLATES_FILE, 'r', encoding='utf-8') as f:
                    comment_templates = json.load(f)
                
                for user in final_user_data:
                    category = user.get('category', 'その他')
                    templates = comment_templates.get(category, comment_templates.get('その他', []))
                    if templates:
                        comment_template = random.choice(templates)
                        natural_name = extract_natural_name(user.get('name', ''))
                        if natural_name:
                            # 名前が取得できた場合は、名前を挿入
                            user['comment_text'] = comment_template.format(user_name=natural_name)
                        else:
                            # 名前が取得できなかった場合は、プレースホルダー部分を削除して不自然さをなくす
                            user['comment_text'] = comment_template.replace("{user_name}さん、", "").strip()
                    else:
                        user['comment_text'] = "ご訪問ありがとうございます！" # フォールバック
            except FileNotFoundError:
                logging.error(f"コメントテンプレートファイルが見つかりません: {COMMENT_TEMPLATES_FILE}")
            except Exception as e:
                logging.error(f"コメント生成中にエラーが発生しました: {e}")

            # --- フェーズ6: 結果をJSONファイルに保存 ---
            try:
                os.makedirs(OUTPUT_DIR, exist_ok=True)
                output_path = os.path.join(OUTPUT_DIR, OUTPUT_JSON_FILE)
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(final_user_data, f, ensure_ascii=False, indent=4)
                logging.info(f"結果を {output_path} に保存しました。")
            except Exception as e:
                logging.error(f"JSONファイルへの保存中にエラーが発生しました: {e}")

        except Exception as e:
            logging.error(f"処理中にエラーが発生しました: {e}", exc_info=True)
            screenshot_path = os.path.join(OUTPUT_DIR, "error_screenshot.png")
            if 'page' in locals() and not page.is_closed(): page.screenshot(path=screenshot_path)
            logging.info(f"エラー発生時のスクリーンショットを {screenshot_path} に保存しました。")
        finally:
            logging.info("処理が完了しました。")
            if 'page' in locals() and not page.is_closed():
                page.close()

if __name__ == "__main__":
    main()