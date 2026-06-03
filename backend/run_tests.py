import urllib.request
import json

def run_test(name, url, method="GET", data=None):
    print(f"\n=== {name} ===")
    req = urllib.request.Request(url, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
        encoded_data = json.dumps(data).encode("utf-8")
        req.data = encoded_data
    
    try:
        with urllib.request.urlopen(req) as response:
            status = response.status
            body = response.read().decode("utf-8")
            print(f"Status: {status}")
            try:
                parsed = json.loads(body)
                print(json.dumps(parsed, indent=2))
            except json.JSONDecodeError:
                print(body)
    except Exception as e:
        print(f"Error: {e}")
        if hasattr(e, "read"):
            print(e.read().decode("utf-8"))

# Test 1
run_test("Test 1: Health Check", "http://localhost:8000/health")

# Test 2
run_test("Test 2: Dashboard", "http://localhost:8000/dashboard")

# Test 3
chat_data_3 = {
    "message": "Which teams are overloaded right now?",
    "conversation_history": []
}
run_test("Test 3: Chat (Simple capacity)", "http://localhost:8000/chat", method="POST", data=chat_data_3)

# Test 4
chat_data_4 = {
    "message": "Should we take on a new mobile app project for a new client starting next month?",
    "conversation_history": []
}
run_test("Test 4: Chat (Strategic)", "http://localhost:8000/chat", method="POST", data=chat_data_4)
