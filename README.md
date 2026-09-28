# hateblo-posting

はてなブログ AtomPub API で記事を操作する Python 3.11+ 用CLIです。
Markdownを保ったまま、他のツールが出力したLaTeX数式をはてなの数式記法へ変換します。

## インストール

```sh
uv sync --locked
uv run hateblo --help
# 常用する場合（このリポジトリ内で実行）
uv tool install .
```

`pip install .` でもインストールできます。以下はインストール後の `hateblo` コマンドの例です。

## 認証情報

ブログの「設定 → 詳細設定 → AtomPub」のはてなID、ブログID、APIキーを使います。
ブログIDには独自ドメインではなく、AtomPubのエンドポイントに記載された元のドメインを指定します。

```sh
hateblo --user your-id --blog your-id.hatenablog.com auth login
hateblo auth status
hateblo auth logout
```

`login` はAPIキーを非表示入力し、Windows Credential Manager、macOS Keychain、
Linux Secret Service / KWalletのいずれかに保存します。平文ストアへのフォールバックはしません。
OSストアが使えないヘッドレス環境では `HATENA_API_KEY` にCIのシークレットを設定してください。
キーを引数、ソースコード、`.env`、設定ファイルに書く必要はありません。
`status` は設定の存在確認で、APIに接続する認証テストではありません。
`logout` は指定アカウントのOSストアのキーだけを削除します。環境変数は別途解除してください。

はてなIDとブログIDのみを `%APPDATA%/hateblo-posting/config.json`（Windows）、
`$XDG_CONFIG_HOME/hateblo-posting/config.json`（その他、既定 `~/.config`）に保存します。
設定の優先順位は `--user / --blog` → `HATENA_USER / HATENA_BLOG` → 保存設定です。
APIキーは `HATENA_API_KEY` → 選択アカウントのOSストアです。
アカウントオプションはサブコマンドの**前**に置きます。

通信先は `https://blog.hatena.ne.jp` の指定ブログに限定し、リダイレクトには従いません。
HTTPS Basic認証を使用します。エラー表示にAPIレスポンス本文・認証ヘッダーを含めません。

## 記事の操作

**新規投稿前に、ブログ側の編集モードをMarkdownに設定してください。**
AtomPubは新規記事にブログの編集モード、更新には元の記事の編集モードを使用します。
APIの `content type` を変えて編集モードを切り替えることはできません。

```sh
hateblo list                   # 1ページと次ページURLをJSON出力
hateblo list --all             # 全ページ
hateblo get 123456789          # 本文・カテゴリ・公開状態などをJSON出力
hateblo get 123456789 --body    # 元の本文だけを出力
hateblo categories

hateblo create article.md --title "記事タイトル" --dry-run
hateblo create article.md --title "記事タイトル"   # 既定は下書き
hateblo create article.md --title "記事タイトル" --publish
hateblo update 123456789 article.md
hateblo update 123456789 --title "新タイトル"
hateblo update 123456789 --publish
hateblo update 123456789 --draft
hateblo update 123456789 --category Python --category 数学
hateblo update 123456789 --clear-categories
hateblo delete 123456789 --yes
```

新規作成・更新のJSON出力の `id` を次回の操作に使います。
更新では指定しないタイトル・本文・カテゴリ・公開状態・投稿日時を取得済み記事から保持します。
明示的な `--publish` / `--draft` は予約投稿状態を解除します。
同時編集の競合検知は行わないので、Web編集とCLI更新を同時に行わないでください。
`--no-convert` で変換を無効化すると、Markdown以外の記事の元記法も送信できます。
更新時の `--dry-run` は現状取得のためAPIを読み取りますが、書き込みません。
新規作成の `--dry-run` は認証もネットワークも不要です。
通信失敗時に書き込みを自動再試行しません。特に新規投稿は一覧で成否を確認してください。
固定ページ、予約投稿の新規設定、画像アップロードは対象外です。

## 他ツールの記事を取り込む

```yaml
---
title: 二次方程式
categories: [数学, LaTeX]
slug: quadratic-equation
---
```

先頭のYAML front matterから `title`、`categories`（未指定時は `tags`）、
`custom_url`（未指定時は `slug`）を読み取り、本文から除去します。
CLIで指定した値が優先されます。`categories: []` はカテゴリの全削除です。
`draft`・`date` などその他のキーは投稿設定に使いません。公開は必ず `--publish` で指定します。
更新で渡すファイルのfront matterも更新対象になります。

