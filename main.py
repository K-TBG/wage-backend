from fastapi import FastAPI, HTTPException, Header
from dotenv import load_dotenv
from datetime import datetime
import json
import os
import requests
import time
app = FastAPI()

average_rate = 17.8
DEPUTY_BASE_URL = "https://02ccfd29062105.uk.deputy.com"

# Load environment
load_dotenv()

API_PASSWORD = os.getenv("API_PASSWORD")
if not API_PASSWORD:
    raise RuntimeError("API_PASSWORD is not set")

try:
    STORE_CONFIG = json.loads(os.getenv("STORE_CONFIG"))
except Exception as e:
    raise RuntimeError(f"Failed to load STORE_CONFIG: {e}")


def verify_password(password: str = Header(None)):
    if password != API_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid or missing password")

def get_store_keys(store_id: str):
    store = STORE_CONFIG.get(store_id)
    if not store:
        raise HTTPException(status_code=400, detail=f"Unknown store_id: {store_id}")
    return store["square"], store["deputy"]

def get_store_ids(store_id: str):
    store = STORE_CONFIG.get(store_id)
    if not store:
        raise HTTPException(status_code=400, detail=f"Unknown store_id: {store_id}")
    return store["square_id"], store["deputy_id"]

def fetch_deputy_data(deputy_key: str, deputy_company_id: int, date: str):
    
    headers = {"Authorization": f"Bearer {deputy_key}"}

    ou_url = f"{DEPUTY_BASE_URL}/api/v1/resource/OperationalUnit/QUERY"
    ou_resp = requests.post(ou_url, headers=headers, json={})
    operational_units = ou_resp.json()

    url = f"{DEPUTY_BASE_URL}/api/v1/resource/Timesheet/QUERY"
    date_start, date_end = time_processing(date)

    matching_ou_ids = [
    ou["Id"]
    for ou in operational_units
    if ou["Company"] == deputy_company_id
    ]

    body = {
    "search": {
        "s1": {"field": "StartTime", "type": "gt", "data": date_start},
        "s2": {"field": "StartTime", "type": "lt", "data": date_end},
        "s3": {"field": "IsLeave", "type": "eq", "data": False},
        "s4": {"field": "OperationalUnit", "type": "in", "data": matching_ou_ids}
    }
}


    r = requests.post(url, headers=headers, json=body)
    data = r.json()
    
    return data

def fetch_square_revenue(square_key: str, square_location_id: str, date: str):
    start = f"{date}T00:00:00Z"
    end = f"{date}T23:59:59Z"

    url = "https://connect.squareup.com/v2/orders/search"
    headers = {
        "Authorization": f"Bearer {square_key}",
        "Square-Version": "2025-01-23",
        "Content-Type": "application/json"
    }

    body = {
        "location_ids": [square_location_id],
        "query": {
            "filter": {
                "date_time_filter": {
                    "created_at": {
                        "start_at": start,
                        "end_at": end
                    }
                },
                "state_filter": {
                    "states": ["COMPLETED"]
                }
            }
        }
    }

    r = requests.post(url, headers=headers, json=body)
    data = r.json()
    print(data)

    if "errors" in data:
        raise Exception(data["errors"])

    revenue = 0.0
    taxes = 0.0
    tips = 0.0

    for order in data.get("orders", []):
        money = order.get("total_money", {}).get("amount", 0)
        revenue += money / 100.0

        tax = order.get("total_tax_money",{}).get("amount",0)
        taxes += tax / 100.0

        tip = order.get("total_tip_money",{}).get("amount",0)
        tips += tip / 100.0
    
    revenue -= (taxes + tips)

    return round(revenue, 2)

def calculate_wage_spend(timesheets, hourly_rate: float):
    
    total_hours = 0

    for t in timesheets:
        start = t.get("StartTime")
        end = t.get("EndTime")

        if start is None:
            continue
        if end > int(time.time()):
            end = int(time.time())

        hours = (end - start) / 3600
        total_hours += hours
        
    total_cost = total_hours * hourly_rate

    return {
        "total_hours": round(total_hours, 2),
        "total_cost": round(total_cost, 2),
        "timesheet_count": len(timesheets),
        "entries": timesheets
    }

def time_processing (date_raw):
    date = datetime.strptime(date_raw, "%Y-%m-%d")
    
    start = date.replace(hour = 0, minute = 0, second = 0, microsecond = 0)
    end = date.replace(hour = 23, minute = 59, second = 59, microsecond = 0)

    start_unix = int(start.timestamp())
    end_unix = int(end.timestamp())

    print(start_unix)
    print(end_unix)

    return start_unix, end_unix

@app.get("/wage-spend")
def wage_spend(store_id: str, date: str, password: str = Header(None)):
    verify_password(password)

    square_key, deputy_key = get_store_keys(store_id)
    square_id, deputy_company_id = get_store_ids(store_id)

    deputy_entries = fetch_deputy_data(deputy_key, deputy_company_id, date)
    revenue = fetch_square_revenue(square_key, square_id, date)
    wage_data = calculate_wage_spend(deputy_entries, hourly_rate= average_rate)

    wage_percent = 0.0
    if revenue > 0:
        wage_percent = round((wage_data["total_cost"] / revenue) * 100, 2)

    return {
        "store": store_id,
        "date": date,
        "revenue": revenue,
        "wage_spend": wage_data["total_cost"],
        "timesheet _count":wage_data["timesheet_count"],
        "wage_percent": wage_percent,
        "hours": wage_data["total_hours"]
    }

#  -------------------
# |  DEBUG ENDPOINTS  |
#  -------------------

@app.get("/debug-deputy")
def debug_deputy(store_id: str, date: str, password: str = Header(None)):
    verify_password(password)
    _, deputy_key = get_store_keys(store_id)
    _, deputy_company_id = get_store_ids(store_id)
    return fetch_deputy_data(deputy_key, deputy_company_id, date)

@app.get("/debug-deputy-all")
def debug_deputy_all(store_id: str, password: str = Header(None)):
    verify_password(password)

    try:
        _, deputy_key = get_store_keys(store_id)
        url = f"{DEPUTY_BASE_URL}/api/v1/resource/Timesheet/QUERY"
        headers = {"Authorization": f"Bearer {deputy_key}"}

        r = requests.post(url, headers=headers, json={})

        try:
            parsed = r.json()
        except:
            parsed = "NOT JSON"

        return {
            "status_code": r.status_code,
            "raw_text": r.text,
            "parsed_json": parsed
        }

    except Exception as e:
        return {"python_error": str(e)}
    
@app.get("/locations")
def list_stores():
    return {"stores": list(STORE_CONFIG.keys())}

@app.get("/deputy-id-check")
def deputy_id_request(store_id):
    _,deputy_key = get_store_keys(store_id)
    URL = f"{DEPUTY_BASE_URL}/api/v1/resource/Company/QUERY"
    headers = {"Authorization":f"Bearer {deputy_key}"}
    r = requests.post(URL,headers=headers,json={})
    
    return r.json()
