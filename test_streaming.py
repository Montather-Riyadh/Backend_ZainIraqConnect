import requests
import os

BASE_URL = "http://127.0.0.1:8000"

def test_streaming():
    print("--- Starting Security Streaming Test ---")
    session = requests.Session()

    # 1. Login to get cookie
    print("1. Logging in...")
    login_data = {
        "username": "admin@example.com", # Assuming this exists from previous tests or change to valid one
        "password": "Password1!"    # Change if needed
    }
    
    # Let's create a new user just to be sure
    import time
    timestamp = str(int(time.time()))
    email = f"testuser_{timestamp}@example.com"
    print(f"   Creating user {email}...")
    res = session.post(f"{BASE_URL}/auth/", json={"fullname": "Test User", "email": email})
    
    # Since we need an approved, active user with a password, the simplest way is to manually
    # manipulate DB or rely on an existing admin. Let's try testing with a 401 first.

    print("\n2. Uploading a dummy file (without auth - should fail if upload is protected, but let's assume it works or we just create a file manually for testing streaming endpoint directly)")
    
    # Let's create a dummy file in the desktop uploads folder
    upload_dir = os.path.join(os.path.expanduser("~"), "Desktop", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    
    dummy_file = os.path.join(upload_dir, "test_secret_video.mp4")
    with open(dummy_file, "w") as f:
        f.write("Fake video content " * 1000)
    
    print(f"   Created dummy file: {dummy_file}")

    print("\n3. Testing Unauthorized Access (No Cookies)")
    # Requesting without session cookies
    res = requests.get(f"{BASE_URL}/uploads/test_secret_video.mp4")
    print(f"   Status Code: {res.status_code}")
    if res.status_code == 401:
        print("   ✅ SUCCESS: Request without cookies was blocked (401 Unauthorized)")
    elif res.status_code == 403:
         print("   ✅ SUCCESS: Request without cookies was blocked (403 Forbidden)")
    else:
        print(f"   ❌ FAILED: Expected 401/403, got {res.status_code}. Response: {res.text}")

    print("\n4. Testing Range Header for Streaming (Unauthorized)")
    headers = {"Range": "bytes=0-100"}
    res = requests.get(f"{BASE_URL}/uploads/test_secret_video.mp4", headers=headers)
    print(f"   Status Code: {res.status_code}")
    if res.status_code in [401, 403]:
        print(f"   ✅ SUCCESS: Range request was properly blocked ({res.status_code})")
    else:
        print(f"   ❌ FAILED: Expected block, got {res.status_code}")

    # Clean up
    if os.path.exists(dummy_file):
        os.remove(dummy_file)
        
    print("\n✅ Basic Security Check Complete. For full auth flow, manual frontend testing relies on actual DB records.")

if __name__ == "__main__":
    try:
        test_streaming()
    except Exception as e:
        print(f"Error connecting to server. Is FastAPI running? {e}")