```sh
hateblo convert article.md -o article.hatena.md
hateblo convert article.md --strip-front-matter
hateblo create article.md --dry-run
# 標準入力も利用可能
cat article.md | hateblo convert -
```

`convert` は既定でfront matterをそのまま残します。投稿コマンドは常に除去します。
数式以外の見出し・表・リンク・通常テキストは維持し、改行はLFに統一します。

| 入力 | 出力 |
| --- | --- |
| `$x_i^2$` / `\(x_i^2\)` | `[$ x_i^2 $]` |
| `$$x_i^2$$` / `\[x_i^2\]` | `[$ \displaystyle x_i^2 $]` |
| `math` コードフェンス | `[$ \displaystyle … $]` |

GitHubの ``$`x_i`$`` にも対応します。表示数式は独立した段落として入力してください。
複数行数式は1行にまとめ、TeXの行末コメントを除去します。`\\` や `&` は維持します。
`\displaystyle` で表示用の数式サイズにしますが、自動的な中央揃えは行いません。
コードフェンス（`math` 以外）、インデントコード、インラインコード、HTMLブロック、
リンク先は変換しません。既存の `[$ … $]` の区切りは保持し、内部の既知の
非互換コマンドだけを後述の互換変換で扱います。旧 `[tex:…]` は通知のみです。
`math` フェンスの変換はトップレベルのみです。

単一 `$` は直後・直前に空白がない組だけ変換します。`\$` はドルとして保持します。
通貨と数式は完全に自動判別できないため、通貨の多い文章では `--no-dollar-math` と
`\(…\)` / `\[…\]` を使ってください。未完の明示的な数式区切りはエラーにします。
独自Markdown拡張・任意のHTML内の数式・ローカル画像のアップロードは変換対象外です。

2026年7月追加の `[$ … $]` を使うため、Markdown用エスケープや外部MathJaxの追加が不要です。
参考記事のように独自MathJaxを設定済みの場合も、標準の数式記法で表示を確認してください。

## MathJaxの互換変換・通知

通常の `\llbracket x \rrbracket` を `\mathopen{[\![} x \mathclose{]\!]}` に
近似変換します。形や間隔は元の専用記号と完全には一致しないため、警告を出します。
`\left\llbracket`、`\bigl\llbracket` など拡大指定付きの形は変換せず、手動確認を促します。
公式に移行が案内されている `\bbFont` → `\mathbb`、`\scr` → `\mathscr` にも対応します。

```sh
hateblo convert article.md --math-compat warn -o article.hatena.md
hateblo create article.md --math-compat strict --dry-run
hateblo convert article.md --math-compat off
```

- `warn`（既定）: 既知の安全な置換を実施し、全診断を標準エラー出力に出します。
- `strict`: 近似・移行・変換保留のいずれかがあれば終了コード1で停止します。
  出力ファイルを上書きせず、記事取得・投稿・更新の通信も行いません。
- `off`: この互換変換と診断を無効化します。数式区切りの変換は継続します。
  `--no-convert` は投稿時の数式変換・互換診断をまとめて無効化します。

```text
article.md:12:3: warning[MATH001]: \llbracket: \mathopen{[\![} に近似変換しました。括弧の形・間隔を確認してください。
```

行・列はfront matterを含む入力ファイルの1始まりです。本文・JSON・XMLには警告を混ぜません。
`strict` は**登録済みルールの診断をエラーにする機能**であり、任意の未知コマンドや
TeX構文エラーを網羅的に検出する機能ではありません。独自マクロを使う場合は `off` も選べます。
方法の比較・検出範囲・今後の検証方式は[設計メモ](docs/math-compatibility.md)に記載しています。

## 開発

```sh
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

テストは偽のHTTPトランスポートと資格情報ストアを使い、実ブログには投稿しません。
実際のブログでの表示や認証は、利用者のアカウントで下書きを作成して確認してください。

## 仕様・参考

- [はてなブログAtomPub API](https://developer.hatena.ne.jp/ja/documents/blog/apis/atom/)
- [新しいtex記法の公式案内](https://staff.hatenablog.com/entry/2026/07/14/181844)
- [MathJaxとMarkdownの衝突についての参考記事](https://o-treetree.hatenablog.com/entry/mathjaxexample)
