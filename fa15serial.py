import asyncio
import time
import threading
import serial
import serial.tools.list_ports
from bleak import BleakScanner, BleakClient
import logging

# Configure logging to print to console
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# UUIDs for FA-15 BLE characteristics
UUIDS = {
    "leftCards": "6F00000A-B5A3-F393-E0A9-E50E24DCCA9E",
    "rightCards": "6F00000B-B5A3-F393-E0A9-E50E24DCCA9E",
    "halt": "6F00000C-B5A3-F393-E0A9-E50E24DCCA9E",
    "time": "6F000004-B5A3-F393-E0A9-E50E24DCCA9E",
    "period": "6F000005-B5A3-F393-E0A9-E50E24DCCA9E",
    "weapon": "6F000006-B5A3-F393-E0A9-E50E24DCCA9E",
    "leftScore": "6F000007-B5A3-F393-E0A9-E50E24DCCA9E",
    "rightScore": "6F000008-B5A3-F393-E0A9-E50E24DCCA9E",
    "lamp": "6F000009-B5A3-F393-E0A9-E50E24DCCA9E"
}

# Reverse UUID mapping for lookup
UUID_TO_NAME = {uuid.lower(): name for name, uuid in UUIDS.items()}

# Time phase interpretation (last byte)
TIME_PHASES = {
    0x04: "Active Period",
    0x06: "Pause Period",
    0x05: "Medical Break",  # Fixed from 08 to 05
    0x00: "Stopped"
}

# Global variable to store hex value of data to be transmitted via serial interface
fs_data = bytearray(10)  # Initialize the serial data to send
fs_data[0] = 255  # Data Constant

