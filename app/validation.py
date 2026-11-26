import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


CATEGORIES = ("Clothing", "Medication & Health", "Documents & Tech", "Toiletries", "Miscellaneous")
EXPENSE_CATEGORIES = ("Accommodation", "Flights", "Food", "Activities", "Misc")
WEATHER = ("Cold", "Temperate", "Tropical", "Dry/Heated Indoors")
AIR_QUALITY = ("Low", "Moderate", "High/Unhealthy")


class ValidationError(ValueError):
    pass


def text(value, name, maximum=500, required=False):
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be text.")
    value = value.strip()
    if (required and not value) or len(value) > maximum:
        raise ValidationError(f"{name} must contain {'1' if required else '0'} to {maximum} characters.")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise ValidationError(f"{name} contains invalid control characters.")
    return value


def iso_date(value, name):
    value = text(value, name, 10, True)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValidationError(f"{name} must be a valid YYYY-MM-DD date.") from None
    if parsed.isoformat() != value or parsed.year < 1900 or parsed.year > 9998:
        raise ValidationError(f"{name} must be a date between 1900 and 9998.")
    return value


def local_datetime(value, name):
    value = text(value, name, 19)
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValidationError(f"{name} must be a valid local date and time.") from None
    if parsed.tzinfo or "T" not in value or not 1900 <= parsed.year <= 9998:
        raise ValidationError(f"{name} must be a local date and time, without a UTC offset.")
    return parsed.isoformat(timespec="minutes")


def timezone(value, name):
    value = text(value, name, 100)
    if value:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError(f"{name} must be an IANA zone, such as Europe/London.") from None
    return value


def money(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValidationError(f"{name} must be a valid amount.")
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValidationError(f"{name} must be a valid amount.") from None
    if (
        not amount.is_finite()
        or amount < 0
        or amount > Decimal("999999999.99")
        or (positive and amount == 0)
        or amount != amount.quantize(Decimal("0.01"))
    ):
        raise ValidationError(f"{name} must be {'positive' if positive else 'non-negative'}, with at most 2 decimal places.")
    return int(amount * 100)


def choice(value, name, options):
    if value not in options:
        raise ValidationError(f"{name} must be one of: {', '.join(options)}.")
    return value


def boolean(value, name):
    if type(value) is not bool:
        raise ValidationError(f"{name} must be true or false.")
    return int(value)


def quantity(value):
    if type(value) is not int or not 1 <= value <= 9999:
        raise ValidationError("Quantity must be a whole number between 1 and 9999.")
    return value


HOLIDAY_DEFAULTS = {
    "title": "", "destination": "", "start_date": "", "end_date": "",
    "accommodation_name": "", "accommodation_address": "", "booking_references": "",
    "notes": "", "budget": 0, "currency": "USD", "laundry_available": False,
    "weather": "Temperate", "air_quality": "Low", "dietary_requirements": "",
}
ITEM_DEFAULTS = {"name": "", "category": "Miscellaneous", "quantity": 1, "packed": False}
FLIGHT_DEFAULTS = {
    "airline": "", "flight_number": "", "departure_airport": "", "departure_time": "",
    "departure_timezone": "", "arrival_airport": "", "arrival_time": "",
    "arrival_timezone": "", "terminal": "", "gate": "", "booking_code": "",
}
EXPENSE_DEFAULTS = {"description": "", "category": "Misc", "amount": 0, "date": ""}
DEFAULTS = {
    "holiday": HOLIDAY_DEFAULTS, "packing": ITEM_DEFAULTS,
    "flight": FLIGHT_DEFAULTS, "expense": EXPENSE_DEFAULTS,
}


def validate(kind, payload, current=None):
    if not isinstance(payload, dict):
        raise ValidationError("The JSON payload must be an object.")
    defaults = DEFAULTS[kind]
    unknown = payload.keys() - defaults.keys()
    if unknown:
        raise ValidationError(f"Unknown fields: {', '.join(sorted(unknown))}.")
    data = dict(defaults)
    if kind == "expense":
        data["date"] = date.today().isoformat()
    if current:
        data.update({key: current[key] for key in defaults if key in current})
    data.update(payload)
    if kind == "holiday":
        result = {
            key: text(data[key], key.replace("_", " "), maximum, required)
            for key, maximum, required in (
                ("title", 150, True), ("destination", 200, True),
                ("accommodation_name", 200, False), ("accommodation_address", 500, False),
                ("booking_references", 1000, False), ("notes", 10000, False),
                ("dietary_requirements", 1000, False),
            )
        }
        result["start_date"] = iso_date(data["start_date"], "Start date")
        result["end_date"] = iso_date(data["end_date"], "End date")
        if result["end_date"] < result["start_date"]:
            raise ValidationError("End date cannot be before start date.")
        result["budget_cents"] = money(data["budget"], "Budget")
        currency = text(data["currency"], "Currency", 3, True).upper()
        if not re.fullmatch("[A-Z]{3}", currency):
            raise ValidationError("Currency must be a three-letter currency code.")
        result["currency"] = currency
        result["laundry_available"] = boolean(data["laundry_available"], "Laundry available")
        result["weather"] = choice(data["weather"], "Weather", WEATHER)
        result["air_quality"] = choice(data["air_quality"], "Air quality", AIR_QUALITY)
        return result
    if kind == "packing":
        name = text(data["name"], "Item name", 200, True)
        return {
            "name": name, "name_key": name.casefold(),
            "category": choice(data["category"], "Category", CATEGORIES),
            "quantity": quantity(data["quantity"]),
            "packed": boolean(data["packed"], "Packed"),
        }
    if kind == "expense":
        return {
            "description": text(data["description"], "Description", 300, True),
            "category": choice(data["category"], "Category", EXPENSE_CATEGORIES),
            "amount_cents": money(data["amount"], "Amount", True),
            "date": iso_date(data["date"], "Expense date"),
        }
    result = {}
    for key, value in data.items():
        if key.endswith("_time"):
            result[key] = local_datetime(value, key.replace("_", " "))
        elif key.endswith("_timezone"):
            result[key] = timezone(value, key.replace("_", " "))
        else:
            result[key] = text(value, key.replace("_", " "), 200, key == "flight_number")
    if all(result[key] for key in ("departure_time", "arrival_time", "departure_timezone", "arrival_timezone")):
        departure = datetime.fromisoformat(result["departure_time"]).replace(tzinfo=ZoneInfo(result["departure_timezone"]))
        arrival = datetime.fromisoformat(result["arrival_time"]).replace(tzinfo=ZoneInfo(result["arrival_timezone"]))
        if arrival.timestamp() <= departure.timestamp():
            raise ValidationError("Arrival must be after departure when converted to UTC.")
    return result
