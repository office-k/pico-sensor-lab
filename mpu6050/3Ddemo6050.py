import framebuf
import math
from machine import Pin, SPI, SoftI2C, freq
import time

freq(250_000_000)

# ==========================================================
# 1. ハードウェア設定 (ILI9341 & MPU-6050)
# ==========================================================
WIDTH, HEIGHT = 320, 240

# ★画面いっぱいサイズ（上下240pxに迫る 220x220 バッファ = 約96KB RAM）
BOX_W, BOX_H = 220, 220
BX_START = (WIDTH - BOX_W) // 2  # 50 (左右中央)
BY_START = (HEIGHT - BOX_H) // 2  # 10 (上下中央)

box_buf = bytearray(BOX_W * BOX_H * 2)
fb = framebuf.FrameBuffer(box_buf, BOX_W, BOX_H, framebuf.RGB565)

# I2C (MPU-6050)
i2c = SoftI2C(scl=Pin(17), sda=Pin(16), freq=400_000)
try:
    i2c.writeto_mem(0x68, 0x6B, b"\x00")
except:
    pass

# SPI (TFT)
spi = SPI(
    0,
    baudrate=62_500_000,
    sck=Pin(2),
    mosi=Pin(3),
    miso=Pin(4),
)
cs, dc, rst = (
    Pin(5, Pin.OUT, value=1),
    Pin(6, Pin.OUT, value=1),
    Pin(7, Pin.OUT, value=1),
)


def write_cmd(c):
    dc.value(0)
    cs.value(0)
    spi.write(bytearray([c]))
    cs.value(1)


def write_data(d):
    dc.value(1)
    cs.value(0)
    spi.write(d)
    cs.value(1)


def init_display():
    rst.value(0)
    time.sleep_ms(50)
    rst.value(1)
    time.sleep_ms(50)
    write_cmd(0x01)
    time.sleep_ms(100)
    write_cmd(0x11)
    time.sleep_ms(50)
    write_cmd(0x3A)
    write_data(bytearray([0x55]))
    write_cmd(0x36)
    write_data(bytearray([0x28]))  # 横向き
    write_cmd(0x29)
    time.sleep_ms(20)


def set_window(x0, y0, x1, y1):
    write_cmd(0x2A)
    write_data(bytearray([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF]))
    write_cmd(0x2B)
    write_data(bytearray([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF]))
    write_cmd(0x2C)


# ==========================================================
# 2. 3D幾何学 ＆ 巨大キューブ設定
# ==========================================================
C_RED = 0x00F8
C_GREEN = 0xE007
C_BLUE = 0x1F00
C_YELLOW = 0xE0FF
C_CYAN = 0xFF07
C_MAGENTA = 0x1FF8
C_BG = 0x0000  # ★完全な「漆黒（黒）」

# ★サイズを画面いっぱいの超特大（SIZE=58）にスケールアップ！
SIZE = 58
VERTICES = [
    [-SIZE, -SIZE, -SIZE],
    [SIZE, -SIZE, -SIZE],
    [SIZE, SIZE, -SIZE],
    [-SIZE, SIZE, -SIZE],
    [-SIZE, -SIZE, SIZE],
    [SIZE, -SIZE, SIZE],
    [SIZE, SIZE, SIZE],
    [-SIZE, SIZE, SIZE],
]

FACES = [
    (0, 1, 2, 3, C_RED),  # 赤
    (5, 4, 7, 6, C_CYAN),  # シアン
    (4, 0, 3, 7, C_YELLOW),  # 黄
    (1, 5, 6, 2, C_BLUE),  # 青
    (4, 5, 1, 0, C_GREEN),  # 緑
    (3, 2, 6, 7, C_MAGENTA),  # マゼンタ
]


