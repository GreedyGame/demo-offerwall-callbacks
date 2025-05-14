# Welcome to Cloud Functions for Firebase for Python!
# To get started, simply uncomment the below code or create your own.
# Deploy with `firebase deploy`

from firebase_functions import https_fn
from firebase_admin import initialize_app, firestore
import hashlib
from datetime import datetime

# Initialize Firebase Admin SDK (only once)
initialize_app()

#Get this value from the dashboard
PUBSCALE_SECRET_KEY = "YOUR_SECRET_KEY"
PUBSCALE_WHITELIST_IP = "34.100.236.68"

# Example endpoint: /add_balance?value={value}&userId={userId}&token={token}&signature={signature}
@https_fn.on_request()
def handle_pubscale_callback(req: https_fn.Request) -> https_fn.Response:

    #Validating request IP Address
    ip = req.headers.get("X-Forwarded-For", req.remote_addr)
    if ip != PUBSCALE_WHITELIST_IP:
         return https_fn.Response("Unknown request source", status=403)

    # Parse query parameters
    value_str = req.args.get('value') #Reward value earned by the user for this conversion. (in in-app currency)
    user_id = req.args.get('user_id') #User ID of the user that completed the task
    token = req.args.get('token') #Idempotency token to uniquely identify the transaction
    signature = req.args.get('signature') #Hash that can be used as a checksum to validate the originality of this request

    #Validating query params
    if not value_str or not user_id or not token or not signature:
        return https_fn.Response("Missing 'value' or 'userId' or 'token' or 'signature' parameter", status=400)
    
    #Validating if value is a number
    try:
        value = float(value_str)
    except ValueError:
        return https_fn.Response("'value' must be a number", status=400)
    
    #Validating signature
    template = '{secret_key}.{user_id}.{value}.{token}'.format(secret_key=PUBSCALE_SECRET_KEY,user_id=user_id,value=int(value),token=token)
    hash = hashlib.md5(template.encode('utf-8')).hexdigest()
    if hash != signature:
         return https_fn.Response("Invalid hash", status=401)

    try:
        new_balance = creditRewardToUser(user_id= user_id, reward_value=value, token=token)
        return https_fn.Response(f"Balance updated. New balance: {new_balance}", status = 200)
    except Exception as e:
        return https_fn.Response(f"Error updating balance: {str(e)}", status=500)
    

#This method just handles adding the reward to the user wallet balance and transaction logs
def creditRewardToUser(user_id, reward_value, token):
        
        db = firestore.client()

        @firestore.transactional
        def updateWalletBalanceFirestore(transaction):

            rounded_value = round(reward_value)
            user_doc_ref = db.collection("apps").document("my_app").collection("users").document(user_id)
            snapshot = user_doc_ref.get(transaction = transaction)
            current_balance = snapshot.get("balance") or 0
            new_balance = int(current_balance) + rounded_value

            transaction_data = {
                "amount": rounded_value,
                "timestamp": datetime.now(),
                "source": "PubScale OW",
                "type": "CREDIT"
            }

            # Update balance and push to transactions array
            transaction.set(user_doc_ref, {
                "balance": new_balance,
                "transactions": firestore.ArrayUnion([transaction_data])
            }, merge = True)

            return new_balance
        
        transaction = db.transaction()
        return updateWalletBalanceFirestore(transaction= transaction)
    