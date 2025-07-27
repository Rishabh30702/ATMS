import random

FASTAG_DATABASE = {
    "MH14B": {"status": "Valid", "tag_id": "FT12345", "balance": 60, "vehicle_class": "Car"},
    "KL65AN7722": {"status": "Valid", "tag_id": "FT56789", "balance": 500, "vehicle_class": "Truck"},
    "VEHICLE222": {"status": "Valid", "tag_id": "FT56789", "balance": 500, "vehicle_class": "Truck"},
    "MH12XY4321": {"status": "Invalid", "tag_id": None, "balance": 0.00, "vehicle_class": "Unknown"},
    "RFID9999": {"status": "Invalid", "tag_id": None, "balance": 0.00, "vehicle_class": "Unknown"},
    "MH14BR6899": {
        "pass_type": "Monthly",
        "payment_method": "Cash",
        "exemption_type": "VIP",
        "base_weight": "9800",
        "wim_weight": "0",
        "axle_count": "2",
        "fare": "0",
        "penalty": "0",
        "total_amount": "0",
        "status": "Valid", "tag_id": "FT12345", "balance": 60, "vehicle_class": "Car"
    }
    
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
                "plate": plate_number,
                "status": "Valid",
                "tag_id": f"FT{random.randint(10000, 99999)}",
                "balance": round(random.uniform(50, 300), 2),
                "vehicle_class": random.choice(["Car", "Truck", "Bus"]),
                "pass_type": random.choice(["Local", "Monthly", "Single Journey"]),
                "payment_method": random.choice(["Prepaid", "Postpaid"]),
                "exemption_type": random.choice(["None", "VIP", "Emergency Vehicle"]),
                "base_weight": str(random.randint(1000, 3000)) + " kg",
                "wim_weight": str(random.randint(1000, 3500)) + " kg",
                "axle_count": str(random.choice([2, 3, 4, 6])),
                "fare": str(random.choice([60, 80, 100])),
                "penalty": str(random.choice([0, 50, 100])),
                "total_amount": str(random.choice([60, 110, 150]))
            }

        elif status == "Invalid":
            new_record = {
                "plate": plate_number,
                "status": "Invalid",
                "tag_id": None,
                "balance": 0.00,
                "vehicle_class": "Unknown"
            }

        else:  # No FASTag
            new_record = {
                "plate": plate_number,
                "status": "No FASTag",
                "tag_id": None,
                "balance": 0.00,
                "vehicle_class": "Unknown"
            }

        FASTAG_DATABASE[plate_number] = new_record
        return new_record

def deduct_fastag_amount(plate_number, amount):
    plate_number = plate_number.upper()
    record = FASTAG_DATABASE.get(plate_number)
    if record and record["status"] == "Valid" and record["balance"] >= amount:
        record["balance"] -= amount
        return True
    return False
