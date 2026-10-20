import framebuf
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

# カラー (エンディアン補正済み)
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


# ★省メモリ行バッファ (300 x 36 = たったの約21KB！)
ROW_W, ROW_H = 300, 36
row_buf = bytearray(ROW_W * ROW_H * 2)
fb_row = framebuf.FrameBuffer(row_buf, ROW_W, ROW_H, framebuf.RGB565)


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


def flush_row(x, y):
    set_window(x, y, x + ROW_W - 1, y + ROW_H - 1)
    dc.value(1)
    cs.value(0)
    spi.write(row_buf)
    cs.value(1)


# ==========================================================
# 3. GL計算 ＆ NMEAパーサー
# ==========================================================
def calc_maidenhead(lat, lon):
    try:
        lon += 180.0
        lat += 90.0
        f1 = chr(ord("A") + int(lon / 20.0))
        f2 = chr(ord("A") + int(lat / 10.0))
        s1 = str(int((lon % 20.0) / 2.0))
        s2 = str(int((lat % 10.0) / 1.0))
        sub1 = chr(ord("a") + int(((lon % 20.0) % 2.0) / (2.0 / 24.0)))
        sub2 = chr(ord("a") + int(((lat % 10.0) % 1.0) / (1.0 / 24.0)))
        return f"{f1}{f2}{s1}{s2}{sub1}{sub2}"
    except:
        return "------"


cur_lat, cur_lon, cur_alt, cur_sats = 0.0, 0.0, 0.0, 0
cur_jst = "--:--:--"
last_fix_time = 0


def parse_nmea():
    global cur_lat, cur_lon, cur_alt, cur_sats, cur_jst, last_fix_time
    while uart.any():
        try:
            line = uart.readline()
            if not line:
                break
            line_str = line.decode("ascii", "ignore").strip()

            if "RMC," in line_str:
                p = line_str.split(",")
                if len(p) > 9 and p[2] == "A":
                    last_fix_time = time.ticks_ms()
                    if len(p[1]) >= 6:
                        h = (int(p[1][0:2]) + 9) % 24
                        m = int(p[1][2:4])
                        s = int(p[1][4:6])
                        cur_jst = f"{h:02d}:{m:02d}:{s:02d}"
                    raw_lat, raw_lon = float(p[3]), float(p[5])
                    lat = int(raw_lat / 100) + (raw_lat % 100) / 60.0
                    lon = int(raw_lon / 100) + (raw_lon % 100) / 60.0
                    if p[4] == "S":
                        lat = -lat
                    if p[6] == "W":
                        lon = -lon
                    cur_lat, cur_lon = lat, lon

            elif "GGA," in line_str:
                p = line_str.split(",")
                if len(p) > 9 and p[6] != "0":
                    last_fix_time = time.ticks_ms()
                    cur_sats = int(p[7]) if p[7] else 0
                    cur_alt = float(p[9]) if p[9] else 0.0
        except:
            pass

    is_fixed = (
        time.ticks_diff(time.ticks_ms(), last_fix_time) < 3000
    ) and (last_fix_time != 0)
    return is_fixed, cur_jst, cur_lat, cur_lon, cur_alt, cur_sats


# ==========================================================
# 4. メインループ
# ==========================================================
print("Starting Low-RAM Shack Clock...")
init_display()

# 全画面黒クリア (省メモリ 640B 方式)
set_window(0, 0, WIDTH - 1, HEIGHT - 1)
dc.value(1)
cs.value(0)
black_line = bytearray(WIDTH * 2)
for _ in range(HEIGHT):
    spi.write(black_line)
cs.value(1)

# タイトルヘッダー (1行バッファを使い回して描画)
fb_row.fill(NAVY)
fb_row.rect(0, 0, ROW_W, 28, CYAN)
fb_row.text("Office-K LAB. SHACK CLOCK", 45, 10, CYAN)
flush_row(10, 5)

while True:
    is_fixed, jst, lat, lon, alt, sats = parse_nmea()

    if is_fixed:
        gl = calc_maidenhead(lat, lon)
        status_color = GREEN
        status_text = f"[ 3D-FIX : {sats:02d} SATS ]"
        try:
            h = (int(jst[0:2]) - 9) % 24
            gmt = f"{h:02d}:{jst[3:5]}:{jst[6:8]}"
        except:
            gmt = "--:--:--"
    else:
        gl = "------"
        status_color = YELLOW
        status_text = f"[ SEARCHING... {sats:02d} SATS ]"
        gmt = "--:--:--"

    # ------------------------------------------------------
    # ★1段目：JST日本標準時（特大3倍文字！！）
    # ------------------------------------------------------
    fb_row.fill(NAVY)
    text_scaled(fb_row, "JST", 12, 6, WHITE, scale=3)
    text_scaled(fb_row, jst, 95, 6, CYAN, scale=3)
    flush_row(10, 38)

    # ------------------------------------------------------
    # ★2段目：GMT世界標準時（特大3倍文字！！）
    # ------------------------------------------------------
    fb_row.fill(NAVY)
    text_scaled(fb_row, "GMT", 12, 6, WHITE, scale=3)
    text_scaled(fb_row, gmt, 95, 6, CYAN, scale=3)
    flush_row(10, 78)

    # ------------------------------------------------------
    # ★3段目：標高 ＆ 衛星数（2倍文字）
    # ------------------------------------------------------
    fb_row.fill(NAVY)
    text_scaled(fb_row, "ALT :", 12, 10, WHITE, scale=2)
    alt_str = f"{alt:5.0f} m" if is_fixed else " ---- m"
    text_scaled(fb_row, alt_str, 95, 10, WHITE, scale=2)

    flush_row(10, 118)

    # ------------------------------------------------------
    # ★4段目：GRID LOCATOR ＆ 座標
    # ------------------------------------------------------
    fb_row.fill(NAVY)
    text_scaled(fb_row, "GRID:", 12, 4, WHITE, scale=2)
    text_scaled(fb_row, gl, 95, 4, YELLOW, scale=2)

    coord_str = (
        f"{lat:8.4f} N  {lon:8.4f} E" if is_fixed else "--.---- N  ---.---- E"
    )
    fb_row.text(coord_str, 75, 24, GRAY)
    flush_row(10, 158)

    # ------------------------------------------------------
    # ★5段目：ステータスバー
    # ------------------------------------------------------
    fb_row.fill(NAVY)
    fb_row.rect(0, 4, ROW_W, 26, GRAY)
    sx = (ROW_W - len(status_text) * 8 * 2) // 2
    text_scaled(fb_row, status_text, sx, 9, status_color, scale=2)
    flush_row(10, 198)
