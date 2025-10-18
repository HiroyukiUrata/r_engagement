import logging
import json
import os
import time
import re
from app.core.base_task import BaseTask

THANK_YOU_PROMPT_FILE = "app/prompts/thank_you_prompt.txt"
DEBUG_DIR = "db/debug"

class ScrapeAndAnalyzeUsersTask(BaseTask):
    """
    [タスク1] ユーザーをスクレイピングして分析する
    - 認証が必要なページにアクセスし、ユーザー情報を取得する
    """
    def __init__(self, target_account: str, count: int = 30, **kwargs):
        super().__init__(count=count, **kwargs)
        self.target_account = target_account
        self.action_name = f"ユーザー分析 ({target_account})"
        self.use_auth_profile = True  # ログインセッションを利用する
        self.needs_browser = True

    def _execute_main_logic(self):
        page = self.page
        page.goto("https://room.rakuten.co.jp/items", wait_until="domcontentloaded")

        try: # メインのtry-exceptブロック
            logging.info("「お知らせ」リンクを探しています...")
            # "お知らせ" というテキストを持つリンク要素を特定
            notification_link_locator = page.get_by_role("link", name="お知らせ")
            notification_link_locator.wait_for(state='visible', timeout=15000)
            notification_link_locator.click()

            # ページ遷移を待つ
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            logging.info(f"お知らせページに遷移しました。URL: {page.url}")

            # 「アクティビティ」セクションが表示されるまで待つ
            activity_title_locator = page.locator('div.title:has-text("アクティビティ")')
            try: # アクティビティセクションの存在確認
                activity_title_locator.wait_for(state='visible', timeout=10000)
                logging.info("「アクティビティ」セクションが見つかりました。処理を続行します。")
            except Exception: # TimeoutErrorはPlaywrightの内部エラーなので一般的なExceptionで捕捉
                logging.info("「アクティビティ」セクションが見つかりませんでした。処理対象はありません。タスクを終了します。")
                return [] # アクティビティがなければ空のリストを返して終了

            # --- ユーザー情報の取得処理 ---
            # self.target_countはBaseTaskで設定される
            max_users_to_scrape = self.target_count
            logging.info(f"最大{max_users_to_scrape}件のユーザー情報を取得します...")

            # --- フェーズ1: お知らせリストから基本情報を一括収集 ---
            logging.info("--- フェーズ1: お知らせリストから基本情報を収集します。 ---")
            
            # スクロールして通知を読み込む
            last_count = 0
            max_scroll_attempts = 15 # 無限ループ防止
            for attempt in range(max_scroll_attempts):
                notification_list_items = page.locator("li[ng-repeat='notification in notifications.activityNotifications']")
                current_count = notification_list_items.count()
                
                # 収集目標数（マージンを持たせて多めに）を超えたか、新しい項目がなければ終了
                if current_count >= (max_users_to_scrape + 40) or current_count == last_count:
                    if current_count == last_count:
                        logging.info("スクロールしても新しい通知が読み込まれませんでした。収集を終了します。")
                    else:
                        logging.info(f"十分な数の通知（{current_count}件）を収集しました。")
                    break
                
                last_count = current_count
                logging.info(f"  スクロール {attempt + 1}回目: {current_count}件の通知を検出。ページ最下部へスクロールします...")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2) # 読み込み待機

            count = page.locator("li[ng-repeat='notification in notifications.activityNotifications']").count()
            all_notifications = []
            for i in range(count): # 読み込んだすべての通知を処理
                item = notification_list_items.nth(i)
                try: # 個々の通知アイテムの処理
                    # 先にユーザー名を取得しておく
                    user_name_element = item.locator("span.notice-name span.strong").first
                    user_name = ""
                    if user_name_element.is_visible():
                        user_name = user_name_element.inner_text().strip()

                    profile_image_url = item.locator("div.left-img img").get_attribute("src")
                    # プロフィール画像がないユーザーは対象外
                    if "img_noprofile.gif" in profile_image_url:
                        log_name = f"「{user_name}」" if user_name else ""
                        logging.debug(f"  スキップ: プロフィール画像がないユーザーです。{log_name}")
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
                    logging.warning(f"{i+1}番目のユーザー情報取得中にエラー: {item_error}")
            
            # --- フェーズ2: ユーザー単位で情報を集約し、優先度を付ける ---
            logging.info(f"--- フェーズ2: {len(all_notifications)}件の通知をユーザー単位で集約し、優先度を付けます。 ---")
            aggregated_users = {}
            for notification in all_notifications:
                user_id = notification['id']
                if user_id not in aggregated_users:
                    aggregated_users[user_id] = {
                        'id': user_id, 'name': notification['name'], 'profile_image_url': notification['profile_image_url'],
                        'like_count': 0, 'collect_count': 0, 'is_following': notification['is_following'],
                        'latest_action_text': notification['action_text'], 'latest_action_timestamp': notification['action_timestamp']
                    }
                
                # アクション回数をカウント
                if "いいねしました" in notification['action_text']:
                    aggregated_users[user_id]['like_count'] += 1
                if "コレ！しました" in notification['action_text']:
                    aggregated_users[user_id]['collect_count'] += 1

                # 最新の情報を更新
                if notification['action_timestamp'] > aggregated_users[user_id]['latest_action_timestamp']:
                    aggregated_users[user_id].update({
                        'is_following': notification['is_following'],
                        'latest_action_text': notification['action_text'],
                        'latest_action_timestamp': notification['action_timestamp']
                    })
            logging.info(f"  -> {len(aggregated_users)}人のユニークユーザーに集約しました。")

            # --- ユーザーにカテゴリを付与 ---
            for user in aggregated_users.values():
                like_count = user['like_count']
                is_following = user['is_following']
                collect_count = user['collect_count']
                
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
            
            # --- フェーズ3: 優先度に基づいてソートし、URLを取得 ---
            sorted_users = sorted(aggregated_users.values(), key=lambda u: (-u['like_count'], u['is_following'], -(u['like_count'] > 0 and u['collect_count'] > 0)), reverse=False)
            users_to_process = sorted_users[:max_users_to_scrape] # 目標件数でスライス
            logging.info(f"フェーズ3: 優先度順にソートし、上位{len(users_to_process)}人のURLを取得します。")

            logging.info("--- 処理対象ユーザーとカテゴリ一覧 ---")
            for i, user in enumerate(users_to_process):
                logging.info(f"  {i+1}. {user['name']} ({user['category']})")
            logging.info("------------------------------------")

            scraped_users = []
            if False: # ★★★ URL取得処理を一時的に無効化 ★★★
                for i, user_info in enumerate(users_to_process):
                    logging.debug(f"--- {i+1}/{len(users_to_process)}番目のユーザー「{user_info['name']}」(いいね:{user_info['like_count']}回)のURLを取得中... ---")
                    profile_page_url = ""
                    try:
                        # プロフィール画像をクリックして新しいタブを開く
                        # 該当ユーザーの最初の通知アイテムを探す
                        user_li_locator = page.locator(f"li[ng-repeat='notification in notifications.activityNotifications']:has(img[src=\"{user_info['profile_image_url']}\"])").first
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

                        # 画像をクリックして、現在のタブでページ遷移する
                        image_container_locator.click()
                        
                        # ページ遷移が完了するのを待つ
                        page.wait_for_load_state("domcontentloaded", timeout=15000)
                        profile_page_url = page.url
                        logging.debug(f"  -> 取得したURL: {profile_page_url}")

                        # お知らせページに戻る
                        page.go_back(wait_until="domcontentloaded")
                        
                        # 最終的なユーザー情報を構築
                        user_info['profile_page_url'] = profile_page_url
                        user_info['bio'] = "" # bioは別途取得が必要
                        scraped_users.append(user_info)

                    except Exception as url_error:
                        logging.warning(f"ユーザー「{user_info['name']}」のURL取得中にエラーが発生しました: {url_error}")
                        # エラーが発生しても、URLなしで情報を追加する
                        user_info['profile_page_url'] = "取得失敗"
                        user_info['bio'] = ""
                        scraped_users.append(user_info)
                    
                    time.sleep(1) # サーバーへの負荷を軽減するための短い待機
            else:
                # URL取得をスキップし、集約した情報だけでリストを作成
                logging.info("URL取得処理はスキップされました。")
                for user_info in users_to_process:
                    user_info['profile_page_url'] = "（取得スキップ）"
                    user_info['bio'] = ""
                    scraped_users.append(user_info)

            logging.info(f"--- ユーザー分析完了: {len(scraped_users)}人のユーザー情報を取得しました。 ---")
            return scraped_users

        except Exception as e:
            logging.error(f"お知らせページへの遷移またはユーザー分析中にエラーが発生しました: {e}", exc_info=True)
            raise

