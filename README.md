# dvd_player

初期構築段階のプロジェクトです。Python製の英語学習用DVDプレイヤーを計画しています。画面は左に動画、右に英語／日本語を切り替える字幕一覧を配置します。詳細は仕様案で整理中で、実装はまだありません。

## ディレクトリ構成

- `00.secret/`: ローカルの秘密情報（Git管理対象外）
- `01.doc/`: 要件・設計・テスト仕様
- `02.src/`: アプリケーションのソースコード
- `03.log/`: 再利用するプロンプト、進捗、残課題
- `GitSecurityTool/`: コミット前のセキュリティ検査用サブモジュール

## 開発環境のセットアップ

セキュリティ検査にはGitおよびPython 3.11以上が必要です。

```powershell
git submodule update --init --recursive
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install pre-commit
.\.venv\Scripts\python.exe -m pre_commit install
.\.venv\Scripts\python.exe -m pre_commit run --all-files
```

秘密情報は環境変数または`00.secret/`で管理してください。

## ドキュメント

- [詳細設計書（HTML）](01.doc/詳細設計書.html)

- [基本設計書（HTML）](01.doc/基本設計書.html)

- [仕様書（HTML・仕様案v0.2）](01.doc/仕様書.html)

- [プロジェクト作成ルール](プロジェクト作成ルール.txt)
- [現在の状況](03.log/current_status.txt)
- [残課題](03.log/leftover_tasks.txt)

## ライセンス

本プロジェクトのライセンスは未定義です。GitSecurityToolは同ツールのライセンスを確認してください。

検査設定はルートの`.pre-commit-config.yaml`に配置しています。
サブモジュール内の`GitSecurityTool/`にある検査コードを、プロジェクト専用仮想環境で実行します。
個人用キーワードは`GitSecurityTool/GitSecurityTool/keywords.yaml`です。
既に追跡されている配布ファイルのため、個人用の値に変更した場合はサブモジュール内でもステージしないでください。
検査ログとキーワードファイルには、サブモジュールのローカル除外設定を追加しています。
