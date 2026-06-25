from fastapi import FastAPI, HTTPException, Header
from dotenv import load_dotenv
import json
import os
import requests

# Load the variables stored in .env
load_dotenv

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
    url = "https://connect.squareupsandbox.com/v2/orders/search"
    
    #API Request details, including authorisation
    headers = {
    "Authorization": f"Bearer {square_key}",
    "Square-Version": "2025-01-23",
    "Content-Type": "application/json"
    }

    body = {
        "location_ids": 
            [square_id],

        "query":{
            "filter":{
                "state_filter":{
                    "states":["COMPLETED"]
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

    orders = data.get("orders",[])

    return orders

def fetch_deputy_data(deputy_key: str, date: str):
    #TODO: implement Deputy API call
    return {}

def calculate_wage_spend(square_data, deputy_data):
    #TODO: implement calculation logic
    return 0

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
    store1=STORE_CONFIG.get(store_id)
    if not store1:
        raise HTTPException(status_code=400, detail=f"Unknown store_id:{store_id}")
    square_id = store1.get("square_id")
    deputy_id = store1.get("deputy_id")

    if not square_id or not deputy_id:
        raise HTTPException(status_code=400, detail =f"Missing Location IDs for store_id: {store_id}")
    
    return square_id, deputy_id

@app.get("/wage-spend")
def wage_spend(store_id:str, date: str, password:str=Header(None)):
    #0. Verify the password is correct!
    verify_password(password)
    
    #1. We get the correct API keys for the given store, using function get_store_keys:
    square_key, deputy_key = get_store_keys(store_id)
    square_loc,deputy_loc = get_location_ids(store_id)

    #2. We call Square's API using Square Key.
    square_data = fetch_square_data(square_key,square_loc,date)

    #3. We call Deputy's API using Square Key.
    deputy_data = fetch_deputy_data(deputy_key, deputy_loc,date)

    #4. We calculate the wage spend.
    result = calculate_wage_spend(square_data, deputy_data)

    #5. We return a clean json()
    return{
        "store_id": store_id,
        "date": date,
        "wage_spend": result
    }

@app.get("/locations")
def list_stores():
    return {"stores":list(STORE_CONFIG.keys())}