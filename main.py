#        ,-----------------------,      
# |------|   ESSENTIAL IMPORTS   |-------
#        '-----------------------'


from fastapi import FastAPI, HTTPException, Header
from dotenv import load_dotenv
from datetime import datetime, date, timedelta
import json
import os
import requests
import time
import sqlite3
import fastapi

#TODO: Finish revenue.db for ballymore monthly reports (daily revenue builder, ballymore reporting endpoint)
#Fix the fetch_square_revenue spaghetti code WITHOUT breaking it (good luck)
#Add square debugging endpoints

#        ,-----------------------,      
# |------|   BASIC ARCHITECTURE  |-------
#        '-----------------------'

app = FastAPI()
average_rate = 17.8
DEPUTY_BASE_URL = "https://02ccfd29062105.uk.deputy.com"
load_dotenv()

API_PASSWORD = os.getenv("API_PASSWORD")
if not API_PASSWORD:
    raise RuntimeError("API_PASSWORD is not set")

API_PASSWORD_PARTNER = os.getenv("API_PASSWORD")
if not API_PASSWORD_PARTNER:
    raise RuntimeError("API_PASSWORD_PARTNER is not set")
# Merge the above into one password checker? Might need lots of stored passwords in future

try:
    STORE_CONFIG = json.loads(os.getenv("STORE_CONFIG")) #Make sure STORE_CONFIG still exists
except Exception as e:
    raise RuntimeError(f"Failed to load STORE_CONFIG: {e}")

category_map = {
    "food":["Burgers & Salads","Piano Plates","Smashed Burgers","Fully Loaded Wraps","House Burgers","Chicken Tenders","Sides","Rainbow Bowls","Kids Menu","Lunch","Pastries","Cakes","Bowls","Brunch","Pinsas","Desserts","Beringer's Brunch","Main Menu","All Day Waffles","Cakes / Pastries"],
    "coffee":["Specialty Coffee","Iced Drinks","Hot Drinks","Coffee (Hot)","Summer Menu","Handcrafted Iced Drinks","Specialty Loose Leaf Tea","Hot Drinks & Teas"],
    "alcohol":["Classic Cocktails","House Cocktails","Beer / Cider","White Wine","Spirits","Spritz","Rose & Orange Wines","Red Wines","House Mocktails","Gin","Tequila / Mezcal","Sparkling Wines","Rum","Cognac / Brandy","Whisky","Liqueurs & Aperitifs","Lyres 0%","Draught Beer / Cider","Spritzes & Summer Specials","Canned Beer / Cider","Vodka","Rose Wine","Red Wine","Whiskey","Liqueurs","Mocktails","Tequila","Other Spirits","Sparkling & Champagne","Dessert / Brunch Cocktails"]
    }

#        ,-----------------------,      
# |------|     FUNCTION LIST     |-------
#        '-----------------------'

def init_db(): #Database - WIP
    conn = sqlite3.connect("revenue.db")
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_revenue(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    location TEXT NOT NULL,
    category TEXT NOT NULL,
    amount REAL NOT NULL,
    created_at TEXT NOT NULL
    )
""")
    conn.commit()
    conn.close()
init_db()

def map_category_to_section(square_category_name): #Scans inputted square category to return the relevant "section" listed in category_map
    for section, names in category_map.items():
        if square_category_name in names:
            return section
    return "other"

def insert_daily_revenue(date_str, location, category, amount): #WORK IN PROGESS - will be called daily to store revenue data in revenue.db
    conn = sqlite3.connect("revenue.db")
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO daily_revenue (date, location, category, amount 
    VALUES (?, ?, ?, ?, datetime('now'))
    """,(date_str, location, category, amount))
    conn.commit()
    conn.close()

def cleanup_old_revenue(): #WORK IN PROGESS - will be called daily to cull old data stored in revenue.db
    conn=sqlite3.connect("revenue.db")
    cur=conn.cursor()

    cur.execute("""
    DELETE FROM daily_revenue
    WHERE data < date('now','-90 days')
""")
    conn.commit()
    conn.close()

def verify_password(password: str = Header(None)): #Checks password against string stored in .env
    if password != API_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid or missing password")

def verify_password_partner(password: str = Header(None)): #Checks password against string stored in .env, for Ballymore reports
    if password != API_PASSWORD_PARTNER:
        raise HTTPException(status_code=401, detail="Invalid or missing password")