class GenerateThankYouMessageTask(BaseTask):
    """
    [タスク2] ユーザー情報にお礼の文章を紐づける
    - create_caption.pyを参考に、Geminiを使ってお礼文を生成する
    """
    def __init__(self, users_data: list = None, **kwargs):
        super().__init__(**kwargs) # countは不要なので親クラスのデフォルトに任せる
        self.users_data = users_data
        self.action_name = "お礼文作成 (Gemini)"
        self.use_auth_profile = False # 認証は不要
        self.needs_browser = True

    def _execute_main_logic(self):
        if not self.users_data:
            logging.info("お礼文作成対象のユーザーがいません。")
            return []

        if not os.path.exists(THANK_YOU_PROMPT_FILE):
            logging.error(f"プロンプトファイルが見つかりません: {THANK_YOU_PROMPT_FILE}")
            raise FileNotFoundError(f"Prompt file not found: {THANK_YOU_PROMPT_FILE}")

        logging.info(f"{len(self.users_data)}人分のお礼メッセージを生成します...")

        # 各ユーザーに空の `thank_you_message` を追加
        for user in self.users_data:
            user['thank_you_message'] = ""

        try:
            with open(THANK_YOU_PROMPT_FILE, "r", encoding="utf-8") as f:
                prompt_template = f.read()

            json_string = json.dumps(self.users_data, indent=2, ensure_ascii=False)
            full_prompt = f"{prompt_template}\n\n以下のJSON配列の各要素について、`thank_you_message`を生成してください。元のJSON配列の形式を維持して返してください。\n\n```json\n{json_string}\n```"

            # (create_caption.pyと同様のGemini操作)
            page = self.page
            page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=60000)
            prompt_input = page.get_by_label("ここにプロンプトを入力してください").or_(page.get_by_role("textbox"))
            prompt_input.wait_for(state="visible", timeout=30000)
            page.evaluate("text => navigator.clipboard.writeText(text)", full_prompt)
            prompt_input.press("Control+V")
            prompt_input.press("Enter")
            logging.info("プロンプトを送信しました。")

            page.get_by_label("生成を停止").wait_for(state="hidden", timeout=180000)
            copy_button_locator = page.locator(".response-container-content").last.get_by_label("コードをコピー")
            copy_button_locator.wait_for(state="visible", timeout=30000)
            copy_button_locator.click()
            page.wait_for_timeout(5000)

            generated_json_str = page.evaluate("() => navigator.clipboard.readText()")
            json_part_str = extract_json_from_text(generated_json_str)
            cleaned_str = fix_indentation(clean_raw_json(json_part_str))
            generated_users = json.loads(cleaned_str)

            logging.info("メッセージ生成が完了しました。")
            return generated_users

        except Exception as e:
            logging.error(f"お礼文の生成中にエラーが発生しました: {e}", exc_info=True)
            raise

