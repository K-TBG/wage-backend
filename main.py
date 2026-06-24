from fastapi import FastAPI
from dotenv import load_dotenv
import os

# Load the variables stored in .env
load_dotenv

app=FastAPI()

#Read the API keys stored in .env
SQUARE_KEY = os.getenv("SQUARE_API_KEY")
DEPUTY_KEY = os.getenv("DEPUTY_API_KEY")

@app.get("/")
def home():
    return {
        "message": "Backend is working!",
        "square_key_loaded": SQUARE_KEY is not None,
        "deputy_key_loaded": DEPUTY_KEY is not None
    }

@app.get("/wage-spend")
def wage_spend(date:str):
    return{
        "requested_date":date,
        "status": "Endpoint working"
    }