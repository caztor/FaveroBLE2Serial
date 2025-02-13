import serial
import time

# The 10-byte hex string
hex_string = "FF07143102000000004D"

# Convert the hex string to a bytearray (each pair of hex digits becomes one byte)
data_bytes = bytearray.fromhex(hex_string)

# Convert the bytearray to an ASCII string representation.
# Here we convert each byte to its two-digit uppercase hex representation.
ascii_string = ''.join('{:02X}'.format(b) for b in data_bytes)
# (This will result in "FF07143102000000004D", the same as the original.)

# Configure the serial port.
# Change 'COM1' to the appropriate port on your system.
ser = serial.Serial(port='COM1', baudrate=38400, timeout=1)

print("Starting transmission to COM port at 38400 baud.")
try:
    while True:
        # Send the ASCII string.
        # Encoding to ASCII because the string consists only of valid ASCII characters.
        ser.write(ascii_string.encode('ascii'))
        print(f"Sent: {ascii_string}")
        # Pause for a second before sending again (adjust as needed)
        time.sleep(1)
except KeyboardInterrupt:
    print("Transmission interrupted by user.")
finally:
    ser.close()
    print("Serial port closed.")
