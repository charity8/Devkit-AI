import requests

# Login to get a token
login_res = requests.post("http://127.0.0.1:8000/login", json={
    "email": "test@example.com",
    "password": "mypassword"
})

if login_res.status_code != 200:
    print(f"Login failed: {login_res.json()}")
    exit()

token = login_res.json()["access_token"]
print("Token obtained.")

# Test the Flashcard Generator
headers = {"Authorization": f"Bearer {token}"}
data = {
    "notes": "The Earth is the third planet from the Sun. Water covers 71% of its surface.",
    "num_cards": 3
}

try:
    res = requests.post("http://127.0.0.1:8000/generate-flashcards", json=data, headers=headers, timeout=30)
    print("AI Flashcard Response:")
    print(res.json())
except Exception as e:
    print(f"Error: {e}")