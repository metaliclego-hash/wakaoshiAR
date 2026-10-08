"""白背景のキャラ画像から、背景透過PNGと AR Quick Look 用の等身大パネル USDZ を作る。

使い方:  python tools/make_panel.py ichiko.jfif ichiko --height 160
  → ichiko.png（背景透過）と ichiko.usdz を出力

--ref-top / --ref-bottom（元画像の行番号）を指定すると、その区間が --height の高さになる。
  例: python tools/make_panel.py ichiko.jfif ichiko --height 160 --ref-top 409 --ref-bottom 1123
"""
import argparse, io, zipfile
import numpy as np
from PIL import Image
from scipy import ndimage

WHITE_TOL = 5        # 白とみなす許容差（0-255）
ENCLOSED_MIN = 300   # 囲まれた白領域を背景とみなす最小ピクセル数
EDGE_BAND = 3        # 輪郭の半透明処理を行う幅(px)
THICKNESS = 0.5      # パネルの厚み(cm)


def cut_out(img):
    rgb = np.asarray(img.convert('RGB')).astype(np.float32)
    dist = 255 - rgb.min(axis=2)                 # 白からの離れ具合
    whiteish = dist <= WHITE_TOL

    labels, n = ndimage.label(whiteish)
    sizes = ndimage.sum(np.ones_like(labels), labels, range(n + 1))
    border = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])))
    bg_ids = [i for i in range(1, n + 1) if i in border or sizes[i] >= ENCLOSED_MIN]
    bg = np.isin(labels, bg_ids)

    # 輪郭付近は「白との合成」を逆算してアルファを求める（color-to-alpha）
    band = ndimage.binary_dilation(bg, iterations=EDGE_BAND) & ~bg
    alpha = np.ones(bg.shape, np.float32)
    alpha[bg] = 0
    a_edge = np.clip(dist / 255.0 * 1.6, 0, 1)
    alpha[band] = np.minimum(alpha[band], a_edge[band])

    out = rgb.copy()
    a3 = np.maximum(alpha, 1e-3)[..., None]
    out = np.where(band[..., None], 255 - (255 - rgb) / a3, rgb)
    out = np.clip(out, 0, 255)
    rgba = np.dstack([out, alpha * 255]).astype(np.uint8)
    rgba[alpha == 0, :3] = 0
    res = Image.fromarray(rgba, 'RGBA')
    bbox = res.getbbox()
    return res.crop(bbox), bbox


def panel_usda(w, h, tex):
    hw, t = w / 2, THICKNESS
    def mesh(name, z, front, mat):
        idx = '0, 1, 2, 3' if front else '3, 2, 1, 0'
        n = '(0, 0, 1)' if front else '(0, 0, -1)'
        return f'''
    def Mesh "{name}" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {{
        int[] faceVertexCounts = [4]
        int[] faceVertexIndices = [{idx}]
        point3f[] points = [({-hw:.3f}, 0, {z}), ({hw:.3f}, 0, {z}), ({hw:.3f}, {h:.3f}, {z}), ({-hw:.3f}, {h:.3f}, {z})]
        normal3f[] normals = [{n}, {n}, {n}, {n}] (
            interpolation = "vertex"
        )
        texCoord2f[] primvars:st = [(0, 0), (1, 0), (1, 1), (0, 1)] (
            interpolation = "vertex"
        )
        uniform token subdivisionScheme = "none"
        rel material:binding = </Root/{mat}>
    }}'''

    def material(name, diffuse):
        return f'''
    def Material "{name}"
    {{
        token outputs:surface.connect = </Root/{name}/S.outputs:surface>
        def Shader "S"
        {{
            uniform token info:id = "UsdPreviewSurface"
            {diffuse}
            float inputs:opacity.connect = </Root/{name}/Tex.outputs:a>
            float inputs:opacityThreshold = 0.02
            float inputs:metallic = 0.0
            float inputs:roughness = 1.0
            token outputs:surface
        }}
        def Shader "Tex"
        {{
            uniform token info:id = "UsdUVTexture"
            asset inputs:file = @{tex}@
            token inputs:wrapS = "clamp"
            token inputs:wrapT = "clamp"
            float2 inputs:st.connect = </Root/{name}/UV.outputs:result>
            float3 outputs:rgb
            float outputs:a
        }}
        def Shader "UV"
        {{
            uniform token info:id = "UsdPrimvarReader_float2"
            string inputs:varname = "st"
            float2 outputs:result
        }}
    }}'''

    return f'''#usda 1.0
(
    defaultPrim = "Root"
    metersPerUnit = 0.01
    upAxis = "Y"
)

def Xform "Root"
{{{mesh("Front", 0, True, "FrontMat")}{mesh("Back", -t, False, "BackMat")}
{material("FrontMat", f"color3f inputs:diffuseColor.connect = </Root/FrontMat/Tex.outputs:rgb>")}
{material("BackMat", "color3f inputs:diffuseColor = (0.85, 0.85, 0.85)")}
}}
'''


def write_usdz(path, files):
    """USDZ仕様どおり無圧縮・各ファイルのデータ先頭を64バイト境界に揃えて書き出す"""
    with open(path, 'wb') as f, zipfile.ZipFile(f, 'w', zipfile.ZIP_STORED) as zf:
        for name, data in files:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            header_end = f.tell() + 30 + len(name.encode())
            pad = (-(header_end + 4)) % 64
            info.extra = b'\x12\x34' + pad.to_bytes(2, 'little') + b'\0' * pad
            zf.writestr(info, data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('name')
    ap.add_argument('--height', type=float, default=160, help='高さ(cm)。ref指定時はその区間の高さ')
    ap.add_argument('--ref-top', type=int, help='高さの基準区間の上端（元画像の行）')
    ap.add_argument('--ref-bottom', type=int, help='高さの基準区間の下端（元画像の行）')
    a = ap.parse_args()

    cut, bbox = cut_out(Image.open(a.src))
    cut.save(f'{a.name}.png')
    cm_per_px = a.height / cut.height
    if a.ref_top is not None and a.ref_bottom is not None:
        cm_per_px = a.height / (a.ref_bottom - a.ref_top)
    h = cut.height * cm_per_px
    w = cut.width * cm_per_px
    buf = io.BytesIO(); cut.save(buf, 'PNG')
    tex = f'{a.name}_tex.png'
    usda = panel_usda(w, h, tex)
    write_usdz(f'{a.name}.usdz', [(f'{a.name}.usda', usda.encode()), (tex, buf.getvalue())])
    print(f'{a.name}.png {cut.size}, panel {w:.1f} x {h:.1f} cm -> {a.name}.usdz')


if __name__ == '__main__':
    main()
