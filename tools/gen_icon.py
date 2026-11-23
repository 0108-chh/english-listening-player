from PIL import Image, ImageDraw

S = 512
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
grad = Image.new("RGBA", (S, S))
gd = grad.load()
c1 = (96, 144, 255)
c2 = (23, 72, 205)
for y in range(S):
    row = y / S
    for x in range(0, S, 2):
        t = (x / S) * 0.35 + row * 0.65
        px = (
            int(c1[0] + (c2[0] - c1[0]) * t),
            int(c1[1] + (c2[1] - c1[1]) * t),
            int(c1[2] + (c2[2] - c1[2]) * t),
            255,
        )
        gd[x, y] = px
        gd[x + 1, y] = px
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=116, fill=255)
img.paste(grad, (0, 0), mask)

d = ImageDraw.Draw(img)
W = 38
# 头梁
d.arc([112, 126, 400, 414], start=180, end=360, fill=(255, 255, 255, 255), width=W)
# 两侧耳罩
d.rounded_rectangle([98, 246, 178, 392], radius=40, fill=(255, 255, 255, 255))
d.rounded_rectangle([334, 246, 414, 392], radius=40, fill=(255, 255, 255, 255))
# 中间声波
for i, h in enumerate([40, 74, 40]):
    x = 216 + i * 46
    d.rounded_rectangle([x, 320 - h // 2, x + 20, 320 + h // 2], radius=10,
                        fill=(255, 255, 255, 235))

img.save("app/static/icon.png")
img.save("app/static/app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon ok")
