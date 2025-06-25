import base64
with open("token.pickle", "rb") as token_file:
    encoded_string = base64.b64encode(token_file.read()).decode('utf-8')
print("Copy the following string into the TOKEN_PICKLE_B64 GitHub secret:")
print(encoded_string)