def get_store_keys(store_id:str): #Retrieves store API keys from STORE_CONFIG
    store = STORE_CONFIG.get(store_id)
    if not store:
        raise HTTPException(status_code=400, detail=f"Unknown store_id: {store_id}")
    return store["square"], store["deputy"]

def get_store_ids(store_id: str): #Retrieves store IDs from STORE_CONFIG
    store = STORE_CONFIG.get(store_id)
    if not store:
        raise HTTPException(status_code=400, detail=f"Unknown store_id: {store_id}")
    return store["square_id"], store["deputy_id"]

def fetch_deputy_data(deputy_key: str, deputy_company_id: int, date: str): #API request to Deputy for Timesheet data.
    
    headers = {"Authorization": f"Bearer {deputy_key}"}

    ou_url = f"{DEPUTY_BASE_URL}/api/v1/resource/OperationalUnit/QUERY"
    ou_resp = requests.post(ou_url, headers=headers, json={}) #ou -> Operational Unit. Used to filter by store within deputy.
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

def fetch_square_revenue(square_key: str, square_location_id: str, date: str): #API request to Square for Revenue data. This one is a MESS, but it works
    #Annoyingly complex. Square process closed payments and pending payments using different API queries. PAYMENTS handles pending,
    #ORDERS handles complete (and also contains item-level details.) This function checks both queries and merges them, ensuring no
    #duplicates are returned by checking orderID (a lot of payments have both a PAYMENT log and an ORDER log)

    #This function started out as ~15 lines and became a total maze as I learned about the quirks of Square API. It needs to be 
    #made way less confusing.

    start = f"{date}T00:00:00Z"
    end = f"{date}T23:59:59Z"

    headers = {
        "Authorization": f"Bearer {square_key}",
        "Square-Version": "2025-01-23",
        "Content-Type": "application/json"
    }

    payments_url = "https://connect.squareup.com/v2/payments"
    payments = []
    cursor = None

    while True:
        params = {
            "begin_time": start,
            "end_time": end,
            "location_id": square_location_id,
            "sort_order": "ASC"
        }
        if cursor:
            params["cursor"] = cursor

        r = requests.get(payments_url, headers=headers, params=params)
        data = r.json()

        if "errors" in data:
            raise Exception(data["errors"])

        payments.extend(data.get("payments", []))
        cursor = data.get("cursor")

        if not cursor:
            break

    payment_order_ids = set()
    payment_amounts = []

    for p in payments:
        money = p.get("amount_money", {}).get("amount", 0)
        payment_amounts.append(money)
        order_id = p.get("order_id")
        if order_id:
            payment_order_ids.add(order_id)


    orders_url = "https://connect.squareup.com/v2/orders/search"
    orders = []
    cursor = None

    while True:
        body = {
            "location_ids": [square_location_id],
            "query": {
                "filter": {
                    "date_time_filter": {
                        "updated_at": {   # IMPORTANT: updated_at. This marks COMPLETED payments, as these will be flagged as 'updated'
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

        if cursor:
            body["cursor"] = cursor

        r = requests.post(orders_url, headers=headers, json=body)
        data = r.json()

        if "errors" in data:
            raise Exception(data["errors"])

        orders.extend(data.get("orders", []))
        cursor = data.get("cursor")

        if not cursor:
            break

    unique_orders = {} #This is where we ensure no duplicates exist.
    for o in orders:
        oid = o.get("id")
        if oid:
            unique_orders[oid] = o

    revenue = 0.0
    taxes = 0.0
    tips = 0.0

    # Process orders that have payments
    for oid in payment_order_ids:
        order = unique_orders.get(oid)
        if not order: #This is to highlight when a payment exists with no order. Rare, but it has happened, and it was annoying.
            continue

        money = order.get("total_money", {}).get("amount", 0)
        tax = order.get("total_tax_money", {}).get("amount", 0)
        tip = order.get("total_tip_money", {}).get("amount", 0)

        revenue += money / 100.0
        taxes += tax / 100.0
        tips += tip / 100.0

    for p in payments:
        if not p.get("order_id"):
            money = p.get("amount_money", {}).get("amount", 0)
            revenue += money / 100.0

    revenue -= (taxes + tips) #Revenue should not include taxes, nor tips

    return round(revenue, 2) #I'll fix this mess one day...

def calculate_wage_spend(timesheets, hourly_rate: float):#Dead simple. Compares Timesheets with revenue to give a wage spend figure.
    
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

def time_processing (date_raw): #Just used to strip and format inputted date parameters to make life easier integrating with different API.
    date = datetime.strptime(date_raw, "%Y-%m-%d")
    
    start = date.replace(hour = 0, minute = 0, second = 0, microsecond = 0)
    end = date.replace(hour = 23, minute = 59, second = 59, microsecond = 0)

    start_unix = int(start.timestamp())
    end_unix = int(end.timestamp())
    return start_unix, end_unix

def build_daily_revenue(date_str):#WIP. This will be the function called by Render's cron to build revenue.db, needs a lot of work.
    print(f"Beginning daily revenue scan for {date_str}")

    for store_id, store_info in STORE_CONFIG.items():
        print(f"Processing store: {store_id}")
    

#        ,-----------------------,
# |------|     API ENDPOINTS     |-------|
#        '-----------------------'

@app.get("/wage-spend") #Endpoint called in the wage_tracker app. Simply returns live daily wage spend by using calculate_wage_spend and a live time figure.
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

    splh = round(revenue / wage_data["total_hours"],2)
    ideal_revenue = (wage_data["total_hours"]*average_rate)/0.3
    ideal_hours = (revenue*0.3)/average_rate

    
    return {
        "store": store_id,
        "date": date,
        "revenue": revenue,
        "wage_spend": wage_data["total_cost"],
        "timesheet_count":wage_data["timesheet_count"],
        "wage_percent": wage_percent,
        "hours": wage_data["total_hours"],
        "splh": splh,
        "ideal_revenue": ideal_revenue,
        "ideal_hours": ideal_hours
    }

@app.get("/ballymore-report") #WIP. This will be used for Ballymore to make a monthly report on sites they need data for. 
def ballymore_report(password:str = Header(None)):
    verify_password_partner(password)

    #retrieve information from a stored database. Program needs to run every evening at 3am to collect daily sales and populate
    #the database. Information may only be stored for 3 months before being overwritten.
    #I'm using a database because calculating a whole month's revenue for multiple sites might take too long.
    #Data returned must be categorised (food, coffee, alcohol etc)
    return()

@app.get("/weekly-report") #I made this to make my life easier generating weekly wage spend reports. Loops through all shops and calculates 
                            #their wage spend, per day, and returns the data in neat rows for power query to display in excel.
def weekly_report(start:str, password: str = Header(None)):
    verify_password(password)

    #Start Date:
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code = 400, detail = "Invalid start date format. Use YYY-MM-DD.")

    #7 day range:
    days = [(start_date + timedelta(days=i)) for i in range (7)]
    rows = []
    Number_of_Calculations = 0
    #Loop through all locations
    for store_id, store_info in STORE_CONFIG.items():
        square_key = store_info["square"]
        deputy_key = store_info["deputy"]
        square_loc_id = store_info["square_id"]
        deputy_company_id = store_info["deputy_id"]

        for day in days:
            day_str = day.strftime("%Y-%m-%d")
            deputy_entries = fetch_deputy_data(deputy_key, deputy_company_id,day_str)
            revenue = fetch_square_revenue(square_key,square_loc_id,day_str)
            wage_data = calculate_wage_spend(deputy_entries, average_rate)

            wage_percent = 0.0
            if revenue > 0:
                wage_percent = round((wage_data["total_cost"]/revenue)*100,2)
            
            #Build flat row for power query:

            rows.append({
                "location":store_id,
                "date":day_str,
                "percent":wage_percent,
                "revenue":revenue,
                "wage_spend":wage_data["total_cost"],
                "hours":wage_data["total_hours"],
                "timesheets":wage_data["timesheet_count"]
                })
            Number_of_Calculations += 1

    print("Finished request.")
    print(Number_of_Calculations)
    return rows

#        ,-----------------------,
# |------|  DEBUGGING ENDPOINTS  |-------|
#        '-----------------------'

#I made these to debug certain aspects of the system, should I break anything (which happens way too often)
#I need to make square versions, for when I break square. Right now I've only ever broken Deputy so only Deputy ones exist.

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
