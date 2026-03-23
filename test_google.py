import os
import requests
from dotenv import load_dotenv

load_dotenv()

key = os.getenv('GOOGLE_SEARCH_API_KEY')
cx = os.getenv('GOOGLE_SEARCH_ENGINE_ID')

print(f"Testing Key: {key[:10]}...")
print(f"Testing CX: {cx}")

url = f"https://www.googleapis.com/customsearch/v1?key={key}&cx={cx}&q=test"
response = requests.get(url)

print(f"Status Code: {response.status_code}")
print("Response Body:")
print(response.text)
