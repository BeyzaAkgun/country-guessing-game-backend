import asyncio
import websockets
import json

async def test_player(name, token, match_id):
    url = f"ws://127.0.0.1:8000/ws/match/{match_id}?token={token}"
    print(f"{name}: connecting to {url[:60]}...")
    try:
        async with websockets.connect(url) as ws:
            print(f"{name}: connected!")
            async for message in ws:
                data = json.loads(message)
                print(f"{name} received: {json.dumps(data, indent=2)}")
                # Auto-answer for testing
                if data.get("event") == "question":
                    country = data["data"]["country_name"]
                    answer = json.dumps({"event": "answer", "data": {"answer": country.lower()}})
                    await ws.send(answer)
                    print(f"{name} sent answer: {country.lower()}")
    except Exception as e:
        print(f"{name} error: {e}")

async def main():
    # Replace these values
    MATCH_ID = "764c54f6-d63f-4984-bd27-885f39830524"
    TOKEN1 = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiYTU4MzM2NC03NWJiLTQxZDEtYjE5Mi0xNDI4YjI5Y2MxYzkiLCJ0eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzcyNDgwNDU3LCJpYXQiOjE3NzI0Nzg2NTd9.fBGOoKH8VbJAA-GXEEXoloOqs02EduHc5ffaisNn58g"
    TOKEN2 = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI1MzVkZDRmNS0yZGQ0LTQ1YzAtYmQ4Ny05YjUxM2I2NzYwMzAiLCJ0eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzcyNDgwNDkyLCJpYXQiOjE3NzI0Nzg2OTJ9.DkGQOBmc871ERmeBo7vkecrAgWgrgkH65FthQ86Mm90"

    await asyncio.gather(
        test_player("Player1", TOKEN1, MATCH_ID),
        test_player("Player2", TOKEN2, MATCH_ID),
    )

asyncio.run(main())