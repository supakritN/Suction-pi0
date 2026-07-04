# Suctioning Trainer

โค้ดสำหรับเครื่องฝึก suctioning ที่ใช้บอร์ด ESP32-S3 มีหน้าเว็บสำหรับตั้งค่า, calibration, ดูค่า sensor, ฝึกใช้งาน และคำนวณคะแนน

- `docs/HANDOFF.md` อธิบายภาพรวมของระบบ
- ไฟล์หลักคือ `Suction_arduinoCode.ino` โค้ดเกือบทั้งหมดอยู่ในไฟล์นี้
- `SensorStats.h` เป็นไฟล์เล็ก ๆ สำหรับเก็บ struct ของค่าสถิติ sensor

## โครงสร้างไฟล์

- `Suction_arduinoCode.ino`: firmware หลัก มี web portal, state machine, calibration, sensor logic, scoring, `setup()` และ `loop()`
- `SensorStats.h`: struct สำหรับเก็บค่าเฉลี่ย, min, max, range ของ light sensor และ pressure sensor
- `docs/HANDOFF.md`: ภาพรวมระบบ, flow การทำงาน, diagram แบบ SVG, sensor logic, route และ scoring

## Hardware

- Board: ESP32-S3

## Library ที่ใช้

- WiFi
- WebServer
- Preferences
- DNSServer

## Pin ของ IR / Light Sensor

- Neck entry sensor: GPIO 15
- 6 cm light sensor: GPIO 16, GPIO 9
- 8 cm light sensor: GPIO 17, GPIO 10
- ค่า threshold ของ black marker ที่คอ: signed delta `>= 1500`
- marker แรกของสาย suction ใช้เป็นจุดเริ่มจับเวลาและเริ่ม tracking เท่านั้น ไม่นับเป็น contact/depth error
- marker ถัดไปที่คาดหวัง: marker ที่ 2 = `6 cm`, marker ที่ 3 = `8 cm`

## Pin ของ Pressure Sensor

- OUT : GPIO 4
- SCK : GPIO 5
- ใช้ logic อ่านแบบ HX710B 24-bit / 27 pulses

## ดูค่า Sensor แบบ Real-time

- เปิดหน้า `/sensors` จากหน้า setup ของ ESP32
- หน้านี้แสดงค่า raw ของ pressure sensor และ light sensor
