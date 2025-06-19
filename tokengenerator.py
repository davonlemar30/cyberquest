from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/gmail.send']

flow = InstalledAppFlow.from_client_secrets_file('client_secret.json', SCOPES)

# Print the actual redirect URI being used
print("Redirect URIs being used:", flow.redirect_uri)

creds = flow.run_local_server(port=8080)  # Try forcing port 8080

# Save the token
import pickle
with open('token.pickle', 'wb') as token:
    pickle.dump(creds, token)

print("Token generated successfully!")
