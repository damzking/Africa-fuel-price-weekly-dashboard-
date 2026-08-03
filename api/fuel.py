from http.server import BaseHTTPRequestHandler
from html import unescape
import csv
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen


SOURCE_URL = "https://www.globalpetrolprices.com/gasoline_prices/"
FUELY_URL = "https://fuely.ng/"
HISTORY_FILE = Path(__file__).resolve().parent / "fuel_history.json"
HISTORY_CSV = Path(__file__).resolve().parent / "fuel_history.csv"
CBN_NFEM_URL = "https://www.cbn.gov.ng/api/GetAllNFEM_RatesGRAPH"
CACHE_SECONDS = 60 * 60 * 6
_CACHE = {"time": 0, "payload": None}

AFRICAN_COUNTRIES = {
    "Algeria",
    "Angola",
    "Benin",
    "Botswana",
    "Burkina Faso",
    "Burundi",
    "Cameroon",
    "Cape Verde",
    "Central African Republic",
    "Chad",
    "Comoros",
    "Congo",
    "DR Congo",
    "Djibouti",
    "Egypt",
    "Equatorial Guinea",
    "Eritrea",
    "Ethiopia",
    "Gabon",
    "Gambia",
    "Ghana",
    "Guinea",
    "Guinea-Bissau",
    "Ivory Coast",
    "Kenya",
    "Lesotho",
    "Liberia",
    "Libya",
    "Madagascar",
    "Malawi",
    "Mali",
    "Mauritania",
    "Mauritius",
    "Morocco",
    "Mozambique",
    "Namibia",
    "Niger",
    "Nigeria",
    "Rwanda",
    "Senegal",
    "Seychelles",
    "Sierra Leone",
    "Somalia",
    "South Africa",
    "Sudan",
    "Swaziland",
    "Tanzania",
    "Togo",
    "Tunisia",
    "Uganda",
    "Zambia",
    "Zimbabwe",
}


def _clean_country(value):
    value = re.sub(r"<[^>]+>", "", value)
    value = unescape(value)
    value = value.replace("*", "").replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _fetch_html():
    request = Request(
        SOURCE_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            )
        },
    )
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def _ensure_history_csv():
    fieldnames = ["source_date", "exchange_rate", "rows", "recorded_at"]
    if HISTORY_CSV.exists():
        return

    with HISTORY_CSV.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()

    if not HISTORY_FILE.exists():
        return

    try:
        legacy_history = json.loads(HISTORY_FILE.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    if not legacy_history:
        return

    _save_history(legacy_history)


def _load_history():
    _ensure_history_csv()
    if not HISTORY_CSV.exists():
        return []

    history = []
    with HISTORY_CSV.open("r", newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            if not row.get("source_date"):
                continue
            history.append(
                {
                    "source_date": row.get("source_date"),
                    "exchange_rate": json.loads(row["exchange_rate"]) if row.get("exchange_rate") else None,
                    "rows": json.loads(row["rows"]) if row.get("rows") else [],
                    "recorded_at": row.get("recorded_at"),
                }
            )
    return _sort_history(history)


def _save_history(history):
    _ensure_history_csv()
    fieldnames = ["source_date", "exchange_rate", "rows", "recorded_at"]
    with HISTORY_CSV.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for record in _sort_history(history):
            writer.writerow(
                {
                    "source_date": record.get("source_date"),
                    "exchange_rate": json.dumps(record.get("exchange_rate"), ensure_ascii=False),
                    "rows": json.dumps(record.get("rows", []), ensure_ascii=False),
                    "recorded_at": record.get("recorded_at"),
                }
            )


def _parse_source_date(value):
    if not isinstance(value, str):
        return None

    normalized = value.strip().replace(" ", "-").title()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue

    return None


def _sort_history(history):
    return sorted(
        history,
        key=lambda item: (
            _parse_source_date(item.get("source_date")) or datetime.max,
            item.get("source_date", ""),
        ),
    )


def _find_previous_record(history, current_source_date):
    sorted_history = _sort_history(history)
    if not sorted_history:
        return None

    current_index = next(
        (index for index, item in enumerate(sorted_history) if item.get("source_date") == current_source_date),
        None,
    )

    if current_index is None:
        return sorted_history[-2] if len(sorted_history) >= 2 else None

    return sorted_history[current_index - 1] if current_index > 0 else None


def _update_history(payload):
    history = _load_history()
    source_date = payload.get("source_date")
    if not source_date:
        return history

    if any(record.get("source_date") == source_date for record in history):
        return history

    history.append(
        {
            "source_date": source_date,
            "exchange_rate": payload.get("exchange_rate"),
            "rows": payload.get("rows", []),
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    history = _sort_history(history)
    _save_history(history)
    return history


def _enrich_payload_with_previous(payload, previous):
    if not previous:
        payload["previous_week_date"] = None
        payload["history_count"] = len(_load_history())
        payload["week_index"] = payload["history_count"]
        return payload

    previous_rows = {row["country"]: row for row in previous.get("rows", [])}
    for row in payload.get("rows", []):
        previous_row = previous_rows.get(row["country"])
        if not previous_row:
            row["previous_week_price_ngn_per_litre"] = None
            row["change_ngn"] = None
            row["change_pct"] = None
            continue

        previous_price = previous_row.get("price_ngn_per_litre")
        change_ngn = round(row["price_ngn_per_litre"] - previous_price, 2)
        change_pct = None
        if previous_price:
            change_pct = round((change_ngn / previous_price) * 100, 2)

        row["previous_week_price_ngn_per_litre"] = previous_price
        row["change_ngn"] = change_ngn
        row["change_pct"] = change_pct

    payload["previous_week_date"] = previous.get("source_date")
    history = _load_history()
    payload["history_count"] = len(history)
    payload["week_index"] = payload["history_count"]
    return payload


def _fetch_cbn_rate():
    request = Request(
        CBN_NFEM_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
        },
    )
    with urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))

    latest = max(data, key=lambda item: int(item["id"]))
    return {
        "rate": float(latest["weightedAvgRate"]),
        "date": latest["ratedate"],
        "source": CBN_NFEM_URL,
    }


def _extract_fuely_average(html):
    if not html:
        return None

    price_matches = re.findall(r"(?:₦|N)\s*([0-9][0-9,]*(?:\.[0-9]+)?)", html)
    if not price_matches:
        return None

    values = []
    for raw in price_matches:
        cleaned = raw.replace(",", "")
        try:
            values.append(float(cleaned))
        except ValueError:
            continue

    if not values:
        return None

    if len(values) >= 2:
        average = sum(values[:2]) / 2
        return round(average, 2)

    return round(values[0], 2)


def _fetch_fuely_average():
    request = Request(
        FUELY_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            )
        },
    )
    with urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")

    average = _extract_fuely_average(html)
    if average is None:
        raise ValueError("Could not find Fuely Nigeria average in the page HTML")

    return {
        "average_ngn_per_litre": average,
        "source": FUELY_URL,
    }


