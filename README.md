# 英語学習用DVDプレイヤー

Pythonで実装中のWindows用DVDプレイヤーです。左に動画、右に英語／日本語の字幕一覧を配置します。

## 現在の実装

- DVDドライブ列挙、読み込み、タイトル・前後チャプター選択
- 再生／一時停止、停止、音量、シーク、連続操作可能な2秒戻し
- 英語／日本語タブ、字幕画像一覧、現在字幕の強調と自動追従
- 事前処理済み字幕データ（JSON＋画像）の読み込みと検証
- VLCが利用できない場合の案内

**DVD字幕の自動抽出を実装しました（実DVDの先頭60秒で確認）。** dvdvideo対応FFmpegで英語・日本語の画像字幕を抽出し、時刻付き一覧とキャッシュへ登録します。実FFmpegによる合成DVD字幕の変換は確認済みです。実DVDで映像再生・一時停止・タイトル切替・2秒戻しを確認しました。字幕同期精度や全編動作は未検証です。この環境にはポータブルVLC 3.0.24を導入し、エンジンの生成・解放を確認済みです。接続されたDVDで映像再生も確認しました。

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
4. キャッシュがなければDVD字幕の取得が始まります。事前処理済み字幕を使う場合は「事前処理した字幕を読み込む」からJSONを選択します。
5. 英語／日本語タブで切り替えます。手動スクロール後は「現在の字幕へ」で追従に戻ります。

2秒戻しは再生／一時停止の状態を維持する設計です。先頭では0秒まで戻り、位置変更不可の媒体では無効になります。

## 事前処理字幕の形式（開発用）

詳細設計書のmanifest形式を使用します。この版では`complete: true`のみ読み込めます。`title_id`は内部の0始まり（画面のタイトル1は0）。英語は`en`、日本語は`ja`とし、各言語を別々に読み込みます。

`media_id`はDVDのVIDEO_TS配下のIFOファイル名と内容から計算します。開発時は次のコマンドで取得できます。ドライブ文字は実際のものへ置き換えてください。

```powershell
.\.venv\Scripts\python.exe -c "from dvd_player.playback import media_identity; print(media_identity('D:/'))"
```

JSONと同じフォルダ以下へ画像を置き、`image_path`へ相対パスを記載します。媒体・タイトル不一致、時刻不正、ID重複、保存範囲外の参照は拒否します。

字幕データの読み込み時に画像とJSONをローカルキャッシュへ保存し、同じDVD・タイトルの次回読み込み時に自動で再利用します。同一言語で複数の字幕を読み込んだ場合は、タブ内のトラック選択欄で切り替えられます。DVDからの直接取得に対応しました。表示はトラック単位の取得完了後から行います。トラック途中の部分表示と、未知言語の手動割り当ては未実装です。

## ポータブルVLCの導入

この作業環境では導入済みです。別の環境では次を実行すると、公式VLC 3.0.24（64bit）を`.tools/`へ取得・SHA256照合・展開します。アプリはこの配置を自動検出します。システムへのインストールは行いません。

```powershell
.\VLC導入.ps1
```

`.tools/`のバイナリはGit管理外です。GitHubから取得した環境では上記操作またはVLC本体の別途導入が必要です。

## DVD字幕の自動取得

この環境にはdvdvideo対応のFFmpeg full 9.0.2を導入済みです。別環境では次を実行してください。配布元更新で固定SHA256と一致しない場合は、安全のため展開を中止します。

```powershell
.\FFmpeg導入.ps1
```

または、libdvdnav/libdvdreadを有効にしたFFmpeg full版のbinフォルダを`FFMPEG_HOME`へ指定します。`ffmpeg`と`ffprobe`の両方が必要です。通常のessentials版ではdvdvideoが含まれない場合があります。

DVD・タイトルを開くとキャッシュを確認し、英語／日本語が揃っていなければ自動取得を開始します。「DVD字幕を取得／再取得」で手動実行、「字幕取得を中止」で停止できます。タイトル変更・終了時も外部処理を中止します。

言語メタデータがeng/enなら英語、jpn/jaなら日本語として扱います。同一言語の複数トラックも取得します。言語不明は推測せず件数を案内します。

- 取得処理はワーカーで実行し、画像・時刻をトラック単位で表示・保存します。
- 透過フレームを字幕終了として扱い、表示中の画像を切り出します。
- 各外部変換の上限は15分、変換中画像は512MiB・100,000枚を目安に監視します。
- DVDを読み直すため、取得中はドライブ負荷が増えます。再生に影響する場合は取得を止め、先に字幕を取得してから再生してください。
- FFmpegのdvdvideoには暗号化解除機能はありません。収録字幕があっても、媒体へのアクセス条件により取得できない場合があります。
- 実DVDとVLCとの時間原点・同期精度は実機検証が必要です。

実デコードの自動テストには任意のPyAV（合成字幕ファイル作成専用）を使います。アプリ実行にPyAVは不要です。

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

参照：[FFmpeg dvdvideo](https://ffmpeg.org/ffmpeg-formats.html#dvdvideo)、[Windows full版の配布・対応ライブラリ](https://www.gyan.dev/ffmpeg/builds/)。

## ローカル保存先

通常はWindowsのLOCALAPPDATA配下の`dvd_player/`を使用します。開発時は`DVD_PLAYER_DATA_DIR`で変更できます。

- `cache/`：読み込み済み字幕画像・JSON。媒体・タイトル・トラック別に管理。上限512MiBを超える場合は古い別タイトルから削除。同じタイトルの字幕は保護し、保存不可なら元データで表示を継続。
- `logs/`：操作・エラーコードのログ。1ファイル2MiB、バックアップ3世代。字幕内容や画像、個人名を含むパスは記録しません。

キャッシュを削除したい場合はアプリを終了し、上記`cache/`フォルダを削除してください。次回は元の字幕JSONを読み直します。

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

- [実DVDでの確認結果と未確認項目](01.doc/実機確認結果.md)

- `00.secret/`：ローカル素材・秘密情報（Git管理外）
- `01.doc/`：[仕様書](01.doc/仕様書.html)、[基本設計書](01.doc/基本設計書.html)、[詳細設計書](01.doc/詳細設計書.html)
- `02.src/dvd_player/`：アプリ実装
- `02.src/tests/`：ロジック・GUIのテスト
- `03.log/`：[進捗](03.log/current_status.txt)、[残課題](03.log/leftover_tasks.txt)
- `GitSecurityTool/`：検査サブモジュール

設計書は予定する全体仕様を含みます。現在の実装範囲は本READMEと進捗記録を参照してください。

## ライセンス

本プロジェクトのライセンスは未定義です。外部ライブラリ・VLC・GitSecurityToolにはそれぞれのライセンスが適用されます。
