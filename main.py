from fastapi import FastAPI, HTTPException, Header
from dotenv import load_dotenv
import json
import os

# Load the variables stored in .env
load_dotenv

API_PASSWORD = os.getenv("API_PASSWORD")
if not API_PASSWORD:
    raise RuntimeError("API_PASSWORD is not set")

def verify_password(password:str = Header(None)):
    if password != API_PASSWORD:
        raise HTTPException(status_code=401,detail="Invalid or missing password")

def fetch_square_data(square_key: str, date: str):
    #Convert date to RFC3339 timestamps for Square filtering
    start = f"{date}T00:00:00Z"
    end = f"{date}T23:59:59Z"

    #URL to send the API request to:
    url = "https://connect.squareupsandbox.com/v2/payments/search"
    
    #API Request details, including authorisation
    headers = {
        "Authorization": f"Bearer {square_key}",
        "Content-Type": "application/json",
        "Square-Version":"2024-06-20"
    }

    body = {
        "query":{
            "filter":{
                "date_time_filter":{
                    "created_at":{
                        "start_at":start,
                        "end_at":end
                    }
                }
            }
        }
    }

    response = requests.post(url, headers=headers,json=body)

    if response.status_code != 200:
        raise HTTPException(
            status_code = 500, detail = f"Square API error: {response.text}"
        )
    return response.json

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


@app.get("/")
def home():
    return {
        "message": "Backend is working!",
        "square_key_loaded": SQUARE_KEY is not None,
        "deputy_key_loaded": DEPUTY_KEY is not None
    }

def get_store_keys(store_id:str):
    store = STORE_CONFIG.get(store_id)
    if not store:
        raise HTTPException(status_code=400,detail=f"Unknown stored_id: {store_id}")
    square_key = store.get("square")
    deputy_key = store.get("deputy")

    if not square_key or not deputy_key:
        raise HTTPException(status_code=500, detail=f"Missing API Key for store_id:{store_id}")
    return square_key, deputy_key

@app.get("/wage-spend")
def wage_spend(store_id:str, date: str, password:str=Header(None)):
    #0. Verify the password is correct!
    verify_password(password)
    
    #1. We get the correct API keys for the given store, using function get_store_keys:
    square_key, deputy_key = get_store_keys(store_id)

    #2. We call Square's API using Square Key.
    square_data = fetch_square_data(square_key,date)

    #3. We call Deputy's API using Square Key.
    deputy_data = fetch_deputy_data(deputy_key,date)

    #4. We calculate the wage spend.
    result = calculate_wage_spend(square_data, deputy_data)

    #5. We return a clean json()
    return{
        "store_id": store_id,
        "date": date,
        "wage_spend": result
    }
