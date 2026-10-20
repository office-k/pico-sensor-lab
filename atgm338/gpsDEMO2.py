import framebuf
import math
from machine import Pin, SPI, UART, freq
import time

freq(250_000_000)

# ==========================================================
# 1. ハードウェア設定 (ILI9341 & GPS UART0)
# ==========================================================
WIDTH, HEIGHT = 320, 240

# UART0 (TX=GP16, RX=GP17, 9600bps)
uart = UART(0, baudrate=9600, tx=Pin(16), rx=Pin(17), timeout=10)

# TFT (ILI9341)
spi = SPI(0, baudrate=62_500_000, sck=Pin(2), mosi=Pin(3), miso=Pin(4))
cs, dc, rst = (
    Pin(5, Pin.OUT, value=1),
    Pin(6, Pin.OUT, value=1),
    Pin(7, Pin.OUT, value=1),
)

# カラー定義 (エンディアン補正済み)
BLACK = 0x0000
WHITE = 0xFFFF
GRAY = 0xEF7B
CYAN = 0xFF07
YELLOW = 0xE0FF
GREEN = 0xE007
NAVY = 0x0F00
RED = 0x00F8


# ==========================================================
# 2. ILI9341 ドライバ
# ==========================================================
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


# レーダー用バッファ (140x140 = 約39KB)
RADAR_W, RADAR_H = 140, 140
r_buf = bytearray(RADAR_W * RADAR_H * 2)
fb_radar = framebuf.FrameBuffer(r_buf, RADAR_W, RADAR_H, framebuf.RGB565)

# バーグラフ用バッファ (300x50 = 約30KB)
BAR_W, BAR_H = 300, 50
b_buf = bytearray(BAR_W * BAR_H * 2)
fb_bar = framebuf.FrameBuffer(b_buf, BAR_W, BAR_H, framebuf.RGB565)

# 衛星データ保持辞書 {prn: (elevation, azimuth, snr)}
satellites = {}


def parse_gsv():
    global satellites
    while uart.any():
        try:
            line = uart.readline()
            if not line:
                break
            s = line.decode("ascii", "ignore").strip()
            if "GSV," in s:
                p = s.split(",")
                for i in range(4, len(p) - 4, 4):
                    if p[i] and p[i + 1] and p[i + 2]:
                        prn = int(p[i])
                        ele = int(p[i + 1])
                        azi = int(p[i + 2])
                        snr = (
                            int(p[i + 3])
                            if (p[i + 3] and p[i + 3].isdigit())
                            else 0
                        )
                        satellites[prn] = (ele, azi, snr)
        except:
            pass


# ==========================================================
# 3. メインループ
# ==========================================================
print("Starting GPS SkyPlot & Signal Bars...")
init_display()

# 全画面黒クリア
set_window(0, 0, WIDTH - 1, HEIGHT - 1)
dc.value(1)
cs.value(0)
bl = bytearray(WIDTH * 2)
for _ in range(HEIGHT):
    spi.write(bl)
cs.value(1)

# タイトル描画
t_buf = bytearray(300 * 25 * 2)
tb = framebuf.FrameBuffer(t_buf, 300, 25, framebuf.RGB565)
tb.fill(NAVY)
tb.rect(0, 0, 300, 23, CYAN)
tb.text("GPS RADAR & SIGNAL MONITOR", 40, 8, CYAN)
set_window(10, 5, 309, 29)
dc.value(1)
cs.value(0)
spi.write(t_buf)
cs.value(1)

RCX, RCY = RADAR_W // 2, RADAR_H // 2

while True:
    parse_gsv()

    # ------------------------------------------------------
    # 1. スカイプロット（天頂レーダー円）
    # ------------------------------------------------------
    fb_radar.fill(NAVY)
    fb_radar.rect(0, 0, RADAR_W, RADAR_H, GRAY)
    fb_radar.hline(5, RCY, RADAR_W - 10, GRAY)
    fb_radar.vline(RCX, 5, RADAR_H - 10, GRAY)

    # 同心円（天頂・仰角ガイド）
    for r in [60, 40, 20]:
        for deg in range(0, 360, 15):
            rad = math.radians(deg)
            fb_radar.pixel(
                int(RCX + r * math.cos(rad)),
                int(RCY + r * math.sin(rad)),
                GRAY,
            )

    # 衛星プロット
    valid_sats = []
    for prn, (ele, azi, snr) in list(satellites.items()):
        if snr > 0:
            valid_sats.append((prn, snr))
        dist = (90.0 - ele) / 90.0 * 55.0
        rad = math.radians(azi - 90)
        sx = int(RCX + dist * math.cos(rad))
        sy = int(RCY + dist * math.sin(rad))
        sc = GREEN if snr >= 35 else (YELLOW if snr >= 20 else CYAN)
        fb_radar.fill_rect(sx - 2, sy - 2, 5, 5, sc)

    set_window(10, 35, 10 + RADAR_W - 1, 35 + RADAR_H - 1)
    dc.value(1)
    cs.value(0)
    spi.write(r_buf)
    cs.value(1)

    # ------------------------------------------------------
    # 2. 右側ステータス
    # ------------------------------------------------------
    info_buf = bytearray(150 * RADAR_H * 2)
    fb_info = framebuf.FrameBuffer(info_buf, 150, RADAR_H, framebuf.RGB565)
    fb_info.fill(NAVY)
    fb_info.rect(0, 0, 150, RADAR_H, GRAY)
    fb_info.text("[SATELLITES]", 20, 15, WHITE)
    fb_info.text(f"TOTAL : {len(satellites):02d}", 20, 45, YELLOW)
    fb_info.text(f"ACTIVE: {len(valid_sats):02d}", 20, 75, GREEN)
    fb_info.text("MODE  : 3D NAV", 20, 105, CYAN)
    set_window(160, 35, 309, 35 + RADAR_H - 1)
    dc.value(1)
    cs.value(0)
    spi.write(info_buf)
    cs.value(1)

    # ------------------------------------------------------
    # 3. 信号強度バーグラフ（イコライザー）
    # ------------------------------------------------------
    fb_bar.fill(NAVY)
    fb_bar.rect(0, 0, BAR_W, BAR_H, GRAY)
    valid_sats.sort(key=lambda x: x[1], reverse=True)

    for idx, (prn, snr) in enumerate(valid_sats[:8]):
        bx = 15 + idx * 35
        bar_h = int(min(32, snr * 0.7))
        bc = GREEN if snr >= 35 else (YELLOW if snr >= 20 else CYAN)
        fb_bar.fill_rect(bx, 36 - bar_h, 20, bar_h, bc)
        fb_bar.text(f"{prn:02d}", bx, 38, WHITE)

    set_window(10, 180, 309, 229)
    dc.value(1)
    cs.value(0)
    spi.write(b_buf)
    cs.value(1)

    time.sleep_ms(500)