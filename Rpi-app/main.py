import os
import time
import threading
import tkinter as tk

import serial
from serial.tools import list_ports


# -----------------------------
# Raspberry Pi display
# -----------------------------
os.environ["DISPLAY"] = ":0"


# -----------------------------
# Config
# -----------------------------
BAUD_RATE = 115200

sensor_values = []
cards = []


# -----------------------------
# Find ESP USB
# -----------------------------
def find_esp():

    ports = list_ports.comports()

    for port in ports:

        print(
            port.device,
            port.description
        )

        if (
            "USB" in port.description
            or "CP210" in port.description
            or "CH340" in port.description
            or "ACM" in port.device
        ):
            return port.device

    return None


# -----------------------------
# Serial Thread
# -----------------------------
def serial_worker():

    global sensor_values

    while True:

        port = find_esp()

        if port is None:
            print("Waiting for ESP...")
            time.sleep(2)
            continue


        try:

            print("Connecting:", port)

            esp = serial.Serial(
                port,
                BAUD_RATE,
                timeout=1
            )

            print("ESP Connected")


            while True:

                line = esp.readline().decode(
                    errors="ignore"
                ).strip()


                if line:

                    print(
                        "RX:",
                        line
                    )

                    data = line.split(",")

                    # accept any number of sensors
                    if all(x in ["0", "1"] for x in data):
                        sensor_values = data


        except Exception as e:

            print(
                "Serial disconnected:",
                e
            )

            time.sleep(2)


# -----------------------------
# Build Sensor UI
# -----------------------------
def rebuild_ui(count):

    global cards


    for card in cards:
        card.destroy()


    cards = []


    columns = 4


    for i in range(count):

        label = tk.Label(
            root,
            text=f"SENSOR {i+1}",
            font=(
                "Arial",
                28
            ),
            width=10,
            height=4,
            relief="ridge",
            borderwidth=3
        )


        label.grid(
            row=i // columns,
            column=i % columns,
            padx=10,
            pady=10,
            sticky="nsew"
        )


        cards.append(label)


    for i in range(columns):

        root.columnconfigure(
            i,
            weight=1
        )


# -----------------------------
# Update Screen
# -----------------------------
def update_gui():


    if len(cards) != len(sensor_values):

        rebuild_ui(
            len(sensor_values)
        )


    for i, value in enumerate(sensor_values):

        if value == "1":

            cards[i].config(
                text=f"SENSOR {i+1}\nCONNECTED",
                bg="green"
            )


        else:

            cards[i].config(
                text=f"SENSOR {i+1}\nOFF",
                bg="gray"
            )


    # keep exit button above sensors
    exit_button.lift()


    root.after(
        100,
        update_gui
    )


# -----------------------------
# Exit
# -----------------------------
def exit_app():

    print("Closing app")

    root.destroy()


# -----------------------------
# Main Window
# -----------------------------
root = tk.Tk()

root.title(
    "Suction Monitor"
)

root.attributes(
    "-fullscreen",
    True
)


# ESC keyboard exit
root.bind(
    "<Escape>",
    lambda event: exit_app()
)


# -----------------------------
# Exit Button
# -----------------------------
exit_button = tk.Button(
    root,
    text="✕ EXIT",
    font=(
        "Arial",
        18
    ),
    command=exit_app
)


exit_button.place(
    relx=1.0,
    rely=0,
    anchor="ne",
    x=-10,
    y=10
)


exit_button.lift()


# -----------------------------
# Start Serial
# -----------------------------
threading.Thread(
    target=serial_worker,
    daemon=True
).start()


# Start GUI update
update_gui()


root.mainloop()
