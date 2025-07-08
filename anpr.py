def detect_plate(reader, frame):
    results = reader.readtext(frame)
    for _, text, conf in results:
        clean = text.replace(" ", "").upper()
        if conf > 0.7 and 6 <= len(clean) <= 12:
            return clean
    return None
