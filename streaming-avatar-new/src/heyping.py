import requests

url = "https://api.heygen.com/v1/streaming.task"

payload = {
    "session_id": "75c9954a-94ff-11ef-b6d9-0ab9eb0a4133",
    "text": "please check the leads"
}
headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "x-api-key": "OGYzOTcxMjU3YjhiNDU5NDk0NzVjZjNlYzJkYmUwOTItMTcyODM4MTQ2Ng=="
}

response = requests.post(url, json=payload, headers=headers)

print(response.text)