def _extract_prices(html):
    date_match = re.search(r"Gasoline prices around the world,\s+([^|<]+)", html)
    source_date = date_match.group(1).strip() if date_match else None

    countries = [
        _clean_country(match)
        for match in re.findall(
            r"class=['\"]graph_outside_link['\"][^>]*>(.*?)</a>",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]

    graphic_start = html.find('id="graphic"')
    graphic_html = html[graphic_start:] if graphic_start != -1 else html
    prices = [
        float(value)
        for value in re.findall(
            r"background:\s*#e2bb04[^>]*>\s*<div[^>]*>\s*([0-9]+(?:\.[0-9]+)?)\s*</div>",
            graphic_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]

    if not countries or not prices or len(countries) != len(prices):
        fallback = []
        for match in re.finditer(
            r"<tr[^>]*>\s*(?:<td[^>]*>\s*(?:<a[^>]*>)?([^<]+)(?:</a>)?\s*</td>)\s*<td[^>]*>\s*([0-9]+(?:\.[0-9]+)?)\s*</td>",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            fallback.append((match.group(1), float(match.group(2))))

        if fallback:
            countries, prices = zip(*fallback)
            countries = [_clean_country(value) for value in countries]
            prices = list(prices)

    if not countries or not prices:
        raise ValueError("Could not parse fuel prices from source HTML")

    exchange_rate = _fetch_cbn_rate()
    rows = []
    for country, price in zip(countries, prices):
        if country in AFRICAN_COUNTRIES:
            rows.append(
                {
                    "country": country,
                    "fuel_type": "Gasoline",
                    "price_usd_per_litre": price,
                    "price_ngn_per_litre": round(price * exchange_rate["rate"], 2),
                    "source_date": source_date,
                    "source": SOURCE_URL,
                }
            )

    rows.sort(key=lambda item: item["price_ngn_per_litre"])
    fuely_average = _fetch_fuely_average()
    return {
        "source_date": source_date,
        "exchange_rate": {
            "usd_ngn": exchange_rate["rate"],
            "date": exchange_rate["date"],
            "source": exchange_rate["source"],
        },
        "fuely": fuely_average,
        "count": len(rows),
        "rows": rows,
    }


def get_payload():
    now = time.time()
    if _CACHE["payload"] and now - _CACHE["time"] < CACHE_SECONDS:
        return _CACHE["payload"]

    try:
        payload = _extract_prices(_fetch_html())
    except Exception:
        if _CACHE["payload"]:
            return _CACHE["payload"]
        raise

    history = _update_history(payload)
    previous = _find_previous_record(history, payload.get("source_date"))
    payload = _enrich_payload_with_previous(payload, previous)

    _CACHE["time"] = now
    _CACHE["payload"] = payload
    return payload


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            payload = get_payload()
            status = 200
        except Exception as error:
            payload = {"error": str(error), "rows": []}
            status = 502

        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "s-maxage=21600, stale-while-revalidate=86400")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
