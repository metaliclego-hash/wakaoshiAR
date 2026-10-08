# wakaoshiAR

和歌山市子の等身大パネル（キャラ身長160cm）を iPad / iPhone の AR Quick Look で表示する。

- `index.html` … 「ARで見る」ページ（`<a rel="ar">` で `ichiko.usdz` を開く）
- `tools/make_panel.py` … 白背景画像から背景透過PNGとUSDZを生成

```
python tools/make_panel.py ichiko.jfif ichiko --height 160 --ref-top 409 --ref-bottom 1123
```
