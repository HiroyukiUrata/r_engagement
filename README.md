# 楽天ROOM エンゲージメント分析ツール

楽天ROOMのエンゲージメント活動を支援するための、スクレイピングおよび自動コメント投稿ツールです。

## 主な機能

- 楽天ROOMのお知らせページから「いいね」「フォロー」等のアクティビティを分析します。
- 分析結果に基づき、ユーザーごとに最適な感謝コメントを自動生成します。
- GUIを通じて対象ユーザーを選択し、コメント投稿の準備を自動化（コメント入力まで）します。

## セットアップ手順 (初回のみ)

このアプリケーションを新しいPCでセットアップするための手順です。

### 1. 前提条件

以下のソフトウェアがインストールされている必要があります。

1.  **Python (3.8以上を推奨)**
    - **Windowsの場合:** 公式サイトからインストーラーをダウンロードし、インストール時に「Add Python to PATH」にチェックを入れてください。
    - **Raspberry Pi (Raspbian)の場合:** 通常はプリインストールされています。ターミナルで `python3 --version` を実行してバージョンを確認してください。もしインストールされていない、またはバージョンが古い場合は、以下のコマンドでインストールします。
      ```bash
      sudo apt update
      sudo apt install python3 python3-pip python3-venv -y
      ```

2.  **Git**
    - **Windowsの場合:** 公式サイトからダウンロードしてインストールします。
    - **Raspberry Pi (Raspbian)の場合:**
      ```bash
      sudo apt install git -y
      ```

3.  **Google Chrome または Chromium**
    - **Windowsの場合:** Google Chromeをインストールしてください。
    - **Raspberry Pi (Raspbian)の場合:** この後の手順でPlaywrightが必要なブラウザをインストールするため、手動でのインストールは不要です。

### 2. プロジェクトのダウンロード

コマンドプロンプトやターミナルを開き、プロジェクトを配置したいディレクトリに移動してから、以下のコマンドを実行してプロジェクトをダウンロードします。

```bash
# 例: ホームディレクトリに移動
cd ~

# GitHubからプロジェクトをダウンロード
# これにより 'r_engagement' というフォルダが作成されます
git clone <あなたのリポジトリのURL>
```

### 3. 実行環境の構築

ダウンロードしたプロジェクトのフォルダ内で、アプリケーションを動かすための準備をします。

```bash
# 1. プロジェクトフォルダに移動
cd r_engagement

# 2. このプロジェクト専用のPython環境(venv)を作成
python -m venv venv

# 3. 作成した専用環境を有効化 (Linux / Raspberry Pi / macOSの場合)
source venv/bin/activate
# (Windowsの場合は .\venv\Scripts\activate)

# 4. 必要なライブラリをインストール
pip install -r requirements.txt

# 5. Playwrightのシステム依存関係をインストール (Linux/Raspberry Piのみ)
# このコマンドを実行すると、必要なライブラリをインストールするための `sudo apt-get install ...` から始まるコマンドが表示されます。
# 表示されたコマンドをコピー＆ペーストして実行してください。
playwright install-deps

# 6. Playwright専用のブラウザをインストール
playwright install
```

### 4. デバッグ用Chromeの起動設定

このアプリケーションは、デバッグモードで起動しているChrome(Chromium)に接続して動作します。

**Windowsの場合:**
プロジェクトフォルダ内の `start_chrome_debug.bat` をダブルクリックして起動します。

**Raspberry Pi / Linux の場合:**
このリポジトリには `start_chrome_debug.sh` が含まれています。
以下のコマンドを実行してスクリプトに実行権限を与え、起動します。
```bash
chmod +x start_chrome_debug.sh
./start_chrome_debug.sh
```

### 5. 実行

すべての準備が整いました。デバッグ用のChromeを起動した後、別のターミナルを開いて以下のコマンドでアプリケーションを起動します。

```bash
python app.py
```

---

## 開発者向け情報

### データベース
- ユーザーデータは `db/engagement_data.json` に保存されます。このファイルは `.gitignore` によりリポジトリには含まれません。

### コメントテンプレート
- 自動生成されるコメントのテンプレートは `comment_templates.json` で定義されています。

### プロンプト
- AIにコメントテンプレートを生成させるためのプロンプトは `PROMPT_TEMPLATES.md` に記載されています。