import random

FASTAG_DATABASE = {
    "MH14BK6899": {"status": "Valid", "tag_id": "FT12345", "balance": 60, "vehicle_class": "Car"},
    "UP32GH5678": {"status": "Valid", "tag_id": "FT56789", "balance": 90.75, "vehicle_class": "Truck"},
    "MH12XY4321": {"status": "Invalid", "tag_id": None, "balance": 0.00, "vehicle_class": "Unknown"},
}

def check_fastag(plate_number):
    plate_number = plate_number.upper()
    record = FASTAG_DATABASE.get(plate_number)
    if record:
        return record
    else:
        # Simulate a FASTag result and store it
        status = random.choice(["Valid", "Invalid", "No FASTag"])
        if status == "Valid":
            new_record = {
                "status": "Valid",
                "tag_id": f"FT{random.randint(10000, 99999)}",
                "balance": round(random.uniform(50, 300), 2),
                "vehicle_class": random.choice(["Car", "Truck", "Bus"])
            }
        elif status == "Invalid":
            new_record = {
                "status": "Invalid",
                "tag_id": None,
                "balance": 0.00,
                "vehicle_class": "Unknown"
            }
        else:  # No FASTag
            new_record = {
                "status": "No FASTag",
                "tag_id": None,
                "balance": 0.00,
                "vehicle_class": "Unknown"
            }

        # Store it for future use
        FASTAG_DATABASE[plate_number] = new_record
        return new_record

def deduct_fastag_amount(plate_number, amount):
    plate_number = plate_number.upper()
    record = FASTAG_DATABASE.get(plate_number)
    if record and record["status"] == "Valid" and record["balance"] >= amount:
        record["balance"] -= amount
        return True
    return False
