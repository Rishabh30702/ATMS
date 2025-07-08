import random

FASTAG_DATABASE = {
    "DL1ABC1234": {"status": "Valid", "tag_id": "FT12345", "balance": 280.50, "vehicle_class": "Car"},
    "UP32GH5678": {"status": "Valid", "tag_id": "FT56789", "balance": 90.75, "vehicle_class": "Truck"},
    "MH12XY4321": {"status": "Invalid", "tag_id": None, "balance": 0.00, "vehicle_class": "Unknown"},
}

def check_fastag(plate_number):
    plate_number = plate_number.upper()
    record = FASTAG_DATABASE.get(plate_number)
    if record:
        return record
    else:
        # Simulate a random outcome for unknown plates
        status = random.choice(["Valid", "Invalid", "No FASTag"])
        if status == "Valid":
            return {
                "status": "Valid",
                "tag_id": f"FT{random.randint(10000, 99999)}",
                "balance": round(random.uniform(50, 300), 2),
                "vehicle_class": random.choice(["Car", "Truck", "Bus"])
            }
        elif status == "Invalid":
            return {
                "status": "Invalid",
                "tag_id": None,
                "balance": 0.00,
                "vehicle_class": "Unknown"
            }
        else:
            return {
                "status": "No FASTag",
                "tag_id": None,
                "balance": 0.00,
                "vehicle_class": "Unknown"
            }
