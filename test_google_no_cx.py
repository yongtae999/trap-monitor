import os
import requests
from dotenv import load_dotenv

load_dotenv()

key = os.getenv('GOOGLE_SEARCH_API_KEY')

print(f"Testing Key: {key[:10]}...")

# Test WITHOUT cx to see if the error message changes
url = f"https://www.googleapis.com/customsearch/v1?key={key}&q=test"
response = requests.get(url)

print(f"Status Code: {response.status_code}")
print("Response Body:")
print(response.text)
