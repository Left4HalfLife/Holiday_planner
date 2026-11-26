from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def escape(value):
    return str(value).replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def fold(line):
    # RFC 5545 limits physical lines to 75 octets, not 75 Unicode characters.
    lines = []
    current = ""
    for char in line:
        if len((current + char).encode("utf-8")) > 75:
            lines.append(current)
            current = " "
        current += char
    lines.append(current)
    return "\r\n".join(lines)


def flight_time(value, zone):
    parsed = datetime.fromisoformat(value)
    if zone:
        parsed = parsed.replace(tzinfo=ZoneInfo(zone)).astimezone(timezone.utc)
        return parsed.strftime("%Y%m%dT%H%M%SZ")
    return parsed.strftime("%Y%m%dT%H%M%S")


def export_ics(holiday):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    description = "\n".join(filter(None, [
        holiday["accommodation_name"], holiday["accommodation_address"],
        f"Booking references: {holiday['booking_references']}" if holiday["booking_references"] else "",
        holiday["notes"],
    ]))
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Holiday Planner//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "BEGIN:VEVENT", f"UID:holiday-{holiday['id']}@holiday-planner.local",
        f"DTSTAMP:{stamp}", f"SUMMARY:{escape(holiday['title'])}",
        f"LOCATION:{escape(holiday['destination'])}", f"DESCRIPTION:{escape(description)}",
        f"DTSTART;VALUE=DATE:{holiday['start_date'].replace('-', '')}",
        "DTEND;VALUE=DATE:" + (date.fromisoformat(holiday["end_date"]) + timedelta(days=1)).strftime("%Y%m%d"),
        "END:VEVENT",
    ]
    for flight in holiday["flights"]:
        if not flight["departure_time"]:
            continue
        departure = flight_time(flight["departure_time"], flight["departure_timezone"])
        lines.extend([
            "BEGIN:VEVENT", f"UID:flight-{flight['id']}@holiday-planner.local", f"DTSTAMP:{stamp}",
            f"SUMMARY:{escape(flight['flight_number'])} {escape(flight['departure_airport'])} to {escape(flight['arrival_airport'])}",
            f"DTSTART:{departure}",
            f"LOCATION:{escape(flight['departure_airport'])}",
            "DESCRIPTION:" + escape(
                f"Airline: {flight['airline']}\nTerminal: {flight['terminal']}\n"
                f"Gate: {flight['gate']}\nBooking: {flight['booking_code']}\n"
                f"Arrival: {flight['arrival_time']} {flight['arrival_timezone']}"
            ),
        ])
        if flight["arrival_time"]:
            arrival = flight_time(flight["arrival_time"], flight["arrival_timezone"])
            # A floating time and a UTC time cannot form one interoperable event.
            if departure.endswith("Z") == arrival.endswith("Z") and arrival > departure:
                lines.append(f"DTEND:{arrival}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
