import framebuf
from machine import Pin, SPI, SoftI2C, freq
import time

# 250MHz オーバークロック
freq(250_000_000)

# ==========================================================
# 1. ピンアサイン設定
# ==========================================================
# TFT (ILI9341)
PIN_SCK = 2
PIN_MOSI = 3
PIN_MISO = 4
PIN_CS = 5
PIN_DC = 6
PIN_RST = 7

# I2C (BME280 / BMP280)
# ※GP17(I2C0)とGP18(I2C1)をまたぐため、柔軟なSoftI2Cで駆動
i2c = SoftI2C(scl=Pin(17), sda=Pin(16), freq=100_000)

WIDTH = 320
HEIGHT = 240

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
# 2. ILI9341 ドライバ
# ==========================================================
def write_cmd(cmd):
    dc.value(0)
    cs.value(0)
    spi.write(bytearray([cmd]))
    cs.value(1)


def write_data(data):
    dc.value(1)
    cs.value(0)
    spi.write(data)
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
    write_data(bytearray([0x55]))  # RGB565
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
# 3. BME280 / BMP280 自己完結ドライバ
# ==========================================================
# I2Cアドレススキャン (0x76 または 0x77)
devices = i2c.scan()
bme_addr = None
for a in [0x76, 0x77]:
    if a in devices:
        bme_addr = a
        break

if not bme_addr:
    print("Warning: Sensor not found on GP17/18!")
    bme_addr = 0x76  # フォールバック

# チップID確認 (0x60: BME280, 0x58: BMP280)
is_bme = False
try:
    chip_id = i2c.readfrom_mem(bme_addr, 0xD0, 1)[0]
    if chip_id == 0x60:
        is_bme = True
except:
    pass

# キャリブレーション読み込み
try:
    calib = i2c.readfrom_mem(bme_addr, 0x88, 24)
    dig_T1 = calib[1] << 8 | calib[0]
    dig_T2 = (
        (calib[3] << 8 | calib[2])
        if not (calib[3] & 0x80)
        else (calib[3] << 8 | calib[2]) - 65536
    )
    dig_T3 = (
        (calib[5] << 8 | calib[4])
        if not (calib[5] & 0x80)
        else (calib[5] << 8 | calib[4]) - 65536
    )
    dig_P1 = calib[7] << 8 | calib[6]
    dig_P2 = (
        (calib[9] << 8 | calib[8])
        if not (calib[9] & 0x80)
        else (calib[9] << 8 | calib[8]) - 65536
    )
    dig_P3 = (
        (calib[11] << 8 | calib[10])
        if not (calib[11] & 0x80)
        else (calib[11] << 8 | calib[10]) - 65536
    )
    dig_P4 = (
        (calib[13] << 8 | calib[12])
        if not (calib[13] & 0x80)
        else (calib[13] << 8 | calib[12]) - 65536
    )
    dig_P5 = (
        (calib[15] << 8 | calib[14])
        if not (calib[15] & 0x80)
        else (calib[15] << 8 | calib[14]) - 65536
    )
    dig_P6 = (
        (calib[17] << 8 | calib[16])
        if not (calib[17] & 0x80)
        else (calib[17] << 8 | calib[16]) - 65536
    )
    dig_P7 = (
        (calib[19] << 8 | calib[18])
        if not (calib[19] & 0x80)
        else (calib[19] << 8 | calib[18]) - 65536
    )
    dig_P8 = (
        (calib[21] << 8 | calib[20])
        if not (calib[21] & 0x80)
        else (calib[21] << 8 | calib[20]) - 65536
    )
    dig_P9 = (
        (calib[23] << 8 | calib[22])
        if not (calib[23] & 0x80)
        else (calib[23] << 8 | calib[22]) - 65536
    )

    if is_bme:
        dig_H1 = i2c.readfrom_mem(bme_addr, 0xA1, 1)[0]
        h_cal = i2c.readfrom_mem(bme_addr, 0xE1, 7)
        dig_H2 = (
            (h_cal[1] << 8 | h_cal[0])
            if not (h_cal[1] & 0x80)
            else (h_cal[1] << 8 | h_cal[0]) - 65536
        )
        dig_H3 = h_cal[2]
        dig_H4 = (h_cal[3] << 4) | (h_cal[4] & 0x0F)
        if dig_H4 & 0x800:
            dig_H4 -= 4096
        dig_H5 = (h_cal[5] << 4) | (h_cal[4] >> 4)
        if dig_H5 & 0x800:
            dig_H5 -= 4096
        dig_H6 = h_cal[6] if not (h_cal[6] & 0x80) else h_cal[6] - 256
        i2c.writeto_mem(bme_addr, 0xF2, b"\x01")  # Humidity oversampling x1

    i2c.writeto_mem(
        bme_addr, 0xF4, b"\x27"
    )  # Normal mode, temp/press oversampling x1
