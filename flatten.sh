# Install jq if you don't have it
# sudo pacman -S jq

# Start fresh (Replace 'ghp_your_token' with your actual PAT)
echo "GITHUB_TOKEN=ghp_your_token_here" > .secrets

# Flatten and append each JSON file automatically
echo -n "UCAM_LOGIN_CREDENTIALS=" >> .secrets
jq -c . configs_to_edit/ucam_login_credentials.json >> .secrets

echo -n "TEACHER_CONTACT_DETAILS=" >> .secrets
jq -c . configs_to_edit/teacher_contact_details.json >> .secrets

echo -n "GOOGLE_SERVICE_ACCOUNT_KEY=" >> .secrets
jq -c . google_cloud_keys/service_account_key.json >> .secrets

echo -n "GOOGLE_OAUTH_CLIENT_SECRET=" >> .secrets
jq -c . google_cloud_keys/oauth_client_secret.json >> .secrets

# Add the base64 token
echo "TOKEN_PICKLE_B64=$(base64 -w 0 token.pickle)" >> .secrets