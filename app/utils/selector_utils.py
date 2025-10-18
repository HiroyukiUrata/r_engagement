import re

def convert_to_robust_selector(selector: str) -> str:
    """
    ハッシュ値を含む可能性のあるCSSセレクタを、より堅牢な形式に変換します。
    例: 'div.container--a3dH_ a.link--15_8Q' -> 'div[class*="container--"] a[class*="link--"]'

    Args:
        selector (str): 変換元のCSSセレクタ。

    Returns:
        str: 変換後のCSSセレクタ。
    """
    if not selector:
        return ""

    # セレクタを空白文字で分割し、各要素を処理
    parts = selector.split()
    robust_parts = []

    for part in parts:
        # 正規表現で `クラス名--ハッシュ値` のパターンを探す
        # 例: .container--a3dH_
        match = re.search(r'\.([\w-]+--[\w\d_-]+)', part)
        if match:
            class_with_hash = match.group(1) # container--a3dH_
            class_base = class_with_hash.split('--')[0] + '--' # container--
            # `.` を含む元のクラス指定を `[class*="..."]` に置換
            robust_part = part.replace(f'.{class_with_hash}', f'[class*="{class_base}"]')
            robust_parts.append(robust_part)
        else:
            robust_parts.append(part)

    return " ".join(robust_parts)