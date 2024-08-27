import json
import re

from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from util.profile_folder_protocols import BrowserProfileProtocol


BALANCES_PATTERN = re.compile(r"coinbase.*?\.[A-z]{2,3}/graphql/query\?&operationName=SendReceivePreloadable")
USER_DETAILS_PATTERN = re.compile(r"coinbase.*?\.[A-z]{2,3}/graphql/query\?&operationName=userQuery")
PAYMENT_METHODS_PATTERN = re.compile(r"coinbase.*?\.[A-z]{2,3}/graphql/query\?&operationName=usePaymentMethodsQuery")

TRANSACTION_PATTERNS = [
    re.compile(r"coinbase.*?\.[A-z]{2,3}/graphql/query\?&operationName=AssetPagePortfolioWalletQuery"),
    re.compile(r"coinbase.*?\.[A-z]{2,3}/graphql/query\?&operationName=AccountActivityRedesignedQuery"),
    re.compile(r"coinbase.*?\.[A-z]{2,3}/graphql/query\?&operationName=usePaginatedAccount")
]


def get_coinbase_paymentmethods(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results_dups = []
    results = []

    for cache_rec in profile.iterate_cache(url=PAYMENT_METHODS_PATTERN):
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
                "Source": "Cache",
                "Data Location": str(cache_rec.data_location)
            }
            results_dups.append(result)
                
        for items in results_dups:
            if items not in results:
                results.append(items)

    return ArtifactResult(results)


def get_coinbase_userdetails(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []

    for cache_rec in profile.iterate_cache(url=USER_DETAILS_PATTERN):
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
            "Source": "Cache",
            "Data Location": str(cache_rec.data_location)
        }

        results.append(result)

    return ArtifactResult(results)


def get_coinbase_balances(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results_dups = []
    results = []

    for cache_rec in profile.iterate_cache(url=BALANCES_PATTERN):
        
        cache_data = json.loads(cache_rec.data.decode("utf-8"))
    
        data = cache_data.get("data")
        viewer = data.get("viewer")
        
        receive_accounts = viewer.get('receiveAccounts', [])
        if not receive_accounts:
            log_func("No receive accounts identified.")

        send_accounts = viewer.get('sendAccounts', [])
        if not send_accounts:
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
                "Source": "Cache",
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


def get_coinbase_transactions(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []

    def process_transaction_node(node, log_func):
        category = node.get('category')
        details = node.get('details')
        created_at = node.get("createdAt")
        title = node.get('title')
        amount = node.get('amount')
        currency = amount.get('currency')  
        value = amount.get('value')

        if category in ['CRYPTO_SEND', 'CRYPTO_RECEIVE']:
            address = details.get('cryptoSendRecipient', {}).get('address', 'Unknown') # no receive address details so always 'unknown'
            transaction_url = details.get('transactionUrl', "N/A")
            payment_methods = "N/A"
            withdraw_to = "N/A"
            deposit_from = "N/A"

        elif category in ['BUY', 'SELL', 'CONVERT']:
            address = "N/A"
            transaction_url = "N/A"
            payment_methods = details.get('paymentMethod', "N/A")    
            withdraw_to = "N/A"
            deposit_from = "N/A"

        elif category in ['FIAT_WITHDRAWAL', 'FIAT_DEPOSIT', 'USER_RECEIVE']:
            address = "N/A"
            transaction_url = "N/A"
            payment_methods = "N/A"            
            withdraw_to = details.get('to', "N/A")
            deposit_from = details.get('from', "N/A")

        elif category in ['UNSTAKING', 'STAKING', 'INTEREST']:
            address = "N/A"
            transaction_url = "N/A"
            payment_methods = "N/A"
            withdraw_to = "N/A"
            deposit_from = "N/A"

        else: 
            log_func("ERROR - Unknown transaction category identified.")

        return {
            "Created Date/Time": created_at,
            "Category": category,
            "Type": title,
            "Currency": currency,
            "Value": value,
            "Address": address,
            "Transaction URL": transaction_url,
            "Payment Method": payment_methods,
            "Withdraw To": withdraw_to,
            "Deposit From": deposit_from,
            "Source": "Cache"
        }

    for url_pattern in TRANSACTION_PATTERNS:
        for cache_rec in profile.iterate_cache(url=url_pattern):
            cache_data = json.loads(cache_rec.data.decode("utf-8"))

            if "viewer" in cache_data.get("data", {}):
                data_node = cache_data["data"].get("viewer", {}).get("accountByUuidV2", {})

            else:
                data_node = cache_data.get("data", {}).get("node", {}) # '&operationName=usePaginatedAccount'stores the transaction data slightly differently

            account_history_entries = data_node.get("accountHistoryEntries", {})
            edges = account_history_entries.get('edges', [])

            for edge in edges:
                result = process_transaction_node(edge.get('node'), log_func)
                if result:
                    result["Data Location"] = str(cache_rec.data_location)
                    results.append(result)

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
    ArtifactSpec(
        "Coinbase",
        "Coinbase Transactions",
        "Recovers Coinbase Transactions from the Cache",
        "0.1",
        get_coinbase_transactions,
        ReportPresentation.table
    ),
)
