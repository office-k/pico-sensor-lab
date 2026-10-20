import framebuf
from machine import Pin, SPI, freq, time_pulse_us
import time

freq(250_000_000)

# ==========================================================
# 1. ピン設定
# ==========================================================
PIN_SCK = 2
PIN_MOSI = 3
PIN_MISO = 4
PIN_CS = 5
PIN_DC = 6
PIN_RST = 7

# 超音波 (Trig=GP17, Echo=GP16)
PIN_TRIG = 17
PIN_ECHO = 16

trig = Pin(PIN_TRIG, Pin.OUT, value=0)
echo = Pin(PIN_ECHO, Pin.IN)

WIDTH, HEIGHT = 320, 240

# ハードウェアSPI (62.5MHz)
spi = SPI(
    0,
    baudrate=62_500_000,
    sck=Pin(PIN_SCK),
    mosi=Pin(PIN_MOSI),
    miso=Pin(PIN_MISO),
)
cs = Pin(PIN_CS, Pin.OUT, value=1)
dc = Pin(PIN_DC, Pin.OUT, value=1)
rst = Pin(PIN_RST, Pin.OUT, value=1)

# ==========================================================
# 2. カラー定義 (エンディアン補正済み)
# ==========================================================
BLACK = 0x0000
WHITE = 0xFFFF
GRAY = 0xEF7B
CYAN = 0xFF07
YELLOW = 0xE0FF
GREEN = 0xE007
NAVY = 0x0F00
RED = 0x00F8


# ==========================================================
# 3. ILI9341 ドライバ
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


# ==========================================================
# 4. 万能デカ文字関数 ＆ パネルバッファ
# ==========================================================
PANEL_W, PANEL_H = 300, 150
p_buf = bytearray(PANEL_W * PANEL_H * 2)
fb = framebuf.FrameBuffer(p_buf, PANEL_W, PANEL_H, framebuf.RGB565)


def text_scaled(target_fb, text_str, x, y, color, scale=2):
    w = len(text_str) * 8
    tmp_buf = bytearray(w * 8 * 2)
    tmp_fb = framebuf.FrameBuffer(tmp_buf, w, 8, framebuf.RGB565)
    tmp_fb.fill(0)
    tmp_fb.text(text_str, 0, 0, color)
    for py in range(8):
        for px in range(w):
            if tmp_fb.pixel(px, py) != 0:
                target_fb.fill_rect(
                    x + px * scale, y + py * scale, scale, scale, color
                )


# ==========================================================
# 5. 超音波距離計測関数
# ==========================================================
def measure_distance():
    trig.value(0)
    time.sleep_us(2)
    trig.value(1)
    time.sleep_us(10)
    trig.value(0)

    duration = time_pulse_us(echo, 1, 30000)
    if duration > 0:
        dist = duration / 58.2
        return min(max(dist, 2.0), 300.0)
    return -1.0


# ==========================================================
# 6. メインループ
# ==========================================================
print("Starting Sonar Monitor...")
init_display()

# 全画面黒クリア (省メモリ 640B 方式)
set_window(0, 0, WIDTH - 1, HEIGHT - 1)
dc.value(1)
cs.value(0)
black_line = bytearray(WIDTH * 2)
for _ in range(HEIGHT):
    spi.write(black_line)
cs.value(1)

# タイトルヘッダー (300x30)
t_buf = bytearray(300 * 30 * 2)
tb = framebuf.FrameBuffer(t_buf, 300, 30, framebuf.RGB565)
tb.rect(0, 0, 300, 28, CYAN)
tb.text("Office-K LAB. SONAR MONITOR", 35, 10, CYAN)
set_window(10, 8, 309, 37)
dc.value(1)
cs.value(0)
spi.write(t_buf)
cs.value(1)

smooth_dist = 50.0

while True:
    d = measure_distance()
    if d > 0:
        smooth_dist = smooth_dist * 0.6 + d * 0.4

    fb.fill(NAVY)
    fb.rect(0, 0, PANEL_W, PANEL_H, GRAY)

    if d > 0:
        val_str = "{:5.1f}".format(smooth_dist)
    else:
        val_str = " ---.-"

    # 警告ステータス
    if smooth_dist > 12.0:
        status_color = GREEN
        status_text = "[ SAFE ]"
    elif smooth_dist > 5.0:
        status_color = YELLOW
        status_text = "[ CAUTION ]"
    else:
        status_color = RED
        status_text = "[ STOP!! ]"

    # ★数字を3倍の特大文字に！
    text_scaled(fb, "RANGE:", 10, 18, WHITE, scale=2)
    text_scaled(fb, val_str, 95, 10, status_color, scale=3)
    text_scaled(fb, "cm", 250, 18, WHITE, scale=2)

    # ソナーバー
    fb.rect(18, 55, 264, 30, WHITE)
    bar_len = int(max(0, min(260, (100.0 - smooth_dist) * 2.8)))
    fb.fill_rect(20, 57, bar_len, 26, status_color)


    # ★警告テキストを「3倍特大文字」＆「自動中央揃え」に拡大！
    sx = (PANEL_W - len(status_text) * 24) // 2
    text_scaled(fb, status_text, sx, 102, status_color, scale=3)
    
    # パネル転送
    set_window(10, 50, 309, 199)
    dc.value(1)
    cs.value(0)
    spi.write(p_buf)
    cs.value(1)

    time.sleep_ms(60)