except Exception as e:
    print("Init error:", e)


def read_sensor():
    try:
        data = i2c.readfrom_mem(bme_addr, 0xF7, 8 if is_bme else 6)
        p_raw = (data[0] << 12) | (data[1] << 4) | (data[2] >> 4)
        t_raw = (data[3] << 12) | (data[4] << 4) | (data[5] >> 4)

        # 温度計算
        v1 = (t_raw / 16384.0 - dig_T1 / 1024.0) * dig_T2
        v2 = (
            (t_raw / 131072.0 - dig_T1 / 8192.0)
            * (t_raw / 131072.0 - dig_T1 / 8192.0)
        ) * dig_T3
        t_fine = v1 + v2
        temperature = t_fine / 5120.0

        # 気圧計算
        p1 = (t_fine / 2.0) - 64000.0
        p2 = p1 * p1 * dig_P6 / 32768.0
        p2 = p2 + p1 * dig_P5 * 2.0
        p2 = (p2 / 4.0) + (dig_P4 * 65536.0)
        p1 = (dig_P3 * p1 * p1 / 524288.0 + dig_P2 * p1) / 524288.0
        p1 = (1.0 + p1 / 32768.0) * dig_P1
        if p1 != 0:
            pressure = 1048576.0 - p_raw
            pressure = ((pressure - p2 / 4096.0) * 6250.0) / p1
            p1 = dig_P9 * pressure * pressure / 2147483648.0
            p2 = pressure * dig_P8 / 32768.0
            pressure = (pressure + (p1 + p2 + dig_P7) / 16.0) / 100.0
        else:
            pressure = 0.0

        # 湿度計算 (BME280のみ)
        humidity = 0.0
        if is_bme:
            h_raw = (data[6] << 8) | data[7]
            h = t_fine - 76800.0
            h = (
                h_raw
                - (
                    dig_H4 * 64.0
                    + dig_H5 / 16384.0 * h
                    * (
                        1.0
                        + dig_H6
                        / 67108864.0
                        * h
                        * (1.0 + dig_H3 / 67108864.0 * h)
                    )
                )
            ) * (
                dig_H2
                / 65536.0
                * (
                    1.0
                    + dig_H6
                    / 67108864.0
                    * h
                    * (1.0 + dig_H3 / 67108864.0 * h)
                )
            )
            humidity = h * (1.0 - dig_H1 * h / 524288.0)
            humidity = max(0.0, min(100.0, humidity))

        return temperature, pressure, humidity
    except:
        return 0.0, 0.0, 0.0


# ==========================================================
# 4. 描画システム (全部2倍 ＆ 座標カンタン調整版)
# ==========================================================
BLACK = 0x0000
WHITE = 0xFFFF
GRAY = 0xEF7B

# ★ここがバイト逆転を直した本来の色です！
CYAN = 0xFF07  # これで画面で【本物の水色（シアン）】が出ます！
YELLOW = 0xE0FF  # これで画面で【本物の黄色】が出ます！
GREEN = 0xE007  # これで画面で【本物の緑色】が出ます！
NAVY = 0x0F00  # これで画面で【本物のネイビー（濃紺）】が出ます！
RED = 0x00F8  # 赤
BLUE = 0x1F00  # 青

PANEL_W = 300
PANEL_H = 50
panel_buf = bytearray(PANEL_W * PANEL_H * 2)
fb = framebuf.FrameBuffer(panel_buf, PANEL_W, PANEL_H, framebuf.RGB565)


