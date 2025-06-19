from google import genai

# 1. Instantiate the client with your API key
client = genai.Client(api_key="AIzaSyC4OxtDp2QXW_wovbvTtkdkEkgqYv2Gx2M")

# 2. Make a call to the gemini model
response = client.models.generate_content(
    # Replace "gemini-2.0-flash" with the exact model name your docs mention
    model="gemini-2.0-flash",
    contents="Explain how AI works"
)

# 3. Print the response
print(response.text)
