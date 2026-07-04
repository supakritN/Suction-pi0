# Raspberry Pi Sensor Monitor App

A Raspberry Pi touchscreen application for monitoring sensor status from an ESP device through a USB serial connection.

## Overview

This application runs on Raspberry Pi connected to a touchscreen display.  
The Raspberry Pi reads sensor data from an ESP device through the USB port and displays the sensor connection status in real time.

System flow:

```text
Sensors
   |
   |
  ESP
   |
   | USB Serial
   |
Raspberry Pi
   |
   |
Touchscreen Display
```

Example serial data from ESP:

```text
1,0,1,1
```

Application display:

```text
Sensor 1 : ON
Sensor 2 : OFF
Sensor 3 : ON
Sensor 4 : ON
```

The number of sensors is detected automatically from the comma-separated serial data.

## Requirements

- Raspberry Pi
- Raspberry Pi OS with Desktop
- Touchscreen display
- Python 3
- ESP device connected by USB

Install dependencies:

```bash
pip install -r requirements.txt
```

## Setup

Create Python virtual environment:

```bash
python -m venv venv
```

Activate environment:

```bash
source venv/bin/activate
```

Install packages:

```bash
pip install -r requirements.txt
```

## Run Application

Run manually:

```bash
python main.py
```

## Display Issue

If running through SSH or terminal and the application cannot open with an error:

```text
_tkinter.TclError: no display name and no $DISPLAY environment variable
```

Set Raspberry Pi display manually:

```bash
export DISPLAY=:0
```

Then run again:

```bash
python main.py
```

## Desktop Auto Start

Create desktop startup file:

```bash
mkdir -p ~/.config/autostart

nano ~/.config/autostart/suction.desktop
```

Add:

```ini
[Desktop Entry]
Type=Application
Name=Suction Monitor
Exec=env DISPLAY=:0 /path/to/Rpi-app/venv/bin/python /path/to/Rpi-app/main.py
Terminal=false
```

Restart Raspberry Pi:

```bash
sudo reboot
```

The application will automatically open after Raspberry Pi starts.

## Project Structure

```text
Rpi-app/
│
├── main.py
├── requirements.txt
├── README.md
└── venv/
```

## Serial Format

ESP should send sensor data using comma-separated values.

Example:

```text
0,0,0,0
1,0,1,0
1,1,1,1
```

Baud rate:

```text
115200
```

The application automatically searches for connected USB serial devices.
