import json
import re

from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from util.profile_folder_protocols import BrowserProfileProtocol

def get_coinbase_paymentmethods(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results_dups = []
    results = []

    url_pattern = re.compile(r"coinbase.*?\.[A-z]{2,3}/graphql/query\?&operationName=usePaymentMethodsQuery")

    for cache_rec in profile.iterate_cache(url=url_pattern):
        cache_data = json.loads(cache_rec.data.decode("utf-8"))
    
        data = cache_data.get("data", {})
        viewer = data.get("viewer", {})
        payment_methods = viewer.get("paymentMethodsV2", [])

        if not payment_methods:
            log_func("No payment methods identified")

        for entry in payment_methods:
            result = { 
                "UUID": entry.get('uuid'),
                "Type": entry.get('type'),
                "Name": entry.get('name'),
                "Currency": entry.get('currency'),
                "Primary Buy Enabled": entry.get('primaryBuy'),
                "Primary Sell Enabled": entry.get('primarySell'),
                "Instant Buy Enabled": entry.get('instantBuy'),
                "Instant Sell Enabled": entry.get('instantSell'),
                "Created At": entry.get('createdAt'),
                "Updated At": entry.get('updatedAt'),
                "Verified": entry.get('verified'),
                "Data Location": str(cache_rec.data_location)
            }
            results_dups.append(result)
                
        for items in results_dups:
            if items not in results:
                results.append(items)

    return ArtifactResult(results)

def get_coinbase_userdetails(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []

    url_pattern = re.compile(r"coinbase.*?\.[A-z]{2,3}/graphql/query\?&operationName=userQuery")

    for cache_rec in profile.iterate_cache(url=url_pattern):
        cache_data = json.loads(cache_rec.data.decode("utf-8"))
    
        data = cache_data.get("data", {})
        viewer = data.get("viewer", {})
        user_properties = viewer.get("userProperties") # should always exist since user information is a requirement to use the coinbase website.
        email = user_properties.get('email')
        personal_details = user_properties.get("personalDetails")
        legal_names = personal_details.get("legalName")
        address = personal_details.get('address')
        country = address.get('country')
        dob = personal_details.get('dateOfBirth')
        address_full = address['line1'], address['line2'], address['city'], address['postalCode'], country['code']

        result = { 
            "First Name": legal_names['firstName'],
            "Last Name": legal_names['lastName'],
            "Email": email,
            "Date of Birth": dob,
            "Address": " ".join(address_full),
            "Data Location": str(cache_rec.data_location)
        }

        results.append(result)

    return ArtifactResult(results)

def get_coinbase_balances(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results_dups = []
    results = []

    url_pattern = re.compile(r"coinbase.*?\.[A-z]{2,3}/graphql/query\?&operationName=SendReceivePreloadable")

    for cache_rec in profile.iterate_cache(url=url_pattern):
        
        cache_data = json.loads(cache_rec.data.decode("utf-8"))
    
        data = cache_data.get("data")
        viewer = data.get("viewer")
        
        receive_accounts = viewer.get('receiveAccounts', [])
        if not receive_accounts:
            log_func("No receive accounts identified.")

        send_accounts = viewer.get('sendAccounts', [])
        if not receive_accounts:
            log_func("No send accounts identified")

        for item in receive_accounts:
            available_balance = item['availableBalance']
            asset_or_fiat = item['assetOrFiatCurrency']
            asset = asset_or_fiat['asset']

            result = {
                "Type": item['type'],
                "Currency": available_balance['currency'],
                "Name": asset['name'],
                "Balance": available_balance['value'],
                "Data Location": str(cache_rec.data_location)
            }

            results_dups.append(result)

        for item in send_accounts:
            available_balance = item['availableBalance']
            asset_or_fiat = item['assetOrFiatCurrency']
            asset = asset_or_fiat['asset']

            result = {
                "Type": item['type'],
                "Currency": available_balance['currency'],
                "Name": asset['name'],
                "Balance": available_balance['value'],
                "Data Location": str(cache_rec.data_location)
            }
            
            results_dups.append(result)

        for items in results_dups:
            if items not in results:  # slow but ultimately fine
                results.append(items)

    return ArtifactResult(results)

__artifacts__ = (
    ArtifactSpec(
        "Coinbase",
        "Coinbase Payment Methods",
        "Recovers Coinbase Payement Methods records from the Cache",
        "0.1",
        get_coinbase_paymentmethods,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "Coinbase",
        "Coinbase User Details",
        "Recovers Coinbase User Details records from the Cache",
        "0.1",
        get_coinbase_userdetails,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "Coinbase",
        "Coinbase Balances",
        "Recovers Coinbase Balances records from the Cache",
        "0.1",
        get_coinbase_balances,
        ReportPresentation.table
    ),
)
