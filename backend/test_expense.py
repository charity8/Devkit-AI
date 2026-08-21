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

# Test the Expense Parser
headers = {"Authorization": f"Bearer {token}"}
data = {"text": "Uber ride to airport 25.50"}

try:
    res = requests.post("http://127.0.0.1:8000/parse-expense", json=data, headers=headers, timeout=15)
    print("Expense Parser Response:")
    print(res.json())
except Exception as e:
    print(f"Error: {e}")