# Convert an integer (0-99) to a BCD-encoded bytearray
def int_to_bcd(value: int) -> bytearray:
    if not (0 <= value <= 99):  # BCD only supports two-digit numbers (0-99)
        raise ValueError("Input must be between 0 and 99")

    return (value // 10 << 4) | (value % 10)  # Convert to BCD and return the result

# Score interpretation
def interpret_scores(data: bytearray, name: str) -> int:
    global fs_data
    
    # Debugging: Log the raw input received
    logging.info(f"Received input - data: {repr(data)}, name: {repr(name)}")
    
    # Ensure data is a valid bytearray with length 1
    if not isinstance(data, bytearray) or len(data) != 1:
        logging.error(f"Invalid input data. Received: {repr(data)} (Type: {type(data)})")
        raise ValueError(f"Invalid input data. Must be a bytearray of length 1, received: {repr(data)}")
    
    score = data[0]  # Extract score value
    
    if name == "leftScore":
        fs_data[2] = int_to_bcd(score)  # Update left score global variable
        logging.info(f"Updated fs_data[2]: {score}")
    elif name == "rightScore":
        fs_data[1] = int_to_bcd(score)  # Update left score global variable
        logging.info(f"Updated fs_data[1]: {score}")
    else:
        logging.error(f"Invalid name parameter. Received: {repr(name)}")
        raise ValueError("Invalid name. Must be 'leftScore' or 'rightScore'.")
    
    # Debugging: Log updated scores
    logging.info(f"Updated {name}: {score}")

    return score

# Period interpretation
def interpret_period(data: bytearray) -> str:
    global fs_data
    
    if not isinstance(data, bytearray) or len(data) != 1:
        logging.error(f"Invalid input data. Received: {repr(data)} (Type: {type(data)})")
        return "Invalid Period Data"
    
    period_number = data[0]
    period_number_serial = period_number & 0x03  # Keep values to 0-3
    
    fs_data[6] &= ~(0b00000011)  # Clears only the first two bits (without affecting others)

    # Set bits based on period_number (0-3)
    fs_data[6] |= (period_number & 0b00000011)  # Ensures only valid bits are set
    
    # Interpret the period/match value
    if period_number == 0x00:
        period_status = "No Period/Match '-'"
    elif 0x01 <= period_number <= 0x09:
        period_status = f"Period/Match No {period_number}"
    elif period_number == 0x0A:
        period_status = "Error"
    else:
        period_status = f"Unknown Period Value ({period_number})"
      
    logging.info(f"Updated fs_data[6]: 0x{fs_data[6]:02X} (binary: {bin(fs_data[6])})")
    
    return f"{period_status}"

# Time interpretation
def interpret_time(data: bytearray) -> str:
    global fs_data
    
    if not isinstance(data, bytearray) or len(data) != 4:
        logging.error(f"Invalid input data. Received: {repr(data)} (Type: {type(data)})")
        return "Invalid Time Data"
    
    hundreds = data[0]  # 100th of a second
    seconds = data[1]   # Seconds
    minutes = data[2]   # Minutes
    phase_byte = data[3]  # Phase information
    
    # Update global time variables
    fs_data[3] = int_to_bcd(seconds)  # Store full seconds byte (units and tens)
    fs_data[4] = int_to_bcd(minutes)  # Store only the unit digit of minutes
    
    # Interpret phase using last byte
    phase_status = TIME_PHASES.get(phase_byte, f"Unknown Phase ({phase_byte})")
    
    # Time format: MM:SS:XX (Phase)
    time_display = f"{minutes}:{seconds:02d}:{hundreds:02d}"
    
    logging.info(f"Updated fs_data[3]: {hex(fs_data[3])}, fs_data[4]: {hex(fs_data[4])}")
    
    return f"{time_display} ({phase_status})"

# Weapon interpretation
def interpret_weapons(data: bytearray) -> str:
    if not isinstance(data, bytearray) or len(data) != 1:
        logging.error(f"Invalid input data. Received: {repr(data)} (Type: {type(data)})")
        raise ValueError(f"Invalid input data. Must be a bytearray of length 1, received: {repr(data)}")
    
    weapon_map = {
        0x14: "Sabre",
        0x00: "Épée",
        0x01: "Épée",
        0x02: "Épée",
        0x0A: "Foil"
    }
    
    weapon = weapon_map.get(data[0], "?")
    logging.info(f"Weapon setting: {weapon} (Hex: {hex(data[0])})")
    
    return weapon

# Lamp interpretation
def interpret_lamps(data: bytearray) -> str:
    global fs_data
    if not isinstance(data, bytearray) or len(data) != 2:
        logging.error(f"Invalid input data. Received: {repr(data)} (Type: {type(data)})")
        raise ValueError(f"Invalid input data. Must be a bytearray of length 2, received: {repr(data)}")
    
    # Reset lamps before updating
    fs_data[5] = 0x00
    
    if data[0] & 0x04:
        fs_data[5] |= 0x01  # Left White Lamp
    if data[1] & 0x01:
        fs_data[5] |= 0x02  # Right White Lamp
    if data[0] & 0x01:
        fs_data[5] |= 0x04  # Red Lamp (Left Point)
    if data[0] & 0x40:
        fs_data[5] |= 0x08  # Green Lamp (Right Point)
    if data[1] & 0x04:
        fs_data[5] |= 0x10  # Right Yellow Lamp
    if data[0] & 0x10:
        fs_data[5] |= 0x20  # Left Yellow Lamp
    
    logging.info(f"Updated fs_data[5]: {hex(fs_data[5])}")
    
    return (
        f"LEFT - Score: {'ON' if fs_data[5] & 0x04 else 'OFF'} / "
        f"White: {'ON' if fs_data[5] & 0x01 else 'OFF'} / "
        f"Yellow: {'ON' if fs_data[5] & 0x20 else 'OFF'}\n"
        f"RIGHT - Score: {'ON' if fs_data[5] & 0x08 else 'OFF'} / "
        f"White: {'ON' if fs_data[5] & 0x02 else 'OFF'} / "
        f"Yellow: {'ON' if fs_data[5] & 0x10 else 'OFF'}"
    )

# Interpret fencing cards and priority from a bytearray and update fs_data
def interpret_cards(data: bytearray, name: str) -> int:
    global fs_data

    # Debugging: Log the raw input received
    logging.info(f"Received input - data: {repr(data)}, name: {repr(name)}")

    # Validate 'name' early
    if name not in {"leftCards", "rightCards"}:
        logging.error(f"Invalid name parameter: {repr(name)}")
        raise ValueError("Invalid name. Must be 'leftCards' or 'rightCards'.")

    # Ensure data is a valid bytearray of length 2
    if not isinstance(data, bytearray) or len(data) != 2:
        logging.error(f"Invalid input data: {repr(data)} (Type: {type(data)})")
        raise ValueError("Invalid input data. Must be a bytearray of length 2.")

    # Extract Cards
    red_card = bool(data[0] & 0x10)   # Bit 4 of first byte
    p_card = data[0] & 0x03           # Bits 0-1 of first byte
    yellow_card = bool(data[1] & 0x01) # Bit 0 of second byte

    # Extract Priority
    priority = bool(data[1] & 0x04)

    # Debugging: Log extracted values
    logging.info(f"Extracted - Red: {red_card}, P-Card: {p_card}, Yellow: {yellow_card}, Priority: {priority}")

    # Status representation
    p_card_mapping = {0: "OFF", 1: "1st", 2: "2nd", 3: "3rd"}
    p_card_status = p_card_mapping.get(p_card, "OFF")
    
    yellow_status = "ON" if yellow_card else "OFF"
    red_status = "ON" if red_card else "OFF"

    priority_status = "ON" if priority else "OFF"

    # Update Penalties
    if name == "leftCards":
        fs_data[8] = (fs_data[8] | 0x02) if red_card else (fs_data[8] & ~0x02)
        fs_data[8] = (fs_data[8] | 0x08) if yellow_card else (fs_data[8] & ~0x08)
        fs_data[6] = (fs_data[6] | 0x08) if priority else (fs_data[6] & ~0x08)
    else:  # name == "rightCards"
        fs_data[8] = (fs_data[8] | 0x01) if red_card else (fs_data[8] & ~0x01)
        fs_data[8] = (fs_data[8] | 0x04) if yellow_card else (fs_data[8] & ~0x04)
        fs_data[6] = (fs_data[6] | 0x04) if priority else (fs_data[6] & ~0x04)

    # Debugging: Log updated values
    logging.info(f"Updated: fs_data[8]: {hex(fs_data[8])}, fs_data[6]: {hex(fs_data[6])} (binary: {bin(fs_data[6])})")

    return f"Yellow: {yellow_status} / Red: {red_status} / P-Card: {p_card_status} / Priority: {priority_status}"

# General BLE Notification Handler
async def handle_notification(sender, data):
    """Handles BLE notifications, logs debug information, and decodes specific values."""
    timestamp = time.strftime("%H:%M:%S", time.localtime())

    # Extract UUID string correctly
    sender_uuid = str(sender.uuid).lower()

    # Identify characteristic by UUID
    characteristic_name = UUID_TO_NAME.get(sender_uuid, f"Unknown UUID {sender_uuid}")

    # Interpret specific data types
    if characteristic_name == "time":
        readable_data = interpret_time(data)
    elif characteristic_name == "lamp":
        readable_data = interpret_lamps(data)
    elif characteristic_name in ["leftScore", "rightScore"]:
        readable_data = interpret_scores(data, characteristic_name)
    elif characteristic_name in ["leftCards", "rightCards"]:
        readable_data = interpret_cards(data, characteristic_name)
    elif characteristic_name == "period":
        readable_data = interpret_period(data)
    elif characteristic_name == "weapon":
        readable_data = interpret_weapons(data)
    else:
        readable_data = f"Raw Value: {data.hex()}"

    print(f"[{timestamp}] 🔵 BLE Notification from {characteristic_name} ({sender_uuid}): {readable_data} | Raw: {data.hex()}")

# Reads current values from all subscribed characteristics upon connection
async def read_initial_values(client):
    print("📥 Reading initial values...")
    for name, uuid in UUIDS.items():
        try:
            data = await client.read_gatt_char(uuid)
            readable_data = (
                interpret_time(data) if name == "time" else
                interpret_lamps(data) if name == "lamp" else
                interpret_scores(data, name) if name in ["leftScore", "rightScore"] else
                interpret_cards(data, name) if name in ["leftCards", "rightCards"] else
                interpret_period(data) if name == "period" else
                interpret_weapons(data) if name == "weapon" else
                data.hex()
            )
            print(f"📄 Initial {name}: {readable_data} | Raw: {data.hex()}")
        except Exception as e:
            print(f"⚠️ Failed to read {name}: {e}")

# Subscribe to all characteristics
async def subscribe_to_fa15(device_address):
    """Connects to the FA-15 device, reads initial values, and subscribes to notifications."""
    async with BleakClient(device_address) as client:

        favero_modelNumber = await client.read_gatt_char("2A24")
        favero_firmwareRevision = await client.read_gatt_char("2A26")
        favero_softwareRevision = await client.read_gatt_char("2A28")

        favero_modelNumber = favero_modelNumber.decode('utf-8')
        favero_firmwareRevision = favero_firmwareRevision.decode('utf-8')
        favero_softwareRevision = favero_softwareRevision.decode('utf-8')

        print(f"🔗 Connected to {favero_modelNumber} (FW: {favero_firmwareRevision} SW: {favero_softwareRevision}) at {device_address}")

        await read_initial_values(client)

        for name, uuid in UUIDS.items():
            try:
                await client.start_notify(uuid, handle_notification)
                print(f"✅ Subscribed to {name} ({uuid})")
            except Exception as e:
                print(f"⚠️ Failed to subscribe to {name}: {e}")

        print(f"📡 Listening for notifications... Press Ctrl+C to stop.")
        while True:
            await asyncio.sleep(1)

# Generate a 10-byte string mimicking the real serial data format, including checksum
def generate_10_byte_string(data: bytearray):

    # Ensure data is a valid bytearray with length 1
    if not isinstance(data, bytearray) or len(data) != 10:
        logging.error(f"Invalid input data. Received: {repr(data)} (Type: {type(data)})")
        raise ValueError(f"Invalid input data. Must be a bytearray of length 10, received: {repr(data)}")

    # fs_data[5] = fs_ % 256  # Lamps
    # fs_data[6] = fs_ % 256  # Period
    # fs_data[8] = fs_ % 256  # Cards

    data[9] = sum(data[:9]) % 256

    return data

# Send formatted data over serial or print for debugging
def send_favero_data(ser):
    global fs_data
    while True:
        byte_string = generate_10_byte_string(fs_data)
        if ser:
            ser.write(byte_string)
            print(f"Sent: {byte_string.hex()}")
        else:
            print(f"Debug Output: {byte_string.hex()}")
        time.sleep(1)

# List available COM ports, indicate status, and allow user selection
def list_com_ports():
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("No COM ports found.")
        return None

    print("Available COM ports:")
    for i, port in enumerate(ports):
        try:
            with serial.Serial(port.device) as ser:
                print(f"{i + 1}: {port.device} - {port.description} (Available)")
        except serial.SerialException:
            print(f"{i + 1}: {port.device} - {port.description} (In Use)")

    while True:
        choice = input("Select a COM port by number, 'r' to rescan, or 'c' to continue without selecting: ")
        if choice.lower() == 'r':
            return list_com_ports()
        elif choice.lower() == 'c':
            return None
        elif choice.isdigit() and 1 <= int(choice) <= len(ports):
            return ports[int(choice) - 1].device
        else:
            print("Invalid selection. Please try again.")

# Scans for FA-15 devices and allows the user to select one
async def scan_for_fa15():
    while True:
        print("🔍 Scanning for BLE devices...")
        devices = await BleakScanner.discover()

        fa15_devices = [d for d in devices if d.name and "FA15" in d.name]
        if fa15_devices:
            print("\nAvailable FA-15 Devices:")
            for i, device in enumerate(fa15_devices):
                print(f"{i+1}: {device.name} [{device.address}]")

            choice = input("\nSelect the FA-15 device number to connect to (or 'r' to rescan): ").strip()
            if choice.lower() == 'r':
                continue
            try:
                choice = int(choice) - 1
                if 0 <= choice < len(fa15_devices):
                    return fa15_devices[choice].address
            except ValueError:
                pass

        print("❌ No FA-15 devices found. Try rescanning.")

# Main function
async def main():
    """Scans for BLE devices, allows selection, and connects to FA-15."""
    device_address = await scan_for_fa15()
    if device_address:
        print(f"🔗 Connecting to FA-15 at {device_address}...")
        await subscribe_to_fa15(device_address)

# Run script
if __name__ == "__main__":
    selected_port = list_com_ports()
    ser = None

    if selected_port:
        try:
            ser = serial.Serial(selected_port, 9600, timeout=1)
            print(f"Emulating Favero scoring machine on {selected_port} at 9600 baud")
        except serial.SerialException as e:
            print(f"Serial error: {e}")
            ser = None
    else:
        print("No COM port selected. Running in debug mode.")

    # Start Serial Transmission in a separate thread
    serial_thread = threading.Thread(target=send_favero_data, args=(ser,))
    serial_thread.daemon = True
    serial_thread.start()

    asyncio.run(main())
