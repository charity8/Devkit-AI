import requests
import json

# Step 1: Login
login_url = "http://127.0.0.1:8000/login"
login_data = {
    "email": "test@example.com",
    "password": "mypassword"
}

try:
    login_res = requests.post(login_url, json=login_data, timeout=10)
    login_res.raise_for_status()
    token = login_res.json()["access_token"]
    print("✅ Login successful. Token obtained.")
except Exception as e:
    print(f"❌ Login failed: {e}")
    exit()

# Step 2: Generate flashcards (wait longer)
flashcard_url = "http://127.0.0.1:8000/generate-flashcards"
flashcard_data = {
    "notes": "who is God",
    "num_cards": 1
}
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}

try:
    # ⬇️ INCREASED TIMEOUT TO 60 SECONDS ⬇️
    response = requests.post(flashcard_url, json=flashcard_data, headers=headers, timeout=60)
    print(f"Status Code: {response.status_code}")
    print("Response:")
    print(json.dumps(response.json(), indent=2))
except Exception as e:
    print(f"❌ Error: {e}")