# 高速スキャンライン塗りつぶし
def fill_triangle(x0, y0, x1, y1, x2, y2, color):
    if y0 > y1:
        x0, y0, x1, y1 = x1, y1, x0, y0
    if y0 > y2:
        x0, y0, x2, y2 = x2, y2, x0, y0
    if y1 > y2:
        x1, y1, x2, y2 = x2, y2, x1, y1
    total_h = y2 - y0
    if total_h == 0:
        return
    for i in range(total_h):
        second_half = i > (y1 - y0) or y1 == y0
        seg_h = (y2 - y1) if second_half else (y1 - y0)
        if seg_h == 0:
            continue
        alpha = i / total_h
        beta = (i - (y1 - y0 if second_half else 0)) / seg_h
        ax = int(x0 + (x2 - x0) * alpha)
        bx = int((x1 + (x2 - x1) * beta) if second_half else (x0 + (x1 - x0) * beta))
        if ax > bx:
            ax, bx = bx, ax
        fb.hline(ax, y0 + i, bx - ax + 1, color)


def fill_quad(p0, p1, p2, p3, color):
    fill_triangle(p0[0], p0[1], p1[0], p1[1], p2[0], p2[1], color)
    fill_triangle(p0[0], p0[1], p2[0], p2[1], p3[0], p3[1], color)


# ==========================================================
# 3. センサー補正 ＆ メインループ
# ==========================================================
init_display()

# 全画面初期クリア（完全黒）
set_window(0, 0, WIDTH - 1, HEIGHT - 1)
dc.value(1)
cs.value(0)
black_line = bytearray(WIDTH * 2)
for _ in range(HEIGHT):
    spi.write(black_line)
cs.value(1)

smooth_x, smooth_y = 0.0, 0.0
CX_BOX, CY_BOX = BOX_W // 2, BOX_H // 2

print("Starting Fullscreen 3D Cube...")

while True:
    try:
        d = i2c.readfrom_mem(0x68, 0x3B, 6)
        ax = (d[0] << 8 | d[1]) if not (d[0] & 0x80) else (d[0] << 8 | d[1]) - 65536
        ay = (d[2] << 8 | d[3]) if not (d[2] & 0x80) else (d[2] << 8 | d[3]) - 65536
        az = (d[4] << 8 | d[5]) if not (d[4] & 0x80) else (d[4] << 8 | d[5]) - 65536

        # ★横向き画面に合わせて軸を入れ替え（縦横逆転を修正！）
        raw_x = math.atan2(ay, az)
        raw_y = math.atan2(-ax, math.sqrt(ay * ay + az * az))        

    except:
        raw_x, raw_y = 0.0, 0.0

    # フィルターで滑らか追従
    smooth_x = smooth_x * 0.75 + raw_x * 0.25
    smooth_y = smooth_y * 0.75 + raw_y * 0.25

    # 3D回転行列
    cx, sx = math.cos(smooth_x), math.sin(smooth_x)
    cy, sy = math.cos(smooth_y), math.sin(smooth_y)

    coords = []
    for x, y, z in VERTICES:
        # 画面の横向きに合わせて自然に回転
        x1 = x * cx - z * sx
        z1 = x * sx + z * cx
        y2 = y * cy + z1 * sy
        coords.append([int(CX_BOX + x1), int(CY_BOX + y2)])

    # バッファクリア（外枠は描かずに完全な黒で塗りつぶし）
    fb.fill(C_BG)

    # 手前を向いている面だけを高速塗りつぶし！
    for i0, i1, i2, i3, color in FACES:
        p0, p1, p2, p3 = coords[i0], coords[i1], coords[i2], coords[i3]
        cross = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (
            p2[0] - p0[0]
        )
        if cross > 0:
            fill_quad(p0, p1, p2, p3, color)

    # 画面中央へ一撃転送！
    set_window(BX_START, BY_START, BX_START + BOX_W - 1, BY_START + BOX_H - 1)
    dc.value(1)
    cs.value(0)
    spi.write(box_buf)
    cs.value(1)