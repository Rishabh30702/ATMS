def detect_plate(reader, frame):
    results = reader.readtext(frame)
    for _, text, conf in results:
        if conf > 0.7 and len(text) > 5:
            return text.strip()
    return None