# 2倍デカ文字関数
def text_2x(target_fb, text_str, x, y, color):
    w = len(text_str) * 8
    tmp_buf = bytearray(w * 8 * 2)
    tmp_fb = framebuf.FrameBuffer(tmp_buf, w, 8, framebuf.RGB565)
    tmp_fb.fill(0)
    tmp_fb.text(text_str, 0, 0, color)
    for py in range(8):
        for px in range(w):
            if tmp_fb.pixel(px, py) != 0:
                target_fb.fill_rect(x + px * 2, y + py * 2, 2, 2, color)


def draw_panel(x, y, label, val_str, unit, color):
    fb.fill(NAVY)
    fb.rect(0, 0, PANEL_W, PANEL_H, color)
    fb.rect(2, 2, PANEL_W - 4, PANEL_H - 4, color)

    # ------------------------------------------------------
    # ★ここをいじれば位置（右寄せ）を自由に調整できます！
    # （PANEL_W=300 なので、数字を大きくすると右へ寄ります）
    # ------------------------------------------------------
    LABEL_X = 10  # ラベルの横位置
    VAL_X = 140  # ★数字の横位置（右へ寄せるなら120〜140に増やす）
    UNIT_X = 250  # ★単位の横位置（右端に寄せるなら240〜250に増やす）
    Y_POS = 17  # 上下の位置（17で上下中央あたり）

    # パネル内すべて2倍サイズで描画！
    text_2x(fb, label, LABEL_X, Y_POS, WHITE)  # 項目名
    text_2x(fb, val_str, VAL_X, Y_POS, color)  # 測定数値
    text_2x(fb, unit, UNIT_X, Y_POS, WHITE)  # 単位

    # 液晶へ転送
    set_window(x, y, x + PANEL_W - 1, y + PANEL_H - 1)
    dc.value(1)
    cs.value(0)
    spi.write(panel_buf)
    cs.value(1)

# ==========================================================
# 5. メインループ
# ==========================================================
print("Starting Sensor Monitor...")
init_display()

# 画面全体を黒でクリア
set_window(0, 0, WIDTH - 1, HEIGHT - 1)
dc.value(1)
cs.value(0)
black_line = bytearray(WIDTH * 2)
for _ in range(HEIGHT):
    spi.write(black_line)
cs.value(1)

# タイトルヘッダー枠描画 (300x30)
title_buf = bytearray(PANEL_W * 30 * 2)
tb = framebuf.FrameBuffer(title_buf, PANEL_W, 30, framebuf.RGB565)
tb.fill(BLACK)
tb.rect(0, 0, PANEL_W, 28, CYAN)
tb.text("Office-K LAB. ENV MONITOR", 45, 10, CYAN)
set_window(10, 8, 10 + PANEL_W - 1, 8 + 30 - 1)
dc.value(1)
cs.value(0)
spi.write(title_buf)
cs.value(1)

# 下部ステータス枠描画 (300x20)
btn_buf = bytearray(PANEL_W * 20 * 2)
bb = framebuf.FrameBuffer(btn_buf, PANEL_W, 20, framebuf.RGB565)
bb.fill(BLACK)
bb.rect(0, 0, PANEL_W, 18, GRAY)
bb.text("[ ACTIVE MONITORING : OK ]", 50, 5, GREEN)
set_window(10, 212, 10 + PANEL_W - 1, 212 + 20 - 1)
dc.value(1)
cs.value(0)
spi.write(btn_buf)
cs.value(1)

# 計測ループ
while True:
    temp, press, hum = read_sensor()

    # 3段のサイバーパネルをリアルタイム更新！
    draw_panel(12, 45, "TEMP", "{:6.2f}".format(temp), "C", YELLOW)
    draw_panel(12, 100, "HUMIDITY", "{:6.2f}".format(hum), "%", GREEN)
    draw_panel(12, 155, "PRESSURE", "{:6.1f}".format(press), "hPa", CYAN)

    time.sleep_ms(300)  # 0.3秒間隔でリアルタイム更新