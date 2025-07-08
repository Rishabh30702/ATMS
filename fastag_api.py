import random

# Simulated FASTag records
FASTAG_DATABASE = {
    "DL1ABC1234": {"status": "Valid", "tag_id": "FT12345", "balance": 280.50, "vehicle_class": "Car"},
    "UP32GH5678": {"status": "Valid", "tag_id": "FT56789", "balance": 90.75, "vehicle_class": "Truck"},
    "MH12XY4321": {"status": "Invalid", "tag_id": None, "balance": 0.00, "vehicle_class": "Unknown"},
}

def check_fastag(plate_number):
    # Simulate API call delay
    # time.sleep(1)  # Uncomment to simulate slow response
    record = FASTAG_DATABASE.get(plate_number.upper())
    if record:
        return record
    else:
        return {"status": "No FASTag", "tag_id": None, "balance": 0.00, "vehicle_class": "Unknown"}