# --- create_caption.py から移動してきた補助関数 ---
def extract_json_from_text(text: str) -> str:
    """テキストからJSON部分（```json ... ```）を抽出する"""
    match = re.search(r"```json\s*([\s\S]+?)\s*```", text)
    if match:
        return match.group(1).strip()
    return text # マッチしない場合は元のテキストをそのまま返す

def clean_raw_json(raw_json_str: str) -> str:
    """不完全なJSON文字列から余分な文字を削除する"""
    cleaned = raw_json_str.strip()
    if cleaned.startswith("`"): cleaned = cleaned.lstrip("`")
    if cleaned.endswith("`"): cleaned = cleaned.rstrip("`")
    return cleaned

def fix_indentation(json_string: str) -> str:
    """JSON文字列のインデントを修正する"""
    return json.dumps(json.loads(json_string), indent=2, ensure_ascii=False)

def scrape_and_analyze_users_task(target_account: str, **kwargs):
    """ラッパー関数: ユーザー分析"""
    task = ScrapeAndAnalyzeUsersTask(target_account=target_account, **kwargs)
    return task.run()

def generate_thank_you_message_task(users_data: list, **kwargs):
    """ラッパー関数: お礼文作成"""
    task = GenerateThankYouMessageTask(users_data=users_data, **kwargs)
    return task.run()
