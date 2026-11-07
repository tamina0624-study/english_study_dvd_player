# 英語学習用DVDプレイヤー

Pythonで実装中のWindows用DVDプレイヤーです。左に動画、右に英語／日本語の字幕一覧を配置します。

## 現在の実装

- DVDドライブ列挙、読み込み、タイトル・前後チャプター選択
- 再生／一時停止、停止、音量、シーク、連続操作可能な2秒戻し
- 英語／日本語タブ、字幕画像一覧、現在字幕の強調と自動追従
- 事前処理済み字幕データ（JSON＋画像）の読み込みと検証
- VLCが利用できない場合の案内

**DVD字幕の自動抽出は未実装です。** 現在は事前処理済み字幕の読み込み口と同期処理まで実装しています。実DVDでの再生・タイトル選択・シーク・同期精度は未検証です。この環境ではVLC本体が見つからないため、映像再生を確認していません。

## セットアップ・起動

Python 3.11以上、Windows、Pythonと同じビット数の[VLC](https://www.videolan.org/vlc/download-windows.html)、DVDドライブが必要です。初期開発環境はPython 3.13です。

プロジェクトルートで実行します。仮想環境が既にある場合は作成を省略できます。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m dvd_player
```

セットアップ済みなら、`起動.ps1`でも起動できます。

```powershell
.\起動.ps1
```

VLCが標準のインストール先にない場合は、VLCフォルダを`VLC_HOME`環境変数に指定してください。フォルダ内の`libvlc.dll`と`plugins`を使用します。

今回導入・確認したパッケージはPySide6 6.12.0、python-vlc 3.0.21203です。DVDとの互換性を確認した組合せではありません。

## 操作方法

1. DVDを挿入し、必要なら「ドライブ再検索」を押します。
2. ドライブを選び「DVDを開く」を押し、タイトルを選択します。
3. 再生、一時停止、2秒戻しなどを操作します。
4. 準備済み字幕がある場合は「事前処理した字幕を読み込む」からJSONを選択します。
5. 英語／日本語タブで切り替えます。手動スクロール後は「現在の字幕へ」で追従に戻ります。

2秒戻しは再生／一時停止の状態を維持する設計です。先頭では0秒まで戻り、位置変更不可の媒体では無効になります。

## 事前処理字幕の形式（開発用）

詳細設計書のmanifest形式を使用します。この版では`complete: true`のみ読み込めます。`title_id`は内部の0始まり（画面のタイトル1は0）。英語は`en`、日本語は`ja`とし、各言語を別々に読み込みます。

`media_id`はDVDのVIDEO_TS配下のIFOファイル名と内容から計算します。開発時は次のコマンドで取得できます。ドライブ文字は実際のものへ置き換えてください。

```powershell
.\.venv\Scripts\python.exe -c "from dvd_player.playback import media_identity; print(media_identity('D:/'))"
```

JSONと同じフォルダ以下へ画像を置き、`image_path`へ相対パスを記載します。媒体・タイトル不一致、時刻不正、ID重複、保存範囲外の参照は拒否します。

字幕の文字変換、キャッシュの自動生成・管理、字幕トラック選択・言語割り当て、実行ログの永続保存は未実装です。

## テスト・セキュリティ検査

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s 02.src/tests -v
.\.venv\Scripts\python.exe -m pip check
git submodule update --init --recursive
.\.venv\Scripts\python.exe -m pip install pre-commit
.\.venv\Scripts\python.exe -m pre_commit install
```

コミット時は仮想環境を有効化します。

```powershell
.\.venv\Scripts\Activate.ps1
python -m pre_commit run --all-files
```

字幕画像・動画・秘密情報はGitへ登録しないでください。ローカル素材は`00.secret/`へ配置できます。GitSecurityToolの個人用キーワードは`GitSecurityTool/GitSecurityTool/keywords.yaml`です。配布時点で追跡されているファイルのため、個人用変更をサブモジュールへコミットしないでください。

## 構成・ドキュメント

- `00.secret/`：ローカル素材・秘密情報（Git管理外）
- `01.doc/`：[仕様書](01.doc/仕様書.html)、[基本設計書](01.doc/基本設計書.html)、[詳細設計書](01.doc/詳細設計書.html)
- `02.src/dvd_player/`：アプリ実装
- `02.src/tests/`：ロジック・GUIのテスト
- `03.log/`：[進捗](03.log/current_status.txt)、[残課題](03.log/leftover_tasks.txt)
- `GitSecurityTool/`：検査サブモジュール

設計書は予定する全体仕様を含みます。現在の実装範囲は本READMEと進捗記録を参照してください。

## ライセンス

本プロジェクトのライセンスは未定義です。外部ライブラリ・VLC・GitSecurityToolにはそれぞれのライセンスが適用されます。
