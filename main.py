from fastapi import FastAPI, HTTPException, Header
from dotenv import load_dotenv
from datetime import datetime, timezone
import json
import os
import requests

average_rate = 17.8

# Load the variables stored in .env
load_dotenv()

API_PASSWORD = os.getenv("API_PASSWORD")
if not API_PASSWORD:
    raise RuntimeError("API_PASSWORD is not set")

def verify_password(password:str = Header(None)):
    if password != API_PASSWORD:
        raise HTTPException(status_code=401,detail="Invalid or missing password")

def fetch_square_data(square_key: str, square_id, date: str):
    #Convert date to RFC3339 timestamps for Square filtering
    start = f"{date}T00:00:00Z"
    end = f"{date}T23:59:59Z"

    #URL to send the API request to:
    url = "https://connect.squareup.com/v2/orders/search"
    
    #API Request details, including authorisation
    headers = {
    "Authorization": f"Bearer {square_key}",
    "Square-Version": "2025-01-23",
    "Content-Type": "application/json"
    }

    body = {
    "location_ids": [square_id],
    "query": {
        "filter": {
            "state_filter": {
                "states": ["COMPLETED"]
            },
            "date_time_filter": {
                "closed_at": {
                    "start_at": f"{date}T00:00:00+00:00",
                    "end_at": f"{date}T23:59:59+00:00"
                }
            }
        }
    }
}


    response = requests.post(url, headers=headers,json=body)
    print("Square status:",response.status_code)
    print("Square raw:",response.text)

    data = response.json()

    if "errors" in data:
        raise HTTPException(status_code=500, detail=data["errors"])
    total_revenue = 0
    orders = data.get("orders",[])

    for order in orders:
        money = order.get("total_money", {})
        amount = money.get("amount", 0)
        total_revenue += amount

    # Convert from pence to pounds
    total_revenue = total_revenue / 100

    return {"orders":orders,"revenue":total_revenue}

def fetch_deputy_data(deputy_key: str, deputy_id ,date: str):

    url = "https://02ccfd29062105.uk.deputy.com/api/v1/resource/Timesheet/QUERY"
    
    headers = {
        "Authorization":f"Bearer {deputy_key}",
        "Content-Type":"application/json"
    }

    body = {
    "search": {
        "s1": {
            "field": "Date",
            "type": "ge",
            "data": f"{date}T00:00:00"
        },
        "s2": {
            "field": "Date",
            "type": "le",
            "data": f"{date}T23:59:59"
        }
    }
}
    response = requests.post(url,headers=headers,json=body)
    print("Deputy status:",response.status_code)
    print("Deputy raw:", response.text)

    data=response.json()

    if "Errors" in data:
        raise HTTPException(status_code=500, detail = data["Errors"])
    
    #Filter by location
    if isinstance(data, dict):
        timesheets = data.get("data", [])
    else:
        timesheets = data  # already a list

    filtered = [t for t in timesheets if t.get("Location")==deputy_id]
    print("Filtered timesheets count:", len(filtered))
    if filtered:
        print("Sample timesheet:", filtered[0])

    return filtered

def calculate_wage_percent(revenue, wage_spend):
    if revenue <= 0:
        return 0.0
    return round((wage_spend / revenue)*100,2)

def calculate_wage_spend(square_data, deputy_timesheets):
    total_hours = 0
    now = datetime.now(timezone.utc)

    for t in deputy_timesheets:
        start = datetime.fromisoformat(t["StartTime"])

        #In-Progress Shift
        if t.get("EndTime") is None:
            seconds = (now - start).total_seconds()
            hours = seconds / 3600
        
        #Closed Shift
        else:
            if t.get("TotalTime") is not None:
                hours = t["TotalTime"]/3600
            else:
                #Manual calculation, in case TotalTime is 0 for some reason
                end = datetime.fromisoformat(t["EndTime"])
                seconds = (end-start).total_seconds()
                hours = seconds / 3600
            
        total_hours += hours
    total_cost = total_hours * average_rate

    return{
        "total_hours": round(total_hours,2),
        "total_cost": round(total_cost,2),
        "average_hourly_rate": average_rate
    }

app=FastAPI()

#Read the API keys stored in .env
try:
    STORE_CONFIG = json.loads(os.getenv("STORE_CONFIG"))
except Exception as e:
    raise RuntimeError(f"Failed to load STORE_CONFIG:{e}")


def get_store_keys(store_id:str):
    store = STORE_CONFIG.get(store_id)
    if not store:
        raise HTTPException(status_code=400,detail=f"Unknown stored_id: {store_id}")
    square_key = store.get("square")
    deputy_key = store.get("deputy")

    if not square_key or not deputy_key:
        raise HTTPException(status_code=500, detail=f"Missing API Key for store_id:{store_id}")
    return square_key, deputy_key

def get_store_ids(store_id:str):
    store=STORE_CONFIG.get(store_id)

    if not store:
        raise HTTPException(status_code=400, detail=f"Unknown store_id:{store_id}")
    square_id = store.get("square_id")
    deputy_id = store.get("deputy_id")

    if not square_id or not deputy_id:
        raise HTTPException(status_code=400, detail =f"Missing Location IDs for store_id: {store_id}")
    
    return square_id, deputy_id

@app.get("/wage-spend")
def wage_spend(store_id:str, date: str, password:str=Header(None)):
    #0. Verify the password is correct!
    verify_password(password)
    
    #1. We get the correct API keys for the given store, using function get_store_keys:
    square_key, deputy_key = get_store_keys(store_id)
    square_loc,deputy_loc = get_store_ids(store_id)

    #2. We call Square's API using Square Key.
    square_data = fetch_square_data(square_key,square_loc,date)
    revenue = square_data["revenue"]

    #3. We call Deputy's API using Square Key.
    deputy_data = fetch_deputy_data(deputy_key, deputy_loc,date)

    #4. We calculate the wage spend.
    result = calculate_wage_spend(square_data, deputy_data)

    wage_spend = result["total_cost"]
    hours_worked = result["total_hours"]

    wage_percent = calculate_wage_percent(revenue, wage_spend)

    #5. We return a clean json()
    return{
        "store_id": store_id,
        "date": date,
        "revenue": revenue,
        "hours_worked":hours_worked,
        "wage_percent": wage_percent,
        "wage_spend":wage_spend

    }

@app.get("/locations")
def list_stores():
    return {"stores":list(STORE_CONFIG.keys())}